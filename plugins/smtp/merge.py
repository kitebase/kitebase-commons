"""A mail merge: one text, sent to each record ticked in a list.

`smtp_merge` is the list's command: the ticked rows (`ids`, or the one under
the cursor) of its `table`. It opens the merge form with a draft that says
who will receive the message and who has no address. The text's
placeholders read each record in turn, so one text becomes one message per
recipient.

`smtp_merge_send` is the form's save. It prepares every message before
sending any: a placeholder that does not resolve for one record refuses the
whole merge, naming the records, and the form stays open. The attachments
are read once and shared. Then it sends, one message after the other, and
says how it went: how many left, who was skipped for want of an address,
who failed. With `keep_log` off the messages leave no row in the log.

The sending is synchronous, in the request: right for tens of messages. A
merge of thousands, and the quotas of a provider, are the work of a job.
"""
from typing import Any, Dict, List

from sqlalchemy import inspect

import kitebase.context
import kitebase.utils
from kitebase.endpoint_db import coerce_value
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, Unavailable
from kitebase.i18n import _, _f

from smtp.accounts import of_user
from smtp.endpoints import _recipient, check_readable
from smtp.mailer import dispatch, prepare, read_attachments

# The fields of the merge form that are not parameters of the text
MERGE_FIELDS = ('account', 'subject', 'body', 'attachments', 'receipt', 'keep_log',
                'model', 'ids', 'recipients')

# How many names a summary lists before saying how many more
SHOWN = 10


def _label(model: str, record_id: Any) -> str:
    """How a record is named to the user: its display field, or its key."""
    app = kitebase.utils.get_app()
    table = app.tables.get(model)
    display = kitebase.utils.search_info(table).get('display_field')
    if display:
        Model = app.models[model]
        key = inspect(Model).primary_key[0].key
        with app.get_session() as session:
            row = session.get(Model, coerce_value(Model, key, record_id))
            if row is not None and getattr(row, display, None):
                return str(getattr(row, display))
    return f'{model} {record_id}'


def _names(labels: List[str]) -> str:
    shown = ', '.join(labels[:SHOWN])
    more = len(labels) - SHOWN
    return shown + (_f(' and {n} more', n=more) if more > 0 else '')


def _ids(data: Dict[str, Any]) -> List[Any]:
    ids = data.get('ids') or ([data['id']] if data.get('id') is not None else [])
    if not isinstance(ids, list) or not ids:
        raise Invalid(_('Tick the records to write to first'))
    return ids


def recipients(model: str, ids: List[Any]):
    """The records with an address and those without, each checked readable."""
    found, missing = [], []
    for record_id in ids:
        check_readable(model, record_id)
        address = _recipient(model, record_id)
        if address:
            found.append((record_id, address))
        else:
            missing.append(_label(model, record_id))
    return found, missing


@endpoint('smtp_merge', access='smtp.send')
def smtp_merge(data):
    """The list's command: the ticked rows of `table`; `page` names the form."""
    model = data.get('table')
    if not model:
        raise Invalid(_('A mail merge is a command of a list'))
    ids = _ids(data)
    found, missing = recipients(str(model), ids)
    summary = _f('{n} recipients', n=len(found))
    if missing:
        summary += '. ' + _f('Without an address, skipped: {names}', names=_names(missing))
    user = (kitebase.context.current() or {}).get('id')
    accounts = of_user(user) if user is not None else []
    draft = {'account': accounts[0] if accounts else None, 'model': model, 'ids': ids,
             'recipients': summary, 'attachments': [], 'receipt': False, 'keep_log': True}
    for key in ('subject', 'body'):
        if data.get(key):
            draft[key] = data[key]
    return {'status': 'success', 'code': 200, 'data': {
        'action': 'open_form', 'page': data.get('page') or 'smtp_merge',
        'draft': {'values': draft}, 'title': _('Mail merge')}}


@endpoint('smtp_merge_send', access='smtp.send')
def smtp_merge_send(data):
    draft = data.get('data')
    if not isinstance(draft, dict) or not draft.get('model'):
        raise Invalid(_("'data' is the merge form's draft"))
    model, ids = str(draft['model']), _ids(draft)
    found, missing = recipients(model, ids)
    if not found:
        raise Invalid(_('None of the records has an address'))
    params = {k: v for k, v in draft.items() if k not in MERGE_FIELDS}
    refs = [{'ref': a['ref']} for a in draft.get('attachments') or []
            if isinstance(a, dict) and a.get('ref')]
    files = read_attachments(refs, trusted=False)

    # Every message prepared before any leaves: one refusal stops the merge
    prepared, refused = [], []
    for record_id, address in found:
        message = {'account': draft.get('account'), 'to': [address],
                   'subject': draft.get('subject'), 'body': draft.get('body') or '',
                   'receipt': bool(draft.get('receipt')), 'params': params,
                   'record': {'model': model, 'id': record_id}}
        try:
            prepared.append(prepare(message, trusted=False, files=files))
        except Invalid as e:
            refused.append(f'{_label(model, record_id)}: {e}')
    if refused:
        raise Invalid(_f('Nothing was sent. {n} messages cannot leave: {list}',
                         n=len(refused), list='; '.join(refused[:SHOWN])))

    keep_log = draft.get('keep_log') is not False
    sent, failed, dry = 0, [], 0
    for (record_id, _address), p in zip(found, prepared):
        try:
            result = dispatch(p, log=keep_log)
        except Unavailable as e:
            failed.append(f'{_label(model, record_id)}: {e}')
            continue
        dry += result['status'] == 'dry_run'
        sent += result['status'] == 'sent'

    lines = []
    if sent:
        lines.append(_f('{n} messages sent', n=sent))
    if dry:
        lines.append(_f('{n} messages written to a file (dry run), not sent', n=dry))
    if missing:
        lines.append(_f('Without an address, skipped: {names}', names=_names(missing)))
    if failed:
        lines.append(_f('Failed: {list}', list='; '.join(failed[:SHOWN])))
    if not keep_log:
        lines.append(_('No log was kept of these messages'))
    return {'status': 'success', 'code': 200, 'data': {'sent': sent + dry, 'failed': len(failed)},
            '$flow': {'info': lines}}
