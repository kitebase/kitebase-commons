"""
Opportunities written through the db port, and the pipelines they stand in.

What has to hold: the standard pipeline is written only where there is none;
an opportunity with no pipeline goes to the first active one, with no stage to
its first stage; a stage of another pipeline is refused, unless the pipeline
was what changed, and then it starts again from the first stage of the new
one; the closing date follows the outcome; priority and outcome stay in their
sets.

    (cd commons/demo && uv run pytest -q ../plugins/crm/tests)
"""
import pytest

from kitebase.endpoints import CommandDispatcher


def make(app, name=None, stages=None):
    from crm.api import make_pipeline
    with app.get_session() as s:
        pid = make_pipeline(s, name, stages)
        s.commit()
        return pid


def stage_ids(app, pipeline_id):
    Stage = app.models['Stage']
    with app.get_session() as s:
        return [r.id for r in s.query(Stage).filter_by(pipeline_id=pipeline_id)
                .order_by(Stage.sequence)]


def send(method, data, **more):
    return CommandDispatcher().send({'operation': 'db', 'parameters': {
        'table': 'Opportunity', 'method': method, 'data': data, **more}})


def create(**data):
    return send('create', {'name': 'Deal', 'partner_id': 1, **data})


def row(app, opp_id=None):
    Opp = app.models['Opportunity']
    with app.get_session() as s:
        q = s.query(Opp)
        r = q.filter_by(id=opp_id).one() if opp_id else q.one()
        s.expunge(r)
        return r


# ── Pipelines ────────────────────────────────────────────────────────────────

def test_the_standard_pipeline_is_written_only_where_there_is_none(app):
    first = make(app)
    assert first is not None and len(stage_ids(app, first)) == 4
    assert make(app) is None


def test_a_named_pipeline_is_written_with_its_stages_in_order(app):
    make(app)
    pid = make(app, 'Renewals', ['Expiring', 'Proposal sent', 'Signed'])
    Stage = app.models['Stage']
    with app.get_session() as s:
        names = [r.name for r in s.query(Stage).filter_by(pipeline_id=pid).order_by(Stage.sequence)]
    assert names == ['Expiring', 'Proposal sent', 'Signed']


# ── Where an opportunity stands ──────────────────────────────────────────────

def test_with_no_pipeline_yet_an_opportunity_is_refused(app):
    result = create()
    assert result['status'] == 'error' and 'no pipeline' in result['message']


def test_with_nothing_named_it_starts_from_the_first_stage_of_the_first_pipeline(app):
    sales = make(app)
    make(app, 'Renewals', ['Expiring', 'Signed'])
    assert create()['status'] == 'success'
    opp = row(app)
    assert (opp.pipeline_id, opp.stage_id) == (sales, stage_ids(app, sales)[0])
    assert opp.outcome == 'open' and opp.closed_at is None


def test_an_archived_pipeline_is_not_the_default(app):
    sales = make(app)
    renewals = make(app, 'Renewals', ['Expiring', 'Signed'])
    with app.get_session() as s:
        s.get(app.models['Pipeline'], sales).active = False
        s.commit()
    assert create()['status'] == 'success'
    assert row(app).pipeline_id == renewals


def test_a_pipeline_named_alone_gives_its_first_stage(app):
    make(app)
    renewals = make(app, 'Renewals', ['Expiring', 'Signed'])
    assert create(pipeline_id=renewals)['status'] == 'success'
    assert row(app).stage_id == stage_ids(app, renewals)[0]


def test_a_stage_of_another_pipeline_is_refused(app):
    sales = make(app)
    renewals = make(app, 'Renewals', ['Expiring', 'Signed'])
    result = create(pipeline_id=sales, stage_id=stage_ids(app, renewals)[1])
    assert result['status'] == 'error' and 'not one of the pipeline' in result['message']


def test_changing_the_pipeline_starts_again_from_its_first_stage(app):
    sales = make(app)
    renewals = make(app, 'Renewals', ['Expiring', 'Signed'])
    create(stage_id=stage_ids(app, sales)[2])
    opp = row(app)
    result = send('update', {'pipeline_id': renewals}, id=opp.id)
    assert result['status'] == 'success', result
    assert row(app).stage_id == stage_ids(app, renewals)[0]


def test_moving_between_stages_is_free(app):
    sales = make(app)
    stages = stage_ids(app, sales)
    create(stage_id=stages[3])
    opp = row(app)
    assert send('update', {'stage_id': stages[0]}, id=opp.id)['status'] == 'success'
    assert row(app).stage_id == stages[0]


# ── Outcome and priority ─────────────────────────────────────────────────────

def test_the_closing_date_follows_the_outcome_and_the_stage_stays(app):
    sales = make(app)
    stage = stage_ids(app, sales)[2]
    create(stage_id=stage)
    opp = row(app)
    send('update', {'outcome': 'lost'}, id=opp.id)
    closed = row(app)
    assert closed.closed_at is not None and closed.stage_id == stage
    send('update', {'outcome': 'open'}, id=opp.id)
    assert row(app).closed_at is None


@pytest.mark.parametrize('data, text', [
    ({'outcome': 'maybe'}, 'outcome is one of'),
    ({'priority': 4}, 'from 0 to 3'),
    ({'priority': -1}, 'from 0 to 3'),
])
def test_values_out_of_their_set_are_refused(app, data, text):
    make(app)
    result = create(**data)
    assert result['status'] == 'error' and text in result['message']
