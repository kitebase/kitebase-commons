"""The activities as a person reads and changes them.

`activity_timeline` is the history of one record: the activities linked to
it, to do first (overdue, today, upcoming), then the done ones, newest first.
`activity_mine` is what the current user has to do. `activity_log` writes an
activity on a record, `activity_done` marks one done or to do again,
`activity_postpone` moves it to another day. `activity_types` is the
vocabulary a form picks from.

Who sees an activity: whoever reads one of the records it is linked to, the
user it is assigned to, and whoever reads the table without condition. Who
changes one: the user it is assigned to, and whoever may update activities
and sees one of its records. A record is read with the user's permissions and
record rules (kitebase.refs); the links are read for the system once the
record has been read.
"""
import datetime
from typing import Any, Dict, Iterable, List, Optional

import kitebase.context
import kitebase.utils
from kitebase import access, apptime
from kitebase.endpoint_db import coerce_value
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound
from kitebase.i18n import _, _f
from kitebase.refs import any_readable, check_readable, label

from activities.api import log_activity, priority_text, valid_priority


def _ok(data: Any) -> Dict[str, Any]:
    return {'status': 'success', 'code': 200, 'data': data}


def _me() -> Optional[Any]:
    return (kitebase.context.current() or {}).get('id')


def _day(activity: Any) -> Optional[datetime.date]:
    if activity.due_date is not None:
        return activity.due_date
    return activity.start_at.date() if activity.start_at is not None else None


def _when(activity: Any, today: datetime.date) -> str:
    if activity.done_at is not None:
        return 'done'
    day = _day(activity)
    if day is None:
        return 'open'
    return 'overdue' if day < today else 'today' if day == today else 'upcoming'


_ORDER = {'overdue': 0, 'today': 1, 'upcoming': 2, 'open': 3}


