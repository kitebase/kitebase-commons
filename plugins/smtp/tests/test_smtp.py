"""
The smtp plugin on an application: accounts from the secrets, sending through a
real SMTP server (aiosmtpd), the log and its links, the switches of a
development installation, and who reads the mail of a record.

The application is built once for the module: common, users and smtp from the
commons, plus `crm`, written here, with a table to link messages to.

    (cd commons/demo && uv run pytest -q ../plugins/smtp/tests)
"""
import email
import importlib.util
import os
import shutil
import socket
from datetime import date
from decimal import Decimal
import sys
from email import policy
from pathlib import Path

import pytest
import yaml
from aiosmtpd.controller import Controller

import kitebase.access
import kitebase.context
import kitebase.plugins
import kitebase.source
import kitebase.utils
from kitebase.access import Guard
from kitebase.diagnostics import run_checks
from kitebase.errors import Invalid
from kitebase.media import AllocContext
from kitebase.server_utils import handle_generic_endpoint

COMMONS = Path(__file__).resolve().parents[2]

CRM_MODEL = {'tables': {
    'Agent': {'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60},
    ]},
    'Customer': {'columns': [
        {'name': 'id', 'type': 'ID'},
        {'name': 'name', 'type': 'String', 'length': 60},
        {'name': 'region', 'type': 'String', 'length': 10},
        {'name': 'since', 'type': 'Date'},
        {'name': 'balance', 'type': 'Numeric', 'precision': 12, 'scale': 2},
        {'name': 'pin', 'type': 'String', 'length': 10, 'secret': True},
        {'name': 'margin', 'type': 'Integer', 'column_group': 'pricing'},
        {'name': 'agent_id', 'foreign_key': {'target': 'Agent.id', 'relation': 'agent',
                                             'backref': 'customers'}},
    ]},
}}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class Login:
    """The server's check of a login: the `info` account's credentials."""

    def __call__(self, server, session, envelope, mechanism, auth_data):
        from aiosmtpd.smtp import AuthResult
        ok = (auth_data.login, auth_data.password) == (b'info', b'not-for-the-client')
        return AuthResult(success=ok)


class Inbox:
    """What the SMTP server received."""

    def __init__(self):
        self.envelopes = []

    async def handle_DATA(self, server, session, envelope):
        self.envelopes.append(envelope)
        return '250 OK'

    def last(self):
        envelope = self.envelopes[-1]
        return envelope, email.message_from_bytes(envelope.content, policy=policy.default)


@pytest.fixture(scope='module')
def smtpd():
    inbox = Inbox()
    controller = Controller(inbox, hostname='127.0.0.1', port=free_port(),
                            authenticator=Login(), auth_require_tls=False)
    controller.start()
    yield inbox, controller.port
    controller.stop()


@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root = tmp_path_factory.mktemp('crmapp')
    crm = root / 'plugins' / 'crm'
    crm.mkdir(parents=True)
    (crm / 'config.yaml').write_text(yaml.safe_dump({'name': 'crm', 'depends_on': ['common']}),
                                     encoding='utf-8')
    (crm / 'model.yaml').write_text(yaml.safe_dump(CRM_MODEL), encoding='utf-8')
    (root / 'secrets').mkdir()
    (root / 'config.yaml').write_text(yaml.safe_dump({
        'name': 'crmapp',
        'plugins': [{'path': str(COMMONS), 'include': ['common', 'users', 'smtp']}, 'plugins'],
        'db_engine': f'sqlite:///{root / "crm.sqlite"}',
        'media': {'roots': {'mail': {'type': 'fs', 'path': 'media/mail', 'allocate': 'by_record'}}},
    }), encoding='utf-8')

    cwd = os.getcwd()
    os.chdir(root)
    try:
        pm = kitebase.plugins.PluginsManager()
        pm.load_config('config.yaml')
        pm.load_plugins()
        db = kitebase.utils.get_app()
        db.calc_db(pm)
        kitebase.source.Generator(db).generate(filename='crm_model.py')
        spec = importlib.util.spec_from_file_location('crm_model', root / 'crm_model.py')
        model = importlib.util.module_from_spec(spec)
        sys.modules['crm_model'] = model
        spec.loader.exec_module(model)
        db.initialize_db(pm.config['db_engine'], model)
        db.root = root
        yield db
    finally:
        os.chdir(cwd)


