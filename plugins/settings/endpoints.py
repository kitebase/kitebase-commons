"""Reading and writing a group of settings: what the form of a group asks.

`get_settings` gives each item of the group with its default, its value and
whether the installation set it; `settings_values` gives the values alone, the
record a form loads. `set_settings` checks every value with the type the catalog
declares and writes nothing if one is refused, so a form is either saved whole
or told by field; it answers with the values, as a form's save expects. A value
set is kept even if it equals the default; `reset` names the items that go back
to following the catalog.

`settings_list` is every item of every group, and the rows no catalog declares
any more (orphans), for the administrator's view; `settings_drop_orphans`
deletes those rows.
"""
import json
from typing import Any, Dict, List

import kitebase.utils
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound
from kitebase.i18n import _

from settings.provider import catalog, coerce, delete, groups, rows, write


def _group(app: Any, name: Any):
    """The group's definition and its items; None if no plugin declares it."""
    definition = groups(app).get(name)
    entries = [e for e in catalog(app).values() if e['group'] == name]
    return definition, entries


def _text(value: Any) -> Any:
    """A label or a help of the catalog, in the current locale: the YAML is
    written in English and translated on the way out, as get_page does."""
    return _(value) if isinstance(value, str) and value else value


def _missing(name: Any) -> NotFound:
    return NotFound(_("No settings group '{g}'").format(g=name))


@endpoint('get_settings', access='Setting.read')
def get_settings(data):
    app, name = kitebase.utils.get_app(), data.get('group')
    definition, entries = _group(app, name)
    if definition is None:
        raise _missing(name)
    found = rows(app, [e['key'] for e in entries])
    items = []
    for e in entries:
        is_set = e['key'] in found
        items.append({
            'key': e['key'], 'name': e['name'], 'type': e['type'],
            'label': _text(e.get('label') or e['name']), 'help': _text(e.get('help')),
            'default': e.get('default'),
            'value': found[e['key']] if is_set else e.get('default'),
            'set': is_set,
        })
    return {'status': 'success', 'code': 200,
            'data': {'group': name, 'label': _text(definition.get('label') or name),
                     'help': _text(definition.get('help')), 'items': items}}


def _values(app: Any, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    found = rows(app, [e['key'] for e in entries])
    return {e['name']: found.get(e['key'], e.get('default')) for e in entries}


@endpoint('settings_values', access='Setting.read')
def settings_values(data):
    app, name = kitebase.utils.get_app(), data.get('group')
    definition, entries = _group(app, name)
    if definition is None:
        raise _missing(name)
    return {'status': 'success', 'code': 200, 'data': _values(app, entries)}


@endpoint('set_settings', access='Setting.update')
def set_settings(data):
    app, name = kitebase.utils.get_app(), data.get('group')
    definition, entries = _group(app, name)
    if definition is None:
        raise _missing(name)
    by_name = {e['name']: e for e in entries}
    # `values` from code, `data` from a form's save
    values = data.get('values') or data.get('data') or {}
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
        raise Invalid(_('Some values are not valid'), data={'errors': errors})
    write(app, coerced, [by_name[i]['key'] for i in reset])
    return {'status': 'success', 'code': 200, 'data': _values(app, entries)}


def _shown(value: Any) -> Any:
    """A value as a grid cell: scalars as they are, structures as JSON text."""
    return json.dumps(value) if isinstance(value, (list, dict)) else value


@endpoint('settings_list', access='Setting.read')
def settings_list(data):
    app = kitebase.utils.get_app()
    entries = catalog(app)
    labels = {g: _text(d.get('label') or g) for g, d in groups(app).items()}
    found = rows(app)
    out = []
    for key, e in entries.items():
        is_set = key in found
        out.append({'id': key, 'group': e['group'], 'group_label': labels.get(e['group']),
                    'label': _text(e.get('label') or e['name']), 'type': e['type'],
                    'default': _shown(e.get('default')),
                    'value': _shown(found[key] if is_set else e.get('default')),
                    'state': 'set' if is_set else 'default',
                    'state_label': _('set') if is_set else _('default')})
    for key, value in found.items():
        if key not in entries:
            out.append({'id': key, 'group': key.split('.')[0], 'group_label': None,
                        'label': key, 'type': None, 'default': None,
                        'value': _shown(value), 'state': 'orphan',
                        'state_label': _('orphan')})
    return {'status': 'success', 'code': 200, 'data': out}


@endpoint('settings_drop_orphans', access='Setting.delete')
def settings_drop_orphans(data):
    """Delete the rows no catalog declares: the ticked ones, or all of them."""
    app = kitebase.utils.get_app()
    entries = catalog(app)
    orphans = [k for k in rows(app) if k not in entries]
    asked = data.get('ids')
    if asked:
        orphans = [k for k in orphans if k in asked]
    delete(app, orphans)
    message = (_('{n} orphan settings deleted').format(n=len(orphans)) if orphans
               else _('No orphan setting to delete'))
    return {'status': 'success', 'code': 200, 'data': {'message': message}}
