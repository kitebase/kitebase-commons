"""
The list of the tables: every table the user may read, and nothing else.

What has to hold: a table whose read the user lacks is not offered (it would
open on a refusal); each row names the generated list that opens it and the
seed sets that carry it; a junction says it is one. The comparison with a seed
reads the set asked and writes only as a user allowed to create the tree.

    (cd server && uv run pytest -q ../commons/plugins/tables/tests)
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

import kitebase.utils
from kitebase import access

ENDPOINTS = Path(__file__).resolve().parents[1] / 'endpoints.py'
spec = importlib.util.spec_from_file_location('tables_endpoints_under_test', ENDPOINTS)
tables = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tables)


def table(sql_name, plugin, **attributes):
    return SimpleNamespace(table_name=sql_name, attributes=attributes,
                           plugins=[SimpleNamespace(name=plugin)])


@pytest.fixture
def app(monkeypatch):
    instance = SimpleNamespace(tables={
        'Book': table('books', 'books', label='Book'),
        'BookTagLink': table('book_tag_links', 'books', many_to_many={'target1': {}, 'target2': {}}),
        'Loan': table('loans', 'library'),
    })
    monkeypatch.setattr(kitebase.utils, 'get_app', lambda: instance)
    monkeypatch.setattr(tables.seed, 'seed_files', lambda app, set_ref=None: [])
    return instance


def listed(holds):
    with access.holding(holds):
        return tables.tables_list({})['data']


def test_every_table_for_whoever_reads_them_all(app):
    rows = listed(lambda p: True)
    assert [r['id'] for r in rows] == ['Book', 'BookTagLink', 'Loan']
    assert rows[0] == {'id': 'Book', 'label': 'Book', 'table': 'books', 'plugin': 'books',
                       'kind': 'table', 'page': 'auto.book_list', 'seed': ''}
    assert rows[1]['kind'] == 'junction' and rows[1]['page'] == 'auto.booktaglink_list'


def test_a_table_that_cannot_be_read_is_not_offered(app):
    rows = listed(lambda p: p in {'Book.read', 'Loan.read'})
    assert [r['id'] for r in rows] == ['Book', 'Loan']


# ── The comparison with a seed ─────────────────────────────────────────────
#
# kitebase.seed does the comparing and the writing (server/tests/test_seed.py);
# here what the door adds: the set it reads, the permissions it asks.

@pytest.fixture
def seeded(app, monkeypatch, tmp_path):
    app.tables['Pipeline'] = table('pipelines', 'crm')
    files = [SimpleNamespace(plugin='crm', set='base', model='Pipeline', path=tmp_path / 'P.yaml')]
    monkeypatch.setattr(tables.seed, 'seed_files',
                        lambda app, set_ref=None: [f for f in files
                                                   if set_ref in (None, f'{f.plugin}/{f.set}')])
    monkeypatch.setattr(tables.seed, 'read_file', lambda path: [{'name': 'Sales'}])
    monkeypatch.setattr(tables.seed, 'owned_models', lambda app, model: {'Stage'})
    monkeypatch.setattr(tables.seed, 'by_titles', lambda app, model, rows: rows)
    written = []
    monkeypatch.setattr(tables.seed, 'apply_new',
                        lambda app, model, rows, keys: (written.append(keys) or ['Sales: written'], 1))
    return written


def test_the_list_says_which_sets_carry_a_table(seeded):
    rows = {r['id']: r for r in listed(lambda p: True)}
    assert rows['Pipeline']['seed'] == 'crm/base'
    assert rows['Book']['seed'] == ''


def test_the_comparison_reads_the_file_of_the_set(seeded, monkeypatch):
    item = tables.seed.Compared(tables.seed.AMBIGUOUS, 'Sales', index=1, reason='in_table', count=2)
    monkeypatch.setattr(tables.seed, 'compare', lambda app, model, rows, only_given=False: [item])
    with access.holding(lambda p: True):
        answer = tables.seed_compare({'table': 'Pipeline', 'set': 'crm/base'})
    assert answer['data'] == [{'id': 1, 'state': 'ambiguous', 'state_label': 'ambiguous',
                               'key': 'Sales', 'detail': '2 rows of the table have it',
                               'db_id': None, 'form': None}]
    with access.holding(lambda p: True):
        answer = tables.seed_compare({'table': 'Book', 'set': 'crm/base'})
    assert answer['status'] == 'error' and 'no file for Book' in answer['message']


def test_the_command_asks_the_set_or_a_file(seeded, monkeypatch):
    monkeypatch.setattr(tables.seed, 'identity_field', lambda app, model: 'name')
    with access.holding(lambda p: True):
        answer = tables.seed_choose({'id': 'Pipeline'})['data']
        # where no set carries the table, the file is the only thing to ask
        straight = tables.seed_choose({'id': 'Book'})['data']
    assert answer['action'] == 'choose'
    assert [o['label'] for o in answer['options']] == ['crm/base', 'A file...']
    assert answer['options'][0]['then'] == {'action': 'stack_push', 'panel': 'tables_seed_compare',
                                            'props': {'table': 'Pipeline', 'set': 'crm/base'}}
    assert answer['options'][1]['then'] == dict(straight, params={'table': 'Pipeline'})
    assert straight['action'] == 'upload' and straight['params'] == {'table': 'Book'}


def test_a_table_with_nothing_to_recognize_its_rows_by_is_said(seeded, monkeypatch):
    monkeypatch.setattr(tables.seed, 'identity_field', lambda app, model: None)
    with access.holding(lambda p: True):
        answer = tables.seed_choose({'id': 'Pipeline'})['data']
    assert 'neither a code nor a name' in answer['message']


def uploaded(name, content):
    return tables.UploadedFile(filename=name, chunks=[content])


def test_a_file_uploaded_opens_the_comparison_with_its_rows(seeded):
    with access.holding(lambda p: True):
        answer = tables.seed_upload({'table': 'Pipeline',
                                     'file': uploaded('mine.csv', b'name,sequence\nSales,10\n')})
    assert answer['data'] == {'action': 'stack_push', 'panel': 'tables_seed_compare', 'props': {
        'table': 'Pipeline', 'rows': [{'name': 'Sales', 'sequence': '10'}], 'source': 'mine.csv'}}


def test_a_file_not_in_a_seed_format_is_refused(seeded):
    with access.holding(lambda p: True):
        wrong = tables.seed_upload({'table': 'Pipeline', 'file': uploaded('mine.xlsx', b'PK')})
        latin = tables.seed_upload({'table': 'Pipeline', 'file': uploaded('mine.csv', b'name\n\xe0\n')})
    assert wrong['status'] == 'error' and 'mine.xlsx' in wrong['message']
    assert latin['status'] == 'error' and 'not UTF-8' in latin['message']


def test_the_rows_of_a_file_come_back_with_every_call(seeded, monkeypatch):
    """Nothing of the file stays on the server: the page sends its rows again."""
    seen = []
    monkeypatch.setattr(tables.seed, 'compare',
                        lambda app, model, rows, only_given=False: seen.append((rows, only_given)) or [])
    with access.holding(lambda p: True):
        tables.seed_compare({'table': 'Pipeline', 'rows': [{'name': 'Mine'}]})
        tables.seed_compare({'table': 'Pipeline', 'set': 'crm/base'})
        refused = tables.seed_compare({'table': 'Pipeline'})
    # a file says only some columns, a set all of them
    assert seen == [([{'name': 'Mine'}], True), ([{'name': 'Sales'}], False)]
    assert refused['status'] == 'error'


def test_an_empty_value_reads_as_empty():
    change = {'path': 'notes', 'kind': 'changed', 'db': None, 'seed': 'mine'}
    assert tables._change(change) == 'notes: (empty) now, mine in the file'


def test_writing_asks_to_create_every_table_of_the_tree(seeded, monkeypatch):
    """The rows go by their place in the file, as the comparison numbered them."""
    monkeypatch.setattr(tables.seed, 'compare', lambda app, model, rows, only_given=False: [
        tables.seed.Compared(tables.seed.NEW, 'Sales', index=1),
        tables.seed.Compared(tables.seed.NEW, 'Renewals', index=2)])
    with access.holding(lambda p: p != 'Stage.create'):
        with pytest.raises(access.AccessDenied):
            tables.seed_apply({'table': 'Pipeline', 'set': 'crm/base', 'ids': [1]})
    assert seeded == []
    with access.holding(lambda p: True):
        answer = tables.seed_apply({'table': 'Pipeline', 'set': 'crm/base', 'ids': [1, 'db4']})
    assert answer['data']['written'] == 1 and answer['data']['detail'] == 'Sales: written'
    assert seeded == [['Sales']]
