"""The roles as the user form offers them, and the check on what it saves.

`acl_roles` is the catalogue the roles field picks from: every declared role
with its label, the plugin that declares it (the group it is shown in) and the
roles it implies, so the list can show what a choice brings along. Who reads
the users reads it: the codes are no secret to whoever sees them in a row.

`acl_roles` is also the validator of `User.roles` (model.yaml): a list of
declared role codes. The column is plain JSON, and whoever writes it directly,
from the form or through the API, is told which code is unknown rather than
having a typo kept, holding nothing.

`acl_effective` answers what a set of roles gives, permission by permission:
the five actions on every table, then every other permission something asks
for. Each answer names the assigned roles that give it, and those that take
it away within themselves, so the tree of `implies` can be checked by eye.
It takes the roles rather than a user: the form asks about its draft, before
anything is saved.
"""
from typing import Any, Dict, List, Optional

import kitebase.utils
from kitebase.endpoints import endpoint
from kitebase.i18n import _
from kitebase.transforms import register_validator

from kitebase import access
from kitebase.endpoints import _ACCESS

from acl.guard import GUARD, _covers, _items, _known_permissions, granted


def role_catalog(app: Any) -> List[Dict[str, Any]]:
    """Every declared role, in declaration order, as the form shows it."""
    catalog = []
    for code, definition in _items(app.pm.data.get('roles') or {}):
        definition = definition or {}
        catalog.append({
            'value': code,
            'label': definition.get('label') or code,
            'group': definition.get('$plugin') or '',
            'implies': list(definition.get('implies') or []),
        })
    return catalog


@endpoint('acl_roles', access='User.read')
def acl_roles(data):
    return {'status': 'success', 'code': 200,
            'data': role_catalog(kitebase.utils.get_app())}


def _answer(permission: str, roles: List[str], labels: Dict[str, str]) -> Dict[str, Any]:
    by, denied_by = [], []
    for code in roles:
        resolved = GUARD.roles.get(code, ())
        if granted(permission, resolved):
            by.append(labels[code])
        elif any(p.startswith('-') and _covers(p[1:], permission) for p in resolved):
            denied_by.append(labels[code])
    return {'ok': bool(by), 'by': by, 'denied_by': denied_by}


def effective(app: Any, roles: List[str], is_admin: bool = False) -> Dict[str, Any]:
    """What `roles` give, table by table and then permission by permission."""
    declared = dict(_items(app.pm.data.get('roles') or {}))
    known = [c for c in roles if c in declared]
    labels = {c: (declared[c] or {}).get('label') or c for c in known}

    def answer(permission: str) -> Dict[str, Any]:
        if is_admin:
            return {'ok': True, 'by': [_('Administrator')], 'denied_by': []}
        return _answer(permission, known, labels)

    tables = []
    for name in sorted(app.tables, key=lambda t: (app.tables[t].plugins[0].name, t)):
        table = app.tables[name]
        tables.append({
            'name': name,
            'label': table.attributes.get('label') or name,
            'plugin': table.plugins[0].name,
            'actions': {a: answer(f'{name}.{a}') for a in access.TABLE_ACTIONS},
        })

    declared_permissions = dict(_items(app.pm.data.get('permissions') or {}))
    table_codes = {f'{t}.{a}' for t in app.tables for a in access.TABLE_ACTIONS}
    others = sorted(_known_permissions(app, _ACCESS) - table_codes)
    permissions = [{'code': code,
                    'label': (declared_permissions.get(code) or {}).get('label') or code,
                    **answer(code)} for code in others]

    return {'admin': is_admin,
            'unknown': [c for c in roles if c not in declared],
            'actions': list(access.TABLE_ACTIONS),
            'tables': tables,
            'permissions': permissions}


@endpoint('acl_effective', access='User.read')
def acl_effective(data):
    roles = data.get('roles') or []
    if not isinstance(roles, list):
        roles = []
    return {'status': 'success', 'code': 200,
            'data': effective(kitebase.utils.get_app(),
                              [c for c in roles if isinstance(c, str)],
                              bool(data.get('is_admin')))}


def validate_roles(value: Any, record: Dict[str, Any]) -> Optional[str]:
    if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
        return _('A list of role codes is expected, such as ["library.desk"]')
    declared = {code for code, _definition in
                _items(kitebase.utils.get_app().pm.data.get('roles') or {})}
    unknown = [c for c in value if c not in declared]
    if unknown:
        return _('Unknown role: {codes}').format(codes=', '.join(unknown))
    return None


register_validator('acl_roles', validate_roles)
