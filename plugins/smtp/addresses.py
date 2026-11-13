"""The addresses of a record, and which of them a message goes to.

A record may be reached at more than one address: a partner at its own and at
those of its contacts, each contact doing something inside it (technical
office, accounts). smtp does not know what a partner is: the plugin that does
registers, per model, a function that lists them.

    register_addresses('Partner', partner_addresses, partner_functions)

    def partner_addresses(record_id) -> list of
        {'model': 'Partner', 'id': 7, 'name': 'Ross, Mark',
         'email': 'ross@example.com', 'functions': ['TEC', 'WHS'],
         'note': 'Technical office, Warehouse', 'main': False}

`model` and `id` are the row the address belongs to, which a message to one
contact reads its placeholders from; `functions` are the codes a command
names; `note` is what the dialog shows beside the name; `main` marks the
address a message goes to when nothing else is asked. The record has been
checked readable before the provider is called; an address whose `email`
column the user does not read is dropped here, whatever the provider says.

`partner_functions` lists the codes with their labels, `[{value, label}]`:
the dialog offers them to tick the contacts holding one.

A table without an email of its own may borrow the addresses of the record a
many-to-one relation reaches: `register_addresses_via('Invoice', 'partner')`.

A model with no provider has one address, its `email` column, as main.

`choose` is which addresses a message takes: the main ones, or those holding
one of the `functions` asked. When nobody holds them, `fallback` decides:
`main` sends to the main address all the same (an invoice must arrive),
`skip` sends nothing (a technical newsletter). The outcome says which
happened, for the summary that tells the user.
"""
from email.utils import formataddr
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import inspect

import kitebase.utils
from kitebase import access
from kitebase.endpoint_db import coerce_value
from kitebase.errors import Invalid, NotFound
from kitebase.i18n import _f
from kitebase.refs import check_readable

Provider = Callable[[Any], List[Dict[str, Any]]]

_providers: Dict[str, Provider] = {}
_functions: Dict[str, Callable[[], List[Dict[str, Any]]]] = {}

FALLBACKS = ('main', 'skip')


def register_addresses(model: str, provider: Provider,
                       functions: Optional[Callable[[], List[Dict[str, Any]]]] = None) -> None:
    """The function that lists the addresses of a record of `model`, and the
    one that lists the functions they may hold, `[{value, label}]`, in their
    order: what the dialog offers to pick the addresses by."""
    _providers[model] = provider
    if functions is not None:
        _functions[model] = functions


def register_addresses_via(model: str, relation: str) -> None:
    """The addresses of a record of `model` are those of the record its
    many-to-one `relation` reaches: an invoice is written to its partner.

        register_addresses_via('Invoice', 'partner')

    `relation` may be a dotted path (`order.partner`). The record reached is
    read only when the user reads it; the message stays about the record of
    `model`, whose placeholders it fills."""
    def target(record_id: Any) -> Optional[Tuple[str, Any]]:
        app = kitebase.utils.get_app()
        Model = app.models[model]
        key = inspect(Model).primary_key[0].key
        with app.get_session() as session:
            row = session.get(Model, coerce_value(Model, key, record_id))
            for step in relation.split('.'):
                row = getattr(row, step, None) if row is not None else None
            if row is None:
                return None
            Target = type(row)
            return Target.__name__, getattr(row, inspect(Target).primary_key[0].key)

    def provider(record_id: Any) -> List[Dict[str, Any]]:
        found = target(record_id)
        if found is None:
            return []
        try:
            check_readable(*found)
        except (access.AccessDenied, NotFound):
            return []
        return of_record(*found)

    def functions() -> List[Dict[str, Any]]:
        app = kitebase.utils.get_app()
        Model = app.models[model]
        for step in relation.split('.'):
            Model = inspect(Model).relationships[step].mapper.class_
        return functions_of(Model.__name__)

    register_addresses(model, provider, functions)


def functions_of(model: str) -> List[Dict[str, Any]]:
    """The functions the addresses of `model` may hold; none without a provider."""
    lister = _functions.get(model)
    return list(lister()) if lister else []


def own(model: str, record_id: Any) -> Optional[Dict[str, Any]]:
    """The address in the record's own `email` column, named by its display
    field; None when the table has none, the user does not read it, or it is
    empty."""
    app = kitebase.utils.get_app()
    table = app.tables.get(model)
    if table is None or not any(c.name == 'email' for c in table.effective_columns):
        return None
    if not _readable(model):
        return None
    Model = app.models[model]
    key = inspect(Model).primary_key[0].key
    with app.get_session() as session:
        row = session.get(Model, coerce_value(Model, key, record_id))
        email = getattr(row, 'email', None) if row is not None else None
        if not email:
            return None
        display = kitebase.utils.search_info(table).get('display_field') or ''
        name = getattr(row, display, None) if display and display != 'email' else None
        return {'model': model, 'id': record_id, 'name': str(name) if name else '',
                'email': email, 'functions': [], 'note': '', 'main': True}


def _readable(model: str) -> bool:
    app = kitebase.utils.get_app()
    table = app.tables.get(model)
    if table is None:
        return True
    return 'email' not in access.unreadable_columns(model, app) and \
        'email' not in table.secret_columns


def of_record(model: str, record_id: Any) -> List[Dict[str, Any]]:
    """The addresses of a record, those with an email only."""
    provider = _providers.get(model)
    if provider is None:
        row = own(model, record_id)
        return [row] if row else []
    rows = []
    for row in provider(record_id) or []:
        if not row.get('email') or not _readable(str(row.get('model') or model)):
            continue
        rows.append({'model': row.get('model') or model,
                     'id': row.get('id', record_id),
                     'name': row.get('name') or '', 'email': row['email'],
                     'functions': list(row.get('functions') or []),
                     'note': row.get('note') or '', 'main': bool(row.get('main'))})
    return rows


def formatted(row: Dict[str, Any]) -> str:
    """`Name <address>`, as a To field writes it."""
    return formataddr((row['name'], row['email'])) if row.get('name') else row['email']


def check_choice(functions: Any, fallback: Any) -> Tuple[List[str], str]:
    """The `functions` and `fallback` of a command, checked."""
    if functions is None or functions == '':
        functions = []
    if isinstance(functions, str):
        functions = [functions]
    if not isinstance(functions, list) or not all(isinstance(f, str) for f in functions):
        raise Invalid(_f("'functions' is a list of codes, such as {example}", example='["ADM"]'))
    fallback = fallback or 'main'
    if fallback not in FALLBACKS:
        raise Invalid(_f("'fallback' is one of: {values}", values=', '.join(FALLBACKS)))
    return functions, fallback


def choose(rows: Iterable[Dict[str, Any]], functions: Optional[List[str]] = None,
           fallback: str = 'main') -> Tuple[List[Dict[str, Any]], str]:
    """The addresses a message goes to, and how they were found: `main`,
    `functions`, `fallback` (nobody holds them, the main address instead) or
    `skipped` (nobody holds them, and nothing is sent). With no address marked
    main, the first one is."""
    rows = list(rows)
    main = [r for r in rows if r['main']] or rows[:1]
    if not functions:
        return main, 'main'
    wanted = set(functions)
    held = [r for r in rows if wanted & set(r['functions'])]
    if held:
        return held, 'functions'
    if fallback == 'skip' or not main:
        return [], 'skipped'
    return main, 'fallback'
