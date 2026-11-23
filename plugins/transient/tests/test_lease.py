"""Leases: taken, renewed, read while alive, gone when expired.

    (cd server && uv run pytest -q ../commons/plugins/transient/tests)
"""
from datetime import timedelta

import pytest

from kitebase import apptime


@pytest.fixture(autouse=True)
def plugin(app):
    """The plugin's module, importable once the application has loaded it."""
    global lease
    from transient import lease


def _shift(monkeypatch, seconds):
    later = apptime.now() + timedelta(seconds=seconds)
    monkeypatch.setattr(lease.apptime, 'now', lambda: later)


def test_taken_then_renewed_keeps_since(app):
    with app.get_session() as s:
        assert lease.hold(s, 'work:1', 60, user_id=3, doing='one') is True
        first = lease.get(s, 'work:1')
        assert lease.hold(s, 'work:1', 60, doing='two') is False
        again = lease.get(s, 'work:1')
        s.commit()
    assert again['since'] == first['since']
    assert again['doing'] == 'two' and again['user_id'] == 3


def test_one_lease_per_holder_and_subject(app):
    with app.get_session() as s:
        lease.hold(s, 'user:3', 60, model='Order', record_id=7)
        lease.hold(s, 'user:4', 60, model='Order', record_id=7)
        lease.hold(s, 'user:3', 60, model='Order', record_id=7)
        lease.hold(s, 'user:3', 60, model='Order', record_id=8)
        s.commit()
        on_seven = lease.live(s, model='Order', record_id='7')
    assert [row['holder'] for row in on_seven] == ['user:3', 'user:4']


def test_live_by_user(app):
    with app.get_session() as s:
        lease.hold(s, 'work:a', 60, user_id=3)
        lease.hold(s, 'work:b', 60, user_id=4)
        s.commit()
        assert [row['holder'] for row in lease.live(s, user_id=3)] == ['work:a']


def test_an_expired_lease_is_gone_for_readers_before_the_sweep(app, monkeypatch):
    with app.get_session() as s:
        lease.hold(s, 'work:a', 10, user_id=3)
        s.commit()
    _shift(monkeypatch, 11)
    with app.get_session() as s:
        assert lease.live(s, user_id=3) == []
        assert lease.get(s, 'work:a') is None
        assert lease.mark(s, 'work:a', cancel_requested=True) is False
        assert lease.sweep(s) == 1
        s.commit()


def test_mark_changes_without_renewing(app):
    with app.get_session() as s:
        lease.hold(s, 'work:a', 60)
        before = lease.get(s, 'work:a')['expires_at']
        assert lease.mark(s, 'work:a', cancel_requested=True) is True
        row = lease.get(s, 'work:a')
        s.commit()
    assert row['cancel_requested'] is True and row['expires_at'] == before


def test_release_and_forget(app):
    with app.get_session() as s:
        lease.hold(s, 'work:a', 60)
        lease.hold(s, 'user:3', 60, model='Order', record_id=7)
        lease.release(s, 'work:a')
        lease.forget(s, [('Order', 7)])
        s.commit()
        assert lease.live(s) == []


def test_an_unknown_field_is_refused(app):
    with app.get_session() as s, pytest.raises(TypeError):
        lease.hold(s, 'work:a', 60, colour='red')
