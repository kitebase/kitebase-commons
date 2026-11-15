"""The application the tests of activities run on, built once: the plugin with
a bench of three tables in a chain (a job follows its deal, the deal its
customer) and a table whose `follow` names no foreign key; smtp too, in dry
run, for the bridge of the mail sent (activities/mail.py)."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

import kitebase.context
import kitebase.plugins
import kitebase.source
import kitebase.utils
from kitebase import access

COMMONS = Path(__file__).resolve().parents[2]

BENCH_MODEL = {'tables': {
    'Customer': {'name': 'customers', 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60}]},
    'Deal': {'name': 'deals', 'activities.follow': ['customer_id'], 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60},
        {'name': 'customer_id', 'foreign_key': {'target': 'Customer.id'}}]},
    # A typo in `follow`: said at the first activity, not followed in silence
    'Note': {'name': 'notes', 'activities.follow': ['customer'], 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'customer_id', 'foreign_key': {'target': 'Customer.id'}}]},
    'Job': {'name': 'jobs', 'activities.follow': ['deal_id'], 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60},
        {'name': 'deal_id', 'foreign_key': {'target': 'Deal.id'}}]},
}}


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('activities')
    bench = root / 'plugins' / 'bench'
    bench.mkdir(parents=True)
    (bench / 'config.yaml').write_text(yaml.safe_dump(
        {'name': 'bench', 'depends_on': ['activities']}), encoding='utf-8')
    (bench / 'model.yaml').write_text(yaml.safe_dump(BENCH_MODEL), encoding='utf-8')
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'bench',
        'plugins': [{'path': str(COMMONS), 'include': ['activities', 'smtp']}, 'plugins'],
        'db_engine': f'sqlite:///{root / "bench.sqlite"}',
        'media': {'roots': {'mail': {'type': 'fs', 'path': 'media/mail'}}},
    }), encoding='utf-8')
    (root / 'secrets').mkdir()
    (root / 'secrets' / 'smtp.yaml').write_text(yaml.safe_dump({
        '$dry_run': True,
        'office': {'host': '127.0.0.1', 'port': 25, 'security': 'none',
                   'from': 'Office <office@example.com>'},
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
    """Each test: no activities, customer 1 with deal 10 and its job 100,
    customer 2 alone, users 7 and 8; no policy and nobody logged in."""
    with app.get_session() as s:
        for name in ('ActivityLink', 'Activity', 'ActivityType', 'MailLink', 'MailLog', 'Note',
                     'Job', 'Deal', 'Customer', 'User'):
            s.query(app.models[name]).delete()
        s.add(app.models['ActivityType'](id='call', label='Call'))
        s.add(app.models['Customer'](id=1, name='Riverside'))
        s.add(app.models['Customer'](id=2, name='Hillside'))
        s.add(app.models['Deal'](id=10, name='New roof', customer_id=1))
        s.add(app.models['Job'](id=100, name='Measure', deal_id=10))
        for uid, name in ((7, 'Tester'), (8, 'Other')):
            s.add(app.models['User'](id=uid, username=name.lower(), name=name, password='x',
                                     email=f'{name.lower()}@example.com',
                                     mail_accounts=['office']))
        s.commit()
    yield
    access.GUARD.reset()
    kitebase.context.replace({})
