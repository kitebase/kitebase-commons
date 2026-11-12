"""The calls of the client: the accounts, sending, and the mail of a record.

`smtp_accounts` is the vocabulary of `User.mail_accounts`: the names of
secrets/smtp.yaml, never their values. The same function validates the column.

`smtp_send` sends a message (mailer.send) for the user. A link names a record
the user can read, or a label that is no model; attachments do not come from
the client as references, since a reference is read on the server, beyond the
permissions of whoever names it.

`smtp_preview` is what a message would look like: subject, plain text and HTML
with its placeholders filled, and the ones that do not resolve (`missing`),
which the composer shows instead of being refused. The rendering is the
server's, so what is seen is what is sent.

`smtp_compose` opens the compose form, from a command (a row's `table` and
`id`, the record the message is about; `functions` and `fallback`, whom
inside it, addresses.py) or from anywhere: the answer is an
`open_form` with the draft the server prepares (`compose_action`). The form
has no model; its save, `smtp_compose_send`, sends the message, and a refusal
(an address that is not one) leaves the form open with what was written.
`smtp_addresses` lists a record's addresses, for the dialog of the To field.

`smtp_sent` is the mail of one record, newest first; `smtp_sent_page`, a
row command, opens the page that lists it (the `smtp_sent` page). The links are not read
directly: the record is read first, with the user's permissions and record
rules (404 when they do not reach it), and only then its links, for the
system. Whoever sees the record sees the mail about it, and nothing else.
"""
from email.utils import parseaddr
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import inspect

import kitebase.context
import kitebase.utils
from kitebase import access
from kitebase.endpoint_db import coerce_value
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound
from kitebase.media import UploadedFile
from kitebase.i18n import _, _f
from kitebase.transforms import register_validator

from smtp import outbox
from smtp.addresses import check_choice, choose, formatted, functions_of, of_record
from smtp.accounts import names, of_user, options, validate_accounts
from smtp.mailer import addresses, send
from smtp.templates import compose, placeholders


@endpoint('smtp_accounts', access='User.read')
def smtp_accounts(data):
    return {'status': 'success', 'code': 200,
            'data': [{'value': n, 'label': n} for n in names()]}


register_validator('smtp_accounts', validate_accounts)


def check_readable(model: str, record_id: Any) -> bool:
    """Raise unless the user reads the record: AccessDenied without the table's
    `read`, NotFound when the record is not there or a rule hides it. False for
    a name that is no model, a label nobody reads through."""
    app = kitebase.utils.get_app()
    Model = app.models.get(model)
    if Model is None:
        return False
    access.check_table(model, 'read')
    key = inspect(Model).primary_key[0].key
    value = coerce_value(Model, key, record_id)
    with app.get_session() as session:
        if session.get(Model, value) is None or not access.row_visible(session, Model, value):
            raise NotFound(_f('No {model} {id}', model=model, id=record_id))
    return True


@endpoint('smtp_send', access='smtp.send')
def smtp_send(data):
    message = data.get('message')
    if not isinstance(message, dict):
        raise Invalid(_("'message' is a mapping of to, subject, body..."))
    for link in message.get('links') or []:
        if isinstance(link, dict) and link.get('model'):
            check_readable(str(link['model']), link.get('id'))
    return {'status': 'success', 'code': 200, 'data': send(message, trusted=False)}


@endpoint('smtp_attach', access='smtp.send')
def smtp_attach(data):
    upload = data.get('file')
    if not isinstance(upload, UploadedFile):
        raise Invalid(_('A file is uploaded through the upload route, not the dispatcher'))
    app = kitebase.utils.get_app()
    ref = outbox.stage_upload(app, upload)
    return {'status': 'success', 'code': 200,
            'data': {'ref': ref, 'name': outbox.name_of(ref)}}


@endpoint('smtp_my_accounts', access='smtp.send')
def smtp_my_accounts(data):
    """The accounts the current user may send from: the vocabulary of the form's From."""
    user = (kitebase.context.current() or {}).get('id')
    return {'status': 'success', 'code': 200,
            'data': [{'value': n, 'label': n} for n in (of_user(user) if user is not None else [])]}


# ── Composing ─────────────────────────────────────────────────────────────────

# The fields of the compose form that make the message; any other field of
# the form is a parameter of the text, read by [[$name]]
MESSAGE_FIELDS = ('account', 'to', 'cc', 'bcc', 'reply_to', 'subject', 'body', 'receipt',
                  'attachments', 'record', 'links')


