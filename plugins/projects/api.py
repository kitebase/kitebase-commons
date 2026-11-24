"""Stages and states of the projects, for code and for the rules.

    from projects.api import first_stage, open_tasks

These functions check no permission: the caller answers for what it does.
"""
from typing import Any, Optional, Sequence, Tuple

import kitebase.utils
from kitebase.i18n import _

# The values of Project.state; the first three are the open projects
STATES = ('planned', 'active', 'on_hold', 'done', 'cancelled')
OPEN_STATES = STATES[:3]

# The values of TaskStage.category; a task is open in the first two
CATEGORIES = ('todo', 'active', 'done', 'cancelled')
OPEN_CATEGORIES = CATEGORIES[:2]

# The highest Task.priority: 0 normal, 1 high
TOP_PRIORITY = 1


def default_stages() -> Sequence[Tuple[str, str]]:
    """The stages a project starts with when it has none, as (name, category),
    named in the language of whoever creates it."""
    return ((_('To do'), 'todo'), (_('In progress'), 'active'),
            (_('In review'), 'active'), (_('Done'), 'done'))


def add_stages(session: Any, project_id: Any,
               stages: Optional[Sequence[Tuple[str, str]]] = None) -> None:
    """Give a project its stages, in this order: by default default_stages().
    The caller commits."""
    TaskStage = kitebase.utils.get_app().models['TaskStage']
    for place, (name, category) in enumerate(stages or default_stages(), 1):
        session.add(TaskStage(project_id=project_id, name=name, category=category,
                              sequence=place))
    session.flush()


def has_stages(session: Any, project_id: Any) -> bool:
    TaskStage = kitebase.utils.get_app().models['TaskStage']
    return session.query(TaskStage.id).filter(TaskStage.project_id == project_id).first() \
        is not None


def first_stage(session: Any, project_id: Any) -> Optional[int]:
    """Where a new task of a project starts: its first stage still to do, else
    its first stage."""
    TaskStage = kitebase.utils.get_app().models['TaskStage']
    rows = session.query(TaskStage.id, TaskStage.category) \
        .filter(TaskStage.project_id == project_id) \
        .order_by(TaskStage.sequence, TaskStage.id).all()
    todo = next((r[0] for r in rows if r[1] == 'todo'), None)
    return todo if todo is not None else (rows[0][0] if rows else None)


def stage_project(session: Any, stage_id: Any) -> Optional[int]:
    """The project a stage belongs to; None for a stage that is not there."""
    TaskStage = kitebase.utils.get_app().models['TaskStage']
    row = session.query(TaskStage.project_id).filter(TaskStage.id == stage_id).first()
    return row[0] if row else None


def open_tasks(session: Any, project_id: Any) -> int:
    """How many tasks of a project stand in a stage still open."""
    app = kitebase.utils.get_app()
    Task, TaskStage = app.models['Task'], app.models['TaskStage']
    return session.query(Task.id).join(TaskStage, Task.stage_id == TaskStage.id) \
        .filter(Task.project_id == project_id,
                TaskStage.category.in_(OPEN_CATEGORIES)).count()
