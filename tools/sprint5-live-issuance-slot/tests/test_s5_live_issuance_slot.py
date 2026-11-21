"""Private issuance custody tests using only disposable file descriptors."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper.ordinary_live_mapping_verdict import open_live_mapping_verdict_owner
from job_search_helper.repository import RepositoryError


_TOOLS = 'a' * 64
_DISPATCH = 'b' * 64
_EVIDENCE = {key: f'{i:064x}' for i, key in enumerate((
    'live_capture_sha256', 'candidate_validation_sha256', 'authority_extraction_digest',
    'candidate_inventory_digest', 'regression_inventory_digest',
), start=101)}


def binding(root=None):
    value = {key: f'{i:064x}' for i, key in enumerate((
        'publication_sha256', 'verifier_input_sha256', 'raw_capture_manifest_sha256',
        'raw_response_sha256', 'inventory_sha256', 'runtime_binding_sha256', 'company_projection_sha256',
        'company_source_revision', 'control_projection_sha256', 'control_source_revision',
        'collector_policy_sha256', 'worker_source_sha256', 'measurement_tool_sha256',
    ), start=1)}
    value.update(dispatch_sha256=_DISPATCH, reviewed_tools_sha256=_TOOLS,
                 candidate={'source_manifest_sha256': 'c' * 64, 'config_sha256': 'd' * 64,
                            'dependency_manifest_sha256': 'e' * 64},
                 deadline_unix_ms=slots._now_ms() + 60_000,
                 live_request_limit=110, replay_request_limit=123, capsule_bytes_limit=10 * 1024 * 1024)
    if root is not None:
        enroll(root, value)
    return value


def witness_path(root):
    return root.parent / 'retained-owner.sqlite3'


class Witness(slots.IssuanceAdmission):
    """Disposable retained owner store, anchored outside the rolled-back evidence root."""

    def __init__(self, path):
        self.path = path

    def transact(self, dispatch_sha256, binding_sha256, root_identity, transition):
        try:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True)) as db, db:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT binding, root, state FROM dispatches WHERE dispatch=?',
                                 (dispatch_sha256,)).fetchone()
                if row is None or row[:2] != (binding_sha256, json.dumps(root_identity)):
                    raise RepositoryError('The retained owner has no exact enrolled dispatch.')
                values = json.loads(row[2])
                if values['window'] is not None:
                    values['window'] = slots.IssuanceWindow(**values['window'])
                state = slots.IssuanceAdmissionState(**values)
                updated = transition(state)
                if updated != state:
                    db.execute('UPDATE dispatches SET state=? WHERE dispatch=?',
                               (json.dumps(asdict(updated)), dispatch_sha256))
            return updated
        except sqlite3.Error:
            raise RepositoryError('The retained owner authority is unavailable.') from None


def enroll(root, binding):
    info = root.stat()
    with closing(sqlite3.connect(witness_path(root))) as db, db:
        db.execute('INSERT INTO dispatches VALUES(?,?,?,?)', (
            binding['dispatch_sha256'], slots._digest(binding), json.dumps((info.st_dev, info.st_ino)),
            json.dumps(asdict(slots.IssuanceAdmissionState())),
        ))


def retained(root, frozen):
    info = root.stat()
    return Witness(witness_path(root)).transact(frozen['dispatch_sha256'], slots._digest(frozen),
                                               (info.st_dev, info.st_ino), lambda existing: existing)


@pytest.fixture
def root(tmp_path):
    path = tmp_path / 'live-issuance'
    path.mkdir(mode=0o700)
    with closing(sqlite3.connect(witness_path(path))) as db, db:
        db.execute('CREATE TABLE dispatches(dispatch TEXT PRIMARY KEY, binding TEXT, root TEXT, state TEXT)')
    return path


@contextmanager
def owner(root, *, descriptor_path=None, identity=None, tool_pin=_TOOLS, admission=None):
    descriptor = os.open(descriptor_path or root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        info = os.fstat(descriptor)
        with slots.open_issuance_slots(root, descriptor, expected_owner_identity=identity or (info.st_dev, info.st_ino),
                                       reviewed_tools_sha256=tool_pin,
                                       admission=Witness(witness_path(root)) if admission is None else admission) as value:
            yield value
    finally:
        os.close(descriptor)


def test_single_exact_commit_and_fresh_process_readback(root):
    frozen = binding(root)
    assert root.stat().st_mode & 0o777 == 0o700
    with owner(root) as channel:
        assert channel.read_result(frozen) is None
        with channel.reserve(frozen) as attempt:
            assert channel.read_result(frozen) is None
            with pytest.raises(RepositoryError, match='already reserved'):
                with channel.reserve(frozen):
                    pytest.fail('duplicate work was granted')
            result = attempt.commit(deepcopy(frozen), _EVIDENCE)
            assert set(result) == {'schema', 'binding_sha256', 'completed_unix_ms', 'evidence'}
            assert channel.read_result(frozen) is None
            with pytest.raises(RepositoryError, match='no longer active'):
                attempt.commit(frozen, _EVIDENCE)
        assert result['evidence'] == _EVIDENCE
        assert channel.read_result(frozen) == result
    with owner(root) as fresh:
        assert fresh.read_result(frozen) == result
        with pytest.raises(RepositoryError, match='already reserved'):
            with fresh.reserve(frozen):
                pytest.fail('committed work was dispatched twice')
    assert {item.name for item in root.iterdir()} == {_DISPATCH, f'{_DISPATCH}.reservation.json',
                                                     f'{_DISPATCH}.commit.json'}
    assert {item.name for item in (root / _DISPATCH).iterdir()} == {'reservation.json', 'result.json'}
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in root.rglob('*.json'))
    assert result == process(root, frozen, 'read')


@pytest.mark.parametrize('key', [
    'dispatch_sha256', 'publication_sha256', 'verifier_input_sha256', 'raw_capture_manifest_sha256',
    'raw_response_sha256', 'inventory_sha256', 'runtime_binding_sha256', 'company_projection_sha256',
    'company_source_revision', 'control_projection_sha256', 'control_source_revision', 'reviewed_tools_sha256',
    'collector_policy_sha256', 'worker_source_sha256', 'measurement_tool_sha256', 'candidate',
    'deadline_unix_ms', 'live_request_limit', 'replay_request_limit', 'capsule_bytes_limit',
])
def test_changed_owner_readback_cannot_commit_or_reuse(root, key):
    frozen = binding(root)
    original = deepcopy(frozen)
    with owner(root) as channel:
        with channel.reserve(frozen) as attempt:
            if key == 'candidate':
                frozen[key]['config_sha256'] = 'f' * 64
            elif type(frozen[key]) is int:
                frozen[key] -= 1
            else:
                frozen[key] = 'f' * 64
            with pytest.raises(RepositoryError):
                attempt.commit(frozen, _EVIDENCE)
            with pytest.raises(RepositoryError, match='no longer active'):
                attempt.commit(original, _EVIDENCE)
        assert channel.read_result(original) is None
        with pytest.raises(RepositoryError):
            channel.read_result(frozen)
        with pytest.raises(RepositoryError, match='already reserved'):
            with channel.reserve(original):
                pytest.fail('changed inputs reopened the original allowance')
    assert not (root / f'{_DISPATCH}.commit.json').exists()


@pytest.mark.parametrize('field,value', [
    ('dispatch_sha256', '../elsewhere'), ('reviewed_tools_sha256', 'f' * 64),
    ('candidate', {'config_sha256': 'c' * 64}), ('live_request_limit', 129),
    ('replay_request_limit', True), ('capsule_bytes_limit', 64 * 1024 * 1024 + 1),
    ('deadline_unix_ms', 1), ('deadline_unix_ms', 2**63),
])
def test_invalid_pins_or_budget_refuse_before_creating_slot(root, field, value):
    frozen = binding()
    frozen[field] = value
    with owner(root) as channel, pytest.raises(RepositoryError):
        with channel.reserve(frozen):
            pytest.fail('invalid binding acquired a private slot')
    assert not list(root.iterdir())


@pytest.mark.parametrize('evidence', [{}, {'application_authority': True}, {**_EVIDENCE, 'mode': 'live'}])
def test_evidence_is_closed_and_creates_no_consumer_receipt(root, evidence):
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        with pytest.raises(RepositoryError, match='closed digest record'):
            attempt.commit(frozen, evidence)
    assert not (root / _DISPATCH / 'result.json').exists()
    assert not (root / f'{_DISPATCH}.json').exists()


def test_concurrent_callers_cannot_obtain_two_attempts_or_read_a_busy_commit(root, monkeypatch):
    frozen = binding(root)
    reached = Barrier(2, timeout=8)
    busy = Event()
    proceed = Event()
    publish = slots.private._publish_directory
    start = slots._publish

    def simultaneous_rename(directory, staged, target):
        if target == _DISPATCH:
            reached.wait()
        return publish(directory, staged, target)

    def pause_at_visible_commit(directory, name, content):
        start(directory, name, content)
        if name.endswith('.commit.json'):
            busy.set()
            assert proceed.wait(8)

    monkeypatch.setattr(slots.private, '_publish_directory', simultaneous_rename)
    monkeypatch.setattr(slots, '_publish', pause_at_visible_commit)

    def contender():
        with owner(root) as channel:
            try:
                with channel.reserve(frozen) as attempt:
                    return attempt.commit(frozen, _EVIDENCE)
            except RepositoryError:
                return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        tasks = [workers.submit(contender) for _ in range(2)]
        try:
            assert busy.wait(8)
            assert (root / f'{_DISPATCH}.commit.json').is_file()
            with owner(root) as reader:
                assert reader.read_result(frozen) is None
                with pytest.raises(RepositoryError, match='already reserved'):
                    with reader.reserve(frozen):
                        pytest.fail('active work was dispatched twice')
        finally:
            proceed.set()
        finished = [task.result(timeout=8) for task in tasks]
    assert finished.count(None) == 1
    with owner(root) as reader:
        assert reader.read_result(frozen) == next(value for value in finished if value is not None)
    assert not any(item.name.startswith('.issuance-') for item in root.iterdir())


_CHILD = '''
import json
import os
from pathlib import Path
import sys
from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper.repository import RepositoryError
from test_s5_live_issuance_slot import Witness, witness_path
root, frozen, evidence, operation, clock = json.loads(sys.argv[1])
root = Path(root)
info = root.stat()
fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
if clock:
    slots._now_ms = lambda: clock['wall_ms']
    slots._elapsed_ns = lambda: clock['elapsed_ns']
    slots._boot_id = lambda: clock['boot_id']

class CutWitness(Witness):
    def transact(self, *args):
        state = super().transact(*args)
        if operation == 'independent_spend' and state.reservation_sha256 is not None:
            os._exit(31)
        if operation == 'independent_confirmation' and state.commit_sha256 is not None:
            os._exit(31)
        return state

with slots.open_issuance_slots(root, fd, expected_owner_identity=(info.st_dev, info.st_ino),
                               reviewed_tools_sha256=frozen['reviewed_tools_sha256'],
                               admission=CutWitness(witness_path(root))) as owner:
    if operation == 'read':
        print(json.dumps(owner.read_result(frozen)))
        sys.exit(0)
    if operation in ('hold_read', 'refuse_reserve'):
        try:
            if operation == 'hold_read':
                owner.read_result(frozen)
            else:
                with owner.reserve(frozen):
                    sys.exit(67)
        except RepositoryError:
            sys.exit(31)
        sys.exit(68)

    publish = slots.private._publish_directory
    def cut(directory, staged, target):
        if operation == 'unpublished_slot' and target == frozen['dispatch_sha256']:
            os._exit(31)
        publish(directory, staged, target)
        if operation == 'slot_no_anchor' and target == frozen['dispatch_sha256']:
            os._exit(31)
        if operation == 'visible_result_no_commit' and target == 'result.json':
            os._exit(31)
        if operation == 'durable_commit' and target.endswith('.commit.json'):
            os._exit(31)
    slots.private._publish_directory = cut

    with owner.reserve(frozen) as ticket:
        if operation == 'work_uncertain':
            os._exit(31)
        ticket.commit(frozen, evidence)
sys.exit(66)
'''


def process(root, frozen, operation, *, clock=None):
    arguments = json.dumps([str(root), frozen, _EVIDENCE, operation, vars(clock) if clock else None])
    source = Path(__file__).resolve().parents[1] / 'src'
    result = subprocess.run([sys.executable, '-B', '-c', _CHILD, arguments],
                            env={**os.environ, 'PYTHONPATH': os.pathsep.join((str(source), str(source.parent / 'tests')))},
                            check=False,
                            capture_output=True, text=True, timeout=12)
    if operation == 'read':
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    assert result.returncode == 31, result.stderr


@pytest.mark.parametrize('cut', [
    'slot_no_anchor', 'independent_spend', 'work_uncertain', 'visible_result_no_commit',
    'durable_commit', 'independent_confirmation',
])
def test_process_crash_leaves_exact_result_or_spent_allowance(root, cut):
    frozen = binding(root)
    process(root, frozen, cut)
    with owner(root) as fresh:
        if cut in ('slot_no_anchor', 'visible_result_no_commit', 'durable_commit'):
            with pytest.raises(RepositoryError):
                fresh.read_result(frozen)
        elif cut in ('work_uncertain', 'independent_spend'):
            assert fresh.read_result(frozen) is None
        else:
            assert fresh.read_result(frozen)['evidence'] == _EVIDENCE
        with pytest.raises(RepositoryError, match='already reserved'):
            with fresh.reserve(frozen):
                pytest.fail('interrupted or complete work was dispatched twice')


def test_process_death_before_reservation_allows_first_attempt(root):
    frozen = binding(root)
    process(root, frozen, 'unpublished_slot')
    with owner(root) as channel:
        assert channel.read_result(frozen) is None
        with channel.reserve(frozen) as attempt:
            committed = attempt.commit(frozen, _EVIDENCE)
        assert channel.read_result(frozen) == committed


def test_reader_rechecks_deadline_after_durability_barrier(root, monkeypatch):
    frozen = binding(root)
    with owner(root) as channel:
        with channel.reserve(frozen) as attempt:
            attempt.commit(frozen, _EVIDENCE)

        fsync = os.fsync

        def expire_after_sync(fd):
            fsync(fd)
            monkeypatch.setattr(slots, '_now_ms', lambda: frozen['deadline_unix_ms'])

        monkeypatch.setattr(slots.os, 'fsync', expire_after_sync)
        with pytest.raises(RepositoryError, match='stale'):
            channel.read_result(frozen)


def test_deadline_prevents_late_commit_and_late_current_readback(root, monkeypatch):
    frozen = binding(root)
    with owner(root) as channel:
        with channel.reserve(frozen) as attempt:
            original_time = slots._now_ms()
            monkeypatch.setattr(slots, '_now_ms', lambda: frozen['deadline_unix_ms'])
            with pytest.raises(RepositoryError, match='expired'):
                attempt.commit(frozen, _EVIDENCE)
        monkeypatch.setattr(slots, '_now_ms', lambda: original_time)
        second = dict(frozen, dispatch_sha256='d' * 64)
        enroll(root, second)
        with channel.reserve(second) as attempt:
            attempt.commit(second, _EVIDENCE)
        monkeypatch.setattr(slots, '_now_ms', lambda: second['deadline_unix_ms'])
        with pytest.raises(RepositoryError, match='stale'):
            channel.read_result(second)
    assert (root / f"{second['dispatch_sha256']}.commit.json").is_file()


def test_monotonic_deadline_holds_even_with_unchanged_wall_clock(root, monkeypatch):
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        later = slots._elapsed_ns() + 121 * 1_000_000_000
        monkeypatch.setattr(slots, '_elapsed_ns', lambda: later)
        with pytest.raises(RepositoryError, match='expired'):
            attempt.commit(frozen, _EVIDENCE)


def fake_clock(monkeypatch):
    clock = SimpleNamespace(wall_ms=slots._now_ms(), elapsed_ns=slots._elapsed_ns(), boot_id=slots._boot_id())
    monkeypatch.setattr(slots, '_now_ms', lambda: clock.wall_ms)
    monkeypatch.setattr(slots, '_elapsed_ns', lambda: clock.elapsed_ns)
    monkeypatch.setattr(slots, '_boot_id', lambda: clock.boot_id)
    return clock


@pytest.mark.parametrize('operation, check_name, final_check', [
    ('reserve', '_stamp_slot', 2),
    ('commit', '_check_result_custody', 3),
    ('read_result', '_check_result_custody', 2),
])
@pytest.mark.parametrize('expired_by', ['elapsed', 'wall'])
def test_final_custody_cannot_delay_fresh_handoff(root, monkeypatch, operation, check_name, final_check, expired_by):
    clock = fake_clock(monkeypatch)
    original_clock = SimpleNamespace(**vars(clock))
    frozen = binding(root)
    if operation == 'read_result':
        with owner(root) as channel, channel.reserve(frozen) as attempt:
            attempt.commit(frozen, _EVIDENCE)

    check_custody = getattr(slots._IssuanceSlots, check_name)
    checks = 0

    def expire_during_final_check(*args):
        nonlocal checks
        checks += 1
        if checks == final_check:
            if expired_by == 'elapsed':
                clock.elapsed_ns += 61 * 10**9
            else:
                clock.wall_ms = frozen['deadline_unix_ms']
        return check_custody(*args)

    monkeypatch.setattr(slots._IssuanceSlots, check_name, expire_during_final_check)
    with owner(root) as channel, pytest.raises(RepositoryError, match='expired'):
        if operation == 'read_result':
            channel.read_result(frozen)
        else:
            with channel.reserve(frozen) as attempt:
                if operation == 'reserve':
                    pytest.fail('the application entered work after the deadline')
                attempt.commit(frozen, _EVIDENCE)

    assert checks == final_check
    state = retained(root, frozen)
    assert state.expired and state.reservation_sha256
    assert (state.commit_sha256 is not None) == (operation != 'reserve')
    process(root, frozen, 'hold_read', clock=original_clock)
    process(root, frozen, 'refuse_reserve', clock=original_clock)


def test_readback_samples_freshness_after_releasing_custody(root, monkeypatch):
    clock = fake_clock(monkeypatch)
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        attempt.commit(frozen, _EVIDENCE)

    lease = slots._reservation_lock

    @contextmanager
    def expire_as_the_lease_closes(*args):
        with lease(*args) as stamp:
            yield stamp
        clock.elapsed_ns += 61 * 10**9

    monkeypatch.setattr(slots, '_reservation_lock', expire_as_the_lease_closes)
    with owner(root) as channel, pytest.raises(RepositoryError, match='expired'):
        channel.read_result(frozen)
    assert retained(root, frozen).expired


@pytest.mark.parametrize('operation', ['reserve', 'commit', 'read_result'])
@pytest.mark.parametrize('expiry_first', [True, False])
def test_handoff_and_competing_expiry_follow_authority_order(root, monkeypatch, operation, expiry_first):
    clock = fake_clock(monkeypatch)
    initial_wall = clock.wall_ms
    frozen = binding(root)
    if operation == 'read_result':
        with owner(root) as channel, channel.reserve(frozen) as attempt:
            attempt.commit(frozen, _EVIDENCE)

    handoff = slots._IssuanceSlots._require_fresh_handoff
    ready, resume = Event(), Event()

    def pause_after_custody(channel, pins, reservation, **kwargs):
        if operation == 'commit' and not kwargs:
            return handoff(channel, pins, reservation)
        if not expiry_first:
            handoff(channel, pins, reservation, **kwargs)
        ready.set()
        assert resume.wait(timeout=5)
        if expiry_first:
            handoff(channel, pins, reservation, **kwargs)

    monkeypatch.setattr(slots._IssuanceSlots, '_require_fresh_handoff', pause_after_custody)

    def pending():
        with owner(root) as channel:
            if operation == 'read_result':
                return channel.read_result(frozen)
            with channel.reserve(frozen) as attempt:
                if operation == 'commit':
                    return attempt.commit(frozen, _EVIDENCE)
                return 'granted'

    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(pending)
        try:
            assert ready.wait(timeout=5)
            clock.wall_ms = frozen['deadline_unix_ms']
            with owner(root) as competitor, pytest.raises(RepositoryError, match='expired'):
                competitor.read_result(frozen)
            if expiry_first:
                clock.wall_ms = initial_wall
            assert retained(root, frozen).expired
        finally:
            resume.set()
        if expiry_first:
            with pytest.raises(RepositoryError, match='expired'):
                future.result(timeout=5)
        elif operation == 'reserve':
            assert future.result(timeout=5) == 'granted'
        else:
            assert future.result(timeout=5)['evidence'] == _EVIDENCE

    clock.wall_ms = initial_wall
    state = retained(root, frozen)
    assert state.expired and state.reservation_sha256
    assert (state.commit_sha256 is not None) == (operation != 'reserve')
    with owner(root) as refreshed, pytest.raises(RepositoryError, match='expired'):
        refreshed.read_result(frozen)


@pytest.mark.parametrize('boundary', ['evidence_commit', 'owner_confirmation'])
def test_commit_expiry_remains_expired_after_fresh_process_readback(root, monkeypatch, boundary):
    clock = fake_clock(monkeypatch)
    frozen = binding(root)
    publish = slots._publish

    def advance_at_evidence_commit(directory, name, content):
        if name.endswith('.commit.json'):
            clock.elapsed_ns += 61 * 10**9
        return publish(directory, name, content)

    class SlowWitness(Witness):
        def transact(self, *args):
            state = super().transact(*args)
            if state.commit_sha256 and not state.expired:
                clock.elapsed_ns += 61 * 10**9
            return state

    admission = Witness(witness_path(root))
    if boundary == 'evidence_commit':
        monkeypatch.setattr(slots, '_publish', advance_at_evidence_commit)
    else:
        admission = SlowWitness(witness_path(root))
    with owner(root, admission=admission) as channel, channel.reserve(frozen) as attempt:
        with pytest.raises(RepositoryError, match='expired'):
            attempt.commit(frozen, _EVIDENCE)
    assert (root / f'{_DISPATCH}.commit.json').is_file()
    assert retained(root, frozen).expired
    process(root, frozen, 'hold_read', clock=clock)


@pytest.mark.parametrize('expired_by', ['wall', 'boot'])
def test_rejected_clock_or_boot_correction_cannot_revive_evidence(root, monkeypatch, expired_by):
    clock = fake_clock(monkeypatch)
    initial = SimpleNamespace(**vars(clock))
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        attempt.commit(frozen, _EVIDENCE)
    if expired_by == 'wall':
        clock.wall_ms = frozen['deadline_unix_ms']
    else:
        clock.boot_id = '00000000-0000-0000-0000-000000000000'
    process(root, frozen, 'hold_read', clock=clock)
    assert retained(root, frozen).expired
    with owner(root) as restored:
        # Each read runs against the retained expiry before any evidence can be approved.
        clock.wall_ms = initial.wall_ms
        clock.boot_id = initial.boot_id
        with pytest.raises(RepositoryError, match='expired'):
            restored.read_result(frozen)
    process(root, frozen, 'hold_read', clock=initial)


def test_wall_expiry_before_work_cannot_revive_allowance(root, monkeypatch):
    clock = fake_clock(monkeypatch)
    initial = SimpleNamespace(**vars(clock))
    frozen = binding(root)
    clock.wall_ms = frozen['deadline_unix_ms']
    process(root, frozen, 'refuse_reserve', clock=clock)
    assert retained(root, frozen).expired
    process(root, frozen, 'refuse_reserve', clock=initial)
    assert not list(root.iterdir())


def test_custody_rechecked_after_reading_authority(root):
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        attempt.commit(frozen, _EVIDENCE)

    class ReplacingWitness(Witness):
        reads = 0

        def transact(self, *args):
            state = super().transact(*args)
            self.reads += 1
            if self.reads == 3:
                result = root / _DISPATCH / 'result.json'
                original = result.rename(result.with_name('result.original'))
                shutil.copy2(original, result)
            return state

    admission = ReplacingWitness(witness_path(root))
    with owner(root, admission=admission) as channel:
        with pytest.raises(RepositoryError, match='custody'):
            channel.read_result(frozen)
    assert admission.reads == 3


@pytest.mark.parametrize('confirmed', [False, True])
def test_all_private_dispatch_names_can_disappear_without_reopening_allowance(root, confirmed):
    frozen = binding(root)
    physical = root.stat().st_ino
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        if confirmed:
            attempt.commit(frozen, _EVIDENCE)
    independent = retained(root, frozen)
    rollback = root.with_name('before-private-restore')
    rollback.mkdir(mode=0o700)
    for entry in root.iterdir():
        entry.rename(rollback / entry.name)
    assert root.stat().st_ino == physical and not list(root.iterdir())
    process(root, frozen, 'hold_read')
    process(root, frozen, 'refuse_reserve')
    assert retained(root, frozen) == independent and not list(root.iterdir())


def test_loss_of_independent_authority_refuses_unchanged_local_evidence(root):
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        attempt.commit(frozen, _EVIDENCE)
    witness_path(root).rename(root.with_name('retained-owner-unavailable.sqlite3'))
    with owner(root) as channel:
        with pytest.raises(RepositoryError, match='authority is unavailable'):
            channel.read_result(frozen)
        with pytest.raises(RepositoryError, match='authority is unavailable'):
            with channel.reserve(frozen):
                pytest.fail('a missing authority granted an allowance')


def test_unenrolled_or_stale_frozen_digests_cannot_earn_allowance(root):
    fake = binding()
    with owner(root) as channel:
        with pytest.raises(RepositoryError, match='no exact enrolled'):
            with channel.reserve(fake):
                pytest.fail('binding digests enrolled their own dispatch')
    enroll(root, fake)
    changed = dict(fake, verifier_input_sha256='f' * 64)
    with owner(root) as channel:
        with pytest.raises(RepositoryError, match='no exact enrolled'):
            with channel.reserve(changed):
                pytest.fail('stale input digests replaced a trusted enrollment')
    assert not list(root.iterdir())


def test_custody_result_cannot_satisfy_live_verdict_consumer(root):
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        result = attempt.commit(frozen, _EVIDENCE)
    verdict_root = root.with_name('separately-approved-verdicts')
    verdict_root.mkdir(mode=0o700)
    path = verdict_root / f'{_DISPATCH}.json'
    path.write_bytes((root / _DISPATCH / 'result.json').read_bytes())
    path.chmod(0o600)
    info = verdict_root.stat()
    fd = os.open(verdict_root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with open_live_mapping_verdict_owner(verdict_root, fd, expected_owner_identity=(info.st_dev, info.st_ino),
                                             approved_verdict_sha256=slots._digest(result),
                                             reviewed_tools_sha256=_TOOLS) as approved:
            marker = dict.fromkeys(('schema', 'owner', 'admission', 'observation'))
            marker['dispatch_sha256'] = _DISPATCH
            with pytest.raises(RepositoryError, match='not an exact approved live mapping verdict'):
                approved.require(marker, {}, frozen['raw_capture_manifest_sha256'])
    finally:
        os.close(fd)


@pytest.mark.parametrize('target,mutation', [
    ('reservation', 'copy'), ('reservation', 'rewrite'), ('reservation', 'symlink'),
    ('result', 'copy'), ('result', 'rewrite'), ('result', 'hardlink'), ('result', 'perms'), ('result', 'remove'),
    ('anchor', 'copy'), ('anchor', 'remove'), ('commit', 'copy'), ('commit', 'remove'),
    ('slot', 'copy'), ('slot', 'remove'), ('slot', 'restore'),
])
def test_persistent_readback_holds_on_file_or_slot_substitution(root, target, mutation):
    frozen = binding(root)
    with owner(root) as channel, channel.reserve(frozen) as attempt:
        attempt.commit(frozen, _EVIDENCE)
    slot = root / _DISPATCH
    source = {'reservation': slot / 'reservation.json', 'result': slot / 'result.json',
              'anchor': root / f'{_DISPATCH}.reservation.json', 'commit': root / f'{_DISPATCH}.commit.json',
              'slot': slot}[target]
    if mutation in ('copy', 'symlink', 'remove', 'restore'):
        moved = source.with_name(source.name + '.moved')
        source.rename(moved)
        if mutation == 'symlink':
            source.symlink_to(moved)
        elif mutation == 'copy':
            if target == 'slot':
                shutil.copytree(moved, source)
            else:
                shutil.copy2(moved, source)
        elif mutation == 'restore':
            moved.rename(source)
    elif mutation == 'rewrite':
        raw = source.read_bytes()
        source.write_bytes(raw)
    elif mutation == 'hardlink':
        os.link(source, source.with_name('hard-alias'))
    else:
        source.chmod(0o644)
    with owner(root) as channel:
        with pytest.raises(RepositoryError):
            channel.read_result(frozen)
        with pytest.raises(RepositoryError, match='already reserved'):
            with channel.reserve(frozen):
                pytest.fail('physical substitution reset the work allowance')


def test_held_root_survives_replacement_as_a_hold(root):
    frozen = binding(root)
    with owner(root) as channel:
        with channel.reserve(frozen) as attempt:
            old = root.with_name('old-root')
            root.rename(old)
            root.mkdir(mode=0o700)
            with pytest.raises(RepositoryError, match='directory changed'):
                attempt.commit(frozen, _EVIDENCE)
            with pytest.raises(RepositoryError, match='directory changed'):
                channel.read_result(frozen)
    info = old.stat()
    with pytest.raises(RepositoryError, match='directory changed'):
        with owner(root, identity=(info.st_dev, info.st_ino)):
            pytest.fail('replaced named root acquired the old identity')
    assert not list(root.iterdir())


def test_owner_requires_named_physical_descriptor_and_rejects_aliases(root):
    other = root.with_name('other-root')
    other.mkdir(mode=0o700)
    alias = root.with_name('directory-alias')
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(RepositoryError, match='directory changed'):
        with owner(root, descriptor_path=other):
            pytest.fail('descriptor and named root both accepted')
    with pytest.raises(RepositoryError, match='custody'):
        with owner(alias):
            pytest.fail('aliased root was accepted')
    with pytest.raises(RepositoryError, match='configured'):
        with owner(root, tool_pin='unapproved'):
            pytest.fail('invalid independently selected tool pin was accepted')
