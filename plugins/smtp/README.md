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
message is written as `dry_run.eml` in the folder of its log row, which a mail
client opens. While either switch is on, `kitebase check` says so.

## Who sends from which account

The accounts are set up by whoever runs the server. Who may use them is decided
by the administrator: the `mail_accounts` column this plugin adds to `User`
lists the names, and the first is the default. A user with no accounts cannot
send. Work with no user behind it, such as a scheduled task, names its account
in the message.

The `smtp.send` permission is needed to send from the client.

## The media root

The log row's folder holds the attachments that were sent, and the dry-run
files. Its column is on the root `mail`, which the application declares:

```yaml
media:
  roots:
    mail: { type: fs, path: media/mail, allocate: by_record }
```

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
part is its rendering with raw HTML turned off. A `media` attachment is read on
the server with no permission check, so only server code passes one: the
`smtp_send` endpoint refuses references from the client.

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