def _recipient(model: str, record_id: Any, functions: Optional[List[str]] = None,
               fallback: str = 'main') -> Tuple[Optional[str], str]:
    """The To of a message about a record, as text, and how its addresses
    were chosen (addresses.choose)."""
    rows, outcome = choose(of_record(model, record_id), functions, fallback)
    return (', '.join(formatted(r) for r in rows) or None), outcome


def compose_action(record: Optional[Dict[str, Any]] = None, page: str = 'smtp_compose',
                   title: Optional[str] = None, functions: Optional[List[str]] = None,
                   fallback: str = 'main', **values: Any) -> Dict[str, Any]:
    """The answer that opens the compose form with a draft: the account the
    user sends from first, the record's addresses (the main one, or the
    contacts holding one of `functions`), and `values` over them (subject,
    body, the parameters of the text...). For another plugin's command that
    computes what the message says."""
    user = (kitebase.context.current() or {}).get('id')
    accounts = of_user(user) if user is not None else []
    draft: Dict[str, Any] = {'account': accounts[0] if accounts else None,
                             'attachments': [], 'receipt': False}
    if record:
        check_readable(str(record['model']), record['id'])
        draft['record'] = {'model': record['model'], 'id': record['id']}
        to, _outcome = _recipient(str(record['model']), record['id'], functions, fallback)
        if to:
            draft['to'] = to
    draft.update(values)
    return {'action': 'open_form', 'page': page, 'draft': {'values': draft},
            'title': title or _('Write an email')}


@endpoint('smtp_compose', access='smtp.send')
def smtp_compose(data):
    """A command's call: the row's `table` and `id`, and the command's fixed
    `params` (`page`, the variant of the form; `subject`, `body`)."""
    record = ({'model': data['table'], 'id': data['id']}
              if data.get('table') and data.get('id') is not None else None)
    values = {k: data[k] for k in ('subject', 'body', 'to') if data.get(k) is not None}
    functions, fallback = check_choice(data.get('functions'), data.get('fallback'))
    return {'status': 'success', 'code': 200,
            'data': compose_action(record, page=data.get('page') or 'smtp_compose',
                                   functions=functions, fallback=fallback, **values)}


@endpoint('smtp_addresses', access='smtp.send')
def smtp_addresses(data):
    """The addresses of a record, for the dialog of the To field: one row per
    address, `to` being how the field writes it, and the functions some of
    them hold, to tick them by."""
    model, record_id = data.get('model'), data.get('id')
    if not model or record_id is None:
        raise Invalid(_("'model' and 'id' name the record"))
    if not check_readable(str(model), record_id):
        return {'status': 'success', 'code': 200, 'data': {'addresses': [], 'functions': []}}
    rows = of_record(str(model), record_id)
    held = {f for r in rows for f in r['functions']}
    return {'status': 'success', 'code': 200, 'data': {
        'addresses': [{**r, 'to': formatted(r)} for r in rows],
        'functions': [f for f in functions_of(str(model)) if f.get('value') in held]}}


def _recipient_links(record: Dict[str, Any], to: Any) -> List[Dict[str, Any]]:
    """The rows of the record's addresses the message goes to, other than the
    record itself: a contact picked in the dialog sees the message among its
    mail sent."""
    try:
        wanted = {parseaddr(a)[1].lower() for a in addresses(to, 'to')}
    except Invalid:
        return []
    return [{'model': r['model'], 'id': r['id'], 'role': 'recipient'}
            for r in of_record(str(record['model']), record['id'])
            if r['email'].lower() in wanted
            and (r['model'], str(r['id'])) != (record['model'], str(record['id']))]


@endpoint('smtp_compose_send', access='smtp.send')
def smtp_compose_send(data):
    """The compose form's save: its draft becomes a message and is sent."""
    draft = data.get('data')
    if not isinstance(draft, dict):
        raise Invalid(_("'data' is the form's draft"))
    message = {k: draft[k] for k in MESSAGE_FIELDS if draft.get(k) not in (None, '')}
    message['attachments'] = [{'ref': a['ref']} for a in draft.get('attachments') or []
                              if isinstance(a, dict) and a.get('ref')]
    params = {k: v for k, v in draft.items() if k not in MESSAGE_FIELDS}
    if params:
        message['params'] = params
    links = message.get('links') or []
    if not isinstance(links, list) or not all(isinstance(l, dict) and l.get('model')
                                              for l in links):
        raise Invalid(_("'links' is a list of {model, id, role}"))
    for link in links:
        check_readable(str(link['model']), link.get('id'))
    record = message.get('record')
    if record:
        check_readable(str(record['model']), record['id'])
        links = links + _recipient_links(record, message.get('to'))
    message['links'] = links
    result = send(message, trusted=False)
    opts = options()
    if result['status'] == 'dry_run':
        info = _('Dry run: the message was written to a file, not sent')
    else:
        to = [opts['redirect_to']] if opts['redirect_to'] else addresses(message.get('to'), 'to')
        info = _f('Sent to {to}', to=', '.join(parseaddr(a)[1] for a in to))
    lines = [info] + ([result['warning']] if result.get('warning') else [])
    return {'status': 'success', 'code': 200, 'data': {'id': result['id']},
            '$flow': {'info': lines}}


