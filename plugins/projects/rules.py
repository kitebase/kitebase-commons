"""The rules of projects and tasks, on every port that writes them.

A project has stages from the moment it exists: those it was given, or the
default ones. Its state is one of the five, and any may follow any other;
closing it with tasks still open is said, not refused.

A task always stands in a stage of its own project: with none named, the
first one to do. A stage of another project is refused, except when the
project was the thing changed: then the task starts again from the first
stage of the new one. Each move through the stages is a line of the history
of the task, and so of its project.

Hours always stand on a project, by a person, with a number (time_rules).
"""
from datetime import date

import kitebase.context
import kitebase.utils
from kitebase.flow import on_write
from kitebase.i18n import _, _f

from activities.moves import track_moves

from projects.api import (STATES, TOP_PRIORITY, add_stages, first_stage,
                          has_stages, hours_between, open_tasks, span_instants,
                          stage_project)


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


track_moves('Task')


@on_write('TimeEntry')
def time_rules(ctx):
    """Hours always on a project, by a person, with a number: the project of
    the task named, the person of the user writing when none is named, the
    hours between start and end when they are left empty (an end before the
    start is the next day). Hours longer than the interval are said, not
    refused: a range may be written loosely."""
    if ctx.mode == 'delete':
        return
    record = ctx.record
    task = record.get('task_id')
    if task not in (None, ''):
        project = _task_project(ctx.session, task)
        if project is None:
            ctx.stay(_('The task is not there'))
        if record.get('project_id') in (None, ''):
            record['project_id'] = project
        elif not _same(record['project_id'], project):
            ctx.stay(_('The task is not one of the project chosen'))
    if record.get('project_id') in (None, ''):
        ctx.stay(_('Hours belong to a project'))

    if record.get('worker_id') in (None, ''):
        me = (kitebase.context.current() or {}).get('partner_id')
        if me is None:
            ctx.stay(_('Who worked? Your user is linked to no person: choose one'))
        record['worker_id'] = me

    try:
        span = hours_between(record.get('start_at'), record.get('end_at'))
        day = record.get('date')
        if isinstance(day, str):
            day = date.fromisoformat(day)
        if day is not None:
            # The instants on the day of the row, whatever day the form put
            record['start_at'], record['end_at'] = span_instants(
                day, record.get('start_at'), record.get('end_at'))
    except ValueError:
        ctx.stay(_('A start or an end is not a time of day'))
    hours = record.get('hours')
    if hours in (None, ''):
        if span is None:
            ctx.stay(_('How many hours? Write them, or a start and an end'))
        record['hours'] = hours = span
    if float(hours) <= 0:
        ctx.stay(_('The hours are more than zero'))
    if span is not None and float(hours) > float(span):
        ctx.info(_f('{hours} hours are more than the time from start to end ({span})',
                    hours=hours, span=span))


def _task_project(session, task_id):
    Task = kitebase.utils.get_app().models['Task']
    row = session.query(Task.project_id).filter(Task.id == task_id).first()
    return row[0] if row else None
