from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper.repository import RepositoryError
from test_recheck import bundled, root


def test_spend_survives_worker_death_missing_custody_and_elapsed_expiry(root, monkeypatch):
    clock = bundled.fake_clock(monkeypatch)
    original_clock = SimpleNamespace(**vars(clock))
    frozen = bundled.binding(root)
    bundled.process(root, frozen, 'work_uncertain', clock=clock)
    spent = bundled.retained(root, frozen)
    assert spent.reservation_sha256 and spent.commit_sha256 is None and not spent.expired

    displaced = root.with_name('saved-custody')
    displaced.mkdir(mode=0o700)
    for entry in root.iterdir():
        entry.rename(displaced / entry.name)
    clock.elapsed_ns += 45 * 10**9
    bundled.process(root, frozen, 'hold_read', clock=clock)
    bundled.process(root, frozen, 'refuse_reserve', clock=clock)
    assert bundled.retained(root, frozen) == spent

    clock.elapsed_ns += 30 * 10**9
    bundled.process(root, frozen, 'refuse_reserve', clock=clock)
    terminal = bundled.retained(root, frozen)
    assert terminal.expired and terminal.reservation_sha256 == spent.reservation_sha256
    bundled.process(root, frozen, 'hold_read', clock=original_clock)
    bundled.process(root, frozen, 'refuse_reserve', clock=original_clock)
    assert bundled.retained(root, frozen) == terminal


@pytest.mark.parametrize('operation, check_name, final_check', [
    ('reserve', '_stamp_slot', 2),
    ('commit', '_check_result_custody', 3),
    ('read_result', '_check_result_custody', 2),
])
def test_handoff_holds_when_overlapping_reader_latches_expiry(
    root, monkeypatch, operation, check_name, final_check,
):
    clock = bundled.fake_clock(monkeypatch)
    original_wall = clock.wall_ms
    frozen = bundled.binding(root)
    if operation == 'read_result':
        with bundled.owner(root) as channel, channel.reserve(frozen) as attempt:
            attempt.commit(frozen, bundled._EVIDENCE)

    check_custody = getattr(slots._IssuanceSlots, check_name)
    at_final_custody = Event()
    continue_handoff = Event()
    checks = 0

    def pause_final_custody(*args):
        nonlocal checks
        checks += 1
        if checks == final_check:
            at_final_custody.set()
            assert continue_handoff.wait(5)
        return check_custody(*args)

    monkeypatch.setattr(slots._IssuanceSlots, check_name, pause_final_custody)

    def handoff():
        with bundled.owner(root) as channel:
            try:
                if operation == 'read_result':
                    return channel.read_result(frozen)
                with channel.reserve(frozen) as attempt:
                    if operation == 'reserve':
                        return 'work allowance was yielded'
                    return attempt.commit(frozen, bundled._EVIDENCE)
            except RepositoryError:
                return None

    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(handoff)
        try:
            assert at_final_custody.wait(5)
            clock.wall_ms = frozen['deadline_unix_ms']
            with bundled.owner(root) as other, pytest.raises(RepositoryError, match='expired'):
                other.read_result(frozen)
            assert bundled.retained(root, frozen).expired
            clock.wall_ms = original_wall
        finally:
            continue_handoff.set()
        assert pending.result(timeout=5) is None
