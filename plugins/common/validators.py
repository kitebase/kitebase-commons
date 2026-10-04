"""The password policy: what a new password must be, on every way in.

Registered as `password_policy` and declared by the Password type, so it holds
wherever a password is written through kitebase - the user form of an
administrator, and one's own change of password, which calls it too.

The rules come from the application's config.yaml, and only the length is on
unless asked for: current guidance (NIST 800-63B) says length is what makes a
password strong, and mandatory symbols mostly produce `Password1!`.

    password_policy:
      min_length: 8            # the default
      require: [lower, upper, digit, symbol]   # none by default
      not_like_username: true  # off by default

bcrypt's 72-byte ceiling is not a rule here: the hashing refuses it on its own.
"""
import kitebase.utils
from kitebase.i18n import _, _f
from kitebase.transforms import register_validator

DEFAULTS = {'min_length': 8, 'require': [], 'not_like_username': False}

_CLASSES = {
    'lower': (str.islower, 'a lowercase letter'),
    'upper': (str.isupper, 'an uppercase letter'),
    'digit': (str.isdigit, 'a digit'),
    'symbol': (lambda c: not c.isalnum() and not c.isspace(), 'a symbol'),
}


def policy() -> dict:
    """The rules in force: the defaults, with what config.yaml says on top."""
    try:
        given = kitebase.utils.get_app().pm.config.get('password_policy') or {}
    except Exception:
        given = {}
    return {**DEFAULTS, **given}


def password_policy(value, values):
    """The message for a password that breaks a rule, or None."""
    rules = policy()
    password = str(value)

    if len(password) < rules['min_length']:
        return _f('At least {n} characters', n=rules['min_length'])

    missing = [_(label) for name, (test, label) in _CLASSES.items()
               if name in (rules['require'] or []) and not any(test(c) for c in password)]
    if missing:
        return _f('It needs {what}', what=', '.join(missing))

    username = values.get('username')
    if rules['not_like_username'] and username and str(username).lower() in password.lower():
        return _('It must not contain the username')

    return None


register_validator('password_policy', password_policy)
