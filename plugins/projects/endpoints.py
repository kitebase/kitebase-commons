"""The endpoints of the projects: what a form asks while it is filled, and
the commands of the lists.

    projects_hours     the hours between a start and an end, for the form
                       of a time entry (`on_change`); the save computes the
                       same with the same function (rules.py)
    projects_log_time  a new time entry for the task or the project under the
                       cursor, opened in its form
"""
from typing import Any, Dict

import kitebase.context
import kitebase.utils
from kitebase import access
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound
from kitebase.i18n import _, _f
from kitebase.refs import check_readable

from projects.api import hours_between


@endpoint('projects_hours', access=access.AUTHENTICATED)
def projects_hours(data: Dict[str, Any]) -> Dict[str, Any]:
    """{hours} from {start_at, end_at}, read as times of day, an end before
    the start being the next day; nothing when the two do not make an
    interval, so the form leaves the hours as they are."""
    try:
        hours = hours_between(data.get('start_at'), data.get('end_at'))
    except ValueError:
        hours = None
    return {'status': 'success', 'data': {} if hours is None else {'hours': float(hours)}}


@endpoint('projects_log_time', access='TimeEntry.create')
def projects_log_time(data: Dict[str, Any]) -> Dict[str, Any]:
    """The form of a new time entry, on the task under the cursor, or on the
    project with `params: {of: Project}`; worked by the person signed in."""
    model = data.get('of') or 'Task'
    if model not in ('Task', 'Project'):
        raise Invalid(_f('Hours are logged on a task or a project, not on {model}', model=model))
    record_id = data.get('id')
    if record_id is None:
        ids = data.get('ids') or []
        if len(ids) != 1:
            raise Invalid(_('Select a task or a project first'))
        record_id = ids[0]
    if not check_readable(model, record_id):
        raise NotFound(_f('No {model} {id}', model=model, id=record_id))
    values: Dict[str, Any] = {'project_id': record_id}
    if model == 'Task':
        app = kitebase.utils.get_app()
        with app.get_session() as session:
            task = session.get(app.models['Task'], record_id)
            values = {'task_id': task.id, 'project_id': task.project_id}
    me = (kitebase.context.current() or {}).get('partner_id')
    if me is not None:
        values['worker_id'] = me
    return {'status': 'success', 'data': {
        'action': 'open_form', 'page': 'timeentry_form', 'draft': {'values': values},
        'title': _('Log time')}}
