"""A mail merge: one text, sent to each record ticked in a list.

`smtp_merge` is the list's command: the ticked rows (`ids`, or the one under
the cursor) of its `table`. Its params may say whom inside each record
(`functions`, `fallback`: addresses.py). It opens the merge form with a draft
that says how many records and addresses, who went to the main address for
want of a contact with the function, who is skipped. The text's placeholders
read each record in turn, so one text becomes one message per record, with
all its chosen addresses in To: colleagues see each other.

With `per_contact` each address is a message of its own, and its record is
the row the address belongs to (a contact): a personal greeting, and
`[[parent.name]]` reaches the company. The record ticked is linked as well,
so its list of mail sent shows the message.

`smtp_merge_recipients` says it again when the form changes whom inside
(the widget of its `recipients` field). `smtp_merge_send` is the form's save. It prepares every message before
sending any: a placeholder that does not resolve for one record refuses the
whole merge, naming the records, and the form stays open. The attachments
are read once and shared. Then it sends, one message after the other, and
says how it went. With `keep_log` off the messages leave no row in the log.

The sending is synchronous, in the request: right for tens of messages. A
merge of thousands, and the quotas of a provider, are the work of a job.
"""
from typing import Any, Dict, List, Tuple

from sqlalchemy import inspect

import kitebase.context
import kitebase.utils
from kitebase.endpoint_db import coerce_value
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, Unavailable
from kitebase.i18n import _, _f
from kitebase.refs import check_readable

from smtp.accounts import of_user
from smtp.addresses import check_choice, choose, formatted, of_record
from smtp.mailer import dispatch, prepare, read_attachments

# The fields of the merge form that are not parameters of the text
MERGE_FIELDS = ('account', 'subject', 'body', 'attachments', 'receipt', 'keep_log',
                'model', 'ids', 'recipients', 'functions', 'fallback', 'per_contact')

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


class Recipients:
    """Whom a merge writes to: per record its chosen addresses, and the
    records that went to the fallback, were skipped, or have no address."""

    def __init__(self, model: str, ids: List[Any], functions: List[str], fallback: str):
        self.found: List[Tuple[Any, List[Dict[str, Any]]]] = []
        self.missing: List[str] = []
        self.fallen_back: List[str] = []
        self.skipped: List[str] = []
        for record_id in ids:
            check_readable(model, record_id)
            rows = of_record(model, record_id)
            chosen, outcome = choose(rows, functions, fallback)
            if not rows:
                self.missing.append(_label(model, record_id))
            elif outcome == 'skipped':
                self.skipped.append(_label(model, record_id))
            else:
                if outcome == 'fallback':
                    self.fallen_back.append(_label(model, record_id))
                self.found.append((record_id, chosen))

    @property
    def addresses(self) -> int:
        return sum(len(rows) for _id, rows in self.found)

    def notes(self) -> List[str]:
        """Who did not get what was asked, one line each."""
        lines = []
        if self.fallen_back:
            lines.append(_f('No contact with the function, to the main address: {names}',
                            names=_names(self.fallen_back)))
        if self.skipped:
            lines.append(_f('No contact with the function, skipped: {names}',
                            names=_names(self.skipped)))
        if self.missing:
            lines.append(_f('Without an address, skipped: {names}', names=_names(self.missing)))
        return lines


def _choice(data: Dict[str, Any]) -> Tuple[List[str], str]:
    return check_choice(data.get('functions'), data.get('fallback'))


def _summary(model: str, ids: List[Any], data: Dict[str, Any]) -> str:
    """One line on whom a merge writes to, as the form shows it."""
    functions, fallback = _choice(data)
    found = Recipients(model, ids, functions, fallback)
    messages = found.addresses if data.get('per_contact') else len(found.found)
    counts = _f('Messages: {n}, addresses: {m}', n=messages, m=found.addresses)
    return '. '.join([counts] + found.notes())