def write_secrets(app, smtpd, **switches):
    _inbox, port = smtpd
    data = {f'${k}': v for k, v in switches.items()}
    data['office'] = {'host': '127.0.0.1', 'port': port, 'security': 'none',
                      'from': 'Office <office@example.com>'}
    data['info'] = {'host': '127.0.0.1', 'port': port, 'security': 'none',
                    'from': 'info@example.com', 'user': 'info', 'password': 'not-for-the-client'}
    (app.root / 'secrets' / 'smtp.yaml').write_text(yaml.safe_dump(data, sort_keys=False),
                                                      encoding='utf-8')


@pytest.fixture(autouse=True)
def clean(app, smtpd):
    """Each test: an empty log, the two accounts, user 7 sending from office."""
    write_secrets(app, smtpd)
    smtpd[0].envelopes.clear()
    shutil.rmtree(app.root / 'media' / 'mail', ignore_errors=True)
    with app.get_session() as s:
        for name in ('MailLink', 'MailLog', 'Customer', 'Agent', 'User'):
            s.query(app.models[name]).delete()
        s.add(app.models['User'](id=7, username='tester', name='Tester', password='x', email='tester@example.com',
                                 mail_accounts=['office']))
        s.add(app.models['Agent'](id=1, name='Carla Bianchi'))
        s.add(app.models['Customer'](id=42, name='Riverside *Hardware*', region='north',
                                     since=date(2024, 3, 5), balance=Decimal('1234.50'),
                                     pin='0000', margin=30, agent_id=1))
        s.add(app.models['Customer'](id=43, name='Hillside', region='south'))
        s.commit()
    yield


def call(app, op, **data):
    return handle_generic_endpoint(app.dispatcher, op, data, {'username': 'tester', 'id': 7})


def message(**over):
    base = {'to': ['Ann <ann@example.com>'], 'subject': 'Invoice 1033',
            'body': 'The invoice is **attached**.\n\n<b>raw</b>'}
    base.update(over)
    return base


def log(app, log_id):
    with app.get_session() as s:
        row = s.get(app.models['MailLog'], log_id)
        s.expunge(row)
        return row


def folder_ref(app, log_id):
    """The folder of a log row, as the media column computes it."""
    return str(app.media.root('mail').folder(AllocContext('MailLog', 'files', log_id)))


def folder(app, log_id):
    return app.media.list(folder_ref(app, log_id))


# ── Sending ───────────────────────────────────────────────────────────────────

def test_a_message_reaches_the_server_with_text_and_html(app, smtpd):
    result = call(app, 'smtp_send', message=message(cc=['bob@example.com']))
    assert result['status'] == 'success', result

    envelope, msg = smtpd[0].last()
    assert envelope.mail_from == 'office@example.com'
    assert sorted(envelope.rcpt_tos) == ['ann@example.com', 'bob@example.com']
    assert msg['Subject'] == 'Invoice 1033'
    assert msg['From'] == 'Office <office@example.com>'
    text = msg.get_body(('plain',)).get_content()
    html = msg.get_body(('html',)).get_content()
    assert 'The invoice is **attached**.' in text
    assert '<strong>attached</strong>' in html
    assert '<b>raw</b>' not in html and '&lt;b&gt;raw&lt;/b&gt;' in html

    row = log(app, result['data']['id'])
    assert (row.status, row.account, row.user_id) == ('sent', 'office', 7)
    assert row.to == ['Ann <ann@example.com>'] and row.cc == ['bob@example.com']
    assert row.message_id == msg['Message-ID'] and row.sent_at is not None


def test_attachments_are_sent_and_kept_in_the_folder_of_the_log(app, smtpd):
    from smtp.mailer import send
    with kitebase.context.use({'id': 7}):
        result = send(message(attachments=[
            {'name': 'notes.txt', 'content': b'hello'}]))
    _envelope, msg = smtpd[0].last()
    parts = list(msg.iter_attachments())
    assert [(p.get_filename(), p.get_content()) for p in parts] == [('notes.txt', 'hello')]
    assert log(app, result['id']).attachments == ['notes.txt']
    assert [f.name for f in folder(app, result['id'])] == ['notes.txt']


