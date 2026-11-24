# projects

Projects and their tasks: who does what, by when. A task moves through the
stages of its project on a board; the stages are the project's own, and their
category is what every question across projects reads.

It depends on `partners`, `activities` and `tags`. Like the rest of the
commons it is menu-silent: it draws pages, and the application puts them in
its menu. The demo does it in `demo_projects`.

## The model

- **Project**: a piece of work, for a customer (`partner_id`) or internal. A
  manager, expected dates, a description, tags. Its **state** is one of five,
  `planned`, `active`, `on_hold`, `done`, `cancelled`: the first three are the
  open projects. Any state may follow any other. A cancelled project is not a
  finished one, in the figures as in the choice of a job to copy.
- **is_template** marks a **typical job**: a project written to be copied, or a
  real one that went well, which keeps its state, hours and history. It is only
  a filter: the open projects leave it out.
- **TaskStage**: a column of the project's board, owned by the project. A
  project saved with no stages gets the default ones (`api.default_stages`);
  the form adds, renames and moves them. Each has a **category**, `todo`,
  `active`, `done` or `cancelled`: the names are free, the categories are not.
- **Task**: a unit of work, always in a stage of its own project. One assignee,
  a due date, a priority (normal or high), an estimate in hours, a description,
  tags. Left without a stage, it starts in the first one to do; moved to
  another project, it starts again there. There are no sub-tasks: a task too
  large for one person and one stage is a project of its own.

Who works is a **partner**, a person, since many who work never sign in. A user
is a person through `User.partner_id` (the `partners` plugin), which also puts
`partner_id` in the login context: "My tasks" is the rule
`{field: assignee_id, op: eq, value: $ctx.partner_id}`.

An activity on a task reaches its project, and from there its partner
(`activities.follow`). A task moved to another stage is a line of its history,
"From To do to In review" (`activities.moves`). A note on a task is an activity; a note linked to
another project too is how two pieces of work refer to each other.

## The hours

- **TimeEntry**: hours spent on a project, on one of its tasks or on the
  project as a whole, by a person, on a day. A start and an end when they are
  known, kept as instants for the queries but asked as times of day: the save
  puts them on the date of the row, an end before the start on the next
  morning (22:00 to 02:30 is four and a half hours, and the row keeps its
  date). The hours are the datum, and may be less than the interval (a pause).
  Kept as decimals with two places (the type `Hours`): rounding to the half hour
  is a rule of the invoice, not of the record. `source` and `source_ref` say who
  wrote a row that was not typed (a plugin, a bridge to a system that records
  time) and the datum it came from.
- The rules: the project of the task named, the person of the user writing
  when none is named, the hours between start and end when they are left
  empty; hours longer than the interval are said, not refused. A project with
  hours is not deleted: it is cancelled.
- In the form, leaving the start or the end asks the server for the hours
  (`on_change`, endpoint `projects_hours`): the same function the save uses.
- "Log time" on the tasks (and on the projects, for hours on the project as a
  whole) opens the form already filled.
- The form of a task lists its hours in a tab, where they are also written:
  the rules take the project from the task as it is being saved
  (`ctx.parent`). The hours are not parts of the task, so each row needs the
  permissions of `TimeEntry`, and deleting a task keeps its hours on the
  project.
- `project_id` on the hours copies the task's on purpose: hours on the
  project as a whole have no task, and the queries stay plain. A task moved
  to another project takes its hours with it.
- Computed in the query of a list (`model.py`): `open_tasks` and `spent_hours`
  on a project, `spent_hours` and `is_open` on a task. "My tasks" shows the
  open ones through `is_open`.

## The pages

- `project_list`: the open projects, with the tasks of the one clicked below
  and its history on the right;
- `task_list`, `my_tasks` and `task_board`, the board of one project at a time;
- `time_list` (the timesheet) and `my_time`;
- `project_form`, with its stages, `task_form` and `timeentry_form`.

The tasks are not a collection of the project's form: a task has a board, a
history and a form of its own, and its rules read its stage from the
database, where a stage created in the same save is not there until it
is written.

## From code

```python
from projects.api import add_stages, first_stage, open_tasks

add_stages(session, project_id, [("Drafting", "active"), ("Granted", "done")])
```

The functions check no permission: the caller answers for what it writes.
