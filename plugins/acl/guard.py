"""The guard behind every port, answering from roles declared in the plugins.

A plugin declares its roles in `acl.yaml`, beside its model:

    permissions:
      library.renew: { label: Renew a loan }
    roles:
      library.member:
        label: Member
        grants: [Book.read, Loan.read]
      library.librarian:
        implies: [library.member]
        grants:
          - Book: [read, create, update]     # Book.read, Book.create, ...
          - Loan.*                           # every action on Loan
          - library.renew
      library.desk:
        grants:
          - '*.label'                        # every reference shown by its label
          - '-Member.label'                  # but not this one

A grant with a leading `-` takes the permission away inside the role, from
its own grants and from those of the roles it implies: a role says yes to what
it grants and does not deny. A user holds a permission when one of the roles
says yes, so a denial in one role does not reach another.

A user holds role codes in the `roles` column; the token carries them, and the
guard resolves them into permissions once per set of roles. Next to them,
`acl_exceptions` holds the user's own: `+Publisher.create` grants, `-Book.read`
denies, and the denial wins over everything but root:

    effective = (from the roles + granted) - denied

`is_admin` is root:
it passes every check. Roles, exceptions and `is_admin` are the column group
`acl` (model.yaml): `acl.read` shows them and `acl.write` changes them, so
`User.update` alone edits a user without raising anyone's privileges.

A permission no role grants is refused, so with this plugin on a table nobody
was given stays closed, and so does an endpoint that declares no access unless
the app's config assigns it one:

    acl:
      endpoints:
        library.renew: library.renew
"""
import logging
import re
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from kitebase import access
from kitebase.server_utils import add_context_field

ADMIN_FIELD = 'is_admin'
ROLES_FIELD = 'roles'
EXCEPTIONS_FIELD = 'acl_exceptions'

_log = logging.getLogger(__name__)


def _items(definition: Dict[str, Any]):
    """The entries of a merged mapping, without the framework's `$` metadata."""
    return [(k, v) for k, v in (definition or {}).items() if not str(k).startswith('$')]


def expand_grant(item: Any, role: str) -> List[str]:
    """One entry of `grants:` as the permission codes it stands for."""
    if isinstance(item, str):
        return [item]
    entries = _items(item) if isinstance(item, dict) else []
    if len(entries) == 1:
        code, value = entries[0]
        if value is None:
            return [code]
        if isinstance(value, list):
            return [f'{code}.{action}' for action in value]
        if isinstance(value, dict):
            raise ValueError(f"Role '{role}': the grant on '{code}' has a condition, "
                             f"and conditions are not supported yet")
    raise ValueError(f"Role '{role}': cannot read the grant {item!r}")


def resolve_roles(roles: Dict[str, Any]) -> Dict[str, FrozenSet[str]]:
    """
    Every role as the permissions it gives, those of the roles it implies
    included. A cycle is an error: the closure has no answer. A role implied
    but never declared gives nothing, and is reported.
    """
    declared = dict(_items(roles))
    own = {code: [p for item in (d or {}).get('grants') or [] for p in expand_grant(item, code)]
           for code, d in declared.items()}
    resolved: Dict[str, FrozenSet[str]] = {}

    def visit(code: str, path: List[str]) -> FrozenSet[str]:
        if code in resolved:
            return resolved[code]
        if code in path:
            raise ValueError(f"Roles imply each other in a cycle: {' -> '.join(path + [code])}")
        if code not in declared:
            _log.warning("Role '%s' is implied by '%s' but declared nowhere", code, path[-1])
            return frozenset()
        permissions = set(own[code])
        for implied in (declared[code] or {}).get('implies') or []:
            permissions |= visit(implied, path + [code])
        resolved[code] = frozenset(permissions)
        return resolved[code]

    for code in declared:
        visit(code, [])
    return resolved


def _covers(grant: str, permission: str) -> bool:
    if grant == permission:
        return True
    if grant.endswith('.*') and permission.startswith(grant[:-1]):
        return True
    # `*.label` is every table, in CamelCase: not a column group like `acl.read`
    return (grant.startswith('*.') and permission[:1].isupper()
            and permission.partition('.')[2] == grant[2:])


