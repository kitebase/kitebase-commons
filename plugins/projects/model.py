"""The figures of projects and tasks, read in the query that loads a list: a
list shows them like any column, and there is nothing to keep in step.

This module is a mixin of the generated model, which defines the tables.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import object_session

import kitebase.utils

from projects.api import OPEN_CATEGORIES


def _models(*names):
    models = kitebase.utils.get_app().models
    return [models[n] for n in names]


class _Read:
    def _read(self, name):
        session = object_session(self)
        if session is None or self.id is None:
            return None
        cls = type(self)
        return session.scalar(select(getattr(cls, name)).where(cls.id == self.id))


class Project(_Read):
    """The tasks still open and the hours spent on the project."""

    @hybrid_property
    def open_tasks(self):
        return self._read('open_tasks')

    @open_tasks.expression
    def open_tasks(cls):
        Task, TaskStage = _models('Task', 'TaskStage')
        return (select(func.count(Task.id))
                .join(TaskStage, Task.stage_id == TaskStage.id)
                .where(Task.project_id == cls.id, TaskStage.category.in_(OPEN_CATEGORIES))
                .correlate(cls).scalar_subquery())

    @hybrid_property
    def spent_hours(self):
        return self._read('spent_hours')

    @spent_hours.expression
    def spent_hours(cls):
        (TimeEntry,) = _models('TimeEntry')
        return (select(func.coalesce(func.sum(TimeEntry.hours), 0))
                .where(TimeEntry.project_id == cls.id)
                .correlate(cls).scalar_subquery())


class Task(_Read):
    """The hours spent on the task, and whether its stage is still open."""

    @hybrid_property
    def spent_hours(self):
        return self._read('spent_hours')

    @spent_hours.expression
    def spent_hours(cls):
        (TimeEntry,) = _models('TimeEntry')
        return (select(func.coalesce(func.sum(TimeEntry.hours), 0))
                .where(TimeEntry.task_id == cls.id)
                .correlate(cls).scalar_subquery())

    @hybrid_property
    def is_open(self):
        return self._read('is_open')

    @is_open.expression
    def is_open(cls):
        (TaskStage,) = _models('TaskStage')
        return (select(TaskStage.category.in_(OPEN_CATEGORIES))
                .where(TaskStage.id == cls.stage_id)
                .correlate(cls).scalar_subquery())