@endpoint('smtp_preview', access='smtp.send')
def smtp_preview(data):
    message = data.get('message')
    if not isinstance(message, dict):
        raise Invalid(_("'message' is a mapping of to, subject, body..."))
    parts = compose(message)
    parts['placeholders'] = placeholders(
        (message.get('subject') or '') + '\n' + (message.get('body') or ''))
    return {'status': 'success', 'code': 200, 'data': parts}


def _may_read(log: Any, links: List[Any]) -> bool:
    """Whether the user may read one message: with MailLog.read, as its sender,
    or as someone who reads one of the records it concerns."""
    if access.can('MailLog.read'):
        return True
    if log.user_id is not None and log.user_id == (kitebase.context.current() or {}).get('id'):
        return True
    for link in links:
        try:
            if check_readable(link.model, link.record_id):
                return True
        except (access.AccessDenied, NotFound):
            continue
    return False


@endpoint('smtp_message', access=access.PER_TABLE)
def smtp_message(data):
    """One message as the detail of the mail sent shows it."""
    app = kitebase.utils.get_app()
    MailLog, MailLink = app.models['MailLog'], app.models['MailLink']
    with access.system(), app.get_session() as session:
        log = session.get(MailLog, coerce_value(MailLog, 'id', data.get('id')))
        links = session.query(MailLink).filter(MailLink.mail_log_id == log.id).all() if log else []
        if log is None or not _may_read(log, links):
            raise NotFound(_f('No message {id}', id=data.get('id')))
        return {'status': 'success', 'code': 200, 'data': {
            'id': log.id, 'status': log.status, 'account': log.account, 'sender': log.sender,
            'to': ', '.join(log.to or []), 'cc': ', '.join(log.cc or []),
            'bcc': ', '.join(log.bcc or []), 'delivered_to': ', '.join(log.delivered_to or []),
            'subject': log.subject, 'body': log.body,
            'attachments': ', '.join(outbox.name_of(r) for r in log.attachments or []),
            'sent_at': log.sent_at.isoformat(sep=' ', timespec='minutes') if log.sent_at else None,
            'error': log.error,
        }}


@endpoint('smtp_sent_page', access=access.PER_TABLE)
def smtp_sent_page(data):
    """A row command: the page of the mail sent about the row, which reads it
    through smtp_sent. The record is checked here too, so a row the user cannot
    read opens nothing."""
    model, record_id = data.get('table'), data.get('id')
    if not model or record_id is None:
        raise Invalid(_('Select a record first'))
    if not check_readable(str(model), record_id):
        access.check_table('MailLog', 'read')
    return {'status': 'success', 'code': 200,
            'data': {'action': 'stack_push', 'panel': 'smtp_sent',
                     'props': {'model': model, 'id': record_id}}}


@endpoint('smtp_sent', access=access.PER_TABLE)
def smtp_sent(data):
    model, record_id = data.get('model'), data.get('id')
    if not model or record_id is None:
        raise Invalid(_("'model' and 'id' name the record"))
    if not check_readable(str(model), record_id):
        access.check_table('MailLog', 'read')
    app = kitebase.utils.get_app()
    MailLog, MailLink = app.models['MailLog'], app.models['MailLink']
    with access.system(), app.get_session() as session:
        rows = (session.query(MailLink, MailLog)
                .join(MailLog, MailLink.mail_log_id == MailLog.id)
                .filter(MailLink.model == str(model), MailLink.record_id == str(record_id))
                .order_by(MailLog.id.desc()).all())
        # One row per message, as a list shows it: the lists of addresses and
        # attachments as text
        out: List[Dict[str, Any]] = [{
            'id': log.id, 'role': link.role, 'status': log.status,
            'sender': log.sender, 'to': ', '.join(log.to or []), 'cc': ', '.join(log.cc or []),
            'subject': log.subject,
            'attachments': ', '.join(outbox.name_of(r) for r in log.attachments or []),
            'sent_at': log.sent_at.isoformat(sep=' ', timespec='minutes') if log.sent_at else None,
            'error': log.error,
        } for link, log in rows]
    return {'status': 'success', 'code': 200, 'data': out}
