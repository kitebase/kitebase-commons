# activities

Activities on any record: what, when, who, done or to do. The call planned for
tomorrow and the call made are the same row, which changes state; the history
of a record is the list of its activities.

## The tables

- `Activity`: type, subject, note, the user it is assigned to and its author,
  a start and an end for an appointment, a due date for a thing to do, `done_at` once done,
  the priority, and the plugin that wrote it (`source`).
- `ActivityType`: the kinds of activity. The id is a code (`call`, `email`).
- `ActivityLink`: the records an activity concerns, any table of any plugin,
  each with a role: `owner` where it was written, `contact` the person spoken
  to, `mail` the message sent, `follow` a parent reached (below), or none for a
  record concerned.

**The rule of the date.** A row with a due date or a start, and no `done_at`,
is to do. A row with no date is a fact recorded: it is done when written. It
holds on every port that writes an activity.

**The author** is whoever wrote the activity, set by the server and never
changed; empty for the work of the system. An activity assigned to someone
other than its author is a request: the assignee finds it among their own,
the author keeps seeing it and may change it.

**With no record** an activity is personal (renew the domain, call the
accountant): it is linked to nothing, and only its user and its author see it.

**The priority** is a whole number from -9 to 9, higher first: 0 is normal and
the default, 9 the most urgent, below 0 what is parked or waits for time.
Lists sort on it descending, then by date.

## Types

The types are rows of ActivityType, which the application changes in Tables
like any other reference table: the label, the icon, the order (`sequence`)
and whether a person is offered it (`pick`). A plugin registers the ones it
writes, and needs no seed:

```python
from activities.api import register_type

register_type('stage', 'Stage change', 'flag', pick=False)
```

The row of a registered type is made when first needed: when a form asks
for the types, or when code first writes one. It is born in the language of
the application (`locale` in config.yaml), whoever asks first, after the
types already there; from then on the row decides. `pick=False` is for a type
only code writes, such as a stage changed: it is kept, never offered.

`note`, `call`, `meeting`, `email` and `todo` are registered by this plugin.

## Writing activities from code

```python
from activities.api import log_activity

log_activity(('Invoice', 1033), 'email', 'Invoice 1033 sent',
             also=[('MailLog', 88, 'mail')], source='smtp', session=session)
```

The record named first is the owner, `None` for a personal activity; `also` names the others concerned, as
`(model, id)`, `(model, id, role)` or `{model, id, role}`. With no date the
activity is done now; `due_date` or `start_at` make it a thing to do. The
user is the current one unless `user_id` is given (`None` for the work of the
system); the author is the current user. With `session`, the activity commits or rolls back with the caller's
transaction.

These functions check no permission: they are for code, which answers for
what it writes.

## Endpoints

| Endpoint | Access | Does |
|---|---|---|
| `activity_timeline {model, id, state?}` | the record read | the activities of a record: to do first, by group (overdue, today, upcoming), priority and day; then the done ones, newest first |
| `activity_mine {user_id?, state?}` | logged in; another user's, whoever reads every activity | the activities assigned to the user, or to `user_id`: by default those still to do |
| `activity_add {model, id, type, subject, ...}` | `Activity.create`, the record read | writes an activity on the record, or personal with no `model` and `id`; assigned to the user, or to `user_id`; `note`, `due_date`, `start_at`, `end_at`, `priority` optional |
| `activity_done {id, done}` | may change it | marks it done, or to do again (`done: false`) if it has a date |
| `activity_postpone {id, date}` | may change it | moves a thing to do to another day; an appointment keeps its time of day |
| `activity_types` | `ActivityType.read` | the types a person is offered, in the order of `sequence`; the registered ones are made first |

Each activity comes with the record it was written on (`owner`), named as the
user may read it, unless that is the record whose timeline is asked.

**Who sees an activity**: whoever reads one of the records it is linked to,
the user it is assigned to, its author, and whoever reads the table without
condition. An
activity on records the user cannot read does not exist for them (404).
**Who changes one**: the user it is assigned to, its author, and whoever has
`Activity.update` and reads one of its records.

## The parents an activity reaches

A table declares the foreign keys whose records see its activities too:

```yaml
Opportunity:
  activities.follow: [partner_id]
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

## In the client

Three components, which the application places:

- `activities.timeline`, the history of a record. Best in a split area
  under the list, where it follows the row under the cursor and scrolls on
  its own however long the history grows, while the form keeps the screen:

  ```yaml
  partner_list:
    panels:
      - id: activities
        pos: bottom
        trigger: { event: row_click, pass: [id] }
        type: plugin
        component: activities.timeline
        props: { model: Partner }
  ```

  The view names the table, the trigger gives the id; beside a form,
  `form_load` gives it. In a form's layout (`{type: plugin, component:
  activities.timeline}`) the form gives both, and on a new record it waits
  for the first save.
- `activities.mine`, what the user has to do, as a page of `type: plugin`.
  What is written there is personal, on no record.
- `activities.agenda`, what one user has to do, in a split area beside the
  list of users, for whoever reads every activity: what is written there is
  for that user.

All three write with the line on top (type, subject, due date: with none, the
activity is recorded as done), mark done or postpone in place, and filter
what is to do, done, or all: the timeline opens on all, the lists of a user
on what is to do.

## The mail sent

Where the application loads smtp too, a message sent can become a done
activity of type `email` (`mail.py`, loaded only then: `optional` in
config.yaml). It is written on the record of the message, linked to its
MailLog (role `mail`) and to the other records it reached, a recipient as the
person spoken to (`contact`); with no record it is personal.

The message asks for it with the param `activity`: absent, nothing is
written, so the mail of the system and of code stays out of the history. The
application gives the choice to whoever sends with a checkbox in its compose
and merge forms, on by default for a message written by hand, off for a merge:

```yaml
views:
  smtp_compose_form:
    source:
      defaults: { activity: true }
    layout:
      - id: text
        fields:
          - { name: activity, label: Record in the history, type: Boolean }
```

A code that sends and wants its message in the history passes
`params={'activity': True}`.

