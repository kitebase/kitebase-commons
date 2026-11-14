"""The rules of an activity, on every port that writes one: the priority stays
in its range, and a row with no due date and no start is a fact recorded, done
when written (api.settle). Taking the date away from a thing to do records it
as done. The author is set here, on insert, and kept on update."""
import kitebase.context
from kitebase.flow import on_write

from activities.api import priority_text, settle, valid_priority


@on_write('Activity')
def activity_rules(ctx):
    if ctx.mode == 'delete':
        return
    # The author is whoever writes the row, never what the client sends
    if ctx.mode == 'insert':
        ctx.record['author_id'] = (kitebase.context.current() or {}).get('id')
    else:
        ctx.record['author_id'] = (ctx.original or {}).get('author_id')
    priority = ctx.record.get('priority')
    if isinstance(priority, str) and priority.lstrip('-').isdigit():
        priority = ctx.record['priority'] = int(priority)
    if priority is not None and not valid_priority(priority):
        ctx.stay(priority_text())
    settle(ctx.record)
