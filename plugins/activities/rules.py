"""The rules of an activity, on every port that writes one: the priority stays
in its range, and a row with no due date and no start is a fact recorded, done
when written (api.settle). Taking the date away from a thing to do records it
as done."""
from kitebase.flow import on_write

from activities.api import priority_text, settle, valid_priority


@on_write('Activity')
def activity_rules(ctx):
    if ctx.mode == 'delete':
        return
    priority = ctx.record.get('priority')
    if isinstance(priority, str) and priority.lstrip('-').isdigit():
        priority = ctx.record['priority'] = int(priority)
    if priority is not None and not valid_priority(priority):
        ctx.stay(priority_text())
    settle(ctx.record)
