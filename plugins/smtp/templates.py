"""Placeholders in the subject and body of a message, and the two parts of the body.

    subject: 'Invoice [[number]] of [[date]]'
    body:    'Dear [[partner.name]],\\n\\n[[$note]]'

`[[path]]` is a value of the record the message is about (`record: {model,
id}`), following many-to-one relations with dots. `[[$name]]` is a parameter
given by whoever composes (`params: {name: ...}`). A placeholder that does
not resolve is an error naming it, never an empty string sent: a field that
is merely empty resolves to nothing, a path that does not exist does not
resolve.

The record is read for the user: on a guarded session (table permission and
record rules, relations included), and a secret column or one of a group the
user may not read does not resolve. A template cannot show what the form
would not.

The body is markdown. Its plain text part is the markdown with the values put
in as they are, and without the escapes an editor writes (`a\\_b`, `&amp;`); its HTML part renders the markdown with the values escaped, so
a `*` in a customer's name stays a star and does not start emphasis. Raw HTML
is off in the rendering, so whoever writes the text cannot put markup in the
message.
"""
import html
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from markdown_it import MarkdownIt
from sqlalchemy import inspect

import kitebase.utils
from kitebase import access
from kitebase.endpoint_db import coerce_value
from kitebase.errors import Invalid, NotFound
from kitebase.i18n import _, _f, current_locale

PLACEHOLDER = re.compile(r'\[\[\s*(\$?[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*\]\]')

# ASCII punctuation markdown may read as syntax: escaped with a backslash, which
# the rendering removes again
_MARKDOWN_PUNCTUATION = re.compile(r'([\\`*_{}\[\]<>()#+\-.!|~])')

# A backslash before ASCII punctuation, as markdown escapes it
_BACKSLASH_ESCAPE = re.compile(r'\\([!-/:-@\[-`{-~])')

_DATE_FORMATS = {'it': ('%d/%m/%Y', '%d/%m/%Y %H:%M')}

_markdown = MarkdownIt('js-default')

_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.5; color: #222;">
{body}</body></html>
"""


def placeholders(text: Optional[str]) -> List[str]:
    """The placeholders of a text, each once, in order of appearance."""
    seen: List[str] = []
    for name in PLACEHOLDER.findall(text or ''):
        if name not in seen:
            seen.append(name)
    return seen


def as_text(value: Any) -> str:
    """A value as it reads in a message, in the current locale."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return _('yes') if value else _('no')
    formats = _DATE_FORMATS.get(current_locale(), ('%Y-%m-%d', '%Y-%m-%d %H:%M'))
    if isinstance(value, datetime):
        return value.strftime(formats[1])
    if isinstance(value, date):
        return value.strftime(formats[0])
    if isinstance(value, (Decimal, float)):
        text = format(Decimal(str(value)).normalize(), 'f')
        return text.replace('.', ',') if current_locale() == 'it' else text
    if isinstance(value, list):
        return ', '.join(as_text(v) for v in value)
    return str(value)


class _Unresolved(Exception):
    """A path that names nothing readable; the message says why."""


def _column(app: Any, model_name: str, name: str) -> bool:
    """Whether `name` is a value column of the model the user may read."""
    table = app.tables.get(model_name)
    if table is None:
        return False
    column = next((c for c in table.effective_columns if c.name == name), None)
    if column is None or column.attributes.get('media'):
        return False
    return (name not in table.secret_columns
            and name not in access.unreadable_columns(model_name, app))


def _follow(app: Any, record: Any, path: str) -> Any:
    """The value at the end of a dotted path, from a record loaded on a guarded
    session. A relation that leads nowhere (empty, or hidden by a rule) gives
    None: the field is empty, not unknown."""
    current = record
    segments = path.split('.')
    for i, name in enumerate(segments):
        model_name = type(current).__name__
        relations = inspect(type(current)).relationships
        if name in relations:
            if relations[name].uselist:
                raise _Unresolved(_f('{name} is a list of records', name=name))
            if i == len(segments) - 1:
                raise _Unresolved(_f('{name} is a record: name one of its fields', name=name))
            current = getattr(current, name)
            if current is None:
                return None
            continue
        if i != len(segments) - 1 or not _column(app, model_name, name):
            raise _Unresolved(_f('{model} has no field {name}', model=model_name, name=name))
        return getattr(current, name)
    return None


def resolve(names: List[str], record: Optional[Dict[str, Any]],
            params: Optional[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """The value of each placeholder, and the ones that do not resolve with why."""
    params = params or {}
    values: Dict[str, str] = {}
    missing: Dict[str, str] = {}
    paths = []
    for name in names:
        if name.startswith('$'):
            if name[1:] in params:
                values[name] = as_text(params[name[1:]])
            else:
                missing[name] = _f('no value given for {name}', name=name)
        else:
            paths.append(name)
    if not paths:
        return values, missing
    if not record:
        for name in paths:
            missing[name] = _f('{name} needs a record', name=name)
        return values, missing

    app = kitebase.utils.get_app()
    model_name = record.get('model')
    Model = app.models.get(model_name)
    if Model is None:
        raise Invalid(_f("'{model}' is not a table", model=model_name))
    key = inspect(Model).primary_key[0].key
    with app.get_session() as session:
        access.guard_session(session)
        value = coerce_value(Model, key, record.get('id'))
        row = session.get(Model, value)
        if row is None or not access.row_visible(session, Model, value):
            raise NotFound(_f('No {model} {id}', model=model_name, id=record.get('id')))
        for name in paths:
            try:
                values[name] = as_text(_follow(app, row, name))
            except _Unresolved as e:
                missing[name] = str(e)
    return values, missing


def substitute(text: Optional[str], values: Dict[str, str], escape: bool = False) -> str:
    """The text with each resolved placeholder replaced; the others left as written."""
    def one(match: 're.Match[str]') -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)
        value = values[name]
        return _MARKDOWN_PUNCTUATION.sub(r'\\\1', value) if escape else value
    return PLACEHOLDER.sub(one, text or '')


def plain(markdown: Optional[str]) -> str:
    """The markdown as a person reads it in a plain text message: without the
    backslash escapes and the HTML entities an editor writes (`a\\_b`,
    `A &amp; B`), which are syntax, not text."""
    return html.unescape(_BACKSLASH_ESCAPE.sub(r'\1', markdown or ''))


def render_html(markdown: str) -> str:
    """The HTML part of a markdown body."""
    return _HTML.format(body=_markdown.render(markdown or ''))


def compose(message: Dict[str, Any]) -> Dict[str, Any]:
    """Subject, plain text and HTML of a message, its placeholders filled, and
    the placeholders that did not resolve (`missing`, name: why)."""
    subject, body = message.get('subject') or '', message.get('body') or ''
    names = placeholders(subject + '\n' + body)
    values, missing = resolve(names, message.get('record'), message.get('params'))
    return {
        'subject': ' '.join(substitute(subject, values).split()),
        'text': substitute(plain(body), values),
        'html': render_html(substitute(body, values, escape=True)),
        'missing': missing,
    }


def complete(message: Dict[str, Any]) -> Dict[str, Any]:
    """`compose`, refusing a message with a placeholder that does not resolve."""
    parts = compose(message)
    if parts['missing']:
        raise Invalid(_f('Some placeholders do not resolve: {names}',
                         names=', '.join(f'{n} ({why})' for n, why in parts['missing'].items())),
                      data={'missing': parts['missing']})
    return parts
