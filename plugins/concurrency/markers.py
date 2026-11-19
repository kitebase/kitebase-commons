"""
The version of a document, outside its rows.

A document opened in a form gets a marker, `(model, record_id, token)`, read
before its data. Every write that reaches the document through the ORM session
renews the token, when a marker exists: a row of a collection renews the token
of its root, found by climbing the foreign keys declared `owned`. Documents
nobody opened in a form have no marker, and their writes cost nothing more.

A save that carries the token it loaded (`$version` on the root) checks it and
renews it in one statement, before any row of the tree is written:

    UPDATE edit_markers SET token = :new
     WHERE model = 'Order' AND record_id = '7' AND token = :loaded

No row updated is a conflict: the save rolls back whole and answers with the
document as it is now. A missing marker is a conflict too, spurious but on the
safe side. The statement locks the marker until the commit, so two saves of one
document queue up and the second finds the token changed.

A save without a version is not checked (a procedure reading and writing in one
transaction has no old version to defend), but it renews the token all the
same: whoever holds the document open learns it at the save.

Writes the session does not see (bulk updates, SQL) are not seen here: a
procedure that writes that way names the documents it touched with `touched`.
"""
import secrets
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import and_, delete, event, inspect as sa_inspect, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import kitebase.utils
from kitebase import apptime
from kitebase.endpoint_tree import TreeWrite, before_tree_load, before_tree_write
from kitebase.errors import Conflict
from kitebase.i18n import _

MARKER = 'EditMarker'

# A document: the model of its root and the key, as text
Root = Tuple[str, str]

# Per session: the roots its flushes touched, waiting for the end of the flush,
# and the roots a save already renewed, which its own rows must not renew again.
_PENDING = 'concurrency.pending'
_CLAIMED = 'concurrency.claimed'


def _app():
    """The application, when it has the marker table; None otherwise."""
    app = kitebase.utils.get_app()
    try:
        return app if app.find_model_class(MARKER) is not None else None
    except AttributeError:      # no database open
        return None


def _table(app):
    return app.find_model_class(MARKER).__table__


def _token() -> str:
    return secrets.token_hex(16)


def _where(table, roots: Iterable[Root]):
    return or_(*[and_(table.c.model == model, table.c.record_id == key)
                 for model, key in roots])


# ── Opening and saving a document ─────────────────────────────────────────────

@before_tree_load
def version(model: str, record_id: Any) -> Optional[Dict[str, Any]]:
    """The version of a document opened in a form, its marker created if missing."""
    app = _app()
    if app is None or model == MARKER:
        return None
    table, key = _table(app), str(record_id)
    one = and_(table.c.model == model, table.c.record_id == key)
    with app.get_session() as session:
        token = session.execute(select(table.c.token).where(one)).scalar()
        if token is not None:
            session.execute(update(table).where(one).values(touched_at=apptime.now()))
            session.commit()
            return {'$version': token}
        token = _token()
        try:
            session.execute(table.insert().values(model=model, record_id=key, token=token,
                                                  touched_at=apptime.now()))
            session.commit()
        except IntegrityError:
            # Opened at the same instant by someone else: theirs is the marker
            session.rollback()
            token = session.execute(select(table.c.token).where(one)).scalar()
    return {'$version': token}


@before_tree_write
def check(write: TreeWrite) -> Optional[Dict[str, Any]]:
    """A save that brings a version: the version must still be the stored one."""
    app = _app()
    loaded = write.meta.get('$version')
    if app is None or write.action == 'create' or loaded is None:
        return None
    table, root = _table(app), (write.model, str(write.id))
    token = _token()
    done = write.session.execute(
        update(table).where(_where(table, [root]), table.c.token == str(loaded))
        .values(token=token, touched_at=apptime.now()))
    if done.rowcount != 1:
        raise Conflict(_('Someone else saved this document after you opened it: '
                         'your changes were not saved'), data={'reason': 'version'})
    write.session.info.setdefault(_CLAIMED, set()).add(root)
    return {'$version': token}


