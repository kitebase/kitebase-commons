"""The moves of a record through its states, as lines of its history.

    from activities.moves import track_moves

    track_moves('Task')          # in the rules of the plugin that owns Task

A table with a `state` (kitebase/state.py) whose changes are worth telling
asks for it by name. Each change is a done activity of the type `stage` on
the record, and through `activities.follow` on its parents: "From To do to
In review". Moves made close together by the same person are one line: a card
tried in two columns leaves "From A to C", and one moved back where it was
leaves none.

The value a record started from travels in `source` (`state:<value>`), so the
line can be rewritten without reading its text. A line written in between by
anything else (a closing, a note) ends the merge.

A call rather than a key in the model: the rule is registered on the table
named, as any rule of a plugin, and a table that does not ask has none.
"""
from datetime import timedelta
from typing import Any, Optional

import kitebase.context
import kitebase.utils
from kitebase import apptime, state
from kitebase.flow import on_write
from kitebase.i18n import _, _f

from activities.api import log_activity, register_type

# Moves by the same person closer than this are one line
MERGE_MINUTES = 10

SOURCE = 'state:'

register_type('stage', 'Stage', 'git-commit-horizontal', pick=False)


def track_moves(table: str) -> None:
    """Tell every change of the state of `table` in the history of the record."""
    @on_write(table, 'commit')
    def state_moves(ctx):
        if ctx.mode != 'update':
            return
        column = _state_column(table)
        old, new = (ctx.original or {}).get(column), ctx.record.get(column)
        if column is None or _same(old, new):
            return
        _moved(ctx, table, column, old, new)


def _same(a: Any, b: Any) -> bool:
    return str(a) == str(b) if a is not None and b is not None else a is b


def _state_column(table: str) -> Optional[str]:
    declared = state.declared(kitebase.utils.get_app().tables[table])
    return declared['column'] if declared else None


def _label(session: Any, table: str, column: str, value: Any) -> str:
    """A value of the state as a person reads it: the name of the row it
    points to, or the label of its choice."""
    if value is None:
        return _('none')
    app = kitebase.utils.get_app()
    info = state.state_info(app.tables[table]) or {}
    target = info.get('target')
    if target:
        field = app.tables[target].search_info.get('display_field')
        row = session.get(app.models[target], value)
        text = getattr(row, field, None) if row is not None and field else None
        return str(text) if text not in (None, '') else '?'
    col = next((c for c in app.tables[table].effective_columns if c.name == column), None)
    for choice in (col.attributes.get('choices') or []) if col is not None else []:
        if str(choice.get('value')) == str(value):
            return _(str(choice.get('label', value)))
    return str(value)


def _value(text: str, like: Any) -> Any:
    """The value kept in `source`, back in the type of the state."""
    if text == '':
        return None
    return int(text) if isinstance(like, int) and text.lstrip('-').isdigit() else text


def _last_move(ctx, table: str):
    """The last activity of the record, when it is a move the same person
    made a moment ago; None otherwise."""
    app = kitebase.utils.get_app()
    Activity, Link = app.models['Activity'], app.models['ActivityLink']
    last = (ctx.session.query(Activity).join(Link, Link.activity_id == Activity.id)
            .filter(Link.model == table, Link.record_id == str(ctx.record['id']),
                    Link.role == 'owner')
            .order_by(Activity.id.desc()).first())
    me = (kitebase.context.current() or {}).get('id')
    if (last is None or last.type_id != 'stage' or not (last.source or '').startswith(SOURCE)
            or last.author_id != me or last.done_at is None
            or last.done_at < apptime.now() - timedelta(minutes=MERGE_MINUTES)):
        return None
    return last


def _moved(ctx, table: str, column: str, old: Any, new: Any) -> None:
    session = ctx.session
    last = _last_move(ctx, table)
    origin = _value(last.source[len(SOURCE):], new) if last is not None else old
    if last is not None and _same(origin, new):
        session.delete(last)            # back where it was: nothing happened
        return
    subject = _f('From {old} to {new}', old=_label(session, table, column, origin),
                 new=_label(session, table, column, new))
    if last is not None:
        last.subject, last.done_at = subject, apptime.now()
        return
    log_activity((table, ctx.record['id']), 'stage', subject,
                 source=f'{SOURCE}{"" if old is None else old}', session=session)
