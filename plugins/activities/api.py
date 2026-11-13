"""Writing activities from code: what a plugin calls when something happens.

    from activities.api import log_activity

    log_activity(('Invoice', 1033), 'email', 'Invoice 1033 sent',
                 also=[('MailLog', 88, 'mail')], source='smtp', session=session)

The record named first is the owner, the one the activity was written on; the
others are concerned by it. Each record reaches the parents its table declares
(`activities: follow: [partner_id]`), and theirs in turn, so the history of a
partner holds what was written on its opportunities and documents.

These functions are for code, which answers for what it writes: they check no
permission. The endpoints check before they call.
"""
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from sqlalchemy import inspect

import kitebase.context
import kitebase.utils
from kitebase import apptime
from kitebase.endpoint_db import coerce_value
from kitebase.errors import Invalid
from kitebase.i18n import _, _f
from kitebase.registry import Registry, caller

Ref = Union[Tuple[str, Any], Tuple[str, Any, Optional[str]], Dict[str, Any]]

# The types a plugin writes, made on first use: code -> (label, icon)
_TYPES: Registry[Tuple[str, Optional[str]]] = Registry('activity_types', 'activity type')

_MISSING = object()

# The range of `priority`: 0 is normal, higher is more urgent.
PRIORITY = (-9, 9)


def _base_types() -> None:
    for code, label, icon in (('note', 'Note', 'sticky-note'), ('call', 'Call', 'phone'),
                              ('meeting', 'Meeting', 'users'), ('email', 'Email', 'mail'),
                              ('todo', 'To do', 'check-square')):
        _TYPES.add(code, (label, icon), owner=__name__)


def register_type(code: str, label: str, icon: Optional[str] = None) -> None:
    """A type this plugin writes: its row is made the first time it is used,
    so a plugin needs no seed. The application may rename it afterwards."""
    _TYPES.add(code, (label, icon), owner=caller())


def settle(values: Dict[str, Any]) -> None:
    """The rule of the date: a row with no date is a fact recorded, done when
    written. A thing to do has a due date or a start."""
    if values.get('done_at') is None and values.get('due_date') is None \
            and values.get('start_at') is None:
        values['done_at'] = apptime.now()


def valid_priority(value: Any) -> bool:
    """A whole number in the range."""
    low, high = PRIORITY
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def priority_text() -> str:
    return _f('The priority is a whole number from {low} to {high}',
              low=PRIORITY[0], high=PRIORITY[1])


def _ref(ref: Ref) -> Tuple[str, str, Optional[str]]:
    if isinstance(ref, dict):
        model, record_id, role = ref.get('model'), ref.get('id'), ref.get('role')
    else:
        model, record_id, role = (tuple(ref) + (None,))[:3]
    if not model or record_id is None:
        raise Invalid(_f('A record is a model and an id, not {ref}', ref=ref))
    return str(model), str(record_id), role


def _type(session: Any, code: str) -> None:
    app = kitebase.utils.get_app()
    Type = app.models['ActivityType']
    if session.get(Type, code) is not None:
        return
    known = _TYPES.get(code)
    if known is None:
        raise Invalid(_f('Unknown activity type: {code}', code=code))
    label, icon = known
    session.add(Type(id=code, label=_(label), icon=icon))
    session.flush()


def parents(session: Any, model: str, record_id: Any) -> List[Tuple[str, str]]:
    """The records an activity on this one reaches too: the foreign keys its
    table names under `activities: follow`, that are set on the row."""
    app = kitebase.utils.get_app()
    table, Model = app.tables.get(model), app.models.get(model)
    if table is None or Model is None:
        return []
    follow = (table.attributes.get('activities') or {}).get('follow') or []
    if not follow:
        return []
    key = inspect(Model).primary_key[0].key
    row = session.get(Model, coerce_value(Model, key, record_id))
    if row is None:
        return []
    columns = {col.name: col for col in table.effective_columns}
    found = []
    for name in follow:
        fk = (columns[name].attributes.get('foreign_key') or {}) if name in columns else {}
        target = fk.get('table')
        if target is None:
            raise ValueError(f"{model}: 'activities: follow' names {name!r}, "
                             f"which is no foreign key of the table")
        value = getattr(row, name, None)
        if value is not None:
            found.append((target.name, str(value)))
    return found


def link(session: Any, activity_id: int, refs: Iterable[Ref]) -> None:
    """Link an activity to records, then to the parents their tables declare,
    and theirs: once each, whatever the paths that reach it. A record named
    keeps the role it was named with; a parent reached has the role `follow`."""
    app = kitebase.utils.get_app()
    Link = app.models['ActivityLink']
    held: Set[Tuple[str, str]] = {
        (m, r) for m, r in session.query(Link.model, Link.record_id)
        .filter(Link.activity_id == activity_id)}
    queue = [_ref(r) for r in refs]
    while queue:
        model, record_id, role = queue.pop(0)
        if (model, record_id) in held:
            continue
        held.add((model, record_id))
        session.add(Link(activity_id=activity_id, model=model, record_id=record_id, role=role))
        queue.extend((m, r, 'follow') for m, r in parents(session, model, record_id))
    session.flush()


def log_activity(on: Ref, type: str, subject: str, *, also: Iterable[Ref] = (),
                 note: Optional[str] = None, user_id: Any = _MISSING,
                 start_at: Any = None, end_at: Any = None, due_date: Any = None,
                 done_at: Any = None, priority: int = 0, source: Optional[str] = None,
                 session: Any = None) -> int:
    """
    Write an activity on the record `on`, linked to the records in `also`;
    the id of the new row. With no date it is a fact, done now (`settle`).

    `user_id` is the person it is assigned to: the current user when not
    given, nobody for the work of the system. With `session` it is written in
    the caller's transaction, which commits it; without, in a session of its own.
    """
    owner = _ref(on)
    others = [_ref(r) for r in also]
    if user_id is _MISSING:
        user_id = (kitebase.context.current() or {}).get('id')
    values = {'type_id': type, 'subject': subject, 'note': note, 'user_id': user_id,
              'start_at': start_at, 'end_at': end_at, 'due_date': due_date,
              'done_at': done_at, 'priority': priority, 'source': source}
    if not valid_priority(priority):
        raise Invalid(priority_text())
    settle(values)

    app = kitebase.utils.get_app()
    if session is None:
        with app.get_session() as own:
            activity_id = _write(own, values, owner, others)
            own.commit()
        return activity_id
    return _write(session, values, owner, others)


def _write(session: Any, values: Dict[str, Any], owner: Tuple[str, str, Optional[str]],
           others: List[Tuple[str, str, Optional[str]]]) -> int:
    _type(session, values['type_id'])
    row = kitebase.utils.get_app().models['Activity'](**values)
    session.add(row)
    session.flush()
    link(session, row.id, [(owner[0], owner[1], owner[2] or 'owner')] + others)
    return row.id


_base_types()
