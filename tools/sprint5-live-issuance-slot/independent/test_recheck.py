from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import importlib.util
from threading import Barrier, Event
import sqlite3

import pytest
from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper.repository import RepositoryError


spec = importlib.util.spec_from_file_location(
    'bundled_tests',
    '/tmp/jsh-s5-live-issuer-slot.pfmWxjB4/tests/test_s5_live_issuance_slot.py',
)
bundled = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundled)


@pytest.fixture
def root(tmp_path):
    directory = tmp_path / 'issuance'
    directory.mkdir(mode=0o700)
    with closing(sqlite3.connect(bundled.witness_path(directory))) as db, db:
        db.execute('CREATE TABLE dispatches(dispatch TEXT PRIMARY KEY, binding TEXT, root TEXT, state TEXT)')
    return directory


def test_final_reservation_custody_cannot_delay_work_past_expiry(root, monkeypatch):
    clock = bundled.fake_clock(monkeypatch)
    frozen = bundled.binding(root)
    check_custody = slots._IssuanceSlots._stamp_slot
    calls = 0

    def delay_second_custody_check(owner, slot, binding):
        nonlocal calls
        calls += 1
        if calls == 2:
            clock.elapsed_ns += 61 * 10**9
        return check_custody(owner, slot, binding)

    monkeypatch.setattr(slots._IssuanceSlots, '_stamp_slot', delay_second_custody_check)
    granted = False
    with bundled.owner(root) as channel:
        try:
            with channel.reserve(frozen):
                granted = True
        except RepositoryError:
            pass
    assert calls == 2
    assert not granted, 'the application entered work after the elapsed deadline'
    assert bundled.retained(root, frozen).expired


@pytest.mark.parametrize('operation, final_custody_check', [('commit', 3), ('read_result', 2)])
def test_final_result_custody_cannot_delay_response_past_expiry(
    root, monkeypatch, operation, final_custody_check,
):
    clock = bundled.fake_clock(monkeypatch)
    frozen = bundled.binding(root)
    if operation == 'read_result':
        with bundled.owner(root) as channel, channel.reserve(frozen) as attempt:
            attempt.commit(frozen, bundled._EVIDENCE)

    check_custody = slots._IssuanceSlots._check_result_custody
    calls = 0

    def delay_final_custody_check(owner, slot, binding, reservation, saved):
        nonlocal calls
        calls += 1
        if calls == final_custody_check:
            clock.elapsed_ns += 61 * 10**9
        return check_custody(owner, slot, binding, reservation, saved)

    monkeypatch.setattr(slots._IssuanceSlots, '_check_result_custody', delay_final_custody_check)
    result = None
    with bundled.owner(root) as channel:
        try:
            if operation == 'commit':
                with channel.reserve(frozen) as attempt:
                    result = attempt.commit(frozen, bundled._EVIDENCE)
            else:
                result = channel.read_result(frozen)
        except RepositoryError:
            pass
    assert calls == final_custody_check
    assert result is None, 'current evidence was returned after the elapsed deadline'
    assert bundled.retained(root, frozen).expired


def test_eight_concurrent_calls_grant_one_durable_allowance(root):
    frozen = bundled.binding(root)
    enter = Barrier(8, timeout=5)
    working = Event()
    proceed = Event()

    def contender():
        with bundled.owner(root) as channel:
            enter.wait()
            try:
                with channel.reserve(frozen) as attempt:
                    working.set()
                    assert proceed.wait(timeout=5)
                    return attempt.commit(frozen, bundled._EVIDENCE)
            except RepositoryError:
                return None

    with ThreadPoolExecutor(max_workers=8) as workers:
        futures = [workers.submit(contender) for _ in range(8)]
        try:
            assert working.wait(timeout=5)
            state = bundled.retained(root, frozen)
            assert state.reservation_sha256 and state.commit_sha256 is None
            with bundled.owner(root) as channel:
                assert channel.read_result(frozen) is None
        finally:
            proceed.set()
        outcomes = [future.result(timeout=5) for future in futures]
    assert outcomes.count(None) == 7
    with bundled.owner(root) as channel:
        assert channel.read_result(frozen) == next(value for value in outcomes if value is not None)


def test_unavailable_authority_at_confirmation_keeps_evidence_on_hold(root):
    frozen = bundled.binding(root)

    class FailedConfirmation(bundled.Witness):
        def transact(self, dispatch, binding, root_identity, transition):
            def check(state):
                updated = transition(state)
                if updated.commit_sha256 is not None and state.commit_sha256 is None:
                    raise RepositoryError('Disposable authority failed before durable confirmation.')
                return updated

            return super().transact(dispatch, binding, root_identity, check)

    failed = FailedConfirmation(bundled.witness_path(root))
    with bundled.owner(root, admission=failed) as channel, channel.reserve(frozen) as attempt:
        with pytest.raises(RepositoryError, match='failed before durable confirmation'):
            attempt.commit(frozen, bundled._EVIDENCE)
    assert bundled.retained(root, frozen).commit_sha256 is None
    assert (root / f"{frozen['dispatch_sha256']}.commit.json").exists()
    with bundled.owner(root) as channel:
        with pytest.raises(RepositoryError, match='lacks exact independent confirmation'):
            channel.read_result(frozen)
        with pytest.raises(RepositoryError, match='already reserved'):
            with channel.reserve(frozen):
                pytest.fail('a failed confirmation reopened a spent allowance')