@endpoint('smtp_merge', access='smtp.send')
def smtp_merge(data):
    """The list's command: the ticked rows of `table`; `page` names the form,
    `functions` and `fallback` whom inside each record."""
    model = data.get('table')
    if not model:
        raise Invalid(_('A mail merge is a command of a list'))
    ids = _ids(data)
    functions, fallback = _choice(data)
    summary = _summary(str(model), ids, data)
    user = (kitebase.context.current() or {}).get('id')
    accounts = of_user(user) if user is not None else []
    draft = {'account': accounts[0] if accounts else None, 'model': model, 'ids': ids,
             'functions': functions, 'fallback': fallback, 'per_contact': False,
             'recipients': summary, 'attachments': [], 'receipt': False, 'keep_log': True}
    for key in ('subject', 'body'):
        if data.get(key):
            draft[key] = data[key]
    return {'status': 'success', 'code': 200, 'data': {
        'action': 'open_form', 'page': data.get('page') or 'smtp_merge',
        'draft': {'values': draft}, 'title': _('Mail merge')}}


@endpoint('smtp_merge_recipients', access='smtp.send')
def smtp_merge_recipients(data):
    """The summary again, for the form whose functions, fallback or
    `per_contact` changed: `data` is its draft."""
    draft = data.get('data')
    if not isinstance(draft, dict) or not draft.get('model'):
        raise Invalid(_("'data' is the merge form's draft"))
    return {'status': 'success', 'code': 200,
            'data': _summary(str(draft['model']), _ids(draft), draft)}


def _messages(model: str, found: Recipients, per_contact: bool,
              base: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    """The messages of a merge, each with the name the summary gives it."""
    out = []
    for record_id, rows in found.found:
        if not per_contact:
            out.append((_label(model, record_id), {
                **base, 'to': [formatted(r) for r in rows],
                'record': {'model': model, 'id': record_id},
                'links': [{'model': r['model'], 'id': r['id'], 'role': 'recipient'}
                          for r in rows
                          if (r['model'], str(r['id'])) != (model, str(record_id))]}))
            continue
        for r in rows:
            out.append((r['name'] or r['email'], {
                **base, 'to': [formatted(r)],
                'record': {'model': r['model'], 'id': r['id']},
                'links': [{'model': model, 'id': record_id}]
                if (r['model'], str(r['id'])) != (model, str(record_id)) else []}))
    return out


@endpoint('smtp_merge_send', access='smtp.send')
def smtp_merge_send(data):
    draft = data.get('data')
    if not isinstance(draft, dict) or not draft.get('model'):
        raise Invalid(_("'data' is the merge form's draft"))
    model, ids = str(draft['model']), _ids(draft)
    functions, fallback = _choice(draft)
    found = Recipients(model, ids, functions, fallback)
    if not found.found:
        raise Invalid(_('None of the records has an address to write to'))
    params = {k: v for k, v in draft.items() if k not in MERGE_FIELDS}
    refs = [{'ref': a['ref']} for a in draft.get('attachments') or []
            if isinstance(a, dict) and a.get('ref')]
    files = read_attachments(refs, trusted=False)
    base = {'account': draft.get('account'), 'subject': draft.get('subject'),
            'body': draft.get('body') or '', 'receipt': bool(draft.get('receipt')),
            'params': params}
    messages = _messages(model, found, bool(draft.get('per_contact')), base)

    # Every message prepared before any leaves: one refusal stops the merge
    prepared, refused = [], []
    for name, message in messages:
        try:
            prepared.append(prepare(message, trusted=False, files=files))
        except Invalid as e:
            refused.append(f'{name}: {e}')
    if refused:
        raise Invalid(_f('Nothing was sent. {n} messages cannot leave: {list}',
                         n=len(refused), list='; '.join(refused[:SHOWN])))

    keep_log = draft.get('keep_log') is not False
    sent, failed, dry, uncopied = 0, [], 0, 0
    for (name, _message), p in zip(messages, prepared):
        try:
            result = dispatch(p, log=keep_log)
        except Unavailable as e:
            failed.append(f'{name}: {e}')
            continue
        dry += result['status'] == 'dry_run'
        sent += result['status'] == 'sent'
        uncopied += bool(result.get('warning'))

    lines = []
    if sent:
        lines.append(_f('{n} messages sent', n=sent))
    if dry:
        lines.append(_f('{n} messages written to a file (dry run), not sent', n=dry))
    lines += found.notes()
    if failed:
        lines.append(_f('Failed: {list}', list='; '.join(failed[:SHOWN])))
    if uncopied:
        lines.append(_f('{n} messages sent without their copy in the Sent folder: see the log',
                        n=uncopied))
    if not keep_log:
        lines.append(_('No log was kept of these messages'))
    return {'status': 'success', 'code': 200, 'data': {'sent': sent + dry, 'failed': len(failed)},
            '$flow': {'info': lines}}
