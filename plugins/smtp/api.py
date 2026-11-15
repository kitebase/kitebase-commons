"""What other plugins call to hear of the mail sent, without smtp knowing them.

    from smtp.api import on_sent

    @on_sent
    def remember(sent):
        if sent['params'].get('activity'):
            ...

A listener is called once a message has left (`sent` or `dry_run`), never
when it failed, with:

    log_id     the MailLog row; None when the message was sent without a log
    status     'sent' or 'dry_run'
    subject    the subject as it left, placeholders filled
    record     {model, id}, the record the message was written on, or None
    links      every {model, id, role} the message is linked to, the record too
    user_id    who sent it; None for a message sent by the system
    params     the message's params: what the form added, such as a choice
               another plugin reads

The message has already left: a listener that fails is written to the log
with its module, and the sending stays a success. A listener registers from a
module of its own plugin listed under `optional: smtp`, so that neither
plugin depends on the other.
"""
import logging
from typing import Any, Callable, Dict

from kitebase.registry import Registry, owner_of

logger = logging.getLogger(__name__)

Sent = Dict[str, Any]

_LISTENERS: Registry[Callable[[Sent], None]] = Registry('smtp_on_sent', 'listener of the mail sent')


def on_sent(listener: Callable[[Sent], None]) -> Callable[[Sent], None]:
    """Call `listener` for every message that leaves; usable as a decorator."""
    owner = owner_of(listener)
    _LISTENERS.add(f'{owner}.{listener.__name__}', listener, owner=owner)
    return listener


def notify(sent: Sent) -> None:
    """Tell the listeners a message left. Called by mailer.dispatch."""
    for name, listener in list(_LISTENERS.items()):
        try:
            listener(sent)
        except Exception:
            logger.exception('smtp: the listener %s failed on mail %s', name,
                             sent.get('log_id'))