def granted(permission: str, permissions: Iterable[str]) -> bool:
    """
    Whether `permissions` covers `permission`: `Book.*` covers `Book.read`,
    `*.label` covers `Book.label`, and a `-` before a code denies what it covers.
    """
    permissions = list(permissions)
    return (any(_covers(p, permission) for p in permissions if not p.startswith('-'))
            and not any(_covers(p[1:], permission) for p in permissions if p.startswith('-')))


class RoleGuard(access.Guard):

    def __init__(self) -> None:
        self.roles: Dict[str, FrozenSet[str]] = {}
        self.endpoints: Dict[str, str] = {}
        self._cache: Dict[FrozenSet[str], FrozenSet[str]] = {}

    def bind(self, app: Any) -> None:
        self.roles = resolve_roles(app.pm.data.get('roles') or {})
        self.endpoints = (app.pm.config.get('acl') or {}).get('endpoints') or {}
        self._cache = {}

    def permissions(self, codes: Iterable[str]) -> FrozenSet[str]:
        """What a set of roles gives, resolved once per set."""
        key = frozenset(codes)
        if key not in self._cache:
            self._cache[key] = frozenset().union(*(self.roles.get(c, frozenset()) for c in key))
        return self._cache[key]

    def holds(self, permission: str, roles: Iterable[str],
              exceptions: Iterable[str] = ()) -> bool:
        """Whether a user with these roles and exceptions holds `permission`."""
        exceptions = list(exceptions or ())
        if any(e.startswith('-') and _covers(e[1:], permission) for e in exceptions):
            return False
        if any(e.startswith('+') and _covers(e[1:], permission) for e in exceptions):
            return True
        return any(granted(permission, self.roles.get(code, ())) for code in roles or ())

    def allows(self, permission: str, context: Any) -> bool:
        context = context or {}
        if context.get(ADMIN_FIELD):
            return True
        return self.holds(permission, context.get(ROLES_FIELD) or [],
                          context.get(EXCEPTIONS_FIELD) or [])

    def allows_undeclared(self, endpoint: str, context: Any) -> bool:
        if (context or {}).get(ADMIN_FIELD):
            return True
        permission = self.endpoints.get(endpoint)
        return permission is not None and self.allows(permission, context)

    # ── check: what is left to cover before production ─────────────────────

    def diagnose(self, app: Any) -> List[Dict[str, Any]]:
        from kitebase.diagnostics import make_issue
        from kitebase.endpoints import _ACCESS, _ENDPOINTS

        issues: List[Dict[str, Any]] = []
        declared = dict(_items(app.pm.data.get('roles') or {}))
        known = _known_permissions(app, _ACCESS)

        for code, definition in declared.items():
            plugin = (definition or {}).get('$plugin')
            for grant in self.roles.get(code, ()):
                if not _exists(grant.lstrip('-'), known, app.tables):
                    issues.append(make_issue(
                        'warning', 'acl-grant-unknown', f'roles.{code}',
                        f"grants '{grant}', a permission nothing declares", plugin))

        for table in app.tables:
            if not any(granted(f'{table}.read', p) or granted(f'{table}.label', p)
                       for p in self.roles.values()):
                issues.append(make_issue(
                    'warning', 'acl-table-closed', f'tables.{table}',
                    'no role reads it: only the administrator does'))

        for name in sorted(_ENDPOINTS):
            if _ACCESS.get(name, access.UNDECLARED) is access.UNDECLARED \
                    and name not in self.endpoints:
                issues.append(make_issue(
                    'warning', 'acl-endpoint-undeclared', f'endpoints.{name}',
                    "declares no access: closed to all but the administrator; "
                    "declare `access=` or assign one in the app's `acl.endpoints`"))

        issues.extend(self._diagnose_pages(app))
        return issues

    def _diagnose_pages(self, app: Any) -> List[Dict[str, Any]]:
        """A role that opens a page whose query reads a table it cannot read:
        the page opens and its data answers 403, found here instead of on screen."""
        from kitebase.diagnostics import make_issue

        issues = []
        for code, permissions in self.roles.items():
            for problem in unreadable_pages(app, lambda p, ps=permissions: granted(p, ps)):
                issues.append(make_issue(
                    'warning', 'acl-page-unreadable', f"pages.{problem['page']}",
                    f"role '{code}' opens it but cannot read {problem['what']}: its "
                    f"query answers 403; grant {problem['grant']}, or adapt the page",
                    problem['plugin']))
        return issues


