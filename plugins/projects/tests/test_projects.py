"""
Projects and tasks written through the db and save_tree ports.

What has to hold: a project has stages from the moment it exists, the default
ones or those its form gave it; its state stays in the five, and closing it
with tasks open is said, not refused. A task with no stage starts in the
first one to do of its project; a stage of another project is refused, unless
the project was what changed, and then it starts again in the new one. The
user signed in carries the partner they are in the login context.

    (cd commons/demo && uv run pytest -q ../plugins/projects/tests)
"""
import pytest

from kitebase import tokens
from kitebase.errors import Invalid
from kitebase.endpoint_tree import save_tree
from kitebase.endpoints import CommandDispatcher


# Who calls: nobody, or the user signed_in() names
CALLER = {}


def send(table, method, data, **more):
    message = {'operation': 'db', 'parameters': {
        'table': table, 'method': method, 'data': data, **more}}
    if CALLER:
        message['context'] = dict(CALLER)
    return CommandDispatcher().send(message)


def new_project(name='Racking', **data):
    result = send('Project', 'create', {'name': name, **data})
    assert result['status'] == 'success', result
    return result['data']['id']


def stages(app, project_id):
    TaskStage = app.models['TaskStage']
    with app.get_session() as s:
        return [(r.id, r.name, r.category) for r in s.query(TaskStage)
                .filter_by(project_id=project_id).order_by(TaskStage.sequence)]


def task(app, task_id):
    Task = app.models['Task']
    with app.get_session() as s:
        row = s.get(Task, task_id)
        s.expunge(row)
        return row


