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
from kitebase import access, apptime
from kitebase.defaults import op_date
from kitebase.endpoint_db import coerce_value, handle_create, handle_update
from kitebase.endpoints import endpoint
from kitebase.errors import Invalid, NotFound, Refusal
from kitebase.flow import form_view
from kitebase.i18n import _, _f
from kitebase.refs import check_readable

from activities.api import link, log_activity, make_types


def _id(data: Dict[str, Any], missing: str = '') -> Any:
    """The row a row command acts on: the active one, whatever is ticked."""
    if data.get('id') is not None:
        return data['id']
    ids = data.get('ids') or []
    if len(ids) != 1:
        raise Invalid(missing or _('Select an opportunity first'))
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

def _ids(data: Dict[str, Any], missing: str = '') -> List[Any]:
    """The rows a command acts on: the ticked ones, else the active one."""
    ids = data.get('ids') or ([data['id']] if data.get('id') is not None else [])
    if not ids:
        raise Invalid(missing or _('Select an opportunity first'))
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


# ── From the partners: a new opportunity, a contact for a campaign ───────────
#
# Commands this plugin adds to the partners' list view (pages.yaml). A new
# opportunity opens its form for the partner of the row; its campaign is
# chosen there, never guessed. A contact for a campaign writes one activity per
# partner, linked to the campaign too: the partners contacted are the
# campaign's members, and a contact still to do is one still to follow up.

@endpoint('crm_new_opportunity', access='Opportunity.create')
def crm_new_opportunity(data):
    partner_id = _id(data, _('Select a partner first'))
    if not check_readable('Partner', partner_id):
        raise NotFound(_f('No {model} {id}', model='Partner', id=partner_id))
    values = {'partner_id': partner_id}
    return {'status': 'success', 'data': {
        'action': 'open_form', 'page': 'opportunity_form', 'draft': {'values': values},
        'title': _('New opportunity')}}


def _campaigns() -> List[Dict[str, Any]]:
    app = kitebase.utils.get_app()
    Campaign = app.models['Campaign']
    with app.get_session() as session:
        rows = (session.query(Campaign).filter(Campaign.active.is_(True))
                .order_by(Campaign.start_date.desc(), Campaign.id.desc()).all())
        return [{'value': c.id, 'label': c.name} for c in rows]


@endpoint('crm_campaign_contact', access='Activity.create')
def crm_campaign_contact(data):
    ids = _ids(data, _('Select a partner first'))
    campaigns = _campaigns()
    if not campaigns:
        raise Invalid(_('There is no active campaign yet: create one first'))
    view, values = form_view('crm_campaign_form')
    types = _types()
    for section in view.get('layout') or []:
        for field in section.get('fields') or []:
            if field.get('name') == 'type':
                field['choices'] = types
            if field.get('name') == 'campaign_id':
                field['choices'] = campaigns
    values.update({'campaign_id': campaigns[0]['value'],
                   # To do: a contact is followed up, and closed when it has its outcome
                   'due_date': op_date().isoformat(),
                   'type': 'call' if any(t['value'] == 'call' for t in types)
                   else (types[0]['value'] if types else None)})
    title = (_f('Contact {n} partners for a campaign', n=len(ids)) if len(ids) > 1
             else _('Contact for a campaign'))
    return {'status': 'success', 'data': {
        'action': 'form', 'title': title, 'view': view, 'values': values,
        'then': {'action': 'endpoint', 'op': 'crm_campaign_contact_save', 'params': {'ids': ids}}}}


@endpoint('crm_campaign_contact_save', access='Activity.create')
def crm_campaign_contact_save(data):
    ids = _ids(data, _('Select a partner first'))
    subject = (data.get('subject') or '').strip()
    campaign = data.get('campaign_id')
    if not data.get('type') or not subject or campaign in (None, ''):
        raise Invalid(_('A campaign, a type and a subject are needed'))
    if not check_readable('Campaign', campaign):
        raise NotFound(_f('No {model} {id}', model='Campaign', id=campaign))
    Activity = kitebase.utils.get_app().models['Activity']
    due = data.get('due_date')
    due = coerce_value(Activity, 'due_date', due) if due else None
    written, skipped = 0, 0
    app = kitebase.utils.get_app()
    # One transaction: the partners are contacted all, or none
    with app.get_session() as session:
        for partner_id in ids:
            if not check_readable('Partner', partner_id):
                skipped += 1
                continue
            log_activity(('Partner', partner_id), str(data['type']), subject,
                         also=[('Campaign', campaign)], note=data.get('note') or None,
                         due_date=due, source='crm.campaign', session=session)
            written += 1
        session.commit()
    message = (_('One partner contacted') if written == 1
               else _f('{n} partners contacted', n=written))
    if skipped:
        message += '. ' + _f('{n} not readable, left out', n=skipped)
    # The rows touched: their history, beside the list, reads the new contact
    return {'status': 'success', 'data': {'message': message, 'touched': ids}}


# ── An opportunity from an activity ──────────────────────────────────────────
#
# A command on the contacts of a campaign (pages.yaml): the contact went well,
# and becomes a negotiation. The partner and the campaign are the activity's own links,
# nothing guessed; the activity is done, and linked to the opportunity, whose
# story starts from it. The new opportunity opens to be completed.

def _activity_refs(session: Any, activity_id: Any) -> Dict[str, Any]:
    Link = kitebase.utils.get_app().models['ActivityLink']
    refs: Dict[str, Any] = {}
    for link in (session.query(Link).filter(Link.activity_id == activity_id)
                 .order_by(Link.id)):
        refs.setdefault(link.model, link.record_id)
    return refs


@endpoint('crm_opportunity_from_activity', access='Opportunity.create')
def crm_opportunity_from_activity(data):
    activity_id = data.get('id')
    if activity_id in (None, ''):
        raise Invalid(_('Save the activity first'))
    app = kitebase.utils.get_app()
    Activity = app.models['Activity']
    with app.get_session() as session:
        activity = session.get(Activity, activity_id)
        if activity is None:
            raise NotFound(_f('No {model} {id}', model='Activity', id=activity_id))
        refs = _activity_refs(session, activity_id)
        subject = activity.subject
    if 'Opportunity' in refs:
        raise Invalid(_('This activity already belongs to an opportunity'))
    partner = refs.get('Partner')
    if partner is None or not check_readable('Partner', partner):
        raise Invalid(_('This activity concerns no partner: an opportunity needs one'))
    values: Dict[str, Any] = {'name': subject, 'partner_id': int(partner)}
    if refs.get('Campaign') is not None:
        values['campaign_id'] = int(refs['Campaign'])

    result = handle_create(app, app.models['Opportunity'], {'data': values},
                           app.tables.get('Opportunity'))
    if result.get('status') != 'success':
        return result
    opportunity = (result.get('data') or {}).get('id')
    with app.get_session() as session:
        activity = session.get(Activity, activity_id)
        if activity.done_at is None:
            activity.done_at = apptime.now()
        link(session, activity_id, [('Opportunity', opportunity)])
        session.commit()
    return {'status': 'success', 'data': {
        'action': 'open_form', 'page': 'opportunity_form', 'id': opportunity,
        'title': _('Opportunity')}}

