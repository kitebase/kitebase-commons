"""
The endpoints of activities, called as the client calls them.

What has to hold: the timeline of a record holds what was written on it and
what reached it, to do first and done last, and names the record each was
written on; a record the user cannot read has no timeline; "mine" is the open
activities assigned to the user; an activity is changed by the user it is
assigned to, or by whoever may update activities and reads one of its records,
and one nobody lets the user read does not exist for them.
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


# ── Writing from the timeline ────────────────────────────────────────────────

def test_an_activity_is_written_on_a_record_the_user_reads(app):
    as_user(7, READER)
    result = call('activity_log', model='Deal', id=10, type='call', subject=' Offer sent ',
                  due_date=day(2).isoformat(), priority='5')
    assert result['status'] == 'success', result
    item = result['data']
    assert (item['subject'], item['priority'], item['user_id'], item['when']) == \
        ('Offer sent', 5, 7, 'upcoming')
    timeline = call('activity_timeline', model='Customer', id=1)['data']
    assert [i['id'] for i in timeline] == [item['id']]


def test_writing_is_refused_without_create_on_a_hidden_record_or_out_of_range(app):
    as_user(7, {**READER, 'Activity.create': None, 'Customer.read': [{'id': 1}]})
    assert call('activity_log', model='Customer', id=2, type='call', subject='x')['code'] == 404
    assert call('activity_log', model='Customer', id=1, type='call', subject='x',
                priority=12)['code'] == 400
    as_user(7, {k: v for k, v in READER.items() if k != 'Activity.create'})
    assert call('activity_log', model='Customer', id=1, type='call', subject='x')['code'] == 403


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
    assert call('activity_types')['data'] == [{'value': 'call', 'label': 'Call', 'icon': None}]
