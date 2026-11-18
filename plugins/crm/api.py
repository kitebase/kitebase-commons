"""The pipelines from code: one more, and where an opportunity starts.

    from crm.api import make_pipeline

    make_pipeline(session, "Renewals", ["Expiring", "Signed"])

The standard pipeline is the plugin's seed (seed/base/Pipeline.yaml). These
functions are for code, which answers for what it writes: they check no
permission.
"""
from typing import Any, Optional, Sequence

import kitebase.utils

# The values of Opportunity.outcome: open while it is negotiated, then won or lost
OUTCOMES = ('open', 'won', 'lost')


def make_pipeline(session: Any, name: str, stages: Sequence[str] = ()) -> int:
    """A pipeline with its stages in this order, after the others. The id of
    the pipeline made. The caller commits."""
    app = kitebase.utils.get_app()
    Pipeline, Stage = app.models['Pipeline'], app.models['Stage']
    pipeline = Pipeline(name=name, sequence=_next_sequence(session, Pipeline))
    session.add(pipeline)
    session.flush()
    for place, stage in enumerate(stages, 1):
        session.add(Stage(pipeline_id=pipeline.id, name=stage, sequence=place))
    session.flush()
    return pipeline.id


def _next_sequence(session: Any, table: Any) -> int:
    last = session.query(table.sequence).order_by(table.sequence.desc()).first()
    return (last[0] if last else 0) + 10


def first_pipeline(session: Any) -> Optional[int]:
    """The pipeline a new opportunity goes to when none is named: the first
    active one."""
    Pipeline = kitebase.utils.get_app().models['Pipeline']
    row = session.query(Pipeline.id).filter(Pipeline.active.is_(True)) \
        .order_by(Pipeline.sequence, Pipeline.id).first()
    return row[0] if row else None


def first_stage(session: Any, pipeline_id: Any) -> Optional[int]:
    """The first stage of a pipeline, where an opportunity starts."""
    Stage = kitebase.utils.get_app().models['Stage']
    row = session.query(Stage.id).filter(Stage.pipeline_id == pipeline_id) \
        .order_by(Stage.sequence, Stage.id).first()
    return row[0] if row else None


def stage_pipeline(session: Any, stage_id: Any) -> Optional[int]:
    """The pipeline a stage belongs to, None for a stage that is not there."""
    Stage = kitebase.utils.get_app().models['Stage']
    row = session.query(Stage.pipeline_id).filter(Stage.id == stage_id).first()
    return row[0] if row else None
