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


def send(table, method, data, **more):
    return CommandDispatcher().send({'operation': 'db', 'parameters': {
        'table': table, 'method': method, 'data': data, **more}})


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
