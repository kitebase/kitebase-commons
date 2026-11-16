"""The rules of an opportunity, on every port that writes one.

It always stands in a pipeline and in one of its stages: with none named, the
first active pipeline and its first stage. A stage of another pipeline is
refused, except when the pipeline was the thing changed: then the opportunity
starts again from the first stage of the new one. The outcome is open, won or
lost, and the closing date follows it. Each move and each closing is written
in the story of the negotiation (below).
"""
from datetime import timedelta

import kitebase.context
import kitebase.utils
from kitebase import apptime
from kitebase.flow import on_write
from kitebase.i18n import _, _f

from activities.api import log_activity, register_type
from crm.api import OUTCOMES, first_pipeline, first_stage, stage_pipeline

PRIORITY = (0, 3)


def _same(a, b) -> bool:
    return a is not None and b is not None and str(a) == str(b)


@on_write('Opportunity')
def opportunity_rules(ctx):
    if ctx.mode == 'delete':
        return
    record, original = ctx.record, ctx.original or {}

    if record.get('pipeline_id') in (None, ''):
        record['pipeline_id'] = first_pipeline(ctx.session)
        if record['pipeline_id'] is None:
            ctx.stay(_('There is no pipeline yet: create one with its stages first'))
    pipeline = record['pipeline_id']

    stage = record.get('stage_id')
    if stage not in (None, '') and not _same(stage_pipeline(ctx.session, stage), pipeline):
        moved = ctx.mode == 'update' and _same(stage, original.get('stage_id')) \
            and not _same(pipeline, original.get('pipeline_id'))
        if not moved:
            ctx.stay(_('The stage is not one of the pipeline chosen'))
        stage = None
    if stage in (None, ''):
        record['stage_id'] = first_stage(ctx.session, pipeline)
        if record['stage_id'] is None:
            ctx.stay(_('The pipeline has no stages yet'))

    priority = record.get('priority')
    if isinstance(priority, str) and priority.isdigit():
        priority = record['priority'] = int(priority)
    low, high = PRIORITY
    if priority is not None and (isinstance(priority, bool) or not isinstance(priority, int)
                                 or not low <= priority <= high):
        ctx.stay(_f('The priority is a whole number from {low} to {high}', low=low, high=high))

    outcome = record.get('outcome') or 'open'
    if outcome not in OUTCOMES:
        ctx.stay(_f('The outcome is one of: {values}', values=', '.join(OUTCOMES)))
    record['outcome'] = outcome
    if outcome == 'open':
        record['closed_at'] = None
    elif outcome != original.get('outcome') or record.get('closed_at') is None:
        record['closed_at'] = apptime.today()


# ── The story of the negotiation ─────────────────────────────────────────────
#
# A stage changed and a closing are done activities of the type `stage`, on
# the opportunity and so in the history of its partner. Moves made close
# together by the same person are one: a card tried in two columns leaves one
# line, "From A to C", and one moved back where it was leaves none. The stage
# it started from travels in `source` ("crm:<stage id>"), so the line can be
# rewritten without reading its text.

MERGE_MINUTES = 10

register_type('stage', 'Stage', 'git-commit-horizontal', pick=False)


@on_write('Opportunity', 'commit')
def opportunity_history(ctx):
    if ctx.mode != 'update':
        return
    old, new = ctx.original or {}, ctx.record
    if not _same(old.get('stage_id'), new.get('stage_id')):
        _moved(ctx, old.get('stage_id'), new.get('stage_id'))
    if old.get('outcome') != new.get('outcome'):
        _closed(ctx, new)


def _stage_id(text: str):
    return int(text) if text.isdigit() else text


def _stage_name(session, stage_id) -> str:
    Stage = kitebase.utils.get_app().models['Stage']
    row = session.get(Stage, stage_id) if stage_id is not None else None
    return row.name if row is not None else '?'


def _last_move(ctx):
    """The last activity of the opportunity, when it is a move the same person
    made a moment ago; None otherwise."""
    app = kitebase.utils.get_app()
    Activity, Link = app.models['Activity'], app.models['ActivityLink']
    last = (ctx.session.query(Activity).join(Link, Link.activity_id == Activity.id)
            .filter(Link.model == 'Opportunity', Link.record_id == str(ctx.record['id']),
                    Link.role == 'owner')
            .order_by(Activity.id.desc()).first())
    me = (kitebase.context.current() or {}).get('id')
    if (last is None or last.type_id != 'stage' or not (last.source or '').startswith('crm:')
            or last.author_id != me or last.done_at is None
            or last.done_at < apptime.now() - timedelta(minutes=MERGE_MINUTES)):
        return None
    return last


def _moved(ctx, old_stage, new_stage) -> None:
    session = ctx.session
    last = _last_move(ctx)
    origin = _stage_id(last.source[len('crm:'):]) if last is not None else old_stage
    if last is not None and _same(origin, new_stage):
        session.delete(last)            # back where it was: nothing happened
        return
    subject = _f('From {old} to {new}', old=_stage_name(session, origin),
                 new=_stage_name(session, new_stage))
    if last is not None:
        last.subject, last.done_at = subject, apptime.now()
        return
    log_activity(('Opportunity', ctx.record['id']), 'stage', subject,
                 source=f'crm:{old_stage}', session=session)


def _closed(ctx, record) -> None:
    outcome = record.get('outcome')
    if outcome == 'won':
        subject = _('Won')
    elif outcome == 'lost':
        LostReason = kitebase.utils.get_app().models['LostReason']
        reason = (ctx.session.get(LostReason, record['lost_reason_id'])
                  if record.get('lost_reason_id') else None)
        subject = _f('Lost: {reason}', reason=reason.name) if reason else _('Lost')
    else:
        subject = _('Opened again')
    log_activity(('Opportunity', record['id']), 'stage', subject, note=record.get('lost_note')
                 if outcome == 'lost' else None, source='crm', session=ctx.session)
