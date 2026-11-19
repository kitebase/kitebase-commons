"""The tables of the application, as the browser lists them, and their seed.

`tables_list` answers one row per table the user may read: a table they
cannot read would open on a refusal, so it is not offered. Each row names the
generated list that opens it, `auto.<table>_list`: the one built from the
columns even where the application draws its own list, and whose rows open
the generated form. Every field of the model, and none of the commands the
application adds to its views, and the seed sets that carry the table.

`seed_compare` and `seed_apply` are the comparison with a set (kitebase.seed):
what differs is shown, and only the new rows the user chose are written, with
the user's own permissions. The rows are read whole, past the record rules:
a rule hiding a row would show it as new, and writing it would make it twice.
"""
from pathlib import PurePath
from typing import Any, Dict, List, Tuple

import kitebase.utils
from kitebase import access, seed
from kitebase.endpoints import endpoint
from kitebase.i18n import _, _f
from kitebase.media import UploadedFile
from kitebase.pages import AUTO_PREFIX


@endpoint('tables_list', access='tables.browse')
def tables_list(data: Dict[str, Any]) -> Dict[str, Any]:
    app = kitebase.utils.get_app()
    sets = _seed_sets(app)
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
            'page': f'{AUTO_PREFIX}{name.lower()}_list',
            'seed': ', '.join(sets.get(name, [])),
        })
    return {'status': 'success', 'data': rows, 'code': 200}


def _seed_sets(app: Any) -> Dict[str, List[str]]:
    """Model -> the sets carrying it, `<plugin>/<set>`. A broken set, none."""
    try:
        files = seed.seed_files(app)
    except seed.SeedError:
        return {}
    sets: Dict[str, List[str]] = {}
    for f in files:
        sets.setdefault(f.model, []).append(f'{f.plugin}/{f.set}')
    return sets


