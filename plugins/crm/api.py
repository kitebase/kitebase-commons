"""The pipelines from code: the standard one, and where an opportunity starts.

    from crm.api import make_pipeline

    make_pipeline(session)          # the standard pipeline, where there is none

These functions are for code, which answers for what it writes: they check no
permission.
"""
from typing import Any, Optional, Sequence

import kitebase.utils
from kitebase.i18n import _, use_locale

# The values of Opportunity.outcome: open while it is negotiated, then won or lost
OUTCOMES = ('open', 'won', 'lost')

STANDARD = ('Sales', ('New', 'Qualified', 'Proposal', 'Negotiation'))


def make_pipeline(session: Any, name: Optional[str] = None,
                  stages: Optional[Sequence[str]] = None) -> Optional[int]:
    """A pipeline with its stages, in the language of the application; with
    no name, the standard one, written only where there is no pipeline at all.
    The id of the pipeline made, None when nothing was written. The caller
    commits."""
    app = kitebase.utils.get_app()
    Pipeline, Stage = app.models['Pipeline'], app.models['Stage']
    if name is None:
        if session.query(Pipeline.id).first() is not None:
            return None
        name, stages = STANDARD
        with use_locale(app.plugins.config.get('locale', 'en')):
            name, stages = _(name), [_(s) for s in stages]
    pipeline = Pipeline(name=name, sequence=_next_sequence(session, Pipeline))
    session.add(pipeline)
    session.flush()
    for place, stage in enumerate(stages or (), 1):
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