def test_the_client_cannot_attach_a_reference(app):
    result = call(app, 'smtp_send', message=message(attachments=[{'media': 'mail:x/y.pdf'}]))
    assert result['status_code'] == 400


def test_a_receipt_is_asked_with_its_header(app, smtpd):
    call(app, 'smtp_send', message=message(receipt=True))
    assert smtpd[0].last()[1]['Disposition-Notification-To'] == 'Office <office@example.com>'


@pytest.mark.parametrize('bad', [
    {'to': []},
    {'to': ['not an address']},
    {'subject': ''},
    {'subject': 'two\nlines'},
    {'links': [{'id': 1}]},
])
def test_a_message_that_cannot_leave_is_refused_and_not_logged(app, bad):
    result = call(app, 'smtp_send', message=message(**bad))
    assert result['status_code'] == 400, result
    with app.get_session() as s:
        assert s.query(app.models['MailLog']).count() == 0


def test_a_server_that_does_not_answer_leaves_a_failed_row(app, smtpd):
    data = yaml.safe_load((app.root / 'secrets' / 'smtp.yaml').read_text())
    data['office']['port'] = free_port()          # nobody listens there
    (app.root / 'secrets' / 'smtp.yaml').write_text(yaml.safe_dump(data, sort_keys=False))
    result = call(app, 'smtp_send', message=message())
    assert result['status_code'] == 503, result
    with app.get_session() as s:
        row = s.query(app.models['MailLog']).one()
        assert row.status == 'failed' and row.error


# ── Accounts ──────────────────────────────────────────────────────────────────

def test_the_account_is_the_users_first_unless_one_of_theirs_is_asked(app, smtpd):
    with app.get_session() as s:
        s.get(app.models['User'], 7).mail_accounts = ['info', 'office']
        s.commit()
    call(app, 'smtp_send', message=message())
    assert smtpd[0].last()[0].mail_from == 'info@example.com'
    call(app, 'smtp_send', message=message(account='office'))
    assert smtpd[0].last()[0].mail_from == 'office@example.com'


def test_an_account_the_user_does_not_hold_is_refused(app):
    assert call(app, 'smtp_send', message=message(account='info'))['status_code'] == 400


def test_a_user_without_accounts_is_told_to_ask(app):
    with app.get_session() as s:
        s.get(app.models['User'], 7).mail_accounts = []
        s.commit()
    result = call(app, 'smtp_send', message=message())
    assert result['status_code'] == 400 and 'administrator' in result['message']


def test_the_system_names_its_account(app, smtpd):
    from smtp.mailer import send
    with kitebase.context.use(None):
        with pytest.raises(Invalid):
            send(message())
        assert send(message(account='info'))['status'] == 'sent'


def test_the_vocabulary_has_the_names_and_never_the_values(app):
    result = call(app, 'smtp_accounts')
    assert [c['value'] for c in result['data']] == ['office', 'info']
    assert 'not-for-the-client' not in repr(result)


def test_the_column_refuses_an_account_that_does_not_exist(app):
    result = call(app, 'db', table='User', method='update', id=7,
                  data={'mail_accounts': ['office', 'nope']})
    assert result['status_code'] == 400 and 'nope' in repr(result)


# ── Switches of a development installation ────────────────────────────────────

def test_redirect_sends_to_one_address_and_logs_both(app, smtpd):
    write_secrets(app, smtpd, redirect_to='dev@example.com')
    result = call(app, 'smtp_send', message=message(bcc=['secret@example.com']))
    envelope, msg = smtpd[0].last()
    assert envelope.rcpt_tos == ['dev@example.com']
    assert msg['To'] == 'Ann <ann@example.com>'
    assert msg['X-Redirected-From'] == 'ann@example.com, secret@example.com'
    row = log(app, result['data']['id'])
    assert row.delivered_to == ['dev@example.com'] and row.bcc == ['secret@example.com']


