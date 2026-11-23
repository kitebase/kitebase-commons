"""
Who is editing a document: a person from the first change of a form, a
procedure that says so; advice that expires by itself.

What has to hold: a touch shows me to the others and not to myself, renews
without moving `since`, and brings the version of the document; a presence
not renewed leaves the list; opening a document tells who is there; deleting
the document takes its presences; a procedure shows as a person would.

    (cd server && uv run pytest -q ../commons/plugins/concurrency/tests)
"""
from datetime import timedelta

import pytest

import kitebase.context
from kitebase import apptime
from kitebase.endpoint_tree import load_tree, save_tree
from kitebase.errors import Invalid, NotFound


@pytest.fixture(autouse=True)
def plugin(app):
    """The plugin's module, importable once the application has loaded it."""
    global presence, editing, presence_release, presence_touch, presence_who
    from concurrency import presence
    from concurrency.presence import editing, presence_release, presence_touch, presence_who

ANN = {'id': 1, 'username': 'ann'}
BOB = {'id': 2, 'username': 'bob'}


def as_(user, fn, data):
    with kitebase.context.use(user):
        result = fn(data)
    assert result['status'] == 'success', result.get('message')
    return result['data']


def book(book_id=1):
    return {'model': 'Book', 'id': book_id}


def names(news):
    return [o['user_name'] for o in news['others']]


def open_book(user, book_id=1):
    with kitebase.context.use(user):
        return load_tree({'page': 'book_form', 'id': book_id})['data']


def rows(app):
    with app.get_session() as s:
        return s.query(app.models['Lease']).all()


def test_a_touch_shows_me_to_the_others_and_not_to_myself(app):
    assert names(as_(ANN, presence_touch, book())) == []
    assert names(as_(BOB, presence_who, book())) == ['ann']
    assert names(as_(ANN, presence_who, book())) == []


def test_looking_writes_nothing(app):
    as_(BOB, presence_who, book())
    assert rows(app) == []


def test_a_touch_renews_without_moving_since_and_one_person_is_one_presence(app):
    as_(ANN, presence_touch, book())
    since = rows(app)[0].since
    as_(ANN, presence_touch, book())
    assert len(rows(app)) == 1 and rows(app)[0].since == since


def test_the_news_bring_the_version_and_the_pace(app):
    tree = open_book(ANN)
    news = as_(ANN, presence_touch, book())
    assert news['version'] == tree['$version']
    assert news['every'] == presence.DEFAULTS['touch_every']


def test_a_save_by_someone_else_shows_in_the_version(app):
    tree = open_book(ANN)
    with kitebase.context.use(BOB):
        save_tree({'page': 'book_form', 'root': {
            'op': 'update', 'id': 1, '$version': tree['$version'], 'values': {'title': 'X'}}})
    assert as_(ANN, presence_touch, book())['version'] != tree['$version']


def test_a_presence_not_renewed_leaves_the_list(app):
    as_(ANN, presence_touch, book())
    with app.get_session() as s:
        s.query(app.models['Lease']).update(
            {'expires_at': apptime.now() - timedelta(seconds=1)})
        s.commit()
    assert names(as_(BOB, presence_who, book())) == []
    # The next touch of the document clears it away
    as_(BOB, presence_touch, book())
    assert [r.holder for r in rows(app)] == ['user:2']


def test_the_seconds_are_the_server_s(app):
    as_(ANN, presence_touch, book())
    with app.get_session() as s:
        s.query(app.models['Lease']).update({
            'since': apptime.now() - timedelta(minutes=25),
            'last_activity': apptime.now() - timedelta(minutes=1)})
        s.commit()
    other = as_(BOB, presence_who, book())['others'][0]
    assert 25 * 60 <= other['for'] < 25 * 60 + 5
    assert 60 <= other['idle'] < 65


def test_releasing_leaves_the_list(app):
    as_(ANN, presence_touch, book())
    as_(ANN, presence_release, book())
    assert rows(app) == []


def test_opening_a_document_tells_who_is_there(app):
    as_(ANN, presence_touch, book())
    tree = open_book(BOB)
    assert names(tree['$presence']) == ['ann']
    assert tree['$presence']['every'] == presence.DEFAULTS['touch_every']


def test_deleting_the_document_takes_its_presences(app):
    open_book(ANN)
    as_(ANN, presence_touch, book())
    with app.get_session() as s:
        for model in ('Loan', 'Note', 'Chapter'):
            s.query(app.models[model]).delete()
        s.delete(s.get(app.models['Book'], 1))
        s.commit()
    assert rows(app) == []


def test_a_procedure_shows_as_a_person_would_and_leaves_when_done(app):
    with kitebase.context.use(ANN):
        with editing('Book', 1, doing='Reprinting'):
            news = as_(BOB, presence_who, book())
            assert news['others'][0]['doing'] == 'Reprinting'
            # Its own presence beside the person's, who edits it too
            as_(ANN, presence_touch, book())
            assert len(rows(app)) == 2
    assert [r.holder for r in rows(app)] == ['user:1']


def test_the_sweep_takes_the_expired_and_the_old_markers(app):
    open_book(ANN)
    as_(ANN, presence_touch, book())
    with app.get_session() as s:
        past = apptime.now() - timedelta(days=2)
        s.query(app.models['Lease']).update({'expires_at': past})
        s.query(app.models['EditMarker']).update({'touched_at': past})
        s.commit()
    presence.sweep(app)
    with app.get_session() as s:
        assert s.query(app.models['EditMarker']).count() == 0
    assert rows(app) == []


def test_a_call_needs_a_document_and_a_user(app):
    with kitebase.context.use(ANN):
        with pytest.raises(Invalid):
            presence_touch({'model': 'Book'})
        with pytest.raises(NotFound):
            presence_touch({'model': 'Nothing', 'id': 1})
    with pytest.raises(Invalid):
        presence_touch(book())
