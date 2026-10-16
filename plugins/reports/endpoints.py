"""`reports.run`: run a registered report and answer with the document.

Called through the download route, with everything already decided:

    {
      "report":   "demo_ui.phonebook",
      "template": "phonebook_a",          # one of the report's variants; default its name
      "format":   "pdf" | "html" | "json",
      "ids":      [3, 1, 2],              # in the order to print them
      "options":  {...},                  # the values of the report's form
      "title":    "Phone book"            # the template's own name when missing
    }

The PDF opens in a tab, from which it is printed. HTML and JSON are saved:
HTML made from data, opened as a blob, would run with the app's origin.
"""
from typing import Any, Dict

import kitebase.utils
from kitebase.apptime import today
from kitebase.db import BaseApp
from kitebase.endpoints import FileResult, endpoint
from kitebase.i18n import _, _f

from reports import registry
from reports.context import LayeredLoader, PublicResolver, plugin_layers, public_roots

HEADER_LINES = 4

FORMATS = {
    'pdf':  ('pdf', 'application/pdf', 'inline'),
    'html': ('html', 'text/html', 'attachment'),
    'json': ('json', 'application/json', 'attachment'),
}


def _refuse(message: str) -> Dict[str, Any]:
    return {'status': 'error', 'code': 400, 'message': message}


def header_lines(config: Dict[str, Any]) -> list:
    """`reports.header` padded to four lines: the standard header reads four,
    and one that config.yaml leaves out prints empty."""
    lines = [str(x) for x in ((config.get('reports') or {}).get('header') or [])]
    return lines + [''] * (HEADER_LINES - len(lines))


def variants(report: registry.Report, loader: LayeredLoader):
    """The templates of a report: its name as prefix, with or without the domain."""
    return loader.variants([report.short_name, report.name])


@endpoint('reports.run')
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
    options = data.get('options') or {}
    if not isinstance(options, dict):
        return _refuse(_('options must be an object'))

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
        token = registry.current_session.set(session)
        try:
            report.loop(r, params)
            ext, mime, disposition = FORMATS[fmt]
            content = {'pdf': r.to_pdf, 'html': lambda: r.to_html().encode('utf-8'),
                       'json': lambda: r.to_json().encode('utf-8')}[fmt]()
        finally:
            registry.current_session.reset(token)

    return FileResult(content, f'{template}_{today():%Y%m%d}.{ext}', mime, disposition)