def _sorted(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """To do first, by group (overdue, today, upcoming), then priority, higher
    first, then day; then the done ones, newest first."""
    todo = sorted((i for i in items if i['when'] != 'done'),
                  key=lambda i: (_ORDER[i['when']], -i['priority'], i['day'] or ''))
    done = sorted((i for i in items if i['when'] == 'done'),
                  key=lambda i: i['done_at'] or '', reverse=True)
    return todo + done


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.isoformat(sep=' ', timespec='minutes')
    return value.isoformat()


def _items(session: Any, rows: Iterable[Any], here: Optional[tuple] = None) -> List[Dict[str, Any]]:
    """The activities as the client shows them, each with the record it was
    written on when that is not `here`, named as the user may read it."""
    app = kitebase.utils.get_app()
    Link = app.models['ActivityLink']
    rows = list(rows)
    owners: Dict[Any, Any] = {}
    if rows:
        for link in session.query(Link).filter(Link.activity_id.in_([r.id for r in rows]),
                                               Link.role == 'owner'):
            owners[link.activity_id] = (link.model, link.record_id)
    today = apptime.today()
    out = []
    for row in rows:
        owner = owners.get(row.id)
        day = _day(row)
        out.append({
            'id': row.id, 'type': row.type_id,
            'type_label': row.type.label if row.type is not None else row.type_id,
            'icon': row.type.icon if row.type is not None else None,
            'subject': row.subject, 'note': row.note,
            'user_id': row.user_id,
            'user': label('User', row.user_id) if row.user_id is not None else None,
            'start_at': _iso(row.start_at), 'end_at': _iso(row.end_at),
            'due_date': _iso(row.due_date), 'done_at': _iso(row.done_at),
            'day': _iso(day), 'when': _when(row, today),
            'priority': row.priority, 'source': row.source,
            'owner': None if owner is None or owner == here else {
                'model': owner[0], 'id': owner[1], 'label': label(*owner)},
        })
    return _sorted(out)


def _links(session: Any, activity_id: Any) -> List[tuple]:
    Link = kitebase.utils.get_app().models['ActivityLink']
    return [(link.model, link.record_id) for link in
            session.query(Link).filter(Link.activity_id == activity_id)]


def _may_read(activity: Any, links: List[tuple]) -> bool:
    if access.can('Activity.read') and access.row_conditions('Activity', 'read') is None:
        return True
    if activity.user_id is not None and activity.user_id == _me():
        return True
    return any_readable(links)


def _may_change(activity: Any, links: List[tuple]) -> bool:
    if activity.user_id is not None and activity.user_id == _me():
        return True
    return access.can('Activity.update') and any_readable(links)


def _activity(session: Any, data: Dict[str, Any], change: bool = False) -> Any:
    """The activity `data['id']` names, if the user may read it, or change it."""
    Activity = kitebase.utils.get_app().models['Activity']
    row = session.get(Activity, coerce_value(Activity, 'id', data.get('id')))
    if row is None:
        raise NotFound(_f('No activity {id}', id=data.get('id')))
    links = _links(session, row.id)
    if not _may_read(row, links):
        raise NotFound(_f('No activity {id}', id=data.get('id')))
    if change and not _may_change(row, links):
        raise access.AccessDenied('Activity.update')
    return row


def _record(data: Dict[str, Any]) -> tuple:
    model, record_id = data.get('model'), data.get('id')
    if not model or record_id is None:
        raise Invalid(_("'model' and 'id' name the record"))
    if not check_readable(str(model), record_id):
        raise NotFound(_f('No {model} {id}', model=model, id=record_id))
    return str(model), str(record_id)


@endpoint('activity_types', access='ActivityType.read')
def activity_types(data):
    app = kitebase.utils.get_app()
    Type = app.models['ActivityType']
    with app.get_session() as session:
        rows = session.query(Type).order_by(Type.sequence, Type.id).all()
        return _ok([{'value': r.id, 'label': r.label or r.id, 'icon': r.icon} for r in rows])


@endpoint('activity_timeline', access=access.PER_TABLE)
def activity_timeline(data):
    here = _record(data)
    app = kitebase.utils.get_app()
    Activity, Link = app.models['Activity'], app.models['ActivityLink']
    with access.system(), app.get_session() as session:
        rows = (session.query(Activity).join(Link, Link.activity_id == Activity.id)
                .filter(Link.model == here[0], Link.record_id == here[1]).all())
        return _ok(_items(session, rows, here))


@endpoint('activity_mine', access=access.AUTHENTICATED)
def activity_mine(data):
    me = _me()
    if me is None:
        return _ok([])
    app = kitebase.utils.get_app()
    Activity = app.models['Activity']
    with access.system(), app.get_session() as session:
        rows = (session.query(Activity)
                .filter(Activity.user_id == me, Activity.done_at.is_(None)).all())
        return _ok(_items(session, rows))


@endpoint('activity_log', access='Activity.create')
def activity_log(data):
    """Write an activity on a record the user reads, as the timeline does."""
    model, record_id = _record(data)
    Activity = kitebase.utils.get_app().models['Activity']
    values = {key: coerce_value(Activity, key, data.get(key))
              for key in ('due_date', 'start_at', 'end_at') if data.get(key) not in (None, '')}
    priority = data.get('priority', 0)
    if isinstance(priority, str) and priority.lstrip('-').isdigit():
        priority = int(priority)
    if not valid_priority(priority):
        raise Invalid(priority_text())
    if not data.get('type') or not (data.get('subject') or '').strip():
        raise Invalid(_('An activity needs a type and a subject'))
    activity_id = log_activity((model, record_id), str(data['type']), data['subject'].strip(),
                               note=data.get('note') or None, priority=priority, **values)
    app = kitebase.utils.get_app()
    with access.system(), app.get_session() as session:
        return _ok(_items(session, [session.get(Activity, activity_id)], (model, record_id))[0])


@endpoint('activity_done', access=access.PER_TABLE)
def activity_done(data):
    """Mark an activity done, or to do again (`done: false`) if it has a date."""
    app = kitebase.utils.get_app()
    with access.system(), app.get_session() as session:
        row = _activity(session, data, change=True)
        if data.get('done', True):
            if row.done_at is None:
                row.done_at = apptime.now()
        elif _day(row) is None:
            raise Invalid(_('With no date an activity is a fact: give it a date to make it to do'))
        else:
            row.done_at = None
        session.commit()
        return _ok(_items(session, [row])[0])


@endpoint('activity_postpone', access=access.PER_TABLE)
def activity_postpone(data):
    """Move a thing to do to another day: an appointment keeps its time of day."""
    app = kitebase.utils.get_app()
    Activity = app.models['Activity']
    day = coerce_value(Activity, 'due_date', data.get('date'))
    if not isinstance(day, datetime.date):
        raise Invalid(_("'date' is the new day, as YYYY-MM-DD"))
    with access.system(), app.get_session() as session:
        row = _activity(session, data, change=True)
        if row.done_at is not None:
            raise Invalid(_('A done activity is not postponed'))
        if row.start_at is not None:
            shift = day - row.start_at.date()
            row.start_at += shift
            if row.end_at is not None:
                row.end_at += shift
        if row.due_date is not None or row.start_at is None:
            row.due_date = day
        session.commit()
        return _ok(_items(session, [row])[0])
