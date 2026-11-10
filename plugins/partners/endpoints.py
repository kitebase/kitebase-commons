"""The roles of a partner as the form offers them, and the check on what it saves.

`partner_roles` is the vocabulary the roles field picks from: the rows of
`PartnerRole` in their order, each as a choice of the checklist. Who reads the
roles table reads it, which is whoever decodes a partner's roles anyway.

It is also the validator of `Partner.roles` (model.yaml): a list of codes that
are rows of `PartnerRole`. Whoever writes the column, from the form or through
the API, is told which code is unknown rather than having a typo kept, which no
view filters on and no default stamps.

`partner_roles_menu` is a navigator command: a menu of what can be given or
taken away, for the active row or the ticked ones, and `partner_roles_change`
does the picked entry. Each record is written by the update of `db`, so the
validator, the row's access and the table's rules hold as they do in the form;
a record a rule stops (a question, a refusal) is left as it was, and named.
"""
from typing import Any, Dict, List, Optional

import kitebase.utils
from kitebase import access
from kitebase.access import AccessDenied
from kitebase.endpoint_db import handle_update
from kitebase.endpoints import endpoint
from kitebase.errors import Refusal
from kitebase.i18n import _, _f
from kitebase.transforms import register_validator


def _roles() -> List[Any]:
    app = kitebase.utils.get_app()
    Role = app.models['PartnerRole']
    with app.get_session() as session:
        rows = session.query(Role).order_by(Role.sequence, Role.id).all()
        return [(r.id, r.label) for r in rows]


@endpoint('partner_roles', access='PartnerRole.read')
def partner_roles(data):
    choices: List[Dict[str, Any]] = [{'value': code, 'label': label or code}
                                     for code, label in _roles()]
    return {'status': 'success', 'code': 200, 'data': choices}


def validate_roles(value: Any, record: Dict[str, Any]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
        return _('A list of role codes is expected, such as ["C", "S"]')
    declared = {code for code, _label in _roles()}
    unknown = [c for c in value if c not in declared]
    if unknown:
        return _('Unknown role: {codes}').format(codes=', '.join(unknown))
    return None


register_validator('partner_roles', validate_roles)


# ── Giving and taking away a role, from a list ──────────────────────────────

def _ids(data: Dict[str, Any]) -> List[Any]:
    return data.get('ids') or ([data['id']] if data.get('id') is not None else [])


@endpoint('partner_roles_menu', access=access.PER_TABLE)
def partner_roles_menu(data):
    """The menu: for one row the role it lacks or holds, for a selection both verbs."""
    access.check_table('Partner', 'read')
    ids = _ids(data)
    if not ids:
        return {'status': 'error', 'code': 400, 'message': _('Select a partner first')}
    if not access.can('Partner.update'):
        return {'status': 'error', 'code': 403, 'message': _('You may not change partners')}

    def entry(label, code, add):
        return {'label': label,
                'then': {'action': 'endpoint', 'op': 'partner_roles_change',
                         'params': {'ids': ids, 'role': code, 'add': add}}}

    options = []
    roles = _roles()
    if len(ids) == 1:
        app = kitebase.utils.get_app()
        with app.get_session() as session:
            row = session.get(app.models['Partner'], ids[0])
            held = set(row.roles or []) if row is not None else set()
        for code, label in roles:
            name = label or code
            if code in held:
                options.append(entry(_f('Remove role {role}', role=name), code, False))
            else:
                options.append(entry(_f('Add role {role}', role=name), code, True))
    else:
        n = len(ids)
        for code, label in roles:
            options.append(entry(_f('Add {role} to {n} selected', role=label or code, n=n), code, True))
        for code, label in roles:
            options.append(entry(_f('Remove {role} from {n} selected', role=label or code, n=n),
                                 code, False))
    return {'status': 'success', 'data': {'action': 'choose', 'options': options}}


@endpoint('partner_roles_change', access=access.PER_TABLE)
def partner_roles_change(data):
    """Add or take away one role on the given partners, each through the update of db."""
    access.check_table('Partner', 'update')
    ids, code, add = _ids(data), data.get('role'), bool(data.get('add'))
    if not ids or not code:
        return {'status': 'error', 'code': 400, 'message': _('A role and the partners are needed')}

    app = kitebase.utils.get_app()
    model = app.models['Partner']
    with app.get_session() as session:
        rows = {r.id: (r.name, list(r.roles or []))
                for r in session.query(model).filter(model.id.in_(ids))}

    touched, stopped = [], []
    for record_id in ids:
        if record_id not in rows:
            continue
        name, roles = rows[record_id]
        if (code in roles) == add:
            continue
        roles = roles + [code] if add else [c for c in roles if c != code]
        try:
            result = handle_update(app, model, {'id': record_id, 'data': {'roles': roles}},
                                   app.tables.get('Partner'))
        except AccessDenied:
            stopped.append(_f('{name}: not allowed', name=name))
            continue
        except Refusal as e:
            result = {'status': 'error', 'message': e.message, 'data': e.data}
        if result.get('status') == 'success':
            touched.append(record_id)
        else:
            errors = (result.get('data') or {}).get('errors') or {}
            stopped.append(f"{name}: {errors.get('roles') or result.get('message')}")

    if touched:
        message = _f('{n} changed', n=len(touched))
    else:
        message = _('Nothing to change')
    if stopped:
        message += '. ' + _f('Left as they were: {names}', names='; '.join(stopped))
    return {'status': 'success', 'data': {'message': message, 'touched': touched}}
