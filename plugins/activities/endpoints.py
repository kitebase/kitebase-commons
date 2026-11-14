"""The activities as a person reads and changes them.

`activity_timeline` is the history of one record: the activities linked to
it, to do first (overdue, today, upcoming), then the done ones, newest first.
`activity_mine` is what the current user has to do, or the user `user_id`
names, for whoever reads every activity. Both take `state`, `todo`, `done` or
`all`: the timeline shows all, the user's list what is to do. `activity_add`
writes an activity, on a record or personal, `activity_done` marks one done or
to do again, `activity_postpone` moves it to another day. `activity_types` is
the vocabulary a form picks from.

Who sees an activity: whoever reads one of the records it is linked to, the
user it is assigned to, its author, and whoever reads the table without
condition. Who changes one: the user it is assigned to, its author, and
whoever may update activities and sees one of its records. A record is read
with the user's permissions and record rules (kitebase.refs); the links are
read for the system once the record has been read.
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

from activities.api import log_activity, make_types, priority_text, valid_priority


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
            'author_id': row.author_id,
            'author': label('User', row.author_id) if row.author_id is not None else None,
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


def _concerns_me(activity: Any) -> bool:
    """Assigned to the user, or written by them."""
    me = _me()
    return me is not None and me in (activity.user_id, activity.author_id)


def _may_read(activity: Any, links: List[tuple]) -> bool:
    if _reads_all():
        return True
    return _concerns_me(activity) or any_readable(links)


def _may_change(activity: Any, links: List[tuple]) -> bool:
    if _concerns_me(activity):
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


def _reads_all() -> bool:
    """May read every activity: the table with no record rule on it."""
    return access.can('Activity.read') and access.row_conditions('Activity', 'read') is None


def _state(data: Dict[str, Any], default: str) -> str:
    state = data.get('state') or default
    if state not in ('todo', 'done', 'all'):
        raise Invalid(_("'state' is todo, done or all"))
    return state


def _filtered(query: Any, Activity: Any, state: str) -> Any:
    if state == 'todo':
        return query.filter(Activity.done_at.is_(None))
    if state == 'done':
        return query.filter(Activity.done_at.isnot(None))
    return query


def _record(data: Dict[str, Any], optional: bool = False) -> Optional[tuple]:
    model, record_id = data.get('model'), data.get('id')
    if optional and not model and record_id is None:
        return None
    if not model or record_id is None:
        raise Invalid(_("'model' and 'id' name the record"))
    if not check_readable(str(model), record_id):
        raise NotFound(_f('No {model} {id}', model=model, id=record_id))
    return str(model), str(record_id)


@endpoint('activity_types', access='ActivityType.read')
def activity_types(data):
    """The types a person picks from, as the table holds them: the registered
    ones are made first, so the application finds them all to rename, reorder
    or hide (`pick`). In the order of `sequence`."""
    app = kitebase.utils.get_app()
    Type = app.models['ActivityType']
    with access.system(), app.get_session() as session:
        make_types(session)
        session.commit()
        rows = session.query(Type).filter(Type.pick.is_(True)).order_by(Type.sequence, Type.id)
        return _ok([{'value': r.id, 'label': r.label or r.id, 'icon': r.icon} for r in rows])


@endpoint('activity_timeline', access=access.PER_TABLE)
def activity_timeline(data):
    here = _record(data)
    state = _state(data, 'all')
    app = kitebase.utils.get_app()
    Activity, Link = app.models['Activity'], app.models['ActivityLink']
    with access.system(), app.get_session() as session:
        query = (session.query(Activity).join(Link, Link.activity_id == Activity.id)
                 .filter(Link.model == here[0], Link.record_id == here[1]))
        rows = _filtered(query, Activity, state).all()
        return _ok(_items(session, rows, here))


@endpoint('activity_mine', access=access.AUTHENTICATED)
def activity_mine(data):
    """The activities assigned to the user, or to `user_id`: someone else's
    agenda is read by whoever reads every activity."""
    me = _me()
    state = _state(data, 'todo')
    app = kitebase.utils.get_app()
    Activity = app.models['Activity']
    who = me
    if data.get('user_id') not in (None, ''):
        who = coerce_value(Activity, 'user_id', data['user_id'])
        if who != me and not _reads_all():
            raise access.AccessDenied('Activity.read')
    if who is None:
        return _ok([])
    with access.system(), app.get_session() as session:
        query = session.query(Activity).filter(Activity.user_id == who)
        rows = _filtered(query, Activity, state).all()
        return _ok(_items(session, rows))


@endpoint('activity_add', access='Activity.create')
def activity_add(data):
    """Write an activity on a record the user reads, as the timeline does, or
    with no record, a personal one. It is assigned to the user, or to the
    user `user_id` names: then it is a request from the one who writes it."""
    here = _record(data, optional=True)
    app = kitebase.utils.get_app()
    Activity, User = app.models['Activity'], app.models['User']
    values = {key: coerce_value(Activity, key, data.get(key))
              for key in ('due_date', 'start_at', 'end_at') if data.get(key) not in (None, '')}
    priority = data.get('priority', 0)
    if isinstance(priority, str) and priority.lstrip('-').isdigit():
        priority = int(priority)
    if not valid_priority(priority):
        raise Invalid(priority_text())
    if not data.get('type') or not (data.get('subject') or '').strip():
        raise Invalid(_('An activity needs a type and a subject'))
    if data.get('user_id') not in (None, ''):
        user_id = coerce_value(Activity, 'user_id', data['user_id'])
        with access.system(), app.get_session() as session:
            if session.get(User, user_id) is None:
                raise Invalid(_f('No user {id}', id=data['user_id']))
        values['user_id'] = user_id
    activity_id = log_activity(here, str(data['type']), data['subject'].strip(),
                               note=data.get('note') or None, priority=priority, **values)
    with access.system(), app.get_session() as session:
        return _ok(_items(session, [session.get(Activity, activity_id)], here)[0])


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
