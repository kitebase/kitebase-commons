# smtp

Outgoing mail. A message is a dict: recipients, subject, a markdown body,
attachments, the records it concerns. It goes out through an SMTP account,
and the plugin logs what left, from which account, for which records, and how
it went.

Incoming mail is not handled here.

## The accounts are secrets

Credentials do not belong in `config.yaml`, which is versioned and shown by the
introspection tools. They go in the installation's secrets folder
(`kitebase.secrets`: `secrets/` beside `config.yaml`, or wherever
`KITEBASE_SECRETS` points), one file per kind. The accounts are `smtp.yaml`:

```yaml
office:
  host: smtp.example.com
  port: 587                          # 587: STARTTLS; 465: SSL
  user: office@example.com
  password: "..."
  from: "Office <office@example.com>"

info:
  host: smtp.example.com
  port: 465
  user: info@example.com
  password: "..."
  from: info@example.com
```

`security: starttls | ssl | none` overrides what the port implies. `user` and
`password` go together, or neither for a relay that takes mail without a login.

The same folder serves any other kind of secret. A plugin that needs
credentials reads them with `secrets.get('<kind>', '<name>')` and checks the
format itself, as `accounts.py` does here. It never copies them into the
configuration, so nothing that dumps or serves the configuration can leak them.

## A development installation

Two switches, in the same file:

```yaml
$redirect_to: me@example.com   # every message goes to this address only
$dry_run: true                 # nothing is sent: each message is written to a file
```

They live in the secrets and not in `config.yaml` because `config.yaml` is the
same in development and production, while the secrets folder belongs to one
installation. A copy of the production database restored in development
therefore brings nothing along that sends mail.

Under `$redirect_to` the log keeps both the recipients written and the address
delivered to, and the message carries `X-Redirected-From`. Under `$dry_run` the
message is written to a file, in `mail:dry_run/`, which a mail client opens;
the log row's `eml` names it. While either switch is on, `kitebase check` says so.

## Who sends from which account

The accounts are set up by whoever runs the server. Who may use them is decided
by the administrator: the `mail_accounts` column this plugin adds to `User`
lists the names, and the first is the default. A user with no accounts cannot
send. Work with no user behind it, such as a scheduled task, names its account
in the message.

The `smtp.send` permission is needed to send from the client.

## Attachments

An attachment is written once, in the media root `mail`, which the application
declares:

```yaml
media:
  roots:
    mail: { type: fs, path: media/mail }
```

The client uploads a file with `smtp_attach` (the upload route), gets back its
reference, and sends the reference with the message. The log row refers to
the files rather than copying them, so all the messages of a mail merge share
one copy. A user's message may carry only the files that user uploaded: the
outbox is divided by user, and a reference to another user's file is refused.
`smtp.attachments` in the merged tree sets the extensions accepted and the
largest file.

## Sending from the server

```python
from smtp.mailer import send

send({
    'to': ['Ann <ann@example.com>'],
    'subject': 'Invoice 1033',
    'body': 'The invoice is **attached**.',
    'attachments': [{'media': 'docs:2026/11/invoice-1033.pdf'},
                    {'name': 'notes.txt', 'content': b'...'}],
    'links': [{'model': 'Partner', 'id': 42, 'role': 'recipient'},
              {'model': 'Invoice', 'id': 1033}],
})
```

The body is markdown. The plain text part is the markdown itself, and the HTML
part is its rendering with raw HTML turned off. Server code may also attach a
file of any root (`media`), read with no permission check, or bytes (`name`,
`content`), which are staged first. The `smtp_send` endpoint accepts neither:
from the client, a message carries only `ref`s its user staged.

## Placeholders

Subject and body may hold placeholders, filled when the message is sent:

```python
send({
    'record': {'model': 'Invoice', 'id': 1033},
    'params': {'note': 'Thank you for your order.'},
    'to': ['ann@example.com'],
    'subject': 'Invoice [[number]] of [[date]]',
    'body': 'Dear [[partner.name]],\n\n[[$note]]',
})
```

- `[[path]]` is a field of the record, following many-to-one relations with
  dots. `[[$name]]` is a parameter.
- An empty field gives nothing. A path that names nothing, a list of records, a
  secret column or a column the user may not read does not resolve. The message
  is then refused, naming each placeholder that did not resolve and why.
- The record is read with the sender's permissions and record rules, so a
  template shows nothing the sender's form would not. It is also linked to the
  message.
- Dates and numbers are written as the current locale writes them.
- A value goes into the HTML part as text: a `*` in a name stays a star.

`smtp_preview` takes the same message and returns `subject`, `text`, `html`,
the `placeholders` found and the ones `missing`, without refusing. A composer
shows the preview, and since the server renders it, what is shown is what is
sent.

## The mail of a record

`MailLink` ties a message to any number of records of any table: the model's
name and the key, with an optional role. Nothing is added to the tables mail is
sent from. A name that is not a model is a label, such as a campaign, which is
written and read like the rest.

The links are never read directly. `smtp_sent` (`{model, id}`) first reads the
record with the caller's permissions and record rules: a 403 without the
table's `read`, a 404 when a rule hides the record. Only then does it return
the mail linked to it, newest first. The mail of a label needs `MailLog.read`.

## Tests

    (cd commons/demo && uv run pytest -q ../plugins/smtp/tests)

They send to a real SMTP server, aiosmtpd, from the demo's `dev` dependency
group.
