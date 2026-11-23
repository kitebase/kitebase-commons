"""The application the tests of jobs run on: the plugin and its base."""
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


@pytest.fixture(scope='session')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('jobs')
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'bench',
        'plugins': [{'path': str(COMMONS), 'include': ['jobs']}],
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
        kitebase.source.Generator(db).generate(filename='jobs_model.py')
        spec = importlib.util.spec_from_file_location('jobs_model', root / 'jobs_model.py')
        model = importlib.util.module_from_spec(spec)
        sys.modules['jobs_model'] = model
        spec.loader.exec_module(model)
        db.initialize_db(pm.config['db_engine'], model)
        yield db
    finally:
        os.chdir(cwd)


@pytest.fixture(autouse=True)
def clean(app):
    with app.get_session() as s:
        s.query(app.models['Lease']).delete()
        s.commit()
    yield
