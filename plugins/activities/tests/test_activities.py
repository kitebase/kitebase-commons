"""
Activities written from code and through the db port.

What has to hold: a row with no date is done when written, one with a due date
or a start is to do; the record named first is the owner; each record reaches
the parents its table declares under `activities: follow`, and theirs, once
each; a type a plugin registered is made on first use, an unknown one refused;
written in the caller's session, an activity rolls back with it.

    (cd commons/demo && uv run pytest -q ../plugins/activities/tests)
"""
import datetime
import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

import kitebase.plugins
import kitebase.source
import kitebase.utils
from kitebase.endpoints import CommandDispatcher
from kitebase.errors import Invalid

COMMONS = Path(__file__).resolve().parents[2]

BENCH_MODEL = {'tables': {
    'Customer': {'name': 'customers', 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60}]},
    'Deal': {'name': 'deals', 'activities': {'follow': ['customer_id']}, 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60},
        {'name': 'customer_id', 'foreign_key': {'target': 'Customer.id'}}]},
    # A typo in `follow`: said at the first activity, not followed in silence
    'Note': {'name': 'notes', 'activities': {'follow': ['customer']}, 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'customer_id', 'foreign_key': {'target': 'Customer.id'}}]},
    'Job': {'name': 'jobs', 'activities': {'follow': ['deal_id']}, 'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60},
        {'name': 'deal_id', 'foreign_key': {'target': 'Deal.id'}}]},
}}


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('activities')
    bench = root / 'plugins' / 'bench'
    bench.mkdir(parents=True)
    (bench / 'config.yaml').write_text(yaml.safe_dump(
        {'name': 'bench', 'depends_on': ['activities']}), encoding='utf-8')
    (bench / 'model.yaml').write_text(yaml.safe_dump(BENCH_MODEL), encoding='utf-8')
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'bench',
        'plugins': [{'path': str(COMMONS), 'include': ['activities']}, 'plugins'],
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
    """Each test: no activities, customer 1 with deal 10 and its job 100,
    customer 2 alone."""
    with app.get_session() as s:
        for name in ('ActivityLink', 'Activity', 'ActivityType', 'Note', 'Job', 'Deal', 'Customer'):
            s.query(app.models[name]).delete()
        s.add(app.models['ActivityType'](id='call', label='Call'))
        s.add(app.models['Customer'](id=1, name='Riverside'))
        s.add(app.models['Customer'](id=2, name='Hillside'))
        s.add(app.models['Deal'](id=10, name='New roof', customer_id=1))
        s.add(app.models['Job'](id=100, name='Measure', deal_id=10))
        s.commit()


def api():
    from activities import api as module
    return module


def links(app, activity_id):
    Link = app.models['ActivityLink']
    with app.get_session() as s:
        return sorted((link.model, link.record_id, link.role) for link in
                      s.query(Link).filter(Link.activity_id == activity_id))


def activity(app, activity_id):
    with app.get_session() as s:
        row = s.get(app.models['Activity'], activity_id)
        s.expunge(row)
        return row


# ── The rule of the date ─────────────────────────────────────────────────────

def test_with_no_date_it_is_a_fact_done_when_written(app):
    row = activity(app, api().log_activity(('Customer', 1), 'call', 'Called about the roof'))
    assert row.done_at is not None


def test_with_a_due_date_it_is_to_do(app):
    row = activity(app, api().log_activity(('Customer', 1), 'call', 'Call back',
                                           due_date=datetime.date(2026, 12, 1)))
    assert row.done_at is None and row.due_date == datetime.date(2026, 12, 1)


def test_with_a_start_it_is_an_appointment_to_do(app):
    row = activity(app, api().log_activity(('Customer', 1), 'call', 'Visit',
                                           start_at=datetime.datetime(2026, 12, 1, 9, 30)))
    assert row.done_at is None


def test_the_db_port_applies_the_rule_too(app):
    result = CommandDispatcher().send({'operation': 'db', 'parameters': {
        'table': 'Activity', 'method': 'create',
        'data': {'type_id': 'call', 'subject': 'Written from a form'}}})
    assert result['status'] == 'success', result
    with app.get_session() as s:
        row = s.query(app.models['Activity']).one()
        assert row.done_at is not None


# ── Priority ─────────────────────────────────────────────────────────────────

def test_the_priority_is_normal_unless_given(app):
    assert activity(app, api().log_activity(('Customer', 1), 'call', 'Normal')).priority == 0
    assert activity(app, api().log_activity(('Customer', 1), 'call', 'Parked',
                                            priority=-9)).priority == -9


