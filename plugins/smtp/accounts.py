"""The SMTP accounts of the installation, from `secrets/smtp.yaml`.

    $redirect_to: dev@example.com     # every message goes here instead
    $dry_run: true                    # nothing is sent: the message is written to a file
    office:
      host: smtp.example.com
      port: 587                       # 587 STARTTLS, 465 SSL; `security:` to force
      user: office@example.com
      password: ...
      from: "Office <office@example.com>"
      sent: Sent                      # a copy of each message in this IMAP folder

`sent` names the folder of the account's mailbox where a copy of each message
is appended, for the providers that do not keep one themselves: declaring it
is asking for the copy. Written alone it is the folder, on the account's host
over IMAPS (993) with the account's login; as a mapping it may say where:

      sent: {host: imap.example.com, port: 993, folder: "Sent Items"}

`security`, `user` and `password` may be given there too.

The keys beginning with `$` are switches of the installation, the others name
an account. The file is read at every use, so an account added while the
server runs is there at the next message.

Which accounts a user may send from is a column of `User` (`mail_accounts`),
which the administrator changes from the interface: the names are not secret,
the values are, and only the names ever leave the server.
"""
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any, Dict, List, Optional

import kitebase.context
import kitebase.utils
from kitebase import secrets
from kitebase.diagnostics import make_issue
from kitebase.errors import Invalid
from kitebase.i18n import _, _f
from kitebase.sections import register_section

KIND = 'smtp'
SECURITY = ('starttls', 'ssl', 'none')


@dataclass
class SentFolder:
    """Where the copy of a sent message goes: an IMAP folder."""
    host: str
    port: int
    security: str
    folder: str
    user: Optional[str] = None
    password: Optional[str] = None


@dataclass
class Account:
    name: str
    host: str
    port: int
    security: str
    sender: str
    user: Optional[str] = None
    password: Optional[str] = None
    sent: Optional[SentFolder] = None


def _entries() -> Dict[str, Any]:
    """The file as written; empty when the installation has none."""
    return {name: secrets.get(KIND, name) for name in secrets.names(KIND)}


def options() -> Dict[str, Any]:
    """The switches of the installation: `redirect_to` (an address or None) and
    `dry_run` (a bool)."""
    entries = _entries()
    return {'redirect_to': entries.get('$redirect_to') or None,
            'dry_run': bool(entries.get('$dry_run'))}


def names() -> List[str]:
    """The names of the accounts, in the order of the file."""
    return [n for n in _entries() if not str(n).startswith('$')]


def _problem(entry: Any) -> Optional[str]:
    """What is wrong with an account as written, or None."""
    if not isinstance(entry, dict):
        return 'an account is a mapping of host, port, user, password, from'
    for key in ('host', 'from'):
        if not entry.get(key):
            return f"'{key}' is missing"
    port = entry.get('port', 587)
    if not isinstance(port, int) or not 0 < port < 65536:
        return f"'port' must be a number, not {port!r}"
    if entry.get('security') is not None and entry['security'] not in SECURITY:
        return f"'security' is one of {', '.join(SECURITY)}, not {entry['security']!r}"
    if bool(entry.get('user')) != bool(entry.get('password')):
        return "'user' and 'password' go together"
    if len(getaddresses([entry['from']])) != 1 or not getaddresses([entry['from']])[0][1]:
        return f"'from' is not an address: {entry['from']!r}"
    return _sent_problem(entry.get('sent'))


def _sent_problem(sent: Any) -> Optional[str]:
    if sent is None:
        return None
    if isinstance(sent, str):
        return None if sent.strip() else "'sent' names a folder"
    if not isinstance(sent, dict) or not sent.get('folder'):
        return "'sent' is a folder, or a mapping with 'folder'"
    port = sent.get('port', 993)
    if not isinstance(port, int) or not 0 < port < 65536:
        return f"'sent.port' must be a number, not {port!r}"
    if sent.get('security') is not None and sent['security'] not in SECURITY:
        return f"'sent.security' is one of {', '.join(SECURITY)}, not {sent['security']!r}"
    if bool(sent.get('user')) != bool(sent.get('password')):
        return "'sent.user' and 'sent.password' go together"
    return None


