"""Email on an opportunity, where the application loads smtp (config.yaml,
`optional`): an opportunity is written to at the addresses of its partner, as
smtp knows them. The commands are in pages.yaml, and leave the view by
themselves without smtp, their endpoints unregistered. A message sent becomes
an activity of the opportunity where activities bridges smtp, so it is in the
story of the negotiation and in the history of the partner.
"""
from smtp.addresses import register_addresses_via

register_addresses_via('Opportunity', 'partner')
