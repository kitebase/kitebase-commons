"""The rules of a partner, on every port that writes one.

A VAT number or a tax code already held by another partner is asked about, not
refused: two rows with the same code are most often the same subject entered
twice, but not always (a branch, a subject re-registered after a merger), and
the person saving knows which. A code left empty is never compared: whether a
code is required is a rule of the application, or of a plugin that knows the
country, and not of this one (README.md shows the form such a rule takes).

The rows holding the code are named, archived ones included and said so: an
archived duplicate is the one nobody finds in the list.
"""
from typing import Any, List

import kitebase.utils
from kitebase.flow import on_write
from kitebase.i18n import _, _f

CODES = (('vat_number', 'VAT number'), ('tax_code', 'Tax code'))


def _holders(ctx, column: str, value: Any) -> List[Any]:
    Partner = kitebase.utils.get_app().models['Partner']
    query = ctx.session.query(Partner).filter(getattr(Partner, column) == value)
    if ctx.mode != 'insert':
        query = query.filter(Partner.id != ctx.record['id'])
    return query.order_by(Partner.id).limit(3).all()


def _named(row: Any) -> str:
    name = row.name or f'#{row.id}'
    return _f('{name} (archived)', name=name) if getattr(row, 'is_archived', False) is True else name


@on_write('Partner')
def duplicate_codes(ctx):
    if ctx.mode == 'delete':
        return
    lines = []
    for column, label in CODES:
        value = ctx.record.get(column)
        if value in (None, ''):
            continue
        # Unchanged on an update: asked when it was written, not at every save
        if ctx.mode == 'update' and ctx.original and ctx.original.get(column) == value:
            continue
        holders = _holders(ctx, column, value)
        if holders:
            lines.append(_f('{label} {value} is already held by {names}', label=_(label),
                            value=value, names=', '.join(_named(r) for r in holders)))
    if lines and not ctx.confirm('partner_duplicate_codes', '. '.join(lines) + '.',
                                 yes=_('Save all the same'), no=_('Do not save')):
        ctx.stay(_('Not saved'))