def _sent(entry: Dict[str, Any]) -> Optional[SentFolder]:
    """The folder of the copies, with what it does not say taken from the account."""
    sent = entry.get('sent')
    if sent is None:
        return None
    if isinstance(sent, str):
        sent = {'folder': sent}
    port = sent.get('port', 993)
    own = bool(sent.get('user'))
    return SentFolder(host=sent.get('host') or entry['host'], port=port,
                      security=sent.get('security') or ('ssl' if port == 993 else 'starttls'),
                      folder=str(sent['folder']),
                      user=sent['user'] if own else entry.get('user'),
                      password=sent['password'] if own else entry.get('password'))


def account(name: str) -> Account:
    """The account of this name, checked: Invalid if it is missing or malformed."""
    entries = _entries()
    if name not in entries or str(name).startswith('$'):
        raise Invalid(_f("No mail account '{name}'", name=name))
    entry = entries[name]
    problem = _problem(entry)
    if problem:
        raise Invalid(_f("Mail account '{name}': {problem}", name=name, problem=problem))
    port = entry.get('port', 587)
    return Account(name=name, host=entry['host'], port=port,
                   security=entry.get('security') or ('ssl' if port == 465 else 'starttls'),
                   sender=entry['from'], user=entry.get('user'), password=entry.get('password'),
                   sent=_sent(entry))


def of_user(user_id: Any) -> List[str]:
    """The accounts the user may send from, in their order."""
    app = kitebase.utils.get_app()
    User = app.models['User']
    with app.get_session() as session:
        user = session.get(User, user_id)
        return list((user.mail_accounts if user is not None else None) or [])


def choose(requested: Optional[str]) -> str:
    """The account a message goes out from. With a user in the context, one of
    theirs (the first when none is requested); without one, the work of the
    system, the account the message names."""
    context = kitebase.context.current() or {}
    if context.get('id') is None:
        if not requested:
            raise Invalid(_('A message sent by the system names its account'))
        return requested
    allowed = of_user(context['id'])
    if not allowed:
        raise Invalid(_('You have no mail account to send from: ask the administrator'))
    if requested is None:
        return allowed[0]
    if requested not in allowed:
        raise Invalid(_f("You may not send from the account '{name}'", name=requested))
    return requested


# ── The column of User ────────────────────────────────────────────────────────

def validate_accounts(value: Any, record: Dict[str, Any]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
        return _('A list of account names is expected, such as ["office", "info"]')
    declared = set(names())
    unknown = [n for n in value if n not in declared]
    if unknown:
        return _f('Unknown mail account: {names}', names=', '.join(unknown))
    return None


# ── check ─────────────────────────────────────────────────────────────────────

def check(app: Any) -> List[Dict[str, Any]]:
    """An account that cannot work is an error: the messages sent from it fail.
    The switches of a development installation are a warning while they are on,
    so a production installation that kept one is told."""
    issues: List[Dict[str, Any]] = []
    where = f'secrets/{KIND}.yaml'
    try:
        entries = _entries()
    except secrets.SecretError as e:
        return [make_issue('error', 'smtp-secrets', where, str(e), 'smtp')]
    if not [n for n in entries if not str(n).startswith('$')]:
        issues.append(make_issue('info', 'smtp-no-account', where,
                                 f'no mail account in {secrets.root() / (KIND + ".yaml")}: '
                                 f'nothing can be sent', 'smtp'))
    for name, entry in entries.items():
        if str(name).startswith('$'):
            if name not in ('$redirect_to', '$dry_run'):
                issues.append(make_issue('warning', 'smtp-switch', f'{where}.{name}',
                                         f"unknown switch '{name}': $redirect_to, $dry_run", 'smtp'))
            continue
        problem = _problem(entry)
        if problem:
            issues.append(make_issue('error', 'smtp-account', f'{where}.{name}', problem, 'smtp'))
    opts = options()
    media = getattr(app, 'media', None)
    if media is None or 'mail' not in media.roots:
        severity = 'error' if opts['dry_run'] else 'warning'
        issues.append(make_issue(severity, 'smtp-media-root', 'media.roots.mail',
                                 "no media root 'mail': messages carry no attachment"
                                 + (" and a dry run has nowhere to write" if opts['dry_run'] else ''),
                                 'smtp'))
    if opts['dry_run']:
        issues.append(make_issue('warning', 'smtp-dry-run', f'{where}.$dry_run',
                                 'dry run: no message is sent, each is written to a file (MailLog.eml)',
                                 'smtp'))
    if opts['redirect_to']:
        issues.append(make_issue('warning', 'smtp-redirect', f'{where}.$redirect_to',
                                 f"every message goes to {opts['redirect_to']}, not to its recipients",
                                 'smtp'))
    return issues


register_section('smtp', check=check)
