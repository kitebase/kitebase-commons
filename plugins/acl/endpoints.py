"""The roles as the user form offers them, and the check on what it saves.

`acl_roles` is the catalogue the roles field picks from: every declared role
with its label, the plugin that declares it (the group it is shown in) and the
roles it implies, so the list can show what a choice brings along. Who reads
the users reads it: the codes are no secret to whoever sees them in a row.

`acl_roles` is also the validator of `User.roles` (model.yaml): a list of
declared role codes. The column is plain JSON, and whoever writes it directly,
from the form or through the API, is told which code is unknown rather than
having a typo kept, holding nothing.
"""
from typing import Any, Dict, List, Optional

import kitebase.utils
from kitebase.endpoints import endpoint
from kitebase.i18n import _
from kitebase.transforms import register_validator

from acl.guard import _items


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
