"""A role as the inspector shows it: what it implies, and what it gives.

The node `roles.<code>` of the inspector shows the role as written; this adds
what the guard makes of it (`introspect.add_detail`). The roles it implies,
directly and through each other, and those that imply it; then every
permission it holds, table by table and the others, each with the roles of the
closure whose own grants give it, so a grant that comes from far down the
`implies` is found where it comes from. A condition says it is held on some
rows only; a denial within the closure says who takes it away. Last the pages
the role opens, each a link to the page as the role receives it, and those
among them whose query it cannot read, what `check` reports.
"""
import json
from typing import Any, Dict, List

from kitebase import access, introspect
from kitebase.endpoints import _ACCESS

from acl.guard import GUARD, _covers, _items, _known_permissions, expand_grant, granted, unreadable_pages

ROOT = 'roles'


def _closure(declared: Dict[str, Any], code: str) -> List[str]:
    """The role and those it implies, through each other, in the order met."""
    out: List[str] = []

    def visit(c: str) -> None:
        if c in out:
            return
        out.append(c)
        for implied in (declared.get(c) or {}).get('implies') or []:
            visit(implied)

    visit(code)
    return out


def _role(code: str, declared: Dict[str, Any]) -> Dict[str, Any]:
    cell: Dict[str, Any] = {'text': code, 'path': f'{ROOT}.{code}'}
    if code not in declared:
        return {'text': code, 'tone': 'no', 'title': 'declared nowhere: it gives nothing'}
    label = (declared[code] or {}).get('label')
    if label:
        cell['title'] = label
    return cell


def role_detail(app: Any, code: str) -> List[Dict[str, Any]]:
    declared = dict(_items(app.pm.data.get(ROOT) or {}))
    if code not in declared:
        raise KeyError(code)
    closure = _closure(declared, code)
    own = {r: [g for item in (declared.get(r) or {}).get('grants') or []
               for g in expand_grant(item, r)] for r in closure if r in declared}
    held = GUARD.roles.get(code, frozenset())
    every_row = GUARD.every_row.get(code, frozenset())
    conditions = GUARD.conditional.get(code, {})

    def cell(permission: str) -> Any:
        if not granted(permission, held):
            deniers = [r for r, grants in own.items()
                       if any(g.startswith('-') and _covers(g[1:], permission) for g in grants)]
            return {'text': 'denied', 'tone': 'no', 'title': f"denied by {', '.join(deniers)}"} \
                if deniers else ''
        givers = [r for r, grants in own.items() if granted(permission, grants)]
        by = f"by {', '.join(givers)}"
        if not granted(permission, every_row) and conditions.get(permission):
            wheres = '; or '.join(json.dumps(w) for w in conditions[permission])
            return {'text': 'where', 'tone': 'cond', 'title': f'{by}, where {wheres}'}
        return {'text': 'yes', 'tone': 'ok', 'title': by}

    blocks: List[Dict[str, Any]] = []
    direct = (declared[code] or {}).get('implies') or []
    blocks.append({
        'title': 'Implies',
        'doc': 'The roles it takes in, directly; then all of them, through each other.',
        'links': [_role(r, declared) for r in direct],
    })
    if len(closure) - 1 > len(direct):
        blocks.append({'title': 'Implies, through each other',
                       'links': [_role(r, declared) for r in closure[1:]]})
    implied_by = [r for r in declared if r != code and code in _closure(declared, r)]
    blocks.append({'title': 'Implied by', 'links': [_role(r, declared) for r in implied_by]})

    names = sorted(app.tables, key=lambda t: (app.tables[t].plugins[0].name, t))
    blocks.append({
        'title': 'Tables',
        'doc': 'What it holds on each table: point at an answer for the roles that give it.',
        'columns': ['Table', *access.TABLE_ACTIONS],
        'rows': [[{'text': t, 'path': f'tables.{t}'},
                  *(cell(f'{t}.{a}') for a in access.TABLE_ACTIONS)] for t in names],
    })

    labels = dict(_items(app.pm.data.get('permissions') or {}))
    table_codes = {f'{t}.{a}' for t in app.tables for a in access.TABLE_ACTIONS}
    others = sorted(_known_permissions(app, _ACCESS) - table_codes)
    blocks.append({
        'title': 'Other permissions',
        'doc': 'Column groups, permissions declared by the plugins, those endpoints ask for.',
        'columns': ['Permission', 'Held'],
        'rows': [[{'text': p, 'title': (labels.get(p) or {}).get('label') or p}, cell(p)]
                 for p in others],
    })

    from kitebase.pages import page_permissions
    holds = lambda p: granted(p, held)  # noqa: E731
    opens = [pid for pid, _ in _items(app.pm.data.get('pages') or {})
             if all(holds(p) for p in page_permissions(app, pid) or [])]
    blocks.append({
        'title': 'Pages it opens',
        'doc': 'Each as the role receives it.',
        'links': [{'text': pid, 'path': f'pages.{pid}', 'subject': code} for pid in sorted(opens)],
    })
    problems = unreadable_pages(app, holds)
    if problems:
        blocks.append({
            'title': 'Pages it opens and cannot read',
            'doc': 'Their query answers 403: what check reports.',
            'columns': ['Page', 'Cannot read', 'Grant'],
            'rows': [[{'text': p['page'], 'path': f"pages.{p['page']}", 'subject': code, 'tone': 'no'},
                      p['what'], p['grant']] for p in problems],
        })
    return blocks


introspect.add_detail(ROOT, role_detail)
