"""The addresses of a partner, for the smtp plugin: its own email, the main
one, and the email of each of its contacts with the functions they hold;
and the functions, rows of PartnerFunction, the dialog ticks them by.

The partner has been checked readable by smtp; its contacts are parts of it
(owned children), read with it.
"""
from typing import Any, Dict, List

import kitebase.utils
from smtp.addresses import register_addresses


def partner_addresses(record_id: Any) -> List[Dict[str, Any]]:
    app = kitebase.utils.get_app()
    Partner, Function = app.models['Partner'], app.models['PartnerFunction']
    with app.get_session() as session:
        partner = session.get(Partner, int(record_id))
        if partner is None:
            return []
        labels = {f.id: f.label for f in session.query(Function)}
        rows = [{'model': 'Partner', 'id': partner.id, 'name': partner.name,
                 'email': partner.email, 'main': True}]
        contacts = (session.query(Partner)
                    .filter(Partner.parent_id == partner.id, Partner.usage == 'contact')
                    .order_by(Partner.name))
        for c in contacts:
            functions = list(c.functions or [])
            rows.append({'model': 'Partner', 'id': c.id, 'name': c.name, 'email': c.email,
                         'functions': functions,
                         'note': ', '.join(labels.get(f, f) for f in functions)})
        return rows


def partner_functions() -> List[Dict[str, Any]]:
    app = kitebase.utils.get_app()
    Function = app.models['PartnerFunction']
    with app.get_session() as session:
        return [{'value': f.id, 'label': f.label or f.id}
                for f in session.query(Function).order_by(Function.sequence, Function.id)]


register_addresses('Partner', partner_addresses, partner_functions)
