"""
The bridge from smtp (activities/mail.py), with smtp in dry run.

What has to hold: a message that asks for it becomes a done activity of type
email, on the record it was written on, linked to its MailLog and to the
records it reached, a recipient as the person spoken to; a message that does
not ask writes nothing; one with no record is personal.
"""
from test_endpoints import as_user


def send(app, **message):
    from smtp.mailer import send as smtp_send
    return smtp_send({'to': ['Ann <ann@example.com>'], 'subject': 'Offer sent',
                      'body': 'The offer.', **message})


def activities(app):
    with app.get_session() as s:
        Activity, Link = app.models['Activity'], app.models['ActivityLink']
        return [(a.type_id, a.subject, a.source, a.user_id, a.done_at is not None,
                 sorted((l.model, l.record_id, l.role) for l in
                        s.query(Link).filter(Link.activity_id == a.id)))
                for a in s.query(Activity)]


def test_a_message_that_asks_is_a_done_email_on_its_record(app):
    as_user(7, {})
    result = send(app, record={'model': 'Deal', 'id': 10}, params={'activity': True},
                  links=[{'model': 'Job', 'id': 100, 'role': 'recipient'}])
    assert result['status'] == 'dry_run'
    [(type_id, subject, source, user_id, done, links)] = activities(app)
    assert (type_id, subject, source, user_id, done) == ('email', 'Offer sent', 'smtp', 7, True)
    assert ('Deal', '10', 'owner') in links
    assert ('MailLog', str(result['id']), 'mail') in links
    assert ('Job', '100', 'contact') in links
    # The deal follows its customer, as for any activity
    assert ('Customer', '1', 'follow') in links


def test_a_message_that_does_not_ask_writes_nothing(app):
    as_user(7, {})
    send(app, record={'model': 'Deal', 'id': 10})
    send(app, record={'model': 'Deal', 'id': 10}, params={'activity': False})
    assert activities(app) == []


def test_a_message_on_no_record_is_a_personal_activity(app):
    as_user(7, {})
    result = send(app, params={'activity': True})
    [(_type, _subject, _source, user_id, _done, links)] = activities(app)
    assert user_id == 7
    assert links == [('MailLog', str(result['id']), 'mail')]
