"""The Print button and the report it runs.

`reports.print` answers the Print button of a view. The view sends what it
knows, and the server decides the rest:

    {
      "table":    "Partner",
      "id":       3,                      # the current row
      "ids":      [3, 1],                 # the ticked rows
      "view_ids": [3, 1, 2],              # the rows on screen, in their order
      "report":   "demo_ui.phonebook"     # once picked, when the table has several
    }

With several reports for the table the answer is a menu of them; with one, or
once picked, it is the `form` step of the print dialog, whose `then` downloads
from `reports.run` with the rows the report takes (`on_empty`).

`reports.run` is called through the download route, with everything decided:

    {
      "report":   "demo_ui.phonebook",
      "ids":      [3, 1, 2],              # in the order to print them
      "template": "phonebook_a",          # one of the report's variants; default its name
      "title":    "Phone book",           # the template's own name when missing
      "format":   "pdf" | "html" | "json" | "xlsx",
      ...                                 # every other key is an option of the report
    }

The values of the dialog arrive flat, so the names above are reserved: an
option named like one of them is refused when the dialog is built.

The PDF opens in a tab, from which it is printed. HTML, JSON and the
spreadsheet are saved: HTML made from data, opened as a blob, would run with
the app's origin. The spreadsheet is the compiled records, one row per band
emitted: the band's name, then its raw values, so numbers stay numbers and
any report, a list or an invoice, has one. A report with a post-processor for
`xlsx` (registry.report_post) writes its own instead.
"""
import copy
import datetime
import decimal
import io
import json
from typing import Any, Dict, Iterator, List

import kitebase.utils
from kitebase.apptime import today
from kitebase.db import BaseApp
from kitebase import access
from kitebase.endpoints import FileResult, endpoint
from kitebase.i18n import _, _f, translate_labels
from kitebase.pages import strip_meta

from reports import registry
from reports.context import LayeredLoader, PublicResolver, plugin_layers, public_roots

HEADER_LINES = 4

# What reports.run reads itself; every other key is an option.
RESERVED = ('report', 'ids', 'template', 'title', 'format')

FORMATS = {
    'pdf':  ('pdf', 'application/pdf', 'inline'),
    'html': ('html', 'text/html', 'attachment'),
    'json': ('json', 'application/json', 'attachment'),
    'xlsx': ('xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
             'attachment'),
}


def _refuse(message: str) -> Dict[str, Any]:
    return {'status': 'error', 'code': 400, 'message': message}


def _cell(value: Any) -> Any:
    """A value openpyxl can write as a typed cell: the rule of the core's
    export (`kitebase.endpoint_export._cell`), which the two must keep alike."""
    if isinstance(value, datetime.datetime) and value.tzinfo is not None:
        return value.replace(tzinfo=None)  # Excel has no timezones
    if isinstance(value, (str, int, float, bool, decimal.Decimal,
                          datetime.date, datetime.time)) or value is None:
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def to_xlsx(r, post=None) -> bytes:
    """The compiled records of `r`, one row per band: its name, then its values;
    or what `post(records, book)` writes in the workbook."""
    from openpyxl import Workbook

    book = Workbook()
    if post is not None:
        post(r.records(), book)
    else:
        sheet = book.active
        sheet.title = 'records'
        for record in r.records():
            sheet.append([record['band']] + [_cell(v) for v in record.get('values', [])])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def header_lines(config: Dict[str, Any]) -> list:
    """`reports.header` padded to four lines: the standard header reads four,
    and one that config.yaml leaves out prints empty."""
    lines = [str(x) for x in ((config.get('reports') or {}).get('header') or [])]
    return lines + [''] * (HEADER_LINES - len(lines))


def variants(report: registry.Report, loader: LayeredLoader):
    """The templates of a report: its name as prefix, with or without the domain."""
    return loader.variants([report.short_name, report.name])


@endpoint('reports.run', access='reports.run')
def run(data: Dict[str, Any]) -> Any:
    report = registry.get(data.get('report') or '')
    if report is None:
        return _refuse(_f("Unknown report: '{report}'", report=data.get('report')))
    fmt = data.get('format') or 'pdf'
    if fmt not in FORMATS:
        return _refuse(_f("Unknown report format: '{format}'", format=fmt))
    ids = data.get('ids') or []
    if not isinstance(ids, list):
        return _refuse(_('ids must be a list'))
    if report.input == 'view' and not ids:
        return _refuse(_('No rows to print'))
    options = {k: v for k, v in data.items() if k not in RESERVED}
    for permission in access.declared(report.access):
        if not access.can(permission):
            raise _denied(report, permission)

    app = kitebase.utils.get_app()
    loader = LayeredLoader(plugin_layers(app.pm))
    known = variants(report, loader)
    template = data.get('template') or (
        report.short_name if report.short_name in known else (known[0] if known else None))
    if template not in known:
        return _refuse(_f("'{template}' is not a template of report '{report}'",
                          template=template, report=report.name))

    r = report.renderer(template, loader=loader, resolver=PublicResolver(public_roots(app.pm)))
    if data.get('title'):
        r.title = str(data['title'])
    # What the standard header prints beside title, date and page: the lines
    # of `reports.header` in config.yaml (AndRep's `_r.name`), and the name of
    # the template, which tells whoever holds the paper how it was printed.
    r.name = header_lines(app.pm.config)
    r.template_name = template
    user = (BaseApp.get_context() or {}).get('username')
    if user:
        r.report_user = user
    locale = app.pm.config.get('locale')
    if locale and not r.page.get('locale'):
        r.locale = locale

    params = {**report.params, 'ids': ids, 'options': options}
    with app.get_session() as session:
        access.guard_session(session)
        token = registry.current_session.set(session)
        try:
            report.loop(r, params)
            ext, mime, disposition = FORMATS[fmt]
            content = {'pdf': r.to_pdf, 'html': lambda: r.to_html().encode('utf-8'),
                       'json': lambda: r.to_json().encode('utf-8'),
                       'xlsx': lambda: to_xlsx(r, registry.get_post(
                           report.name, 'xlsx', template))}[fmt]()
        except access.AccessDenied as e:
            raise _denied(report, e.permission) from None
        finally:
            registry.current_session.reset(token)

    return FileResult(content, f'{template}_{today():%Y%m%d}.{ext}', mime, disposition)


