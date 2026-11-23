"""
The works in progress: what kitebase.notify says, kept where the client reads it.

Each work is a lease of `transient`, held by `work:<key>` (the request id) and
shown to the person who started it. Its row is the last state, not a log:
what it is doing, a counter, whether the current phase may stop. It closes
when the work ends, and expires if nothing renews it (a worker gone).

The client asks `jobs_poll` now and then; the answer says when to come back:
soon while the person has a work open, slowly otherwise. The server decides
the rhythm, the client keeps it. `jobs_cancel` asks a work to stop; it stops
at its first cancellable phase, or never if it has none.
"""
import time
from typing import Any, Dict, Optional

import kitebase.context
import kitebase.notify
import kitebase.utils
from kitebase import access, apptime
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound
from kitebase.i18n import _f

from transient import lease

PREFIX = 'work:'

# The defaults of the `jobs:` section of the application's config.yaml
DEFAULTS = {
    'work_ttl': 120,        # seconds a work lives without a notify (a worker gone)
    'poll_slow': 30,        # seconds between two polls with nothing open
    'poll_fast': 1.5,       # seconds between two polls while a work is open
}
# How often a poll sweeps the expired leases, in this process
SWEEP_EVERY = 3600
_last_sweep: Optional[float] = None


def settings() -> Dict[str, float]:
    app = kitebase.utils.get_app()
    found = (getattr(app.plugins, 'config', None) or {}).get('jobs') or {}
    return {key: type(value)(found.get(key, value)) for key, value in DEFAULTS.items()}


def _person() -> Dict[str, Any]:
    ctx = kitebase.context.current() or {}
    return {'user_id': ctx.get('id'),
            'user_name': ctx.get('full_name') or ctx.get('username')}


class LeaseNotifier(kitebase.notify.Notifier):
    """kitebase.notify on a lease: one row per work, written in a session of its
    own so that it shows while the work runs and its transaction is open."""

    def write(self, key: str, state: Dict[str, Any]) -> bool:
        app = lease.find_app()
        if app is None:
            return False
        holder = PREFIX + key
        with app.get_session() as session:
            lease.hold(session, holder, int(settings()['work_ttl']), **_person(),
                       doing=(state.get('text') or '')[:200], done=state.get('done'),
                       total=state.get('total'), cancellable=bool(state.get('cancellable')))
            row = lease.get(session, holder)
            session.commit()
        return bool(row and row['cancel_requested'])

    def close(self, key: str) -> None:
        app = lease.find_app()
        if app is None:
            return
        with app.get_session() as session:
            lease.release(session, PREFIX + key)
            session.commit()


kitebase.notify.set_notifier(LeaseNotifier())


def _view(row: Dict[str, Any], now) -> Dict[str, Any]:
    return {'key': row['holder'][len(PREFIX):], 'doing': row['doing'],
            'done': row['done'], 'total': row['total'],
            'cancellable': bool(row['cancellable']),
            'cancel_requested': bool(row['cancel_requested']),
            # Seconds, measured here: the client's clock is not this one
            'for': int((now - row['since']).total_seconds())}


@endpoint('jobs_poll', access=access.AUTHENTICATED, quiet=True)
def jobs_poll(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    The works in progress of the person asking, and when to ask again.

    Returns: { works: [{key, doing, done, total, cancellable,
    cancel_requested, for}], next: seconds }
    """
    conf = settings()
    app = lease.find_app()
    person = _person()
    if app is None or person['user_id'] is None:
        return {'works': [], 'next': conf['poll_slow']}
    now = apptime.now()
    with app.get_session() as session:
        rows = [row for row in lease.live(session, user_id=person['user_id'])
                if row['holder'].startswith(PREFIX)]
    _sweep(app)
    return {'works': [_view(row, now) for row in rows],
            'next': conf['poll_fast'] if rows else conf['poll_slow']}


@endpoint('jobs_cancel', access=access.AUTHENTICATED)
def jobs_cancel(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ask a work to stop. Of the person who started it, or of an administrator.
    It stops at its first cancellable phase: until then the line says the
    cancel is waiting.

    Parameters: key, as `jobs_poll` gives it.
    """
    key = data.get('key')
    if not key:
        raise Invalid('key is required')
    app = lease.find_app()
    ctx = kitebase.context.current() or {}
    holder = PREFIX + str(key)
    with app.get_session() as session:
        row = lease.get(session, holder)
        if row is None or (row['user_id'] != ctx.get('id') and not ctx.get('is_admin')):
            raise NotFound(_f('No work {work} in progress', work=key))
        lease.mark(session, holder, cancel_requested=True)
        session.commit()
    return {'status': 'success', 'data': {'key': key}}


def _sweep(app) -> None:
    """Now and then, from a poll: the expired leases, every kind of them."""
    global _last_sweep
    if _last_sweep is not None and time.monotonic() - _last_sweep < SWEEP_EVERY:
        return
    _last_sweep = time.monotonic()
    with app.get_session() as session:
        lease.sweep(session)
        session.commit()
