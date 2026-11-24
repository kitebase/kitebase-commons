"""The rules of projects and tasks, on every port that writes them.

A project has stages from the moment it exists: those it was given, or the
default ones. Its state is one of the five, and any may follow any other;
closing it with tasks still open is said, not refused.

A task always stands in a stage of its own project: with none named, the
first one to do. A stage of another project is refused, except when the
project was the thing changed: then the task starts again from the first
stage of the new one.
"""
from kitebase.flow import on_write
from kitebase.i18n import _, _f

from projects.api import (STATES, TOP_PRIORITY, add_stages, first_stage, has_stages,
                          open_tasks, stage_project)


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


@on_write('Project')
def project_rules(ctx):
    if ctx.mode == 'delete':
        return
    record, original = ctx.record, ctx.original or {}
    state = record.get('state') or 'planned'
    if state not in STATES:
        ctx.stay(_f('The state is one of: {values}', values=', '.join(STATES)))
    record['state'] = state
    if ctx.mode == 'update' and state in ('done', 'cancelled') \
            and original.get('state') != state:
        count = open_tasks(ctx.session, record['id'])
        if count:
            ctx.info(_f('{count} tasks are still open in this project', count=count))


@on_write('Project', 'commit')
def project_stages(ctx):
    # After the rows of the form: the stages it was given count
    if ctx.mode == 'insert' and ctx.obj is not None \
            and not has_stages(ctx.session, ctx.obj.id):
        add_stages(ctx.session, ctx.obj.id)


@on_write('Task')
def task_rules(ctx):
    if ctx.mode == 'delete':
        return
    record, original = ctx.record, ctx.original or {}
    project = record.get('project_id')
    if project in (None, ''):
        ctx.stay(_('A task belongs to a project'))

    stage = record.get('stage_id')
    if stage not in (None, '') and not _same(stage_project(ctx.session, stage), project):
        moved = ctx.mode == 'update' and _same(stage, original.get('stage_id')) \
            and not _same(project, original.get('project_id'))
        if not moved:
            ctx.stay(_('The stage is not one of the project chosen'))
        stage = None
    if stage in (None, ''):
        record['stage_id'] = first_stage(ctx.session, project)
        if record['stage_id'] is None:
            ctx.stay(_('The project has no stages yet'))

    priority = record.get('priority')
    if isinstance(priority, str) and priority.isdigit():
        priority = record['priority'] = int(priority)
    if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)
                                 or not 0 <= priority <= TOP_PRIORITY):
        ctx.stay(_f('The priority is a whole number from 0 to {high}', high=TOP_PRIORITY))
