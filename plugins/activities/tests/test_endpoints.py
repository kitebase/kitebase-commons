"""
The endpoints of activities, called as the client calls them.

What has to hold: the timeline of a record holds what was written on it and
what reached it, to do first and done last, and names the record each was
written on; a record the user cannot read has no timeline; "mine" is the open
activities assigned to the user, and someone else's are read only by whoever
reads every activity; both lists filter what is to do, done or all; an activity is written on a record or on none,
for the user or for another, who then finds a request from its author; it is
changed by the user it is assigned to, by its author, or by whoever may update
activities and reads one of its records, and one nobody lets the user read
does not exist for them.
"""
import datetime

import kitebase.context
from kitebase import access, apptime
from kitebase.endpoints import CommandDispatcher


def log_activity(*args, **kwargs):
    # The plugin is importable once the app fixture has loaded it
    from activities.api import log_activity as write
    return write(*args, **kwargs)


class Policy(access.Guard):
    """Grants what it is given, each permission with its conditions or None."""

    def __init__(self, grants):
        self.grants = grants

    def allows(self, permission, context):
        return permission in self.grants

    def allows_undeclared(self, endpoint, context):
        return False

    def conditions(self, permission, context):
        return self.grants.get(permission)


def call(operation, **parameters):
    """As the client calls: the dispatcher takes the user from the command."""
    return CommandDispatcher().send({'operation': operation, 'parameters': parameters,
                                     'context': kitebase.context.current()})


def as_user(uid, grants):
    kitebase.context.replace({'id': uid, 'username': f'u{uid}'})
    access.GUARD.reset()
    access.set_guard(Policy(grants))


def day(offset):
    return apptime.today() + datetime.timedelta(days=offset)


READER = {'Customer.read': None, 'Deal.read': None, 'Job.read': None, 'User.label': None,
          'ActivityType.read': None, 'Activity.create': None}


# ── The timeline ─────────────────────────────────────────────────────────────

def test_the_timeline_holds_what_reached_the_record_to_do_first(app):
    done = log_activity(('Customer', 1), 'call', 'Called', user_id=8)
    later = log_activity(('Customer', 1), 'call', 'Call back', due_date=day(3), user_id=8)
    late = log_activity(('Job', 100), 'call', 'Measure again', due_date=day(-1), user_id=8)
    urgent = log_activity(('Customer', 1), 'call', 'Urgent', due_date=day(3), priority=9,
                          user_id=8)
    as_user(7, READER)
    result = call('activity_timeline', model='Customer', id=1)
    assert result['status'] == 'success', result
    items = result['data']
    assert [i['id'] for i in items] == [late, urgent, later, done]
    assert [i['when'] for i in items] == ['overdue', 'upcoming', 'upcoming', 'done']
    assert items[0]['owner'] == {'model': 'Job', 'id': '100', 'label': 'Measure'}
    assert items[1]['owner'] is None and items[1]['user'] == 'Other'


def test_a_record_the_user_cannot_read_has_no_timeline(app):
    log_activity(('Customer', 2), 'call', 'Hidden', user_id=8)
    as_user(7, {**READER, 'Customer.read': [{'id': 1}]})
    assert call('activity_timeline', model='Customer', id=2)['code'] == 404
    as_user(7, {})
    assert call('activity_timeline', model='Customer', id=1)['code'] == 403


# ── Mine ─────────────────────────────────────────────────────────────────────

def test_mine_is_what_is_assigned_to_me_and_still_to_do(app):
    mine = log_activity(('Customer', 1), 'call', 'Mine', due_date=day(0), user_id=7)
    log_activity(('Customer', 1), 'call', 'Mine, done', user_id=7)
    log_activity(('Customer', 1), 'call', 'Not mine', due_date=day(0), user_id=8)
    as_user(7, {})
    result = call('activity_mine')
    assert [i['id'] for i in result['data']] == [mine]
    assert result['data'][0]['when'] == 'today'
    # The record it is on, unnamed: the user does not read customers
    assert result['data'][0]['owner'] == {'model': 'Customer', 'id': '1', 'label': None}