def unreadable_pages(app: Any, holds: Callable[[str], bool]) -> List[Dict[str, Any]]:
    """
    The pages whoever `holds` the given permissions opens, but whose query
    reads a table they cannot: each with what it reads and what would cover it.
    Asked for every role by `check`, and for one user by the user form.
    """
    from kitebase.pages import load_page, page_permissions

    problems = []
    for page_id, raw in _items(app.pm.data.get('pages') or {}):
        if not all(holds(n) for n in page_permissions(app, page_id) or []):
            continue
        try:
            refs = _page_references(app, load_page(app, page_id))
        except ValueError:
            continue    # a broken page is reported by the core's checks
        for table, column in sorted(refs, key=str):
            if holds(f'{table}.read'):
                continue
            if holds(f'{table}.label') and (
                    column is None or column in access.label_columns(table, app)):
                continue
            problems.append({
                'page': page_id,
                'title': (raw or {}).get('title') if isinstance(raw, dict) else None,
                'what': f'{table}.{column}' if column else f'the label of {table}',
                # with the label already held only read is left to give
                'grant': (f'{table}.read' if holds(f'{table}.label')
                          else f'{table}.read or {table}.label'),
                'plugin': (raw or {}).get('$plugin') if isinstance(raw, dict) else None,
            })
    return problems


_REFERENCE = re.compile(r'^([A-Z]\w*)\.(\w+)(?:\s+as\s+\w+)?$', re.IGNORECASE)


def _page_references(app: Any, page: Any) -> Set[Tuple[str, Optional[str]]]:
    """The other tables a page reads: `Model.column` in its columns and fields,
    and the label of every foreign key a form shows (column None)."""
    model = ((page or {}).get('content') or {}).get('source', {}).get('model')
    found: Set[Tuple[str, Optional[str]]] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            fk = obj.get('foreign_key')
            if isinstance(obj.get('name'), str) and isinstance(fk, dict) \
                    and fk.get('target') in app.tables:
                found.add((fk['target'], None))
            for value in obj.values():
                walk(value)
        elif isinstance(obj, str):
            match = _REFERENCE.match(obj.strip())
            if match and match.group(1) in app.tables and match.group(1) != model:
                found.add((match.group(1), match.group(2)))

    walk(page)
    return found


def _known_permissions(app: Any, endpoint_access: Dict[str, Any]) -> Set[str]:
    """Every permission something asks for: derived from the tables, declared
    in `permissions:`, required by an endpoint or by an `access:` in YAML."""
    known = {f'{t}.{a}' for t in app.tables for a in access.TABLE_ACTIONS}
    known.update(f'{g}.{a}' for table in app.tables.values()
                 for g in table.column_groups.values() for a in access.COLUMN_ACTIONS)
    known.update(k for k, _ in _items(app.pm.data.get('permissions') or {}))
    known.update(v for v in endpoint_access.values()
                 if isinstance(v, str) and not v.startswith('$'))

    def walk(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            known.update(access.declared(obj.get('access')))
            for value in obj.values():
                walk(value)

    for section in ('pages', 'views', 'menu_items'):
        walk(app.pm.data.get(section))
    return known


def _exists(grant: str, known: Set[str], tables: Iterable[str]) -> bool:
    if grant.startswith('*.'):
        return grant[2:] in access.TABLE_ACTIONS or grant[2:] == '*'
    if grant.endswith('.*'):
        prefix = grant[:-1]
        return grant[:-2] in tables or any(k.startswith(prefix) for k in known)
    return grant in known


GUARD = RoleGuard()
access.set_guard(GUARD)
add_context_field(ROLES_FIELD)
add_context_field(ADMIN_FIELD)
add_context_field(EXCEPTIONS_FIELD)
