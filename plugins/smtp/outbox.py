"""The files a message carries, staged before it is sent.

An attachment is written once, in the media root `mail`, and the messages
that carry it refer to it: a mail merge to five hundred partners keeps one
copy of the PDF, and the log row of each message lists the references.

    mail:outbox/<owner>/<yyyymm>/<token>/<name>

`owner` is the id of the user who staged the file (`system` for work with
no user). It is what makes a reference safe to take from the client: a
user's message may carry the files that user staged, never another's,
whatever reference the client sends. The token keeps two files of the same
name apart.

A dry run writes the message itself to `mail:dry_run/<yyyymm>/<log id>.eml`
(`nolog-<token>.eml` for a message sent without a log).
"""
import secrets as _random
from typing import Any, Iterable, List, Optional, Tuple

import kitebase.context
from kitebase.apptime import today
from kitebase.errors import Invalid
from kitebase.i18n import _f
from kitebase.media import MediaError, checked_upload, parse_ref, parse_size, sanitize_name

ROOT = 'mail'

DEFAULT_ACCEPT = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'txt', 'csv', 'xlsx', 'xls',
                  'docx', 'doc', 'odt', 'ods', 'zip']
DEFAULT_MAX_SIZE = '20MB'


def _owner() -> str:
    user = (kitebase.context.current() or {}).get('id')
    return str(user) if user is not None else 'system'


def _settings(app: Any) -> Tuple[List[str], Optional[int]]:
    section = ((getattr(app.plugins, 'data', None) or {}).get('smtp') or {}).get('attachments') or {}
    return (list(section.get('accept') or DEFAULT_ACCEPT),
            parse_size(section.get('max_size') or DEFAULT_MAX_SIZE))


def _root(app: Any) -> Any:
    try:
        return app.media.root(ROOT)
    except MediaError:
        raise Invalid(_f("Attachments need the media root '{root}' in config.yaml", root=ROOT))


def stage(app: Any, name: str, chunks: Iterable[bytes]) -> str:
    """Store a file for the current user's messages; its reference."""
    _accept, max_size = _settings(app)
    rel = (f'outbox/{_owner()}/{today():%Y%m}/{_random.token_hex(6)}/'
           f'{sanitize_name(name)}')
    return f'{ROOT}:{_root(app).provider.create(rel, chunks, max_size)}'


def stage_upload(app: Any, upload: Any) -> str:
    """Store an uploaded file, after the checks of its kind and extension."""
    accept, _max = _settings(app)
    return stage(app, upload.filename, checked_upload('file', accept, upload))


def owned(ref: str) -> bool:
    """Whether a reference is a file the current user staged."""
    try:
        r = parse_ref(ref)
    except MediaError:
        return False
    return r.root == ROOT and r.path.startswith(f'outbox/{_owner()}/') and not r.is_folder


def name_of(ref: str) -> str:
    return ref.rsplit('/', 1)[-1]


def read(app: Any, ref: str) -> bytes:
    with app.media.open(ref) as f:
        return f.read()


def write_dry_run(app: Any, log_id: Any, content: bytes) -> str:
    """Write the message of a dry run; its reference. A message sent without
    a log has no id, and a name of its own."""
    name = log_id if log_id is not None else f'nolog-{_random.token_hex(6)}'
    rel = f'dry_run/{today():%Y%m}/{name}.eml'
    return f'{ROOT}:{_root(app).provider.create(rel, [content])}'
