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

`sent` keeps a copy of each message in a folder of the account's mailbox, for
the providers that do not keep one themselves (Gmail does, many do not), so
whoever sends from the application finds the message in their own mail
client. Declaring the folder is asking for the copy:

```yaml
office:
  ...
  sent: Sent                                         # IMAPS on the same host, the same login
  # sent: {host: imap.example.com, port: 993, folder: "Sent Items", user: ..., password: ...}
```

The copy is appended after the message has left, marked as read, with its Bcc
(which the message that left does not carry). A copy that fails does not
unsend the message: the log row stays `sent`, its `error` says the copy
failed, and so does the outcome the user sees. Under `$dry_run` or
`$redirect_to` no copy is kept, so a development installation never writes
into the real mailbox. A folder name with characters beyond ASCII would need
IMAP's modified UTF-7: the usual names (`Sent`, `Sent Items`, `INBOX.Sent`)
do not.

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

## A text with its values: what a template is today

A template is a subject and a body with placeholders, written in the form or
given by whoever opens it: a command's `params` (`subject`, `body`), or the
values a plugin passes to `compose_action`. The placeholders are filled per
record when the message leaves, so one text serves one record (compose) or
many (merge). The editor offers the placeholders a page lists, and the
fields of the form that are not part of the message are the `[[$name]]`
parameters: a reminder that says "[[$invoices]] invoices, [[$total]] due"
draws two fields the operator may change before sending.

Templates kept apart from the text, to be picked from a list, do not exist
yet: when they come they will be files in the plugins, versioned with git,
plus a few written by the users in the interface.

## Writing from the interface

Three commands put the plugin on any list, each a `navigator` command (the
demo's `demo_mail` plugin puts them on the partners):

```yaml
- { id: write_email, label: Write an email, scope: row,    endpoint: smtp_compose, params: { page: partner_compose } }
- { id: sent_email,  label: Email sent,     scope: row,    endpoint: smtp_sent_page }
- { id: mail_merge,  label: Mail merge,     scope: global, endpoint: smtp_merge,   params: { page: partner_merge } }
```

- **Write an email** opens the compose form, a form without a model, with a
  draft the server prepares: the user's first account and the record's main
  address. Its To field (`smtp.recipients`) has a button that lists all the
  record's addresses to tick (below). Sending it closes the form; a refusal,
  such as an address that is not one, keeps it open with what was written.
- **Email sent** lists the mail about the record, newest first, with the
  message under the cursor beside it: its addresses, its text, its files.
- **Mail merge**: one text to every ticked row (next section).

`page` names the form, so a context can give its own: a page whose content
refers to `views.smtp_compose_form` (or `smtp_merge_form`) and replaces its
layout, typically to offer the placeholders of its table:

```yaml
- name: body
  widget: markdown
  placeholders: [{ name: name, label: Name }, { name: city, label: City }]
```

Without `page` the plugin's own form opens: the placeholders work the same,
typed by hand. Another plugin's command that computes values opens the form
with them through `compose_action(record, page, **values)`.

The plugin also brings `smtp_log`, every message sent with the same detail,
for whoever reads `MailLog`. Like every page of the commons it is in no menu
until the application puts it there.

## Mail merge on any table

The merge knows no table. The command passes the list's table and the
ticked ids; each record is read with the user's permissions, gives its
addresses and fills the placeholders of its own message. Putting it on
another list is the command alone:

```yaml
views:
  member_table:
    navigator:
      commands:
        - { id: mail_merge, label: Mail merge, scope: global, endpoint: smtp_merge }
```

The form says how many messages leave, to how many addresses, and which
records are skipped and why, and says it again when the operator changes whom
inside each record. Every message is prepared before any leaves, so one
placeholder that does not resolve for one record sends nothing and names the
records. Then the messages leave one after the other, sharing the
attachments, and the summary says how it went. *Keep a log of the messages*
off sends without a row in the log.

A record with several addresses gets one message with all of them in To, so
colleagues see each other. *One message per contact* sends each address a
message of its own, whose placeholders read the row the address belongs to:
`[[name]]` is the person, `[[parent.name]]` the company. The record ticked is
linked to every message either way.

The sending happens in the request, which is right for tens of messages;
thousands, and a provider's quotas, are the work of a job.

## Whom inside a record

A record with an `email` column has one address. A record that stands for an
organisation has more: its own and its contacts', each doing something there
(technical office, accounts). `smtp` does not know what a partner is; the
plugin that does registers, per table, how to list them:

```python
from smtp.addresses import register_addresses

def partner_addresses(record_id):
    return [{'model': 'Partner', 'id': 3, 'name': 'Northwind Trading',
             'email': 'info@northwind.example', 'main': True},
            {'model': 'Partner', 'id': 6, 'name': 'Ross, Mark',
             'email': 'ross@northwind.example', 'functions': ['TEC', 'WHS'],
             'note': 'Technical office, Warehouse'}]

def partner_functions():
    return [{'value': 'TEC', 'label': 'Technical office'}, ...]

register_addresses('Partner', partner_addresses, partner_functions)
```

`model` and `id` are the row the address belongs to. `main` is the address a
message goes to when nothing else is asked; with none marked, the first.
`note` is what the dialog shows beside the name. An address whose `email`
column the user may not read is dropped, whatever the provider says. In the
demo the provider is `demo_mail`'s, a plugin of its own because neither
`partners` nor `smtp` knows the other.

A table with no email of its own borrows the addresses of the record a
many-to-one relation reaches, with one line:

```python
from smtp.addresses import register_addresses_via
register_addresses_via('Invoice', 'partner')
```

An invoice, a statement, an order is then written to its partner and its
contacts, functions included, from the compose form, the merge or a print by
email. The message stays about the invoice: its placeholders read
`[[number]]` and `[[partner.name]]`, and it is in the invoice's mail sent.

Then a message can ask for functions instead of people:

- the compose dialog has a button per function held, which ticks its holders;
- the merge form takes `functions` and `fallback` fields (the variant draws
  them, since the vocabulary is the application's);
- a command may preset them: `params: { functions: [ADM], fallback: main }`.

When nobody in a record holds the functions asked, `fallback: main` writes to
the main address (an invoice must arrive) and `skip` writes nothing (a
technical newsletter). The summary names the records of each case.

## A print by email

Where the application loads `reports` too, the print dialog offers "Email"
(`report_email.py`, loaded only then: `optional` in config.yaml). The print is
made with the dialog's choices, staged as the user's attachment, and the
compose form opens with it and the report's title as subject. A print of one
row is a message about that row: its address in To, its addresses in the
dialog, the message in its mail sent. A print of several rows leaves To empty
and links the message to every row.

## Tests

    (cd commons/demo && uv run pytest -q ../plugins/smtp/tests)

They send to a real SMTP server, aiosmtpd, from the demo's `dev` dependency
group.
