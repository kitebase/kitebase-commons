"""The person of the user signed in, in every login context.

`$ctx.partner_id` is what "mine" compares with where the work is counted on
partners (a task's assignee): a row condition on the server, a view's first
rules in the client. Empty for a user linked to no partner: a rule left
without a value filters nothing, and the person sees it empty.
"""
from kitebase.server_utils import add_context_field

add_context_field('partner_id')