def test_dry_run_writes_the_message_and_sends_nothing(app, smtpd):
    write_secrets(app, smtpd, dry_run=True)
    result = call(app, 'smtp_send', message=message())
    assert smtpd[0].envelopes == []
    assert result['data']['status'] == 'dry_run'
    files = {f.name for f in folder(app, result['data']['id'])}
    assert files == {'dry_run.eml'}
    with app.media.open(folder_ref(app, result['data']['id']) + 'dry_run.eml') as f:
        assert email.message_from_bytes(f.read(), policy=policy.default)['Subject'] == 'Invoice 1033'


def test_check_says_while_a_switch_is_on_and_when_an_account_is_broken(app, smtpd):
    write_secrets(app, smtpd, dry_run=True, redirect_to='dev@example.com')
    data = yaml.safe_load((app.root / 'secrets' / 'smtp.yaml').read_text())
    data['broken'] = {'host': 'x', 'from': 'x@example.com', 'user': 'only-user'}
    (app.root / 'secrets' / 'smtp.yaml').write_text(yaml.safe_dump(data, sort_keys=False))
    issues = {i['code']: i for i in run_checks(app) if i['code'].startswith('smtp')}
    assert issues['smtp-dry-run']['severity'] == 'warning'
    assert issues['smtp-redirect']['severity'] == 'warning'
    assert issues['smtp-account']['severity'] == 'error'
    assert issues['smtp-account']['path'].endswith('.broken')


def test_check_has_nothing_to_say_on_a_clean_installation(app):
    assert [i for i in run_checks(app) if i['code'].startswith('smtp')] == []


# ── The mail of a record ──────────────────────────────────────────────────────

def send_linked(app, *ids):
    links = [{'model': 'Customer', 'id': i, 'role': 'recipient'} for i in ids]
    return call(app, 'smtp_send', message=message(links=links))['data']['id']


def test_the_mail_of_a_record_newest_first(app):
    first = send_linked(app, 42)
    second = send_linked(app, 42, 43)
    result = call(app, 'smtp_sent', model='Customer', id=42)
    assert [m['id'] for m in result['data']] == [second, first]
    assert result['data'][0]['role'] == 'recipient'
    assert [m['id'] for m in call(app, 'smtp_sent', model='Customer', id='43')['data']] == [second]


class NorthOnly(Guard):
    """Reads customers of the north only, and holds no MailLog.read."""

    def allows(self, permission, context):
        return permission != 'MailLog.read'

    def allows_undeclared(self, endpoint, context):
        return True

    def conditions(self, permission, context):
        return [{'region': 'north'}] if permission == 'Customer.read' else None


class NoCustomers(NorthOnly):
    def allows(self, permission, context):
        return permission not in ('Customer.read', 'MailLog.read')


def test_the_mail_of_a_record_the_user_cannot_see_does_not_exist(app, monkeypatch):
    send_linked(app, 42, 43)
    monkeypatch.setattr(kitebase.access, '_guard', lambda: NorthOnly())
    assert len(call(app, 'smtp_sent', model='Customer', id=42)['data']) == 1
    assert call(app, 'smtp_sent', model='Customer', id=43)['status_code'] == 404
    # nor can a message be linked to it
    assert call(app, 'smtp_send', message=message(
        links=[{'model': 'Customer', 'id': 43}]))['status_code'] == 404


def test_without_reading_the_table_the_mail_of_its_records_is_refused(app, monkeypatch):
    send_linked(app, 42)
    monkeypatch.setattr(kitebase.access, '_guard', lambda: NoCustomers())
    assert call(app, 'smtp_sent', model='Customer', id=42)['status_code'] == 403


def test_a_label_is_linked_and_read_with_the_log(app, monkeypatch):
    call(app, 'smtp_send', message=message(links=[{'model': 'campaign', 'id': 'spring'}]))
    assert len(call(app, 'smtp_sent', model='campaign', id='spring')['data']) == 1
    monkeypatch.setattr(kitebase.access, '_guard', lambda: NorthOnly())
    assert call(app, 'smtp_sent', model='campaign', id='spring')['status_code'] == 403


# ── Placeholders ──────────────────────────────────────────────────────────────

CUSTOMER = {'model': 'Customer', 'id': 42}


def preview(app, **over):
    result = call(app, 'smtp_preview', message=message(**over))
    assert result['status'] == 'success', result
    return result['data']