@pytest.mark.parametrize('value', [10, -10, 2.5, True])
def test_a_priority_out_of_range_is_refused(app, value):
    with pytest.raises(Invalid, match='from -9 to 9'):
        api().log_activity(('Customer', 1), 'call', 'Too much', priority=value)


def test_the_db_port_keeps_the_priority_in_range(app):
    def create(priority):
        return CommandDispatcher().send({'operation': 'db', 'parameters': {
            'table': 'Activity', 'method': 'create',
            'data': {'type_id': 'call', 'subject': 'From a form', 'priority': priority}}})
    assert create('9')['status'] == 'success'
    refused = create(12)
    assert refused['status'] == 'error' and 'from -9 to 9' in refused['message']


# ── Links and the parents they reach ─────────────────────────────────────────

def test_the_first_record_is_the_owner_and_the_others_keep_their_role(app):
    activity_id = api().log_activity(('Customer', 2), 'call', 'Hello',
                                     also=[{'model': 'Customer', 'id': 1, 'role': 'contact'}])
    assert links(app, activity_id) == [('Customer', '1', 'contact'), ('Customer', '2', 'owner')]


def test_an_activity_reaches_the_parents_along_the_chain(app):
    activity_id = api().log_activity(('Job', 100), 'call', 'Measured')
    assert links(app, activity_id) == [
        ('Customer', '1', 'follow'), ('Deal', '10', 'follow'), ('Job', '100', 'owner')]


def test_a_record_reached_twice_is_linked_once_with_the_role_it_was_named_with(app):
    activity_id = api().log_activity(('Deal', '10'), 'call', 'Offer sent',
                                     also=[('Customer', 1, 'contact')])
    assert links(app, activity_id) == [('Customer', '1', 'contact'), ('Deal', '10', 'owner')]


def test_an_empty_parent_is_not_followed(app):
    with app.get_session() as s:
        s.add(app.models['Deal'](id=11, name='Unassigned'))
        s.commit()
    activity_id = api().log_activity(('Deal', 11), 'call', 'Cold call')
    assert links(app, activity_id) == [('Deal', '11', 'owner')]


def test_a_name_that_is_no_model_is_kept_as_a_label(app):
    activity_id = api().log_activity(('Customer', 1), 'call', 'Seen at the fair',
                                     also=[('Fair 2026', 'hall B')])
    assert ('Fair 2026', 'hall B', None) in links(app, activity_id)


def test_follow_naming_no_foreign_key_is_said(app):
    with app.get_session() as s:
        s.add(app.models['Note'](id=1, customer_id=1))
        s.commit()
    with pytest.raises(ValueError, match="'customer', which is no foreign key"):
        api().log_activity(('Note', 1), 'call', 'Noted')


# ── Types ────────────────────────────────────────────────────────────────────

def test_a_registered_type_is_made_on_first_use(app):
    activity_id = api().log_activity(('Customer', 1), 'email', 'Invoice sent')
    with app.get_session() as s:
        assert s.get(app.models['ActivityType'], 'email').label == 'Email'
        assert s.get(app.models['Activity'], activity_id).type_id == 'email'


def test_an_unknown_type_is_refused(app):
    with pytest.raises(Invalid):
        api().log_activity(('Customer', 1), 'fax', 'Sent a fax')


def test_a_plugin_registers_its_own_type(app):
    api().register_type('stage', 'Stage change', 'flag')
    api().log_activity(('Deal', 10), 'stage', 'From Contact to Offer')
    with app.get_session() as s:
        assert s.get(app.models['ActivityType'], 'stage').icon == 'flag'


# ── The caller's transaction ─────────────────────────────────────────────────

def test_in_the_callers_session_it_rolls_back_with_it(app):
    with app.get_session() as s:
        api().log_activity(('Customer', 1), 'call', 'Never happened', session=s)
        s.rollback()
    with app.get_session() as s:
        assert s.query(app.models['Activity']).count() == 0
        assert s.query(app.models['ActivityLink']).count() == 0


def test_the_current_user_is_assigned_unless_another_is_named(app):
    import kitebase.context
    kitebase.context.replace({'id': 7, 'username': 'tester'})
    try:
        mine = activity(app, api().log_activity(('Customer', 1), 'call', 'Mine'))
        nobody = activity(app, api().log_activity(('Customer', 1), 'call', 'System', user_id=None))
    finally:
        kitebase.context.replace({})
    assert (mine.user_id, nobody.user_id) == (7, None)