# ── The Print button ──────────────────────────────────────────────────────────

def allowed(report: registry.Report) -> bool:
    """Whether the current user holds the permissions the report declares."""
    return all(access.can(p) for p in access.declared(report.access))


def _denied(report: registry.Report, permission: str) -> access.AccessDenied:
    return access.AccessDenied(permission, _f(
        "You cannot print '{report}': it needs {permission}",
        report=_(report.title), permission=permission))


def rows_taken(report: registry.Report, data: Dict[str, Any]) -> list:
    """The rows a report prints from what the view sent: the ticked ones, or
    with none ticked what `on_empty` says, the rows on screen or the current one."""
    if report.input == 'none':
        return []
    ticked = data.get('ids') or []
    if ticked:
        return list(ticked)
    if report.on_empty == 'row':
        return [data['id']] if data.get('id') is not None else []
    return list(data.get('view_ids') or [])


def _fields(node: Any) -> Iterator[Dict[str, Any]]:
    """Every field of a form layout, at any depth."""
    if isinstance(node, list):
        for item in node:
            yield from _fields(item)
    elif isinstance(node, dict):
        if isinstance(node.get('name'), str) and node.get('type') not in ('section', 'row', 'tabs'):
            yield node
        for key in ('layout', 'fields', 'children', 'tabs', 'content'):
            if key in node:
                yield from _fields(node[key])


def template_label(loader: LayeredLoader, name: str) -> str:
    """How the dialog names a template: its title and its file, which tells two
    copies apart when an installation has not renamed the title."""
    try:
        title = loader.load(name).get('name')
    except (OSError, ValueError):
        title = None
    return f'{title} ({name})' if title and title != name else name


def print_form(app, report: registry.Report, templates: List[str],
               loader: LayeredLoader) -> Dict[str, Any]:
    """The print dialog of a report: the shared part, then its options.

    Raises ValueError when the report's options form is missing or uses a
    reserved name.
    """
    view = copy.deepcopy(app.pm.resolve_refs(app.pm.get('views.reports_print_form')))
    for field in _fields(view['layout']):
        if field['name'] == 'template':
            field['choices'] = [{'value': t, 'label': template_label(loader, t)}
                                for t in templates]

    if report.options:
        options = app.pm.get(f'views.{report.options}')
        if options is None:
            raise ValueError(_f("The options form '{form}' of report '{report}' does not exist",
                                form=report.options, report=report.name))
        options = copy.deepcopy(app.pm.resolve_refs(options))
        for field in _fields(options.get('layout') or []):
            if field['name'] in RESERVED:
                raise ValueError(_f("The option '{name}' of report '{report}' uses a reserved name",
                                    name=field['name'], report=report.name))
        view['layout'] = list(view['layout']) + list(options.get('layout') or [])
        if 'presentation' in options:
            view['presentation'] = options['presentation']
    return view


@endpoint('reports.print', access='reports.run')
def print_menu(data: Dict[str, Any]) -> Dict[str, Any]:
    table = data.get('table')
    if data.get('report'):
        report = registry.get(data['report'])
        if report is None or report.table != table:
            return _refuse(_f("Unknown report: '{report}'", report=data['report']))
        for permission in access.declared(report.access):
            if not access.can(permission):
                raise _denied(report, permission)
    else:
        catalog = [r for r in registry.for_table(table) if allowed(r)] if table else []
        if not catalog:
            return {'status': 'success', 'data': {'message': _('Nothing to print here')}}
        if len(catalog) > 1:
            return {'status': 'success', 'data': {
                'action': 'choose',
                'title': _('Print'),
                'options': [{'label': _(r.title),
                             'then': {'action': 'endpoint', 'op': 'reports.print',
                                      'params': {**data, 'report': r.name}}}
                            for r in catalog],
            }}
        report = catalog[0]

    ids = rows_taken(report, data)
    if report.input == 'view' and not ids:
        return _refuse(_('No rows to print'))

    app = kitebase.utils.get_app()
    loader = LayeredLoader(plugin_layers(app.pm))
    templates = variants(report, loader)
    if not templates:
        return _refuse(_f("Report '{report}' has no template", report=report.name))
    try:
        view = print_form(app, report, templates, loader)
    except ValueError as e:
        return _refuse(str(e))

    values = {f['name']: f['default'] for f in _fields(view['layout']) if 'default' in f}
    values.update({
        'template': report.short_name if report.short_name in templates else templates[0],
        'title': _(report.title),
        'format': 'pdf',
    })
    return {'status': 'success', 'data': {
        'action': 'form',
        'title': _(report.title),
        'view': translate_labels(strip_meta(view)),
        'values': values,
        'then': {'action': 'download', 'op': 'reports.run',
                 'params': {'report': report.name, 'ids': ids}},
    }}