def _source(app: Any, data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    The table and the rows to compare it with: the file of a set, or the rows
    of a file the user uploaded (`rows`), which the page carries back with
    every call: nothing of it is kept on the server.
    """
    model, set_ref = data.get('table'), data.get('set')
    if model not in app.tables:
        raise seed.SeedError(_f('Unknown table: {table}', table=model))
    access.check_table(model, 'read')
    if not set_ref:
        rows = data.get('rows')
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise seed.SeedError(_('Nothing to compare: neither a set nor the rows of a file'))
        return model, rows
    files = [f for f in seed.seed_files(app, set_ref) if f.model == model]
    if not files:
        raise seed.SeedError(_f('The set {set} has no file for {table}', set=set_ref, table=model))
    return model, seed.read_file(files[0].path)


def _error(e: Exception) -> Dict[str, Any]:
    return {'status': 'error', 'message': str(e), 'code': 422}


STATES = {seed.EQUAL: 'equal', seed.DIFFERENT: 'different', seed.NEW: 'new',
          seed.ONLY_DB: 'only in the table', seed.AMBIGUOUS: 'ambiguous'}


def _change(change: Dict[str, Any]) -> str:
    if change['kind'] == 'added':
        return _f('{path} added', path=change['path'])
    if change['kind'] == 'missing':
        return _f('{path} missing', path=change['path'])
    shown = {k: _('(empty)') if change[k] in (None, '') else change[k] for k in ('db', 'seed')}
    return _f('{path}: {db} now, {seed} in the file', path=change['path'], **shown)


def _note(item: Any) -> str:
    if item.reason == 'no_key':
        return _('nothing to recognize it by')
    if item.reason == 'in_file':
        return _f('{count} rows of the file have it', count=item.count)
    if item.reason == 'in_table':
        return _f('{count} rows of the table have it', count=item.count)
    return ''


COMPARE_PAGE = 'tables_seed_compare'


@endpoint('seed_choose', access='tables.seed')
def seed_choose(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    The command of the browser on a table (`id`): what to compare it with, the
    sets that carry it or a file; straight to the file where no set does.
    """
    app = kitebase.utils.get_app()
    model = data.get('id')
    if model not in app.tables:
        return _error(seed.SeedError(_f('Unknown table: {table}', table=model)))
    if not seed.identity_field(app, model):
        return {'status': 'success', 'code': 200, 'data': {'message': _f(
            '{table} has neither a code nor a name to recognize its rows by', table=model)}}
    upload = {'action': 'upload', 'op': 'seed_upload', 'params': {'table': model},
              'accept': list(seed.SUFFIXES)}
    sets = _seed_sets(app).get(model, [])
    if not sets:
        return {'status': 'success', 'data': upload, 'code': 200}
    options = [{'label': s, 'then': {'action': 'stack_push', 'panel': COMPARE_PAGE,
                                     'props': {'table': model, 'set': s}}} for s in sets]
    options.append({'label': _('A file...'), 'then': upload})
    return {'status': 'success', 'code': 200, 'data': {
        'action': 'choose', 'message': _f('Compare {table} with', table=model),
        'options': options}}


UPLOAD_LIMIT = 1024 * 1024      # a seed is configuration: a megabyte is plenty


@endpoint('seed_upload', access='tables.seed')
def seed_upload(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    A file in the shape of a seed, uploaded for `table`: read here and handed
    to the comparison page, which carries its rows. The table is the one the
    user chose, never one the file names. Its headers may be the titles a
    list's export writes: a CSV exported, changed and uploaded comes back.
    """
    app = kitebase.utils.get_app()
    model, upload = data.get('table'), data.get('file')
    if model not in app.tables:
        return _error(seed.SeedError(_f('Unknown table: {table}', table=model)))
    if not isinstance(upload, UploadedFile):
        return _error(seed.SeedError('No file: call through upload/<op>'))
    access.check_table(model, 'read')
    suffix = PurePath(upload.filename).suffix
    try:
        text = upload.read(UPLOAD_LIMIT).decode('utf-8-sig')
        rows = seed.by_titles(app, model, seed.parse_rows(text, suffix, upload.filename))
    except UnicodeDecodeError:
        return _error(seed.SeedError(_f('{name} is not UTF-8 text', name=upload.filename)))
    except seed.SeedError as e:
        return _error(e)
    return {'status': 'success', 'code': 200, 'data': {
        'action': 'stack_push', 'panel': COMPARE_PAGE,
        'props': {'table': model, 'rows': rows, 'source': upload.filename}}}


@endpoint('seed_compare', access='tables.seed')
def seed_compare(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    The rows of a table against a set: one row per row of the file, in its
    order, its id the place in the file; then the rows only the table has.
    Equal rows come too, for the counts; the client decides what to show. A
    row the table has names the form that opens it.
    """
    app = kitebase.utils.get_app()
    try:
        model, rows = _source(app, data)
        # a file a person made says only some columns: the others are not compared
        result = seed.compare(app, model, rows, only_given=not data.get('set'))
    except seed.SeedError as e:
        return _error(e)
    form = f'{AUTO_PREFIX}{model.lower()}_form'
    out = []
    for item in result:
        out.append({
            'id': item.index if item.index is not None else f'db{item.db_id}',
            'state': item.state,
            'state_label': _(STATES[item.state]),
            'key': item.key,
            'detail': _note(item) or '; '.join(_change(c) for c in item.changes or []),
            'db_id': item.db_id,
            'form': form if item.db_id is not None else None,
        })
    return {'status': 'success', 'data': out, 'code': 200}


@endpoint('seed_apply', access='tables.seed')
def seed_apply(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write the new rows chosen, by their place in the file (`ids`, as the
    comparison numbered them), each with what it owns: as the user, who must
    be allowed to create every table of the tree.
    """
    app = kitebase.utils.get_app()
    try:
        model, rows = _source(app, data)
        for name in [model, *sorted(seed.owned_models(app, model))]:
            access.check_table(name, 'create')
        places = {int(i) for i in data.get('ids') or [] if str(i).isdigit()}
        keys = [item.key for item in seed.compare(app, model, rows) if item.index in places]
        lines, written = seed.apply_new(app, model, rows, keys)
    except seed.SeedError as e:
        return _error(e)
    return {'status': 'success', 'code': 200, 'data': {
        'written': written,
        'message': _f('{count} rows added to {table}', count=written, table=model),
        'detail': '\n'.join(lines)}}
