"""
The list of the tables: every table the user may read, and nothing else.

What has to hold: a table whose read the user lacks is not offered (it would
open on a refusal); each row names the generated list that opens it; a
junction says it is one.

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
    return instance


def listed(holds):
    with access.holding(holds):
        return tables.tables_list({})['data']


def test_every_table_for_whoever_reads_them_all(app):
    rows = listed(lambda p: True)
    assert [r['id'] for r in rows] == ['Book', 'BookTagLink', 'Loan']
    assert rows[0] == {'id': 'Book', 'label': 'Book', 'table': 'books', 'plugin': 'books',
                       'kind': 'table', 'page': 'book_list'}
    assert rows[1]['kind'] == 'junction' and rows[1]['page'] == 'booktaglink_list'


def test_a_table_that_cannot_be_read_is_not_offered(app):
    rows = listed(lambda p: p in {'Book.read', 'Loan.read'})
    assert [r['id'] for r in rows] == ['Book', 'Loan']
