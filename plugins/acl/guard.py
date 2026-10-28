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

A user holds role codes in the `roles` column; the token carries them, and the
guard resolves them into permissions once per set of roles. `is_admin` is root:
it passes every check. A permission no role grants is refused, so with this
plugin on a table nobody was given stays closed, and so does an endpoint that
declares no access unless the app's config assigns it one:

    acl:
      endpoints:
        library.renew: library.renew
"""
import logging
from typing import Any, Dict, FrozenSet, Iterable, List

from kitebase import access
from kitebase.server_utils import add_context_field

ADMIN_FIELD = 'is_admin'
ROLES_FIELD = 'roles'

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


def granted(permission: str, permissions: Iterable[str]) -> bool:
    """Whether `permissions` covers `permission`; `Book.*` covers `Book.read`."""
    return any(p == permission or (p.endswith('.*') and permission.startswith(p[:-1]))
               for p in permissions)


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

    def allows(self, permission: str, context: Any) -> bool:
        context = context or {}
        if context.get(ADMIN_FIELD):
            return True
        return granted(permission, self.permissions(context.get(ROLES_FIELD) or []))

    def allows_undeclared(self, endpoint: str, context: Any) -> bool:
        if (context or {}).get(ADMIN_FIELD):
            return True
        permission = self.endpoints.get(endpoint)
        return permission is not None and self.allows(permission, context)


GUARD = RoleGuard()
access.set_guard(GUARD)
add_context_field(ROLES_FIELD)
add_context_field(ADMIN_FIELD)