def test_placeholders_read_the_record_its_relations_and_the_params(app):
    parts = preview(app, record=CUSTOMER, params={'note': 'See you soon'},
                    subject='For [[name]]',
                    body='Dear [[ name ]],\n\nyour agent is [[agent.name]]. [[$note]]')
    assert parts['missing'] == {}
    assert parts['subject'] == 'For Riverside *Hardware*'
    assert parts['text'] == 'Dear Riverside *Hardware*,\n\nyour agent is Carla Bianchi. See you soon'
    assert parts['placeholders'] == ['name', 'agent.name', '$note']


def test_a_value_is_text_in_the_html_never_markdown(app):
    html = preview(app, record=CUSTOMER, body='**[[name]]**')['html']
    assert '<strong>Riverside *Hardware*</strong>' in html


def test_dates_and_numbers_read_as_the_locale_writes_them(app):
    from kitebase.i18n import use_locale
    with use_locale('it'):
        parts = preview(app, record=CUSTOMER, body='[[since]] [[balance]]')
    assert parts['text'] == '05/03/2024 1234,5'
    assert preview(app, record=CUSTOMER, body='[[since]] [[balance]]')['text'] == '2024-03-05 1234.5'


def test_an_empty_relation_is_an_empty_value_not_an_unknown_one(app):
    with app.get_session() as s:
        s.get(app.models['Customer'], 42).agent_id = None
        s.commit()
    parts = preview(app, record=CUSTOMER, body='agent: [[agent.name]].')
    assert (parts['missing'], parts['text']) == ({}, 'agent: .')


@pytest.mark.parametrize('placeholder', [
    'nope', 'agent.nope', 'agent', 'agent.customers', 'name.length', 'pin', '$absent'])
def test_what_does_not_resolve_is_named_and_left_as_written(app, placeholder):
    parts = preview(app, record=CUSTOMER, body=f'x [[{placeholder}]] y')
    assert list(parts['missing']) == [placeholder]
    assert parts['text'] == f'x [[{placeholder}]] y'


def test_a_record_field_without_a_record_does_not_resolve(app):
    assert list(preview(app, body='[[name]]')['missing']) == ['name']


class NoPricing(NorthOnly):
    def allows(self, permission, context):
        return permission != 'pricing.read'

    def conditions(self, permission, context):
        return None


def test_a_column_the_user_may_not_read_does_not_resolve(app, monkeypatch):
    assert preview(app, record=CUSTOMER, body='[[margin]]')['text'] == '30'
    monkeypatch.setattr(kitebase.access, '_guard', lambda: NoPricing())
    assert list(preview(app, record=CUSTOMER, body='[[margin]]')['missing']) == ['margin']


def test_a_record_the_user_cannot_see_is_not_found(app, monkeypatch):
    monkeypatch.setattr(kitebase.access, '_guard', lambda: NorthOnly())
    assert call(app, 'smtp_preview', message=message(
        record={'model': 'Customer', 'id': 43}, body='[[name]]'))['status_code'] == 404


def test_a_message_with_an_unresolved_placeholder_is_not_sent(app, smtpd):
    result = call(app, 'smtp_send', message=message(record=CUSTOMER, body='[[nope]]'))
    assert result['status_code'] == 400 and 'nope' in result['message']
    assert smtpd[0].envelopes == []
    with app.get_session() as s:
        assert s.query(app.models['MailLog']).count() == 0


def test_the_message_sent_is_filled_logged_filled_and_linked_to_its_record(app, smtpd):
    result = call(app, 'smtp_send', message=message(
        record=CUSTOMER, subject='For [[name]]', body='Agent [[agent.name]]'))
    _envelope, msg = smtpd[0].last()
    assert msg['Subject'] == 'For Riverside *Hardware*'
    assert msg.get_body(('plain',)).get_content().strip() == 'Agent Carla Bianchi'
    row = log(app, result['data']['id'])
    assert (row.subject, row.body) == ('For Riverside *Hardware*', 'Agent Carla Bianchi')
    assert [m['id'] for m in call(app, 'smtp_sent', model='Customer', id=42)['data']] == [
        result['data']['id']]
