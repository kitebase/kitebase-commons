"""The roles of a partner as the form offers them, and the check on what it saves.

`partner_roles` is the vocabulary the roles field picks from: the rows of
`PartnerRole` in their order, each as a choice of the checklist. Who reads the
roles table reads it, which is whoever decodes a partner's roles anyway.

It is also the validator of `Partner.roles` (model.yaml): a list of codes that
are rows of `PartnerRole`. Whoever writes the column, from the form or through
the API, is told which code is unknown rather than having a typo kept, which no
view filters on and no default stamps.
"""
from typing import Any, Dict, List, Optional

import kitebase.utils
from kitebase.endpoints import endpoint
from kitebase.i18n import _
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
