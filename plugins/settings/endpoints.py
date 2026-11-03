"""Reading and writing a group of settings: what the form of a group asks.

`get_settings` gives each item of the group with its default, its value and
whether the installation set it; `set_settings` checks every value with the type
the catalog declares and writes nothing if one is refused, so a form is either
saved whole or told by field. A value set is kept even if it equals the default;
`reset` names the items that go back to following the catalog.
"""
from typing import Any, Dict

import kitebase.utils
from kitebase.endpoints import endpoint
from kitebase.i18n import _

from settings.provider import catalog, coerce, groups, rows, write


def _group(app: Any, name: Any):
    """The group's definition and its items; None if no plugin declares it."""
    definition = groups(app).get(name)
    entries = [e for e in catalog(app).values() if e['group'] == name]
    return definition, entries


def _missing(name: Any) -> Dict[str, Any]:
    return {'status': 'error', 'code': 404,
            'message': _("No settings group '{g}'").format(g=name)}


@endpoint('get_settings', access='Setting.read')
def get_settings(data):
    app, name = kitebase.utils.get_app(), data.get('group')
    definition, entries = _group(app, name)
    if definition is None:
        return _missing(name)
    found = rows(app, [e['key'] for e in entries])
    items = []
    for e in entries:
        is_set = e['key'] in found
        items.append({
            'key': e['key'], 'name': e['name'], 'type': e['type'],
            'label': e.get('label') or e['name'], 'help': e.get('help'),
            'default': e.get('default'),
            'value': found[e['key']] if is_set else e.get('default'),
            'set': is_set,
        })
    return {'status': 'success', 'code': 200,
            'data': {'group': name, 'label': definition.get('label') or name,
                     'help': definition.get('help'), 'items': items}}


@endpoint('set_settings', access='Setting.update')
def set_settings(data):
    app, name = kitebase.utils.get_app(), data.get('group')
    definition, entries = _group(app, name)
    if definition is None:
        return _missing(name)
    by_name = {e['name']: e for e in entries}
    values = data.get('values') or {}
    reset = data.get('reset') or []
    errors, coerced = {}, {}
    for item in reset:
        if item not in by_name:
            errors[item] = _('Not a setting of this group')
    for item, value in values.items():
        entry = by_name.get(item)
        if entry is None:
            errors[item] = _('Not a setting of this group')
            continue
        coerced[entry['key']], error = coerce(app, entry['type'], value)
        if error:
            errors[item] = error
    if errors:
        return {'status': 'error', 'code': 400, 'message': _('Some values are not valid'),
                'data': {'errors': errors}}
    write(app, coerced, [by_name[i]['key'] for i in reset])
    return get_settings({'group': name})
