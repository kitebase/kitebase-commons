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

`smtp_sent` is the mail of one record, newest first. The links are not read
directly: the record is read first, with the user's permissions and record
rules (404 when they do not reach it), and only then its links, for the
system. Whoever sees the record sees the mail about it, and nothing else.
"""
from typing import Any, Dict, List

from sqlalchemy import inspect

import kitebase.utils
from kitebase import access
from kitebase.endpoint_db import coerce_value
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound
from kitebase.media import UploadedFile
from kitebase.i18n import _, _f
from kitebase.transforms import register_validator

from smtp import outbox
from smtp.accounts import names, validate_accounts
from smtp.mailer import send
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


@endpoint('smtp_preview', access='smtp.send')
def smtp_preview(data):
    message = data.get('message')
    if not isinstance(message, dict):
        raise Invalid(_("'message' is a mapping of to, subject, body..."))
    parts = compose(message)
    parts['placeholders'] = placeholders(
        (message.get('subject') or '') + '\n' + (message.get('body') or ''))
    return {'status': 'success', 'code': 200, 'data': parts}


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
        out: List[Dict[str, Any]] = [{
            'id': log.id, 'role': link.role, 'status': log.status,
            'sender': log.sender, 'to': log.to, 'cc': log.cc,
            'subject': log.subject,
            'attachments': [outbox.name_of(r) for r in log.attachments or []],
            'sent_at': log.sent_at.isoformat() if log.sent_at else None,
            'error': log.error,
        } for link, log in rows]
    return {'status': 'success', 'code': 200, 'data': out}
