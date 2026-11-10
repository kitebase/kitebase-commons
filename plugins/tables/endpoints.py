"""The tables of the application, as the browser lists them.

`tables_list` answers one row per table the user may read: a table they
cannot read would open on a refusal, so it is not offered. Each row names the
generated list that opens it (`<table>_list`, resolved by the core).
"""
from typing import Any, Dict

import kitebase.utils
from kitebase import access
from kitebase.endpoints import endpoint
from kitebase.i18n import _


@endpoint('tables_list', access='tables.browse')
def tables_list(data: Dict[str, Any]) -> Dict[str, Any]:
    app = kitebase.utils.get_app()
    rows = []
    for name, table in sorted(app.tables.items(), key=lambda item: item[0].lower()):
        if not access.can(f'{name}.read'):
            continue
        rows.append({
            'id': name,
            'label': _(table.attributes.get('label') or name),
            'table': table.table_name,
            'plugin': table.plugins[0].name if table.plugins else '',
            'kind': _('junction') if table.attributes.get('many_to_many') else _('table'),
            'page': f'{name.lower()}_list',
        })
    return {'status': 'success', 'data': rows, 'code': 200}
