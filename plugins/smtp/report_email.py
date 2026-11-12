"""A print sent by email: the destination "Email" of the print dialog.

Loaded only where the application loads `reports` too (config.yaml,
`optional`), so neither plugin needs the other.

The print is made by `reports` with its checks, then staged in the outbox as
the user's own file, and the compose form opens with it attached, the
report's title as subject. A print of one row is a message about that row:
To has its main address, the dialog its addresses, and the message is in its
mail sent. A print of several rows has no recipient to guess: To is empty,
and the message is linked to every row.
"""
from typing import Any, Dict

import kitebase.utils
from kitebase.i18n import _

from reports import registry
from smtp import outbox
from smtp.endpoints import compose_action


def deliver(report: registry.Report, data: Dict[str, Any], file: Any) -> Dict[str, Any]:
    app = kitebase.utils.get_app()
    ref = outbox.stage(app, file.filename, [file.content])
    ids = list(data.get('ids') or [])
    record = ({'model': report.table, 'id': ids[0]}
              if report.table and len(ids) == 1 else None)
    values: Dict[str, Any] = {'subject': data.get('title') or _(report.title),
                              'attachments': [{'ref': ref, 'name': outbox.name_of(ref)}]}
    if report.table and len(ids) > 1:
        values['links'] = [{'model': report.table, 'id': i} for i in ids]
    return compose_action(record, **values)


registry.register_destination('email', 'Email', deliver, access='smtp.send')
