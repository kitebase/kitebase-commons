# office

The core most office applications load together, as one name:

| plugin   | what it brings                                              |
|----------|-------------------------------------------------------------|
| `common` | the shared types and mixins                                 |
| `users`  | users, login, the user log                                  |
| `reports`| printing through AndRep: the Print button and its dialog    |
| `smtp`   | outgoing mail: compose, mail merge, the mail of a record    |
| `tables` | every table through its generated list and form             |

It has no code, tables or pages of its own: it only depends on them, and
`include:` follows dependencies.

```yaml
plugins:
  - path: ../plugins
    include: [office, persons, partners]
```

An application that wants less names the plugins one by one instead; one that
wants more adds them beside it.

Loaded together, `reports` and `smtp` meet: the print dialog offers "Email",
which sends the print as an attachment (smtp's README, "A print by email").

What the group asks of the installation is what its plugins ask: AndRep and a
browser for the PDF (`reports`), the mail accounts in the secrets and the media
root `mail` (`smtp`).
