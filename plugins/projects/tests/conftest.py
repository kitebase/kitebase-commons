"""The application the tests of projects run on, built once: the plugin and what it
depends on, in a database of its own."""
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


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('projects')
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'bench',
        'plugins': [{'path': str(COMMONS), 'include': ['projects']}],
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
    """Each test: partners 1 (a company) and 3 (a person), user 7 linked to
    person 3; no project, no task; nobody logged in."""
    with app.get_session() as s:
        for name in ('TaskTagLink', 'ProjectTagLink', 'ProjectTag', 'ActivityLink', 'Activity',
                     'Task', 'TaskStage', 'Project', 'User', 'Partner'):
            s.query(app.models[name]).delete()
        s.add(app.models['Partner'](id=1, kind='organization', name='Riverside'))
        s.add(app.models['Partner'](id=3, kind='person', name='Carter, Alex'))
        s.flush()
        s.add(app.models['User'](id=7, username='tester', name='Tester', password='x',
                                 email='tester@example.com', partner_id=3))
        s.commit()
    yield
    access.GUARD.reset()
    kitebase.context.replace({})
