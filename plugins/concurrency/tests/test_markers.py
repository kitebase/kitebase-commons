"""
The version of a document: handed out with it, checked and renewed at the save,
renewed by any write that reaches it through its owned rows.

What has to hold: two saves from the same version, the second is refused with
the document as it is now and nothing of it written; a write on a note renews
the version of the book that owns its chapter; a document nobody opened has no
marker and its writes create none; a loan, not owned, renews nothing.

    (cd server && uv run pytest -q ../commons/plugins/concurrency/tests)
"""
import pytest

from kitebase.endpoint_tree import load_tree, save_tree
from kitebase.errors import Conflict


def ok(result):
    assert result['status'] == 'success', result.get('message')
    return result['data']


def open_book(book_id=1):
    return ok(load_tree({'page': 'book_form', 'id': book_id}))


def marker(app, model='Book', key='1'):
    with app.get_session() as s:
        row = s.query(app.models['EditMarker']).filter_by(model=model, record_id=key).first()
        return row.token if row else None


def write(app, model, key, **values):
    """A plain ORM write, as a procedure of a plugin would do it."""
    with app.get_session() as s:
        obj = s.get(app.models[model], key)
        for k, v in values.items():
            setattr(obj, k, v)
        s.commit()


def save(tree, **values):
    root = {'op': 'update', 'id': tree['id'], 'values': values}
    if '$version' in tree:
        root['$version'] = tree['$version']
    return save_tree({'page': 'book_form', 'root': root})


# ── Opening ───────────────────────────────────────────────────────────────────

def test_opening_a_document_hands_out_its_version(app):
    tree = open_book()
    assert tree['$version'] == marker(app)
    assert open_book()['$version'] == tree['$version']


def test_a_document_nobody_opened_has_no_marker_and_its_writes_make_none(app):
    write(app, 'Book', 2, title='Persuasion')
    assert marker(app, key='2') is None


# ── Saving ────────────────────────────────────────────────────────────────────

def test_a_save_with_the_current_version_renews_it(app):
    tree = open_book()
    saved = ok(save(tree, title='Dune Messiah'))
    assert saved['root']['$version'] not in (None, tree['$version'])
    assert saved['root']['$version'] == marker(app)


def test_the_second_save_from_one_version_is_refused_with_the_document_now(app):
    first, second = open_book(), open_book()
    ok(save(first, title='Children of Dune'))

    with pytest.raises(Conflict) as refused:
        save_tree({'page': 'book_form', 'root': {
            'op': 'update', 'id': 1, '$version': second['$version'],
            'values': {'title': 'God Emperor'},
            'children': {'chapters': [{'op': 'create', 'id': -2, 'values': {'title': 'Two'}}]}}})

    assert refused.value.code == 409
    fresh = refused.value.data['root']
    assert fresh['values']['title'] == 'Children of Dune'
    assert fresh['$version'] == marker(app)
    assert [c['values']['title'] for c in fresh['children']['chapters']] == ['One']


def test_a_marker_gone_is_a_conflict_not_a_loss(app):
    tree = open_book()
    with app.get_session() as s:
        s.query(app.models['EditMarker']).delete()
        s.commit()
    with pytest.raises(Conflict):
        save(tree, title='lost?')
    assert open_book()['values']['title'] == 'Dune'


def test_a_save_without_a_version_is_not_checked_but_renews_it(app):
    tree = open_book()
    ok(save({'id': 1}, title='By a procedure'))
    assert marker(app) != tree['$version']
    with pytest.raises(Conflict):
        save(tree, title='Mine')


def test_a_save_that_writes_only_a_child_still_moves_the_version_once(app):
    tree = open_book()
    saved = ok(save_tree({'page': 'book_form', 'root': {
        'id': 1, '$version': tree['$version'],
        'children': {'chapters': [{'op': 'update', 'id': 10, 'values': {'title': 'Uno'}}]}}}))
    # The version the save handed back is the stored one: the rows of the
    # save did not renew it a second time behind the client's back
    assert saved['root']['$version'] == marker(app)
    ok(save(saved['root'], title='Again'))


def test_a_deleted_document_takes_its_marker_with_it(app):
    tree = open_book(2)
    ok(save_tree({'page': 'book_form',
                  'root': {'op': 'delete', 'id': 2, '$version': tree['$version']}}))
    assert marker(app, key='2') is None


# ── Writes from elsewhere ─────────────────────────────────────────────────────

def test_a_note_written_by_a_procedure_renews_the_book(app):
    tree = open_book()
    write(app, 'Note', 100, text='changed')
    assert marker(app) != tree['$version']


def test_a_row_added_under_a_chapter_renews_the_book(app):
    tree = open_book()
    with app.get_session() as s:
        s.add(app.models['Note'](text='new', chapter_id=10))
        s.commit()
    assert marker(app) != tree['$version']


def test_a_chapter_moved_renews_both_books(app):
    one, two = open_book(1), open_book(2)
    write(app, 'Chapter', 10, book_id=2)
    assert marker(app, key='1') != one['$version']
    assert marker(app, key='2') != two['$version']


def test_a_loan_is_not_part_of_the_book(app):
    tree = open_book()
    write(app, 'Loan', 5, who='Bob')
    assert marker(app) == tree['$version']


def test_a_bulk_write_names_what_it_touched(app):
    from concurrency.markers import touched   # importable once the plugin is loaded
    tree = open_book()
    with app.get_session() as s:
        s.query(app.models['Note']).update({'text': 'bulk'})
        touched(s, [('Book', 1)])
        s.commit()
    assert marker(app) != tree['$version']
