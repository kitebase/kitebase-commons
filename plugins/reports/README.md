# reports

Printing for Kitebase applications through [AndRep](https://github.com/claudiodriussi/andrep).

**Under construction.** This directory holds the plan and the way to test it;
the code comes when the plugin is implemented. No application should include it
yet.

## What it will be

AndRep renders templates; the report *loop* — read the data, emit bands — is
Python, and in Kitebase it runs in the backend. Between the two sits a **context
adapter**, written once per platform: it is this plugin.

| Piece | What it gives AndRep | Where it comes from |
|---|---|---|
| Record view | Kitebase records passed to templates as they are, exposing only their declared fields | `SQLAlchemyView` of AndRep, derived here: virtual columns as `extra_fields`, and what a relation may reach |
| Resolver | `root:path` references printed as images | the media roots of `config.yaml`, restricted to the references the loop emitted |
| Loader | templates by qualified name, with their variants | the `andrep/` folder of each plugin, in dependency order, plus the installation layer on top |
| Command | a `print` command in the Navigator, answering with a `choose` menu | endpoints under `reports.*` |

A plugin that ships reports declares `depends_on: [reports]`, registers its
loops with `@report('domain.name')` and keeps its templates in
`andrep/<report>/<variant>.json`.

The design, point by point, is in the Kitebase workspace documentation
(`docs/pending/reporting.md`, and `docs/pending/media.md` for files and
resources).

## Dependencies

AndRep with the `sqlalchemy` extra, from PyPI or from a checkout
(`uv pip install -e "/path/to/andrep/renderer[sqlalchemy]"`), plus its PDF
backend. SQLAlchemy itself is already there through kitebase.

## Status

- **Record views** — in AndRep. The generic base is `andrep.adapters`
  (`RecordView`, `register_view`: fields from the ORM's metadata, relations
  wrapped again, declared safe methods only), and each ORM is a module of its
  own, imported by the integration that needs it. Here, once when the plugin
  loads:

  ```python
  from andrep.adapters import register_view
  from andrep.adapters.sqlalchemy import SQLAlchemyView

  register_view(Base, SQLAlchemyView)   # a Kitebase subclass, when it has one
  ```

  AndRep stays anonymous: views for vertical platforms live in those
  platforms' integration modules, never in AndRep. How a view is written: the
  AndRep manual, "Writing an adapter"; what it guarantees: AndRep's
  `docs/SECURITY.md`, "For integrators".
- **Template security** — done in AndRep: expressions checked when a template is
  loaded, data-only namespace, resources confined and embedded, PDF backends
  limited to `data:` URLs.
- **Everything else in the table above** — to do.

## Testing

Three levels, each with its own command.

**AndRep, whenever its view modules change** — its own suite, from its own venv:

```bash
cd /path/to/andrep/renderer && ../.venv/bin/python -m pytest -q
```

**This plugin** — `tests/` here, run from the demo's venv with AndRep and
pytest installed:

```bash
cd commons/demo
uv pip install pytest -e "/path/to/andrep/renderer[sqlalchemy]"
.venv/bin/python -m pytest -q ../plugins/reports/tests
```

`test_record_views.py` is already there: the acceptance tests of the record
views on a SQLAlchemy model — columns, relations, cycles, what a template can
never reach, safe methods whose arguments must be data, identity of two views of
one record. They pass against AndRep from 0b17cde on; with an older AndRep
they are skipped, saying why.

What must be covered next, beyond "a report prints":

- the Kitebase view: virtual columns readable; a relation does not reach rows the
  user's query would not have returned;
- the resolver: a reference the loop emitted is printed, a reference written by
  hand in the template is refused, a public root (plugin assets) is readable;
- the loader: an installation override replaces the plugin's template, a
  variant born in production is listed, a name outside the layers is refused;
- rendering runs in a worker with a timeout, and the preview is served for a
  sandboxed `<iframe>`.

**The demo app** — a real print from the Navigator, once the demo includes the
plugin.
