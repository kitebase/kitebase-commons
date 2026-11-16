"""Closing an opportunity from a list or the board, and planning what comes next.

Navigator commands on the active row. `crm_close` with `outcome: won` closes
it; with `outcome: lost` and no reason it answers with the menu of the lost
reasons, whose entries call it again with the reason picked. The record is
written by the update of `db`, so the rules hold as in the form: the closing
date follows, the stage stays where it closed, and the story of the
negotiation gets its line.
"""
from datetime import timedelta
from typing import Any, Dict, List

import kitebase.utils
from kitebase import access
from kitebase.defaults import op_date
from kitebase.endpoint_db import coerce_value, handle_update
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound, Refusal
from kitebase.flow import form_view
from kitebase.i18n import _, _f
from kitebase.refs import check_readable

from activities.api import log_activity, make_types


def _id(data: Dict[str, Any]) -> Any:
    """The row a row command acts on: the active one, whatever is ticked."""
    if data.get('id') is not None:
        return data['id']
    ids = data.get('ids') or []
    if len(ids) != 1:
        raise Invalid(_('Select an opportunity first'))
    return ids[0]


def _reasons() -> List[Any]:
    app = kitebase.utils.get_app()
    Reason = app.models['LostReason']
    with app.get_session() as session:
        return [(r.id, r.name) for r in session.query(Reason).order_by(Reason.sequence, Reason.id)]


def _write(record_id: Any, values: Dict[str, Any], done: str) -> Dict[str, Any]:
    app = kitebase.utils.get_app()
    try:
        result = handle_update(app, app.models['Opportunity'], {'id': record_id, 'data': values},
                               app.tables.get('Opportunity'))
    except Refusal as e:
        return {'status': 'error', 'message': e.message, 'code': 422}
    if result.get('status') != 'success':
        return result
    return {'status': 'success', 'data': {'message': done, 'touched': [record_id]}}


@endpoint('crm_close', access=access.PER_TABLE)
def crm_close(data):
    access.check_table('Opportunity', 'update')
    record_id = _id(data)
    outcome = data.get('outcome')
    if outcome == 'won':
        return _write(record_id, {'outcome': 'won'}, _('Won'))
    if outcome == 'open':
        return _write(record_id, {'outcome': 'open', 'lost_reason_id': None}, _('Opened again'))
    if outcome != 'lost':
        raise Invalid(_f('The outcome is one of: {values}', values='won, lost, open'))

    reason = data.get('reason')
    reasons = _reasons()
    if reason is None and reasons:
        # Why it was lost is what the figures count: asked, from the list
        def entry(rid, name):
            return {'label': name, 'then': {'action': 'endpoint', 'op': 'crm_close',
                                            'params': {'id': record_id, 'outcome': 'lost',
                                                       'reason': rid}}}
        return {'status': 'success', 'data': {
            'action': 'choose', 'title': _('Why was it lost?'),
            'options': [entry(rid, name) for rid, name in reasons]}}
    name = dict(reasons).get(reason)
    return _write(record_id, {'outcome': 'lost', 'lost_reason_id': reason},
                  _f('Lost: {reason}', reason=name) if name else _('Lost'))


# ── Planning the next step ───────────────────────────────────────────────────
#
# `crm_plan` answers with a short form (type, subject, day, note), which the
# client shows in a dialog; its values come back to `crm_plan_save`, which
# writes an activity to do on the opportunity. The view refreshes the row, and
# the card shows it as its next activity.

def _types() -> List[Dict[str, Any]]:
    app = kitebase.utils.get_app()
    Type = app.models['ActivityType']
    with app.get_session() as session:
        make_types(session)
        session.commit()
        rows = (session.query(Type).filter(Type.pick.is_(True))
                .order_by(Type.sequence, Type.id).all())
        return [{'value': t.id, 'label': t.label or t.id} for t in rows]


def _readable(record_id: Any) -> None:
    if not check_readable('Opportunity', record_id):
        raise NotFound(_f('No {model} {id}', model='Opportunity', id=record_id))


@endpoint('crm_plan', access='Activity.create')
def crm_plan(data):
    record_id = _id(data)
    _readable(record_id)
    view, values = form_view('crm_plan_form')
    types = _types()
    for section in view.get('layout') or []:
        for field in section.get('fields') or []:
            if field.get('name') == 'type':
                field['choices'] = types
    values.update({'type': 'call' if any(t['value'] == 'call' for t in types)
                   else (types[0]['value'] if types else None),
                   'due_date': (op_date() + timedelta(days=1)).isoformat()})
    return {'status': 'success', 'data': {
        'action': 'form', 'title': _('Plan an activity'), 'view': view, 'values': values,
        'then': {'action': 'endpoint', 'op': 'crm_plan_save', 'params': {'id': record_id}}}}


@endpoint('crm_plan_save', access='Activity.create')
def crm_plan_save(data):
    record_id = _id(data)
    _readable(record_id)
    subject = (data.get('subject') or '').strip()
    if not data.get('type') or not subject:
        raise Invalid(_('An activity needs a type and a subject'))
    Activity = kitebase.utils.get_app().models['Activity']
    due = data.get('due_date')
    log_activity(('Opportunity', record_id), str(data['type']), subject,
                 note=data.get('note') or None,
                 due_date=coerce_value(Activity, 'due_date', due) if due else op_date())
    return {'status': 'success', 'data': {'message': _f('Planned: {subject}', subject=subject),
                                          'touched': [record_id]}}



# ── Handing negotiations to another salesperson ──────────────────────────────
#
# On the active row or the ticked ones: someone leaves, or is away. The menu
# lists the users; the pick writes each opportunity by the update of db.

def _ids(data: Dict[str, Any]) -> List[Any]:
    ids = data.get('ids') or ([data['id']] if data.get('id') is not None else [])
    if not ids:
        raise Invalid(_('Select an opportunity first'))
    return ids


@endpoint('crm_salesperson', access=access.PER_TABLE)
def crm_salesperson(data):
    access.check_table('Opportunity', 'update')
    ids = _ids(data)
    app = kitebase.utils.get_app()
    User = app.models['User']
    with app.get_session() as session:
        users = [(u.id, u.name or u.username) for u in session.query(User).order_by(User.name)]
    title = (_f('Hand {n} opportunities to', n=len(ids)) if len(ids) > 1
             else _('Hand the opportunity to'))
    return {'status': 'success', 'data': {'action': 'choose', 'title': title, 'options': [
        {'label': name, 'then': {'action': 'endpoint', 'op': 'crm_salesperson_set',
                                 'params': {'ids': ids, 'user_id': uid}}}
        for uid, name in users]}}


@endpoint('crm_salesperson_set', access=access.PER_TABLE)
def crm_salesperson_set(data):
    access.check_table('Opportunity', 'update')
    ids, user_id = _ids(data), data.get('user_id')
    if user_id is None:
        raise Invalid(_('Choose who takes them'))
    app = kitebase.utils.get_app()
    model, table = app.models['Opportunity'], app.tables.get('Opportunity')
    touched, stopped = [], []
    for record_id in ids:
        try:
            result = handle_update(app, model, {'id': record_id, 'data': {'user_id': user_id}}, table)
        except Refusal as e:
            result = {'status': 'error', 'message': e.message}
        if result.get('status') == 'success':
            touched.append(record_id)
        else:
            stopped.append(f"#{record_id}: {result.get('message')}")
    message = _f('{n} changed', n=len(touched)) if touched else _('Nothing to change')
    if stopped:
        message += '. ' + _f('Left as they were: {names}', names='; '.join(stopped))
    return {'status': 'success', 'data': {'message': message, 'touched': touched}}
