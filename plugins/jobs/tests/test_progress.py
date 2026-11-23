"""
A work says where it is, its person sees it with a poll, and can stop it where
the work allows.

    (cd server && uv run pytest -q ../commons/plugins/jobs/tests)
"""
import pytest

import kitebase.context
from kitebase.endpoints import CommandDispatcher, _ENDPOINTS
from kitebase.errors import NotFound

ADA = {'id': 1, 'username': 'ada'}
BOB = {'id': 2, 'username': 'bob'}


@pytest.fixture(autouse=True)
def plugin(app):
    global progress
    from jobs import progress
    yield
    kitebase.context.replace(None)


def _as(person):
    kitebase.context.replace(person)


def _poll(person):
    _as(person)
    return progress.jobs_poll({})


def test_a_work_shows_to_its_person_only_and_closes_at_the_end():
    seen = {}

    def working(params):
        from kitebase.notify import notify
        notify('Fetching', done=1, total=3, cancellable=True)
        seen['ada'] = _poll(ADA)
        seen['bob'] = _poll(BOB)
        _as(ADA)
        return 'done'

    _ENDPOINTS['working'] = working
    try:
        result = CommandDispatcher().send({'operation': 'working', 'context': ADA,
                                           'request_id': 'r1'})
    finally:
        _ENDPOINTS.pop('working', None)

    assert result['data'] == 'done'
    [work] = seen['ada']['works']
    assert (work['key'], work['doing'], work['done'], work['total'], work['cancellable']) == \
        ('r1', 'Fetching', 1, 3, True)
    assert seen['ada']['next'] == progress.DEFAULTS['poll_fast']
    assert seen['bob'] == {'works': [], 'next': progress.DEFAULTS['poll_slow']}
    assert _poll(ADA)['works'] == []


def test_a_cancel_stops_the_work_at_its_cancellable_phase():
    steps = []

    def batch(params):
        from kitebase.notify import notify
        for i in range(3):
            notify('Book', done=i, total=3, cancellable=True)
            steps.append(i)
            if i == 0:
                _as(ADA)
                progress.jobs_cancel({'key': 'r2'})
                progress.kitebase.notify._current.get().last_write = 0  # due now
        return 'all'

    _ENDPOINTS['batch'] = batch
    try:
        result = CommandDispatcher().send({'operation': 'batch', 'context': ADA,
                                           'request_id': 'r2'})
    finally:
        _ENDPOINTS.pop('batch', None)

    assert steps == [0]
    assert result['error_type'] == 'Cancelled'
    assert _poll(ADA)['works'] == []


def test_nobody_else_cancels_a_work():
    from transient import lease
    with lease.find_app().get_session() as s:
        lease.hold(s, 'work:r3', 60, user_id=ADA['id'])
        s.commit()
    _as(BOB)
    with pytest.raises(NotFound):
        progress.jobs_cancel({'key': 'r3'})
    _as({**BOB, 'is_admin': True})
    assert progress.jobs_cancel({'key': 'r3'})['status'] == 'success'
