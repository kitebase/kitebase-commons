"""Sending a message: the one path the form, other plugins and jobs all take.

    from smtp.mailer import send

    send({
        'account': 'office',                  # default: the user's first
        'to': ['Ann <ann@example.com>'], 'cc': [], 'bcc': [],
        'reply_to': None,                     # default: none, replies go to `from`
        'record': {'model': 'Invoice', 'id': 1033},   # what [[...]] reads, linked
        'params': {'note': 'Thank you'},      # what [[$...]] reads
        'subject': 'Invoice [[number]]',
        'body': 'Dear [[partner.name]],\n\nthe invoice is **attached**. [[$note]]',
        'attachments': [{'ref': 'mail:outbox/7/202611/3f2a9c1b4e5d/terms.pdf'},
                        {'media': 'books:2026/11/x.pdf'},
                        {'name': 'notes.txt', 'content': b'...'}],
        'receipt': True,                      # Disposition-Notification-To
        'links': [{'model': 'Partner', 'id': 42, 'role': 'recipient'}],
    })                                         # -> {'id', 'status', 'message_id'}

Subject and body are filled and rendered by `templates.complete`: a
placeholder that does not resolve refuses the message before anything is
written. The record the placeholders read is linked to the message, besides
the `links` given. Attachments are files staged in the outbox (outbox.py),
referred to by the log row rather than copied; a `media` reference is read on
the server, so only server code passes one, and from the client (`trusted`
False) a message carries only the files its user staged.

The row is written before the server is contacted and updated with the
outcome. A server that refuses or does not answer leaves the row `failed`,
with the reason, and raises Unavailable. Under `$dry_run` the message is
written to a file instead of being sent (the row's `eml`); under
`$redirect_to` it goes to that address alone, and the row keeps both the
recipients written and the address delivered to.
"""
import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr
from typing import Any, Dict, Iterable, List, Tuple

import kitebase.context
import kitebase.utils
from kitebase.apptime import now
from kitebase.errors import Invalid, Unavailable
from kitebase.i18n import _, _f

from smtp import outbox
from smtp.accounts import Account, account, choose, options
from smtp.templates import complete

DEFAULT_TIMEOUT = 30


def addresses(value: Any, field: str) -> List[str]:
    """A recipient field as a list of addresses, each checked: Invalid names the
    field and the address that is not one."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not all(isinstance(v, str) for v in items):
        raise Invalid(_f("'{field}' is a list of addresses", field=field))
    out = []
    for item in items:
        for name, addr in getaddresses([item]):
            if '@' not in addr or ' ' in addr.strip():
                raise Invalid(_f("'{value}' in {field} is not an email address",
                                 value=item, field=field))
            out.append(formataddr((name, addr)))
    return out


def _bare(addrs: Iterable[str]) -> List[str]:
    return [parseaddr(a)[1] for a in addrs]


def _timeout(app: Any) -> float:
    section = (getattr(app.plugins, 'data', None) or {}).get('smtp') or {}
    return float(section.get('timeout') or DEFAULT_TIMEOUT)


def build(message: Dict[str, Any], acct: Account, parts: Dict[str, Any],
          attachments: List[Tuple[str, bytes]]) -> EmailMessage:
    """The MIME message, headers included, from the parts `complete` made of
    subject and body; the envelope is the caller's."""
    msg = EmailMessage()
    sender = message.get('from') or acct.sender
    msg['From'] = sender
    for header, field in (('To', 'to'), ('Cc', 'cc')):
        if message.get(field):
            msg[header] = ', '.join(message[field])
    if message.get('reply_to'):
        msg['Reply-To'] = message['reply_to']
    msg['Subject'] = parts['subject']
    msg['Date'] = formatdate(localtime=True)
    domain = parseaddr(sender)[1].rpartition('@')[2] or None
    msg['Message-ID'] = make_msgid(domain=domain)
    if message.get('receipt'):
        msg['Disposition-Notification-To'] = sender
    msg.set_content(parts['text'])
    msg.add_alternative(parts['html'], subtype='html')
    for name, content in attachments:
        mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        maintype, subtype = mime.split('/', 1)
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=name)
    return msg


