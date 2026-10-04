"""Changing one's own password.

The password column is `secret` and hashed on write, so no generic form can
offer it: this is the one way to change it without an administrator. It asks
for the current password - a session left open on someone else's desk must not
be enough to take the account over - and writes the new one through the
column's own `validate` and `on_write`: the password policy of common, and the
stored form the column declares. The rules are the same as the user form's.

Setting another user's password is not here: the user form does it, for who
can edit users (pages.yaml).
"""
import kitebase.utils
from kitebase.db import BaseApp
from kitebase.endpoint_db import write_values
from kitebase.endpoints import endpoint
from kitebase.i18n import _
from kitebase.transforms import ValidationError, verify_password

# What the form shows, before and after: a password never stays on screen.
EMPTY = {'current': '', 'new': '', 'confirm': ''}


@endpoint('password_form')
def password_form(data):
    return {'status': 'success', 'code': 200, 'data': dict(EMPTY)}


@endpoint('change_password')
def change_password(data):
    """Set the caller's password. Field errors come back per field."""
    user_id = (BaseApp.get_context() or {}).get('id')
    if not user_id:
        return {'status': 'error', 'code': 401, 'message': _('Not logged in')}

    values = data.get('data') or {}
    current = values.get('current') or ''
    new = values.get('new') or ''
    confirm = values.get('confirm') or ''

    app = kitebase.utils.get_app()
    auth = app.pm.config.get('authentication', {})
    table = auth.get('user_table', 'User')
    field = auth.get('password_field', 'password')

    with app.get_session() as session:
        user = session.get(app.models[table], user_id)
        if user is None:
            return {'status': 'error', 'code': 404, 'message': _('Unknown user')}

        errors = {}
        if not verify_password(current, getattr(user, field)):
            errors['current'] = _('The current password is not right')
        if new and new == current:
            errors['new'] = _('It is the same as the current one')
        if new != confirm:
            errors['confirm'] = _('The two passwords do not match')

        # The column's own rules and stored form: the policy, then the hash. An
        # empty password is not a change, and the column would drop it.
        stored = None
        if 'new' not in errors:
            try:
                written = write_values(app.tables[table], {
                    field: new, auth.get('username_field', 'username'):
                        getattr(user, auth.get('username_field', 'username'), None)})
                stored = written.get(field)
            except ValidationError as e:
                errors['new'] = e.errors.get(field, str(e))
            if stored is None and 'new' not in errors:
                errors['new'] = _('A new password is needed')

        if errors:
            return {'status': 'error', 'code': 400,
                    'message': _('The password was not changed'),
                    'data': {'errors': errors}}

        setattr(user, field, stored)
        session.commit()

    return {'status': 'success', 'code': 200,
            'message': _('Password changed'), 'data': dict(EMPTY)}
