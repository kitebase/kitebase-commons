"""The bridge from smtp: a message sent becomes an activity done, of type
`email`, when the message asks for it.

Loaded only where the application loads smtp too (config.yaml, `optional`),
so neither plugin needs the other. The message asks with a param, `activity`,
which the application's compose and merge forms carry as a checkbox: absent,
nothing is written, so the mail of the system and of code stays out of the
history unless asked.

The activity is written on the record of the message, linked to the other
records it reached and to its MailLog (role `mail`); a recipient of smtp is
the person spoken to (`contact`). With no record it is personal.
"""
from smtp.api import Sent, on_sent

from activities.api import log_activity

# The roles of smtp that have a name of their own here
_ROLES = {'recipient': 'contact'}


@on_sent
def mail_activity(sent: Sent) -> None:
    if not sent['params'].get('activity'):
        return
    record = sent['record']
    on = (record['model'], record['id']) if record else None
    also = [(link['model'], link['id'], _ROLES.get(link.get('role'), link.get('role')))
            for link in sent['links']
            if not record or (str(link['model']), str(link['id']))
            != (str(record['model']), str(record['id']))]
    if sent['log_id'] is not None:
        also.append(('MailLog', sent['log_id'], 'mail'))
    log_activity(on, 'email', sent['subject'], also=also, source='smtp',
                 user_id=sent['user_id'])
