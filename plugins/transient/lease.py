"""
Leases: who holds what, since when, alive until when.

A lease is a row about a subject (a document, or nothing) held by a holder
(`user:3`, `work:<key>`, a process). Taking it again renews it; nothing renews
it and it expires by itself. Whoever reads asks for the live ones only, so an
expired row is already gone for everybody before the sweep deletes it.

Every function works on the caller's session and leaves the commit to it: a
presence is taken in the transaction of its request, a work in progress writes
in a session of its own so that its state shows while the work runs.

    with app.get_session() as session:
        hold(session, 'work:42', ttl=120, user_id=3, doing='Fetching... 3 of 12')
        session.commit()

    live(session, user_id=3)                  # what a person has open
    live(session, model='Order', record_id='7')   # who is on a document
"""
from datetime import timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError

import kitebase.utils
from kitebase import apptime

LEASE = 'Lease'

# What a holder may say about itself; the rest of the row is the lease's own
FIELDS = ('user_id', 'user_name', 'doing', 'done', 'total', 'cancellable',
          'cancel_requested')


def find_app():
    """The application, when it has the lease table; None otherwise."""
    app = kitebase.utils.get_app()
    try:
        return app if app.find_model_class(LEASE) is not None else None
    except AttributeError:      # no database open
        return None


def table(app=None):
    app = app or kitebase.utils.get_app()
    return app.find_model_class(LEASE).__table__


def _subject(t, model: str, record_id: Any):
    return and_(t.c.model == (model or ''), t.c.record_id == str(record_id or ''))


def _mine(t, holder: str, model: str, record_id: Any):
    return and_(_subject(t, model, record_id), t.c.holder == holder)


def _fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise TypeError(f"A lease has no field {', '.join(sorted(unknown))}")
    return fields


def hold(session, holder: str, ttl: int, *, model: str = '', record_id: Any = '',
         **fields: Any) -> bool:
    """
    Take the lease of `holder` on a subject, or renew it: alive `ttl` seconds
    from now, `since` the first time. The fields given replace theirs.
    Returns True when the lease was taken now, False when renewed.
    """
    t, now = table(), apptime.now()
    values = {'last_activity': now, 'expires_at': now + timedelta(seconds=ttl),
              **_fields(fields)}
    mine = _mine(t, holder, model, record_id)
    if session.execute(update(t).where(mine).values(**values)).rowcount:
        return False
    try:
        with session.begin_nested():
            session.execute(t.insert().values(
                model=model or '', record_id=str(record_id or ''), holder=holder,
                since=now, **values))
        return True
    except IntegrityError:
        # Taken at the same instant by another request of the same holder
        session.execute(update(t).where(mine).values(**values))
        return False


def get(session, holder: str, *, model: str = '', record_id: Any = '') -> Optional[Dict[str, Any]]:
    """The live lease of `holder` on a subject, or None."""
    t = table()
    row = session.execute(select(t).where(
        _mine(t, holder, model, record_id), t.c.expires_at > apptime.now())).mappings().first()
    return dict(row) if row else None


def live(session, *, model: Optional[str] = None, record_id: Any = None,
         user_id: Optional[int] = None, holder: Optional[str] = None) -> List[Dict[str, Any]]:
    """The live leases that match, the longest held first."""
    t = table()
    where = [t.c.expires_at > apptime.now()]
    if model is not None:
        where.append(_subject(t, model, record_id))
    if user_id is not None:
        where.append(t.c.user_id == user_id)
    if holder is not None:
        where.append(t.c.holder == holder)
    rows = session.execute(select(t).where(*where).order_by(t.c.since)).mappings().all()
    return [dict(row) for row in rows]


def mark(session, holder: str, *, model: str = '', record_id: Any = '',
         **fields: Any) -> bool:
    """Change fields of a live lease without renewing it: someone else speaks
    about it (a cancel asked). Returns whether there was one."""
    t = table()
    return bool(session.execute(update(t).where(
        _mine(t, holder, model, record_id), t.c.expires_at > apptime.now())
        .values(**_fields(fields))).rowcount)


def release(session, holder: str, *, model: str = '', record_id: Any = '') -> None:
    """End a lease. A courtesy: it expires anyway."""
    t = table()
    session.execute(delete(t).where(_mine(t, holder, model, record_id)))


def forget(connection, subjects: Iterable[Tuple[str, Any]]) -> None:
    """The leases on subjects that no longer exist (documents deleted), in the
    transaction that deletes them."""
    subjects = list(subjects)
    if not subjects:
        return
    t = table()
    connection.execute(delete(t).where(or_(*[_subject(t, m, k) for m, k in subjects])))


def sweep(session, *, model: Optional[str] = None, record_id: Any = None) -> int:
    """Delete what expired, everywhere or on one subject. Order, not
    correctness: an expired row is already invisible to every reader."""
    t = table()
    where = [t.c.expires_at <= apptime.now()]
    if model is not None:
        where.append(_subject(t, model, record_id))
    return session.execute(delete(t).where(*where)).rowcount
