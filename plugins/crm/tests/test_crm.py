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


# ── The story of the negotiation ─────────────────────────────────────────────

def as_user(uid):
    def send_as(method, data, **more):
        return CommandDispatcher().send({
            'operation': 'db', 'context': {'id': uid, 'username': f'u{uid}'},
            'parameters': {'table': 'Opportunity', 'method': method, 'data': data, **more}})
    return send_as


def story(app, opp_id):
    """The stage activities of the opportunity, oldest first: (subject, author, links)."""
    Activity, Link = app.models['Activity'], app.models['ActivityLink']
    with app.get_session() as s:
        rows = (s.query(Activity).join(Link, Link.activity_id == Activity.id)
                .filter(Link.model == 'Opportunity', Link.record_id == str(opp_id),
                        Activity.type_id == 'stage')
                .order_by(Activity.id).all())
        return [(a.subject, a.author_id) for a in rows]


def board(app):
    """Pipeline 'Sales' with New, Qualified, Proposal, Negotiation; one open
    opportunity in New, written by user 7."""
    sales = make(app)
    stages = stage_ids(app, sales)
    as_user(7)('create', {'name': 'Deal', 'partner_id': 1})
    return row(app).id, stages


def test_a_move_is_an_activity_of_the_opportunity_and_of_its_partner(app):
    opp, stages = board(app)
    assert as_user(7)('update', {'stage_id': stages[2]}, id=opp)['status'] == 'success'
    assert story(app, opp) == [('From New to Proposal', 7)]
    Link = app.models['ActivityLink']
    with app.get_session() as s:
        assert s.query(Link).filter_by(model='Partner', record_id='1').count() == 1


def test_moves_close_together_are_one_line(app):
    opp, stages = board(app)
    send = as_user(7)
    send('update', {'stage_id': stages[1]}, id=opp)
    send('update', {'stage_id': stages[3]}, id=opp)
    assert story(app, opp) == [('From New to Negotiation', 7)]


def test_a_card_moved_back_where_it_was_leaves_nothing(app):
    opp, stages = board(app)
    send = as_user(7)
    send('update', {'stage_id': stages[2]}, id=opp)
    send('update', {'stage_id': stages[0]}, id=opp)
    assert story(app, opp) == []
    Link = app.models['ActivityLink']
    with app.get_session() as s:
        assert s.query(Link).count() == 0


def test_another_person_or_a_later_move_starts_a_new_line(app):
    opp, stages = board(app)
    as_user(7)('update', {'stage_id': stages[1]}, id=opp)
    as_user(8)('update', {'stage_id': stages[2]}, id=opp)
    assert story(app, opp) == [('From New to Qualified', 7), ('From Qualified to Proposal', 8)]
    # Old enough: the next move by the same person is a line of its own
    import datetime
    Activity = app.models['Activity']
    with app.get_session() as s:
        for a in s.query(Activity):
            a.done_at = a.done_at - datetime.timedelta(minutes=30)
        s.commit()
    as_user(8)('update', {'stage_id': stages[3]}, id=opp)
    assert story(app, opp)[-1] == ('From Proposal to Negotiation', 8)
    assert len(story(app, opp)) == 3


def test_a_closing_is_a_line_with_its_reason_and_is_never_merged(app):
    opp, stages = board(app)
    with app.get_session() as s:
        s.add(app.models['LostReason'](id=1, name='Price'))
        s.commit()
    send = as_user(7)
    send('update', {'stage_id': stages[1]}, id=opp)
    send('update', {'outcome': 'lost', 'lost_reason_id': 1, 'lost_note': 'Too dear'}, id=opp)
    send('update', {'outcome': 'open'}, id=opp)
    send('update', {'stage_id': stages[2]}, id=opp)
    assert story(app, opp) == [('From New to Qualified', 7), ('Lost: Price', 7),
                               ('Opened again', 7), ('From Qualified to Proposal', 7)]


# ── Closing from a list or the board ─────────────────────────────────────────

def close(opp, **params):
    return CommandDispatcher().send({'operation': 'crm_close', 'context': {'id': 7, 'username': 'u7'},
                                     'parameters': {'id': opp, **params}})


def test_won_closes_it_and_the_view_refreshes_the_row(app):
    opp, _stages = board(app)
    result = close(opp, outcome='won')
    assert result['status'] == 'success' and result['data']['touched'] == [opp]
    assert row(app, opp).outcome == 'won' and row(app, opp).closed_at is not None