def touched(session: Session, roots: Iterable[Tuple[str, Any]]) -> None:
    """
    Renew the version of documents written where the session does not see:
    a bulk update, SQL. `roots` are `(model, key)` of the roots of the
    documents. Committed with the session's transaction.
    """
    app = _app()
    roots = {(model, str(key)) for model, key in roots}
    if app is not None and roots:
        _renew(app, session.connection(), roots)


def _renew(app, connection, roots: Set[Root]) -> None:
    table = _table(app)
    connection.execute(update(table).where(_where(table, roots))
                       .values(token=_token(), touched_at=apptime.now()))


# ── Every write through the session ───────────────────────────────────────────

def _owned_parents(app, model: str) -> List[Tuple[str, str, Optional[str]]]:
    """The foreign keys of `model` declared owned: (column, parent model, parent column)."""
    table = app.tables.get(model)
    found = []
    for col in (table.effective_columns if table else []):
        fk = col.attributes.get('foreign_key')
        if fk and fk.get('owned') and fk.get('table') is not None:
            found.append((col.name, fk['table'].name, fk.get('id')))
    return found


def _key(obj) -> Optional[str]:
    pk = sa_inspect(obj).mapper.primary_key[0].key
    value = getattr(obj, pk, None)
    return None if value is None else str(value)


def _parent(app, session, model: str, column: Optional[str], value: Any):
    cls = app.find_model_class(model)
    if cls is None:
        return None
    if column is None or column == sa_inspect(cls).primary_key[0].key:
        return session.get(cls, value)
    return session.execute(select(cls).where(getattr(cls, column) == value)).scalars().first()


def _roots(app, session, obj, cache: Dict[Any, Set[Root]]) -> Set[Root]:
    """The roots a row belongs to: itself when nothing owns it, else its owners'."""
    if id(obj) in cache:
        return cache[id(obj)]
    model = type(obj).__name__
    parents = _owned_parents(app, model)
    if not parents:
        key = _key(obj)
        found = {(model, key)} if key is not None else set()
    else:
        found = set()
        state = sa_inspect(obj)
        for column, parent_model, parent_column in parents:
            # The parent it has, and the one it leaves when it moves
            values = {getattr(obj, column, None)}
            if column in state.attrs:
                values |= set(state.attrs[column].history.deleted or ())
            for value in values - {None}:
                parent = _parent(app, session, parent_model, parent_column, value)
                if parent is not None:
                    found |= _roots(app, session, parent, cache)
    cache[id(obj)] = found
    return found


@event.listens_for(Session, 'before_flush')
def _collect(session, flush_context, instances) -> None:
    """The roots this flush touches, while the rows still say where they hang."""
    app = _app()
    if app is None:
        return
    pending = session.info.setdefault(_PENDING, {'renew': set(), 'gone': set()})
    cache: Dict[Any, Set[Root]] = {}
    with session.no_autoflush:
        for obj in session.deleted:
            if type(obj).__name__ == MARKER:
                continue
            roots = _roots(app, session, obj, cache)
            if not _owned_parents(app, type(obj).__name__):
                pending['gone'] |= roots      # the document goes, its marker with it
            else:
                pending['renew'] |= roots
        for obj in list(session.new) + [o for o in session.dirty if session.is_modified(o)]:
            if type(obj).__name__ != MARKER:
                pending['renew'] |= _roots(app, session, obj, cache)


@event.listens_for(Session, 'after_flush')
def _apply(session, flush_context) -> None:
    """One UPDATE for the documents touched, one DELETE for those gone."""
    pending = session.info.pop(_PENDING, None)
    app = _app()
    if not pending or app is None:
        return
    gone = pending['gone']
    renew = pending['renew'] - gone - session.info.get(_CLAIMED, set())
    if renew:
        _renew(app, session.connection(), renew)
    if gone:
        table = _table(app)
        session.connection().execute(delete(table).where(_where(table, gone)))


@event.listens_for(Session, 'after_commit')
@event.listens_for(Session, 'after_soft_rollback')
def _forget(session, *args) -> None:
    """What a transaction claimed ends with it."""
    session.info.pop(_CLAIMED, None)
    session.info.pop(_PENDING, None)