def test_the_lists_filter_what_is_to_do_done_or_all(app):
    todo = log_activity(('Customer', 1), 'call', 'Call back', due_date=day(1), user_id=7)
    done = log_activity(('Customer', 1), 'call', 'Called', user_id=7)
    as_user(7, READER)
    ids = lambda op, **p: [i['id'] for i in call(op, **p)['data']]
    assert ids('activity_timeline', model='Customer', id=1) == [todo, done]
    assert ids('activity_timeline', model='Customer', id=1, state='todo') == [todo]
    assert ids('activity_timeline', model='Customer', id=1, state='done') == [done]
    assert ids('activity_mine', state='done') == [done]
    assert ids('activity_mine', state='all') == [todo, done]
    assert call('activity_mine', state='later')['code'] == 400


def test_the_agenda_of_another_user_is_for_whoever_reads_every_activity(app):
    theirs = log_activity(('Customer', 1), 'call', 'Theirs', due_date=day(0), user_id=8)
    as_user(7, {})
    assert call('activity_mine', user_id=8)['code'] == 403
    # Naming oneself is the plain list
    assert call('activity_mine', user_id=7)['status'] == 'success'
    as_user(7, {'Activity.read': [{'user_id': 7}]})
    assert call('activity_mine', user_id=8)['code'] == 403
    as_user(7, {'Activity.read': None, 'User.label': None})
    assert [i['id'] for i in call('activity_mine', user_id='8')['data']] == [theirs]


# ── Writing from the timeline ────────────────────────────────────────────────

def test_an_activity_is_written_on_a_record_the_user_reads(app):
    as_user(7, READER)
    result = call('activity_add', model='Deal', id=10, type='call', subject=' Offer sent ',
                  due_date=day(2).isoformat(), priority='5')
    assert result['status'] == 'success', result
    item = result['data']
    assert (item['subject'], item['priority'], item['user_id'], item['when']) == \
        ('Offer sent', 5, 7, 'upcoming')
    timeline = call('activity_timeline', model='Customer', id=1)['data']
    assert [i['id'] for i in timeline] == [item['id']]


def test_writing_is_refused_without_create_on_a_hidden_record_or_out_of_range(app):
    as_user(7, {**READER, 'Activity.create': None, 'Customer.read': [{'id': 1}]})
    assert call('activity_add', model='Customer', id=2, type='call', subject='x')['code'] == 404
    assert call('activity_add', model='Customer', id=1, type='call', subject='x',
                priority=12)['code'] == 400
    as_user(7, {k: v for k, v in READER.items() if k != 'Activity.create'})
    assert call('activity_add', model='Customer', id=1, type='call', subject='x')['code'] == 403


def test_a_personal_activity_has_no_record_and_only_its_user_sees_it(app):
    as_user(7, {'Activity.create': None})
    result = call('activity_add', type='todo', subject='Renew the domain',
                  due_date=day(1).isoformat())
    assert result['status'] == 'success', result
    item = result['data']
    assert (item['owner'], item['user_id'], item['author_id']) == (None, 7, 7)
    assert [i['id'] for i in call('activity_mine')['data']] == [item['id']]
    as_user(8, {'Activity.update': None})
    assert call('activity_done', id=item['id'])['code'] == 404


def test_a_request_to_another_user_is_theirs_to_do_and_its_authors_to_follow(app):
    as_user(7, {**READER, 'User.label': None})
    item = call('activity_add', model='Customer', id=1, type='call', subject='Call them back',
                due_date=day(1).isoformat(), user_id=8)['data']
    assert (item['user'], item['author']) == ('Other', 'Tester')
    assert call('activity_mine')['data'] == []
    as_user(8, {'User.label': None})
    mine = call('activity_mine')['data']
    assert [(i['id'], i['author']) for i in mine] == [(item['id'], 'Tester')]
    # The author, who reads no customer now, still follows what they asked
    as_user(7, {})
    assert call('activity_postpone', id=item['id'], date=day(3).isoformat())['status'] == 'success'


def test_a_request_to_a_user_who_does_not_exist_is_refused(app):
    as_user(7, READER)
    assert call('activity_add', type='todo', subject='x', user_id=99)['code'] == 400


# ── Done, to do again, postponed ─────────────────────────────────────────────

