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

## The pages

- `project_list`: the open projects, with the tasks of the one clicked below
  and its history on the right;
- `task_list`, `my_tasks` and `task_board`, the board of one project at a time;
- `project_form`, with its stages, and `task_form`.

The tasks are not a collection of the project's form: a task has a board, a
history and a form of its own, and its rules are judged on a single write.

## From code

```python
from projects.api import add_stages, first_stage, open_tasks

add_stages(session, project_id, [("Drafting", "active"), ("Granted", "done")])
```

The functions check no permission: the caller answers for what it writes.
