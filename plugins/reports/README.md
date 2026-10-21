# reports

Printing for Kitebase applications through [AndRep](https://github.com/claudiodriussi/andrep).

**First version.** A view's Print button offers the reports of its table, and
a dialog chooses template, title and output; the report comes back as PDF,
HTML, JSON or a spreadsheet.

## What it is

AndRep renders templates; the report *loop* — read the data, emit bands — is
Python, and in Kitebase it runs in the backend. Between the two sits a **context
adapter**, written once per platform: it is this plugin.

| Piece | What it gives AndRep | Where it comes from |
|---|---|---|
| Record view | Kitebase records passed to templates as they are, exposing only their declared fields | `SQLAlchemyView` of AndRep, derived here: virtual columns as `extra_fields`, and what a relation may reach |
| Resolver | `root:path` references printed as images | the public roots first (plugin assets); with media columns, also the references the template read from an `Image`/`File` column. Network always off |
| Loader | the templates of a report: every file whose name starts with the report's name | the `andrep/` folder of each plugin, in dependency order, plus the installation layer `_andrep/` on top |
| Command | `reports.print` answers the Print button: a menu of the table's reports, or the dialog of the one there is; `reports.run`, through the download route, prints | endpoints under `reports.*` |

A plugin that ships reports declares `depends_on: [reports]`, registers its
loops with `@report('domain.name')` and keeps its templates flat in its
`andrep/` folder, the report's name as prefix:

```python
from reports.registry import load_records, report

@report('myplugin.products', table='Product', label='Product list',
        options='products_options', renderer=ProductsRenderer)
def products(r, params):
    for row in load_records('Product', params['ids'], load=['category']):
        r.emit('row')
```

`table` puts the report in the catalog of that table, under `label`. `options`
names a form view (`views.products_options`) whose fields the dialog adds after
template, title and output; their values reach the loop in `params['options']`.
`template`, `title`, `format`, `report` and `ids` are reserved names. The dialog
is a dialog because `views.reports_print_form` says `presentation: dialog`; an
options view that needs a lookup says `presentation: page`, and wins.

A view offers the reports with a navigator command:

```yaml
navigator:
  commands:
    - id: print
      icon: printer
      toolbar: true
      scope: global
      endpoint: reports.print
      rows: view          # the rows on screen, printed when none is ticked
```

The domain is the plugin's name: `myplugin` registers `myplugin.*` only, and a
second registration of a name needs `replace=True`. `load_records` gives the
records in the order of the ids, with the relations named in `load` read
together; the template reads what it needs from them.

```
myplugin/andrep/products.json
myplugin/andrep/products_a.json
_andrep/products_a.json           # the installation layer wins
_andrep/products_store.json       # a variant born in production
```

The plugin's name in front (`myplugin.products_a.json`) is optional, for when two
plugins would collide in `_andrep/`.

The design, point by point, is in the Kitebase workspace documentation
(`docs/pending/reporting.md`, and `docs/pending/media.md` for files and
resources).

### The standard header

`andrep/` here holds `standard_header` and `standard_header_landscape`: the
lines of `reports.header` in the application's config.yaml (free text, four
lines), the date, the name of the template it was printed with, the page and
the title chosen in the dialog. A template takes one by composition, and a template that needs a
different header declares its own:

```json
"composition": [{"rule": "InsBefore", "target": "standard_header"}]
```

`reports` is the first layer of the loader, so a plugin or the installation's
`_andrep/` can restyle the header of every report at once. Inclusions are one
level deep: the composition of an included template is not applied.

```yaml
reports:
  header: ["Example Trading Ltd", "1 Market Street, Springfield", "info@example.com", "VAT 00000000000"]
```

## Dependencies

Declared in `config.yaml` under `requires`: `andrep[playwright,sqlalchemy]`.
Kitebase checks it when the plugins load, and the application installs it,
from PyPI or from a checkout:

```bash
uv add "andrep[playwright,sqlalchemy]"
uv run playwright install chromium     # once: the browser that makes the PDF
```

The demo takes AndRep from the workspace's checkout, editable, beside kitebase.

## Status

- **Record views**: in AndRep (`andrep.adapters`, `andrep.adapters.sqlalchemy`),
  derived here as `KitebaseView`: virtual columns readable, secret columns
  (`secret: true`, a user's password) not a field. How a view is written: the
  AndRep manual, "Writing an adapter"; what it guarantees: AndRep's
  `docs/SECURITY.md`, "For integrators".
- **Template security**: in AndRep. Expressions checked when a template is
  loaded, data-only namespace, resources confined and embedded, PDF backends
  limited to `data:` URLs.
- **Print button, catalog and dialog**: done. The spreadsheet is one row per
  band emitted: the band's name, then its raw values.
- **Loader, resolver, registry, `reports.run`**: done. The public roots are,
  for now, the `andrep/` folders of the plugins, each named after its plugin
  (`myplugin:logo.png`).
- **To do**: the last template used preselected, the ids checked again
  against the view's query, references read from
  `Image`/`File` columns, rendering in a worker with a timeout.

## Testing

Three levels, each with its own command.

**AndRep, whenever its view modules change**: its own suite, from its own venv:

```bash
cd /path/to/andrep/renderer && ../.venv/bin/python -m pytest -q
```

**This plugin**: `tests/` here, run from the demo's venv, where AndRep is a
dependency (pytest is installed by hand, since `uv sync` removes it):

```bash
cd commons/demo
uv pip install pytest
uv run pytest -q ../plugins/reports/tests
```

- `test_record_views.py`: the acceptance tests of the record views on a plain
  SQLAlchemy model: columns, relations, cycles, what a template can never
  reach, safe methods whose arguments must be data, identity of two views of
  one record.
- `test_reports.py`: the plugin on a Kitebase application built for the test:
  registry and domains, records in the order asked, the Kitebase view (virtual
  and secret columns), the variants by prefix and the installation layer, the
  resolver (a public root readable; relative paths, other roots and URLs
  refused), `reports.run` and its refusals, `reports.print` (the menu, the
  dialog, the rows each report takes) and the spreadsheet.

Still to cover, with the pieces that bring them: a relation does not reach rows
the user's query would not have returned; a reference read from an `Image`
column is printed; rendering runs in a worker with a timeout.

**The demo app**: `demo_ui.phonebook`, the partners' phone book, through the
download route:

```bash
curl -X POST localhost:8302/kitebase/download/reports.run \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"report": "demo_ui.phonebook", "ids": [3, 1], "format": "pdf"}' -o phonebook.pdf
```
