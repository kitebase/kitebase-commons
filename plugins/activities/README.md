# activities

Activities on any record: what, when, who, done or to do. The call planned for
tomorrow and the call made are the same row, which changes state; the history
of a record is the list of its activities.

## The tables

- `Activity`: type, subject, note, the user it is assigned to, a start and an
  end for an appointment, a due date for a thing to do, `done_at` once done,
  the priority, and the plugin that wrote it (`source`).
- `ActivityType`: the kinds of activity. The id is a code (`call`, `email`).
- `ActivityLink`: the records an activity concerns, any table of any plugin,
  each with a role: `owner` where it was written, `contact` the person spoken
  to, `mail` the message sent, `follow` a parent reached (below), or none for a
  record concerned.

**The rule of the date.** A row with a due date or a start, and no `done_at`,
is to do. A row with no date is a fact recorded: it is done when written. It
holds on every port that writes an activity.

**The priority** is a whole number from -9 to 9, higher first: 0 is normal and
the default, 9 the most urgent, below 0 what is parked or waits for time.
Lists sort on it descending, then by date.

## Types

The application seeds the types its people pick from, as it seeds the roles of
a partner. A plugin registers the ones it writes, and their row is made the
first time they are used:

```python
from activities.api import register_type

register_type('stage', 'Stage change', 'flag')
```

`note`, `call`, `meeting`, `email` and `todo` are registered by this plugin.

## Writing activities from code

```python
from activities.api import log_activity

log_activity(('Invoice', 1033), 'email', 'Invoice 1033 sent',
             also=[('MailLog', 88, 'mail')], source='smtp', session=session)
```

The record named first is the owner; `also` names the others concerned, as
`(model, id)`, `(model, id, role)` or `{model, id, role}`. With no date the
activity is done now; `due_date` or `start_at` make it a thing to do. The
user is the current one unless `user_id` is given (`None` for the work of the
system). With `session`, the activity commits or rolls back with the caller's
transaction.

These functions check no permission: they are for code, which answers for
what it writes.

## Endpoints

| Endpoint | Access | Does |
|---|---|---|
| `activity_timeline {model, id}` | the record read | the activities of a record: to do first, by group (overdue, today, upcoming), priority and day; then the done ones, newest first |
| `activity_mine` | logged in | the activities assigned to the user and still to do |
| `activity_log {model, id, type, subject, ...}` | `Activity.create`, the record read | writes an activity on the record, assigned to the user; `note`, `due_date`, `start_at`, `end_at`, `priority` optional |
| `activity_done {id, done}` | may change it | marks it done, or to do again (`done: false`) if it has a date |
| `activity_postpone {id, date}` | may change it | moves a thing to do to another day; an appointment keeps its time of day |
| `activity_types` | `ActivityType.read` | the types a form picks from |

Each activity comes with the record it was written on (`owner`), named as the
user may read it, unless that is the record whose timeline is asked.

**Who sees an activity**: whoever reads one of the records it is linked to,
the user it is assigned to, and whoever reads the table without condition. An
activity on records the user cannot read does not exist for them (404).
**Who changes one**: the user it is assigned to, and whoever has
`Activity.update` and reads one of its records.

## The parents an activity reaches

A table declares the foreign keys whose records see its activities too:

```yaml
Opportunity:
  activities:
    follow: [partner_id]
```

An activity on an opportunity is then linked to its partner as well, with the
role `follow`, and the partner's history holds it. The links follow the chain
(a task follows its project, the project its partner), and each record is
linked once. The chain is walked when the activity is written: whoever reads
the history of a record reads its links, and finds there the activities written
on it and those that reached it.

A link stays as written: an opportunity moved to another partner leaves its
past activities in the history of the first. A name in `follow` that is no
foreign key of the table stops the first activity written on it, with the
table and the name.