def infos(result):
    """The lines a write said beside its outcome, wherever the port put them."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get('$flow'), dict):
                found.extend(node['$flow'].get('info') or [])
            for v in node.values():
                walk(v)
    walk(result)
    return found


# -- Projects -------------------------------------------------------------------

def test_a_new_project_gets_the_default_stages(app):
    pid = new_project()
    assert [(n, c) for _, n, c in stages(app, pid)] == [
        ('To do', 'todo'), ('In progress', 'active'), ('In review', 'active'), ('Done', 'done')]


def test_a_project_saved_with_its_stages_keeps_them(app):
    result = save_tree({'page': 'project_form', 'root': {
        'op': 'create', 'id': -1, 'values': {'name': 'Permit'},
        'children': {'stages': [
            {'op': 'create', 'id': -2, 'values': {'name': 'Drafting', 'category': 'active'}},
            {'op': 'create', 'id': -3, 'values': {'name': 'At the council', 'category': 'active'}},
            {'op': 'create', 'id': -4, 'values': {'name': 'Granted', 'category': 'done'}}]}}})
    assert result['status'] == 'success', result
    pid = result['data']['id']
    assert [n for _, n, _ in stages(app, pid)] == ['Drafting', 'At the council', 'Granted']


def test_a_project_starts_planned_and_its_state_stays_in_the_five(app):
    pid = new_project()
    Project = app.models['Project']
    with app.get_session() as s:
        assert s.get(Project, pid).state == 'planned'
    result = send('Project', 'update', {'state': 'closed'}, id=pid)
    assert result['status'] == 'error' and 'state is one of' in result['message']


def test_closing_a_project_with_tasks_open_is_said_not_refused(app):
    pid = new_project()
    assert send('Task', 'create', {'name': 'Survey', 'project_id': pid})['status'] == 'success'
    result = send('Project', 'update', {'state': 'done'}, id=pid)
    assert result['status'] == 'success'
    assert any('1 tasks are still open' in line for line in infos(result)), result


# -- Tasks ----------------------------------------------------------------------

def test_a_task_with_no_stage_starts_in_the_first_one_to_do(app):
    pid = new_project()
    result = send('Task', 'create', {'name': 'Survey', 'project_id': pid})
    assert result['status'] == 'success', result
    assert task(app, result['data']['id']).stage_id == stages(app, pid)[0][0]


def test_a_task_needs_a_project(app):
    result = send('Task', 'create', {'name': 'Loose'})
    assert result['status'] == 'error'


def test_a_stage_of_another_project_is_refused(app):
    one, other = new_project('One'), new_project('Other')
    result = send('Task', 'create', {'name': 'Survey', 'project_id': one,
                                     'stage_id': stages(app, other)[1][0]})
    assert result['status'] == 'error' and 'not one of the project' in result['message']


def test_a_task_moved_to_another_project_starts_again_there(app):
    one, other = new_project('One'), new_project('Other')
    tid = send('Task', 'create', {'name': 'Survey', 'project_id': one,
                                  'stage_id': stages(app, one)[2][0]})['data']['id']
    assert send('Task', 'update', {'project_id': other}, id=tid)['status'] == 'success'
    assert task(app, tid).stage_id == stages(app, other)[0][0]


def test_the_priority_is_normal_or_high(app):
    pid = new_project()
    assert send('Task', 'create', {'name': 'A', 'project_id': pid, 'priority': 1})['status'] \
        == 'success'
    assert send('Task', 'create', {'name': 'B', 'project_id': pid, 'priority': 3})['status'] \
        == 'error'


# -- Who is signed in -----------------------------------------------------------

def test_the_login_context_carries_the_partner_of_the_user(app):
    assert 'partner_id' in tokens.context_fields({})


# -- Deleting -------------------------------------------------------------------

def test_a_stage_with_tasks_is_not_deleted_and_says_why(app):
    pid = new_project()
    stage = stages(app, pid)[1][0]
    assert send('Task', 'create', {'name': 'Survey', 'project_id': pid,
                                   'stage_id': stage})['status'] == 'success'
    with pytest.raises(Invalid) as refusal:
        save_tree({'page': 'project_form', 'root': {
            'op': 'update', 'id': pid, 'values': {},
            'children': {'stages': [{'op': 'delete', 'id': stage}]}}})
    assert '«In progress»' in str(refusal.value) and 'Task (1)' in str(refusal.value)
    assert len(stages(app, pid)) == 4


def test_an_empty_stage_is_deleted(app):
    pid = new_project()
    stage = stages(app, pid)[2][0]
    result = save_tree({'page': 'project_form', 'root': {
        'op': 'update', 'id': pid, 'values': {},
        'children': {'stages': [{'op': 'delete', 'id': stage}]}}})
    assert result['status'] == 'success', result
    assert len(stages(app, pid)) == 3


def test_a_project_is_deleted_with_its_stages_and_tasks(app):
    pid = new_project()
    send('Task', 'create', {'name': 'Survey', 'project_id': pid})
    assert send('Project', 'delete', {}, id=pid)['status'] == 'success'
    Task = app.models['Task']
    with app.get_session() as s:
        assert s.query(Task).count() == 0
    assert stages(app, pid) == []


# -- History --------------------------------------------------------------------

def test_a_task_moved_is_a_line_of_its_history_and_of_its_project(app):
    pid = new_project()
    ids = [i for i, _, _ in stages(app, pid)]
    tid = send('Task', 'create', {'name': 'Survey', 'project_id': pid})['data']['id']
    assert send('Task', 'update', {'stage_id': ids[1]}, id=tid)['status'] == 'success'
    assert send('Task', 'update', {'stage_id': ids[2]}, id=tid)['status'] == 'success'
    Activity, Link = app.models['Activity'], app.models['ActivityLink']
    with app.get_session() as s:
        lines = [a.subject for a in s.query(Activity).filter_by(type_id='stage')]
        assert lines == ['From To do to In review']
        reached = {(l.model, l.role) for l in s.query(Link)}
    assert reached == {('Task', 'owner'), ('Project', 'follow')}


# -- Hours ----------------------------------------------------------------------

def signed_in(**ctx):
    """Calls from now on come from user 7, with these fields in the context."""
    import kitebase.context
    CALLER.clear()
    CALLER.update({'id': 7, 'username': 'tester', **ctx})
    kitebase.context.replace(dict(CALLER))


def log(**data):
    return send('TimeEntry', 'create', {'date': '2026-11-24', **data})


def entry(app, entry_id):
    TimeEntry = app.models['TimeEntry']
    with app.get_session() as s:
        row = s.get(TimeEntry, entry_id)
        s.expunge(row)
        return row


def test_hours_on_a_task_go_to_its_project_by_the_person_signed_in(app):
    signed_in(partner_id=3)
    pid = new_project()
    tid = send('Task', 'create', {'name': 'Survey', 'project_id': pid})['data']['id']
    result = log(task_id=tid, hours=2)
    assert result['status'] == 'success', result.get('message')
    row = entry(app, result['data']['id'])
    assert (row.project_id, row.worker_id, float(row.hours)) == (pid, 3, 2.0)


def test_with_a_start_and_an_end_the_hours_are_computed(app):
    signed_in(partner_id=3)
    pid = new_project()
    result = log(project_id=pid, start_at='09:00', end_at='10:20')
    assert result['status'] == 'success', result
    assert float(entry(app, result['data']['id']).hours) == 1.33


def test_hours_written_over_a_range_stay_and_more_than_it_are_said(app):
    signed_in(partner_id=3)
    pid = new_project()
    kept = log(project_id=pid, start_at='09:00', end_at='13:00', hours=3.5)
    assert float(entry(app, kept['data']['id']).hours) == 3.5
    longer = log(project_id=pid, start_at='09:00', end_at='10:00', hours=2)
    assert longer['status'] == 'success'
    assert any('more than the time' in line for line in infos(longer)), longer


def test_an_end_before_the_start_is_the_next_day_and_the_date_stays(app):
    signed_in(partner_id=3)
    pid = new_project()
    result = log(project_id=pid, start_at='22:00', end_at='02:30')
    assert result['status'] == 'success', result.get('message')
    row = entry(app, result['data']['id'])
    assert float(row.hours) == 4.5 and str(row.date) == '2026-11-24'
    assert (str(row.start_at), str(row.end_at)) == ('2026-11-24 22:00:00', '2026-11-25 02:30:00')


def test_the_instants_take_the_day_of_the_row_not_the_one_the_form_put(app):
    signed_in(partner_id=3)
    pid = new_project()
    # The form puts the operational date; the row is for the day before
    result = log(project_id=pid, date='2026-11-23',
                 start_at='2026-11-24T09:00:00', end_at='2026-11-24T12:00:00')
    row = entry(app, result['data']['id'])
    assert (str(row.start_at), str(row.end_at), float(row.hours)) == \
        ('2026-11-23 09:00:00', '2026-11-23 12:00:00', 3.0)


def test_hours_are_refused_without_a_number_or_a_person(app):
    pid = new_project()
    signed_in()                                     # a user that is no one
    assert 'Who worked' in log(project_id=pid, hours=1)['message']
    signed_in(partner_id=3)
    assert 'How many hours' in log(project_id=pid)['message']
    assert 'not a time of day' in log(project_id=pid, start_at='9 o clock',
                                      end_at='10:00')['message']
    assert 'more than zero' in log(project_id=pid, hours=0)['message']


def test_a_task_of_another_project_is_refused(app):
    signed_in(partner_id=3)
    one, other = new_project('One'), new_project('Other')
    tid = send('Task', 'create', {'name': 'Survey', 'project_id': one})['data']['id']
    assert 'not one of the project' in log(project_id=other, task_id=tid, hours=1)['message']


def test_a_project_with_hours_is_not_deleted(app):
    signed_in(partner_id=3)
    pid = new_project()
    log(project_id=pid, hours=1)
    refused = send('Project', 'delete', {}, id=pid)
    assert refused['status'] == 'error' and 'Time entry (1)' in refused['message']


def test_the_form_asks_the_hours_of_a_range(app):
    from projects.endpoints import projects_hours
    assert projects_hours({'start_at': '2026-11-24T09:00', 'end_at': '2026-11-24T10:30'})['data'] == {'hours': 1.5}
    assert projects_hours({'start_at': '23:00', 'end_at': '01:00'})['data'] == {'hours': 2.0}
    assert projects_hours({'start_at': '09:00', 'end_at': None})['data'] == {}


def test_log_time_opens_the_form_on_the_task(app):
    from projects.endpoints import projects_log_time
    signed_in(partner_id=3)
    pid = new_project()
    tid = send('Task', 'create', {'name': 'Survey', 'project_id': pid})['data']['id']
    answer = projects_log_time({'id': tid})['data']
    assert answer['page'] == 'timeentry_form'
    assert answer['draft']['values'] == {'task_id': tid, 'project_id': pid, 'worker_id': 3}


# -- Figures --------------------------------------------------------------------

def test_the_figures_of_a_project_and_its_tasks(app):
    signed_in(partner_id=3)
    pid = new_project()
    ids = [i for i, _, _ in stages(app, pid)]
    first = send('Task', 'create', {'name': 'A', 'project_id': pid})['data']['id']
    send('Task', 'create', {'name': 'B', 'project_id': pid, 'stage_id': ids[3]})
    log(task_id=first, hours=2)
    log(project_id=pid, hours=0.5)
    Project, Task = app.models['Project'], app.models['Task']
    with app.get_session() as s:
        project = s.get(Project, pid)
        assert (project.open_tasks, float(project.spent_hours)) == (1, 2.5)
        open_ones = [t.name for t in s.query(Task).filter(Task.is_open.is_(True))]
        assert open_ones == ['A']
        assert float(s.get(Task, first).spent_hours) == 2.0