def deliver(acct: Account, msg: EmailMessage, recipients: List[str], timeout: float) -> None:
    """The SMTP conversation. Raises what smtplib raises."""
    if acct.security == 'ssl':
        server = smtplib.SMTP_SSL(acct.host, acct.port, timeout=timeout,
                                  context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(acct.host, acct.port, timeout=timeout)
    with server:
        if acct.security == 'starttls':
            server.starttls(context=ssl.create_default_context())
        if acct.user:
            server.login(acct.user, acct.password or '')
        server.send_message(msg, from_addr=parseaddr(acct.sender)[1], to_addrs=recipients)


def _validated(message: Dict[str, Any]) -> Dict[str, Any]:
    """The message with its recipients normalised; Invalid if it cannot leave."""
    if not isinstance(message, dict):
        raise Invalid(_('A message is a mapping of to, subject, body...'))
    clean = dict(message)
    for field in ('to', 'cc', 'bcc'):
        clean[field] = addresses(message.get(field), field)
    if not (clean['to'] or clean['cc'] or clean['bcc']):
        raise Invalid(_('The message has no recipient'))
    if clean.get('from'):
        clean['from'] = addresses(clean['from'], 'from')[0]
    if clean.get('reply_to'):
        clean['reply_to'] = addresses(clean['reply_to'], 'reply_to')[0]
    subject = clean.get('subject')
    if not isinstance(subject, str) or not subject.strip():
        raise Invalid(_('The message has no subject'))
    if '\n' in subject or '\r' in subject:
        raise Invalid(_('The subject is one line'))
    links = clean.get('links') or []
    if not isinstance(links, list) or not all(
            isinstance(link, dict) and link.get('model') and link.get('id') is not None
            for link in links):
        raise Invalid(_("'links' is a list of {model, id, role}"))
    record = clean.get('record')
    if record is not None:
        if not isinstance(record, dict) or not record.get('model') or record.get('id') is None:
            raise Invalid(_("'record' is {model, id}"))
        if not any(str(link['model']) == str(record['model'])
                   and str(link['id']) == str(record['id']) for link in links):
            links = links + [{'model': record['model'], 'id': record['id']}]
    if clean.get('params') is not None and not isinstance(clean['params'], dict):
        raise Invalid(_("'params' is a mapping of name to value"))
    clean['links'] = links
    return clean


def _attachments(app: Any, items: Any, trusted: bool) -> List[Tuple[str, bytes]]:
    """The attachments as (reference, bytes), read before anything is written.

    `{ref}` is a file staged in the outbox, which an untrusted caller (the
    client) may name only if it staged it itself. `{media}` (a file of any
    root) and `{name, content}` (bytes, staged here) come from server code.
    """
    if not items:
        return []
    if not isinstance(items, list):
        raise Invalid(_("'attachments' is a list"))
    out = []
    for item in items:
        if not isinstance(item, dict):
            raise Invalid(_('An attachment is {ref}, {media} or {name, content}'))
        if item.get('ref'):
            if not trusted and not outbox.owned(item['ref']):
                raise Invalid(_f("'{ref}' is not a file you attached", ref=item['ref']))
            ref = item['ref']
        elif trusted and item.get('media'):
            ref = item['media']
        elif trusted and item.get('name') and isinstance(item.get('content'), bytes):
            ref = outbox.stage(app, item['name'], [item['content']])
        else:
            raise Invalid(_('An attachment is {ref}, {media} or {name, content}'))
        out.append((ref, outbox.read(app, ref)))
    return out


def _update(app: Any, log_id: Any, **values: Any) -> None:
    MailLog = app.models['MailLog']
    with app.get_session() as session:
        row = session.get(MailLog, log_id)
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


def send(message: Dict[str, Any], trusted: bool = True) -> Dict[str, Any]:
    """Send one message and log it; see the module's docstring. `trusted` is
    False for a message from the client, whose attachments are only the
    files its user staged."""
    app = kitebase.utils.get_app()
    clean = _validated(message)
    parts = complete(clean)
    acct = account(choose(clean.get('account')))
    files = _attachments(app, clean.get('attachments'), trusted)
    refs = [ref for ref, _content in files]
    opts = options()
    recipients = [opts['redirect_to']] if opts['redirect_to'] else \
        _bare(clean['to'] + clean['cc'] + clean['bcc'])

    MailLog, MailLink = app.models['MailLog'], app.models['MailLink']
    context = kitebase.context.current() or {}
    with app.get_session() as session:
        row = MailLog(status='sending', account=acct.name,
                      sender=clean.get('from') or acct.sender, reply_to=clean.get('reply_to'),
                      to=clean['to'], cc=clean['cc'], bcc=clean['bcc'], delivered_to=recipients,
                      subject=parts['subject'], body=parts['text'],
                      receipt=bool(clean.get('receipt')), user_id=context.get('id'),
                      attachments=refs)
        session.add(row)
        session.flush()
        for link in clean['links']:
            session.add(MailLink(mail_log_id=row.id, model=str(link['model']),
                                 record_id=str(link['id']), role=link.get('role')))
        session.commit()
        log_id = row.id

    msg = build(clean, acct, parts, [(outbox.name_of(ref), content) for ref, content in files])
    if opts['redirect_to']:
        msg['X-Redirected-From'] = ', '.join(_bare(clean['to'] + clean['cc'] + clean['bcc']))

    if opts['dry_run']:
        eml = outbox.write_dry_run(app, log_id, msg.as_bytes())
        _update(app, log_id, eml=eml)
        status = 'dry_run'
    else:
        try:
            deliver(acct, msg, recipients, _timeout(app))
        except (smtplib.SMTPException, OSError) as e:
            _update(app, log_id, status='failed', error=str(e), attachments=refs,
                    message_id=msg['Message-ID'])
            raise Unavailable(_f('The mail server did not take the message: {error}',
                                 error=str(e)), data={'id': log_id})
        status = 'sent'
    _update(app, log_id, status=status, attachments=refs, message_id=msg['Message-ID'],
            sent_at=now())
    return {'id': log_id, 'status': status, 'message_id': msg['Message-ID']}
