"""The rules of an opportunity, on every port that writes one.

It always stands in a pipeline and in one of its stages: with none named, the
first active pipeline and its first stage. A stage of another pipeline is
refused, except when the pipeline was the thing changed: then the opportunity
starts again from the first stage of the new one. The outcome is open, won or
lost, and the closing date follows it. Each move and each closing is written
in the story of the negotiation (below).
"""
import kitebase.utils
from kitebase import apptime
from kitebase.flow import on_write
from kitebase.i18n import _, _f

from activities.api import log_activity
from activities.moves import track_moves
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
# A stage changed is a line of the history (activities.moves, which merges the
# moves made close together); a closing is a line of its own, of the same type
# `stage`, never merged.

track_moves('Opportunity')


@on_write('Opportunity', 'commit')
def opportunity_history(ctx):
    if ctx.mode != 'update':
        return
    old, new = ctx.original or {}, ctx.record
    if old.get('outcome') != new.get('outcome'):
        _closed(ctx, new)


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