def test_the_user_it_is_assigned_to_marks_it_done_and_to_do_again(app):
    activity_id = log_activity(('Customer', 1), 'call', 'Call back', due_date=day(1), user_id=7)
    as_user(7, {})
    done = call('activity_done', id=activity_id)
    assert done['status'] == 'success' and done['data']['when'] == 'done'
    again = call('activity_done', id=activity_id, done=False)
    assert again['data']['when'] == 'upcoming'


def test_a_fact_with_no_date_does_not_go_back_to_do(app):
    activity_id = log_activity(('Customer', 1), 'call', 'Called', user_id=7)
    as_user(7, {})
    assert call('activity_done', id=activity_id, done=False)['code'] == 400


def test_another_user_needs_update_and_a_record_they_read(app):
    activity_id = log_activity(('Customer', 1), 'call', 'Call back', due_date=day(1), user_id=8)
    as_user(7, READER)
    assert call('activity_done', id=activity_id)['code'] == 403
    as_user(7, {**READER, 'Activity.update': None})
    assert call('activity_done', id=activity_id)['status'] == 'success'


def test_an_activity_on_records_the_user_cannot_read_does_not_exist_for_them(app):
    activity_id = log_activity(('Customer', 2), 'call', 'Hidden', due_date=day(1), user_id=8)
    as_user(7, {**READER, 'Activity.update': None, 'Customer.read': [{'id': 1}]})
    assert call('activity_done', id=activity_id)['code'] == 404


def test_postponing_moves_the_due_date_or_the_appointment_keeping_its_time(app):
    todo = log_activity(('Customer', 1), 'call', 'Call back', due_date=day(1), user_id=7)
    start = datetime.datetime.combine(day(1), datetime.time(9, 30))
    meeting = log_activity(('Customer', 1), 'meeting', 'Visit', user_id=7, start_at=start,
                           end_at=start + datetime.timedelta(hours=1))
    as_user(7, {})
    moved = call('activity_postpone', id=todo, date=day(5).isoformat())['data']
    assert moved['due_date'] == day(5).isoformat()
    visit = call('activity_postpone', id=meeting, date=day(4).isoformat())['data']
    assert (visit['start_at'], visit['end_at']) == (f'{day(4).isoformat()} 09:30',
                                                     f'{day(4).isoformat()} 10:30')
    assert visit['due_date'] is None


def test_a_done_activity_is_not_postponed(app):
    activity_id = log_activity(('Customer', 1), 'call', 'Called', user_id=7)
    as_user(7, {})
    assert call('activity_postpone', id=activity_id, date=day(5).isoformat())['code'] == 400


def test_the_types_a_form_picks_from(app):
    as_user(7, {'ActivityType.read': None})
    types = call('activity_types')['data']
    # The row the app seeded first, then the registered ones, made now in the
    # order registered
    assert [t['value'] for t in types] == ['call', 'note', 'meeting', 'email', 'todo']
    assert types[0] == {'value': 'call', 'label': 'Call', 'icon': None}
    with app.get_session() as s:
        assert s.get(app.models['ActivityType'], 'meeting').sequence == 30


def test_the_rows_are_born_in_the_language_of_the_application(app):
    app.plugins.load_all_locales()    # as the server does when it starts
    config = app.plugins.config
    saved = config.get('locale')
    config['locale'] = 'it'
    try:
        as_user(7, {'ActivityType.read': None})
        labels = {t['value']: t['label'] for t in call('activity_types')['data']}
    finally:
        config['locale'] = saved
    # The request speaks English; the row is the application's, and says it
    assert labels['meeting'] == 'Appuntamento'


def test_a_type_not_picked_is_not_offered(app):
    from activities import api
    saved = api._TYPES.snapshot()
    try:
        api.register_type('stage', 'Stage change', 'flag', pick=False)
        as_user(7, {'ActivityType.read': None})
        assert 'stage' not in [t['value'] for t in call('activity_types')['data']]
        with app.get_session() as s:
            # The row is there, for the application to offer it if it wants
            assert s.get(app.models['ActivityType'], 'stage').pick is False
            s.get(app.models['ActivityType'], 'note').pick = False
            s.commit()
        assert 'note' not in [t['value'] for t in call('activity_types')['data']]
    finally:
        api._TYPES.restore(saved)