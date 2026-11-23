"""
Who is editing a document now: advice, never a lock.

A person shows up at the first change of a form, not when it opens: whoever
looks writes nothing. The form renews the presence from the person's activity
(`touch`, at most once a minute and only after something happened), and the
presence expires by itself when nothing renews it: the colleague at the coffee
machine leaves the list, not the document. Releasing at the save or at the
close is a courtesy; a tab closed from its handle releases nothing, and nothing
is wrong for that.

Every answer brings the news: the current version of the document (someone
saved?) and who else is there. Opening a document brings them too, as `$`
keys on the root of `load_tree`, without a call of its own.

A long procedure says what it is doing the same way, and whoever opens the
document sees it as they would see a person:

    with editing('Order', 7, doing='Shipping in progress'):
        ...

The presences are leases of `transient` on the document: a person holds
`user:<id>`, a procedure a key of its own.
"""
import secrets
import time
from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import delete, select, update

import kitebase.context
import kitebase.utils
from kitebase import access, apptime
from kitebase.endpoint_tree import before_tree_load
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound

from concurrency.markers import MARKER
from transient import lease

# The defaults of the `concurrency:` section of the application's config.yaml
DEFAULTS = {
    'presence_ttl': 900,        # seconds without activity before a person leaves the list
    'touch_every': 60,          # at most one renewal per this many seconds, from a form
    'marker_horizon': 86400,    # markers untouched this long are swept
}
# How often a request sweeps the whole tables, in this process
SWEEP_EVERY = 3600
_last_sweep: Optional[float] = None


def settings() -> Dict[str, int]:
    app = kitebase.utils.get_app()
    found = (getattr(app.plugins, 'config', None) or {}).get('concurrency') or {}
    return {key: int(found.get(key, value)) for key, value in DEFAULTS.items()}


def _app():
    """The application, when it has the lease table; None otherwise."""
    return lease.find_app()


def _me() -> Dict[str, Any]:
    """The person asking: the holder of their presence and the name others see."""
    ctx = kitebase.context.current() or {}
    if ctx.get('id') is None:
        raise Invalid('A presence needs a user')
    return {'holder': f"user:{ctx['id']}", 'user_id': ctx['id'],
            'user_name': ctx.get('full_name') or ctx.get('username') or str(ctx['id'])}


def _others(session, model: str, key: str, holder: Optional[str]) -> List[Dict[str, Any]]:
    """Who else is there and not expired, the longest there first."""
    now = apptime.now()
    # Seconds, measured here: the client's clock is not this one
    return [{'user_name': row['user_name'], 'doing': row['doing'],
             'for': int((now - row['since']).total_seconds()),
             'idle': int((now - row['last_activity']).total_seconds())}
            for row in lease.live(session, model=model, record_id=key)
            if row['holder'] != holder]


def _version(app, session, model: str, key: str) -> Optional[str]:
    markers = app.find_model_class(MARKER).__table__
    return session.execute(select(markers.c.token).where(
        markers.c.model == model, markers.c.record_id == key)).scalar()


def _news(app, session, model: str, key: str, holder: Optional[str]) -> Dict[str, Any]:
    return {'version': _version(app, session, model, key),
            'others': _others(session, model, key, holder),
            'every': settings()['touch_every']}




# ── The endpoints of a form ───────────────────────────────────────────────────

def _document(app, session, data: Dict[str, Any]):
    """The root a call is about, once the person may read it."""
    model, record_id = data.get('model'), data.get('id')
    if not model or record_id is None:
        raise Invalid('model and id are required')
    cls = app.find_model_class(model)
    if cls is None:
        raise NotFound(f"No table '{model}'")
    access.check_table(model, 'read')
    if not access.row_visible(session, cls, record_id):
        raise NotFound(f"No record {record_id} in '{model}'")
    return model, str(record_id)


def _call(data: Dict[str, Any], act) -> Dict[str, Any]:
    app = _app()
    if app is None:
        return {'status': 'success', 'data': {'version': None, 'others': [], 'every': 0}}
    me = _me()
    with app.get_session() as session:
        model, key = _document(app, session, data)
        act(session, app, model, key, me)
        news = _news(app, session, model, key, me['holder'])
        session.commit()
    _sweep(app)
    return {'status': 'success', 'data': news}