def test_lost_asks_why_from_the_reasons_and_the_pick_closes_it(app):
    opp, stages = board(app)
    with app.get_session() as s:
        s.add_all([app.models['LostReason'](id=1, name='Price', sequence=10),
                   app.models['LostReason'](id=2, name='No budget', sequence=20)])
        s.commit()
    menu = close(opp, outcome='lost')['data']
    assert menu['action'] == 'choose'
    assert [o['label'] for o in menu['options']] == ['Price', 'No budget']
    assert row(app, opp).outcome == 'open'
    then = menu['options'][1]['then']
    result = CommandDispatcher().send({'operation': then['op'], 'context': {'id': 7},
                                       'parameters': then['params']})
    assert result['data']['message'] == 'Lost: No budget'
    closed = row(app, opp)
    assert (closed.outcome, closed.lost_reason_id, closed.stage_id) == ('lost', 2, stages[0])


def test_with_no_reasons_lost_closes_at_once_and_open_again_reopens(app):
    opp, _stages = board(app)
    assert close(opp, outcome='lost')['data']['message'] == 'Lost'
    assert close(opp, outcome='open')['status'] == 'success'
    assert row(app, opp).outcome == 'open' and row(app, opp).closed_at is None


def test_the_salesperson_is_whoever_writes_it_unless_named(app):
    make(app)
    as_user(7)('create', {'name': 'Mine', 'partner_id': 1})
    as_user(7)('create', {'name': 'For Other', 'partner_id': 1, 'user_id': 8})
    Opp = app.models['Opportunity']
    with app.get_session() as s:
        assert {o.name: o.user_id for o in s.query(Opp)} == {'Mine': 7, 'For Other': 8}


# ── The next step, and handing to another salesperson ────────────────────────

def call(op, **params):
    return CommandDispatcher().send({'operation': op, 'context': {'id': 7, 'username': 'u7'},
                                     'parameters': params})


def next_step(app, opp):
    Opp = app.models['Opportunity']
    with app.get_session() as s:
        return s.query(Opp.next_activity, Opp.next_due, Opp.next_state).filter(Opp.id == opp).one()


def test_plan_offers_a_dialog_whose_values_write_an_activity_to_do(app):
    opp, _stages = board(app)
    with app.get_session() as s:
        s.add(app.models['ActivityType'](id='call', label='Call', pick=True))
        s.commit()
    form = call('crm_plan', id=opp)['data']
    assert form['action'] == 'form' and form['values']['type'] == 'call'
    assert form['then'] == {'action': 'endpoint', 'op': 'crm_plan_save', 'params': {'id': opp}}
    result = call('crm_plan_save', id=opp, type='call', subject='Call back',
                  due_date=form['values']['due_date'])
    assert result['data']['touched'] == [opp]
    subject, due, state = next_step(app, opp)
    assert (subject, state) == ('Call back', 'planned') and str(due) == form['values']['due_date']


def test_the_next_step_is_the_first_to_do_and_says_how_it_stands(app):
    import datetime
    from activities.api import log_activity
    from kitebase import apptime
    opp, _stages = board(app)
    assert next_step(app, opp) == (None, None, 'none')
    today = apptime.today()
    with app.get_session() as s:
        s.add(app.models['ActivityType'](id='call', label='Call'))
        s.commit()
    log_activity(('Opportunity', opp), 'call', 'Later', due_date=today + datetime.timedelta(days=5))
    log_activity(('Opportunity', opp), 'call', 'Today', due_date=today)
    assert next_step(app, opp)[0::2] == ('Today', 'today')
    log_activity(('Opportunity', opp), 'call', 'Late', due_date=today - datetime.timedelta(days=1))
    assert next_step(app, opp)[0::2] == ('Late', 'overdue')
    # A done one is history, not a next step
    log_activity(('Opportunity', opp), 'call', 'Done long ago')
    assert next_step(app, opp)[0] == 'Late'


def test_the_ticked_opportunities_go_to_another_salesperson(app):
    make(app)
    for name in ('One', 'Two'):
        as_user(7)('create', {'name': name, 'partner_id': 1})
    Opp = app.models['Opportunity']
    with app.get_session() as s:
        ids = [o.id for o in s.query(Opp).order_by(Opp.id)]
    menu = call('crm_salesperson', ids=ids)['data']
    other = next(o for o in menu['options'] if o['label'] == 'Other')
    then = other['then']
    result = call(then['op'], **then['params'])
    assert result['data']['touched'] == ids
    with app.get_session() as s:
        assert {o.user_id for o in s.query(Opp)} == {8}
