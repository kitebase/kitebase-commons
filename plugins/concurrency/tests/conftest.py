"""The application the tests of concurrency run on, built once: the plugin and
a bench where a book owns its chapters and a chapter its notes, and a loan
hangs from a book without being part of it."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

import kitebase.plugins
import kitebase.source
import kitebase.utils

COMMONS = Path(__file__).resolve().parents[2]


def _id():
    return {'name': 'id', 'type': 'Integer', 'primary_key': True, 'autoincrement': True}


BENCH_MODEL = {'tables': {
    'Book': {'name': 'books', 'columns': [
        _id(), {'name': 'title', 'type': 'String', 'length': 60}]},
    'Chapter': {'name': 'chapters', 'columns': [
        _id(), {'name': 'title', 'type': 'String', 'length': 60},
        {'name': 'book_id', 'type': 'Integer',
         'foreign_key': {'target': 'Book.id', 'owned': True}}]},
    'Note': {'name': 'notes', 'columns': [
        _id(), {'name': 'text', 'type': 'String', 'length': 60},
        {'name': 'chapter_id', 'type': 'Integer',
         'foreign_key': {'target': 'Chapter.id', 'owned': True}}]},
    'Loan': {'name': 'loans', 'columns': [
        _id(), {'name': 'who', 'type': 'String', 'length': 60},
        {'name': 'book_id', 'type': 'Integer', 'foreign_key': {'target': 'Book.id'}}]},
}}


def _collection(cid, model, fk, **extra):
    return {'type': 'collection', 'id': cid, 'model': model, 'fk': fk, **extra}


def _form(model, *layout):
    return {'content': {'type': 'form', 'source': {'model': model}, 'layout': list(layout)}}


PAGES = {'pages': {
    'book_form': _form('Book', _collection('chapters', 'Chapter', 'book_id', form='chapter_form')),
    'chapter_form': _form('Chapter', _collection('notes', 'Note', 'chapter_id')),
}}


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('concurrency')
    bench = root / 'plugins' / 'bench'
    bench.mkdir(parents=True)
    (bench / 'config.yaml').write_text(yaml.safe_dump(
        {'name': 'bench', 'depends_on': ['concurrency']}), encoding='utf-8')
    (bench / 'model.yaml').write_text(yaml.safe_dump(BENCH_MODEL), encoding='utf-8')
    (bench / 'pages.yaml').write_text(yaml.safe_dump(PAGES), encoding='utf-8')
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'bench',
        'plugins': [{'path': str(COMMONS), 'include': ['concurrency']}, 'plugins'],
        'db_engine': f'sqlite:///{root / "bench.sqlite"}',
    }), encoding='utf-8')

    cwd = os.getcwd()
    os.chdir(root)
    try:
        pm = kitebase.plugins.PluginsManager()
        pm.load_config('config.yaml')
        pm.load_plugins()
        db = kitebase.utils.get_app()
        db.calc_db(pm)
        kitebase.source.Generator(db).generate(filename='bench_model.py')
        spec = importlib.util.spec_from_file_location('bench_model', root / 'bench_model.py')
        model = importlib.util.module_from_spec(spec)
        sys.modules['bench_model'] = model
        spec.loader.exec_module(model)
        db.initialize_db(pm.config['db_engine'], model)
        yield db
    finally:
        os.chdir(cwd)


@pytest.fixture(autouse=True)
def clean(app):
    """Each test: no markers; book 1 with chapter 10 and its note 100, book 2
    alone, a loan of book 1."""
    m = app.models
    with app.get_session() as s:
        for name in ('Lease', 'EditMarker', 'Loan', 'Note', 'Chapter', 'Book'):
            s.query(m[name]).delete()
        s.add_all([m['Book'](id=1, title='Dune'), m['Book'](id=2, title='Emma')])
        s.flush()
        s.add(m['Chapter'](id=10, title='One', book_id=1))
        s.flush()
        s.add_all([m['Note'](id=100, text='a', chapter_id=10),
                   m['Loan'](id=5, who='Ann', book_id=1)])
        s.commit()
    yield