@endpoint('presence_touch', access=access.AUTHENTICATED)
def presence_touch(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    I am editing this document: take or renew my presence.

    Parameters: model, id of the root.
    Returns: { version, others: [{user_name, doing, for, idle}], every }, the
    seconds in `for` and `idle` measured by the server.
    """
    def act(session, app, model, key, me):
        lease.hold(session, me['holder'], settings()['presence_ttl'], model=model,
                   record_id=key, user_id=me['user_id'], user_name=me['user_name'])
        # The expired ones of this document go now: the global sweep is rarer
        lease.sweep(session, model=model, record_id=key)
        markers = app.find_model_class(MARKER).__table__
        session.execute(update(markers).where(markers.c.model == model, markers.c.record_id == key)
                        .values(touched_at=apptime.now()))
    return _call(data, act)


@endpoint('presence_who', access=access.AUTHENTICATED)
def presence_who(data: Dict[str, Any]) -> Dict[str, Any]:
    """Who is editing this document, and its version, writing nothing. As `presence_touch`."""
    return _call(data, lambda *args: None)


@endpoint('presence_release', access=access.AUTHENTICATED)
def presence_release(data: Dict[str, Any]) -> Dict[str, Any]:
    """I am no longer editing this document. A courtesy: the presence expires anyway."""
    return _call(data, lambda session, app, model, key, me:
                 lease.release(session, me['holder'], model=model, record_id=key))


@before_tree_load
def present(model: str, record_id: Any) -> Optional[Dict[str, Any]]:
    """Who is editing a document as it opens, beside its version."""
    app = _app()
    if app is None or model in (MARKER, lease.LEASE):
        return None
    holder = None
    ctx = kitebase.context.current() or {}
    if ctx.get('id') is not None:
        holder = f"user:{ctx['id']}"
    with app.get_session() as session:
        others = _others(session, model, str(record_id), holder)
    return {'$presence': {'others': others, 'every': settings()['touch_every']}}


# ── A procedure that says what it is doing ────────────────────────────────────

def acquire(model: str, record_id: Any, doing: str, ttl: Optional[int] = None) -> str:
    """
    Show a procedure as present on a document, for `ttl` seconds (the
    presence ttl by default). Returns its holder, for `release`; acquiring
    again with it renews the lease. Committed at once, in a session of its own.
    """
    app = _app()
    holder = f"proc:{secrets.token_hex(8)}"
    if app is None:
        return holder
    ctx = kitebase.context.current() or {}
    with app.get_session() as session:
        lease.hold(session, holder, ttl or settings()['presence_ttl'], model=model,
                   record_id=record_id, user_id=ctx.get('id'),
                   user_name=ctx.get('full_name') or ctx.get('username'), doing=doing)
        session.commit()
    return holder


def release(model: str, record_id: Any, holder: str) -> None:
    """End what `acquire` showed."""
    app = _app()
    if app is None:
        return
    with app.get_session() as session:
        lease.release(session, holder, model=model, record_id=record_id)
        session.commit()


@contextmanager
def editing(model: str, record_id: Any, doing: str, ttl: Optional[int] = None) -> Iterator[str]:
    """`acquire` for the length of a block, released however it ends."""
    holder = acquire(model, record_id, doing, ttl)
    try:
        yield holder
    finally:
        release(model, record_id, holder)


# ── Order, not correctness ────────────────────────────────────────────────────

def forget(connection, roots) -> None:
    """The presences of documents deleted, in the transaction that deletes them."""
    if _app() is None or not roots:
        return
    lease.forget(connection, roots)


def sweep(app=None) -> None:
    """The presences expired and the markers untouched past the horizon, everywhere."""
    app = app or _app()
    if app is None:
        return
    now = apptime.now()
    markers = app.find_model_class(MARKER).__table__
    horizon = now - timedelta(seconds=settings()['marker_horizon'])
    with app.get_session() as session:
        lease.sweep(session)
        session.execute(delete(markers).where(markers.c.touched_at < horizon))
        session.commit()


def _sweep(app) -> None:
    """Now and then, from a request: no scheduler, and never at startup, where a
    worker restarting alone would take the presences the others hold."""
    global _last_sweep
    if _last_sweep is not None and time.monotonic() - _last_sweep < SWEEP_EVERY:
        return
    _last_sweep = time.monotonic()
    sweep(app)
