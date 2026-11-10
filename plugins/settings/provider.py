"""The catalog of the settings, the rows that override it, and the provider.

The catalog is the `settings:` root of the merged tree: groups, each with its
items, declared by the plugins that use them. A key is `group.item`:

    settings:
      acquisitions:
        label: Purchasing
        items:
          - name: default_discount
            type: Percent
            default: 10
            help: "Proposed for the lines of a new order"

Values are what a form sends and JSON keeps: numbers, strings, booleans, dates
as ISO strings, and anything under `Json`. A Decimal type gives a number checked
against its precision and scale; code that computes with it converts.
"""
import datetime
import decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import kitebase.defaults
import kitebase.utils
from kitebase import settings as port
import kitebase.context
from kitebase.diagnostics import make_issue
from kitebase.i18n import _
from kitebase.sections import register_section

ROOT = 'settings'
VOCABULARY = Path(__file__).with_name('vocabulary') / 'settings.yaml'


def _items(mapping: Dict[str, Any]):
    return [(k, v) for k, v in (mapping or {}).items() if not str(k).startswith('$')]


def catalog(app: Any) -> Dict[str, Dict[str, Any]]:
    """Every declared setting by key, in the order of the YAML."""
    out: Dict[str, Dict[str, Any]] = {}
    for group, definition in _items(app.plugins.data.get(ROOT)):
        if not isinstance(definition, dict):
            continue
        for item in definition.get('items') or []:
            if isinstance(item, dict) and item.get('name'):
                key = f"{group}.{item['name']}"
                out[key] = {**{k: v for k, v in item.items() if not str(k).startswith('$')},
                            'key': key, 'group': group,
                            'plugin': item.get('$plugin') or definition.get('$plugin')}
    return out


def groups(app: Any) -> Dict[str, Dict[str, Any]]:
    """The groups, with their label and help."""
    return {g: d for g, d in _items(app.plugins.data.get(ROOT)) if isinstance(d, dict)}


# ── Types ─────────────────────────────────────────────────────────────────────

def coerce(app: Any, type_name: str, value: Any) -> Tuple[Any, Optional[str]]:
    """The value as it is kept, or the reason it cannot be: (value, error).

    The type comes from the type registry, resolved to its Python type with the
    attributes along its chain (`Percent` is a Numeric of precision 5, scale 2).
    None is always accepted: the setting has no value.
    """
    info = (app.get_type_schema(include_builtin=True) or {}).get(type_name)
    if info is None:
        return None, _("unknown type '{t}'").format(t=type_name)
    if value is None:
        return None, None
    kind = info.get('python_type')
    try:
        if kind == 'bool':
            if not isinstance(value, bool):
                return None, _('true or false is expected')
            return value, None
        if kind == 'int':
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                return None, _('a whole number is expected')
            return int(value), None
        if kind == 'Decimal' or kind == 'float':
            if isinstance(value, bool):
                return None, _('a number is expected')
            number = decimal.Decimal(str(value))
            if not number.is_finite():
                return None, _('a number is expected')
            scale, precision = info.get('scale'), info.get('precision')
            if scale is not None and -number.as_tuple().exponent > scale:
                return None, _('at most {n} decimals').format(n=scale)
            if precision is not None and scale is not None:
                if abs(number) >= decimal.Decimal(10) ** (precision - scale):
                    return None, _('at most {n} digits before the point').format(
                        n=precision - scale)
            return (int(number) if number == number.to_integral_value() else float(number)), None
        if kind == 'str':
            if not isinstance(value, str):
                return None, _('a text is expected')
            length = info.get('length')
            if length is not None and len(value) > length:
                return None, _('at most {n} characters').format(n=length)
            return value, None
        if kind == 'date':
            return datetime.date.fromisoformat(str(value)).isoformat(), None
        if kind == 'datetime':
            return datetime.datetime.fromisoformat(str(value)).isoformat(), None
        return value, None                      # object: Json, kept as it is
    except (ValueError, decimal.InvalidOperation):
        return None, _('not a valid value')


# ── Rows ──────────────────────────────────────────────────────────────────────

def _model(app: Any):
    return app.models['Setting']


def rows(app: Any, keys: Optional[List[str]] = None) -> Dict[str, Any]:
    """The overrides by key."""
    model = _model(app)
    with app.get_session() as session:
        query = session.query(model)
        if keys is not None:
            query = query.filter(model.key.in_(keys))
        return {r.key: r.value for r in query.all()}


def write(app: Any, values: Dict[str, Any], reset: List[str] = ()) -> None:
    """Record decisions: a row for each value that differs from the one in
    force, and none for a value that is already it. A row is kept even when its
    value equals the catalog's default: the installation chose it, and a later
    default must not change it. Only `reset` deletes rows: those keys follow the
    catalog again. The values are already coerced."""
    entries = catalog(app)
    model = _model(app)
    user = (kitebase.context.current() or {}).get('id')
    with app.get_session() as session:
        for key in reset:
            row = session.get(model, key)
            if row is not None:
                session.delete(row)
        for key, value in values.items():
            if key in reset:
                continue
            row = session.get(model, key)
            in_force = row.value if row is not None else entries[key].get('default')
            if value == in_force:
                continue
            if row is None:
                session.add(model(key=key, value=value, updated_by=user))
            else:
                row.value = value
                row.updated_at = kitebase.defaults.now()
                row.updated_by = user
        session.commit()


def delete(app: Any, keys: List[str]) -> None:
    """Delete the rows of these keys, whatever the catalog says of them."""
    if not keys:
        return
    model = _model(app)
    with app.get_session() as session:
        session.query(model).filter(model.key.in_(keys)).delete(synchronize_session=False)
        session.commit()


# ── The provider ──────────────────────────────────────────────────────────────

class TableProvider(port.SettingsProvider):
    """The row of the key, or the catalog's default."""

    def get(self, key: str) -> Any:
        app = kitebase.utils.get_app()
        entry = catalog(app)[key]              # KeyError: not declared
        found = rows(app, [key])
        return found[key] if key in found else entry.get('default')

    def has(self, key: str) -> bool:
        return key in catalog(kitebase.utils.get_app())


# ── check ─────────────────────────────────────────────────────────────────────

def check_catalog(app: Any) -> List[Dict[str, Any]]:
    """A type the registry does not have, or a default its type refuses, is an
    error: the form and the reading would break. A group without a label or an
    item without a help is a warning: the help is the user's documentation."""
    issues = []
    for group, definition in groups(app).items():
        if not definition.get('label'):
            issues.append(make_issue('warning', 'setting-group-label', f'{ROOT}.{group}',
                                     'the group has no label: the form has no title',
                                     definition.get('$plugin')))
    known = app.get_type_schema(include_builtin=True) or {}
    for key, entry in catalog(app).items():
        path, plugin = f'{ROOT}.{key}', entry.get('plugin')
        if entry.get('type') not in known:
            issues.append(make_issue('error', 'setting-type', path,
                                     f"type '{entry.get('type')}' is not in the type registry",
                                     plugin))
            continue
        _value, error = coerce(app, entry['type'], entry.get('default'))
        if error:
            issues.append(make_issue('error', 'setting-default', path,
                                     f"the default does not fit {entry['type']}: {error}",
                                     plugin))
        if not entry.get('help'):
            issues.append(make_issue('warning', 'setting-help', path,
                                     'the setting has no help: the user sees no explanation',
                                     plugin))
    return issues


register_section(ROOT, check=check_catalog, vocabulary=VOCABULARY)
port.set_settings_provider(TableProvider())
