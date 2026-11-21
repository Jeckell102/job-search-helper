"""Exercise the retained adapter against an initialized disposable Coordinator Store."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from threading import Barrier
import time

import pytest

import coordinator_issuance_admission as authority
from coordinator_store import Store
from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper import ordinary_raw_capture as private
from job_search_helper.repository import RepositoryError
from test_s5_live_issuance_slot import _EVIDENCE, _TOOLS, binding


def identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino


def selection_bytes(database, evidence, frozen, **changes):
    root = database.parent
    selection = {
        'schema': 'coordinator-live-issuance-selection-v1',
        'coordinator_root': str(root),
        'coordinator_root_identity': identity(root),
        'database_identity': identity(database),
        'evidence_root': str(evidence),
        'evidence_root_identity': identity(evidence),
        'dispatch_sha256': frozen['dispatch_sha256'],
        'binding_sha256': slots._digest(frozen),
        'source_sha256': {name: sha256(path.read_bytes()).hexdigest() for name, path in authority._SOURCE_FILES.items()},
    }
    selection.update(changes)
    return private._encode(selection)


@pytest.fixture
def installed(tmp_path):
    coordinator = Store(tmp_path / 'tasks')
    coordinator.path.chmod(0o600)
    evidence = tmp_path / 'issuance-evidence'
    evidence.mkdir(mode=0o700)
    frozen = binding()
    return coordinator, evidence, frozen


@contextmanager
def opened(installed, *, frozen=None, raw=None):
    coordinator, evidence, original = installed
    if raw is None:
        raw = selection_bytes(coordinator.path, evidence, original if frozen is None else frozen)
    with authority._open_issuance_store(raw, approved_selection_sha256=sha256(raw).hexdigest()) as store:
        yield store


@contextmanager
def channel(installed, store):
    _, evidence, _ = installed
    descriptor = os.open(evidence, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with slots.open_issuance_slots(evidence, descriptor, expected_owner_identity=identity(evidence),
                                       reviewed_tools_sha256=_TOOLS, admission=store.admission()) as owned:
            yield owned
    finally:
        os.close(descriptor)


def transact(installed, store, transition=lambda state: state):
    _, evidence, frozen = installed
    return store.admission().transact(frozen['dispatch_sha256'], slots._digest(frozen), identity(evidence), transition)


def enroll(installed):
    _, _, frozen = installed
    with opened(installed) as store:
        store.migrate()
        assert store.enroll_prevalidated(private._encode(frozen)) == slots.IssuanceAdmissionState()


def protected_snapshot(coordinator):
    with closing(sqlite3.connect(coordinator.path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        tables = db.execute("SELECT name,sql FROM main.sqlite_schema WHERE type='table' AND name NOT IN (?,?) ORDER BY name",
                            (authority._TABLE, 'sqlite_sequence')).fetchall()
        return {name: (schema, db.execute(f'SELECT * FROM main."{name}" ORDER BY rowid').fetchall())
                for name, schema in tables}


def test_additive_migration_and_exact_slot_lifecycle_preserve_other_data(installed, tmp_path, monkeypatch):
    coordinator, evidence, frozen = installed
    before = protected_snapshot(coordinator)
    app_files = [tmp_path / name for name in ('jobs.sqlite3', 'state.db', 'inventories.sqlite3')]
    for path in app_files:
        path.write_bytes(path.name.encode())
    raw = [path.read_bytes() for path in app_files]
    with opened(installed) as store:
        with pytest.raises(RepositoryError, match='schema'):
            transact(installed, store)
        store.migrate()
        store.migrate()
        with pytest.raises(RepositoryError, match='no exact enrolled'):
            transact(installed, store)
        assert store.enroll_prevalidated(private._encode(frozen)) == slots.IssuanceAdmissionState()
        assert not hasattr(store.admission(), 'migrate') and not hasattr(store.admission(), 'enroll_prevalidated')
        with channel(installed, store) as owned:
            with owned.reserve(frozen) as ticket:
                result = ticket.commit(frozen, _EVIDENCE)
            assert owned.read_result(frozen) == result
        spent = transact(installed, store)
        assert spent.reservation_sha256 and spent.commit_sha256 and not spent.expired
        assert store.enroll_prevalidated(private._encode(frozen)) == spent

    with opened(installed) as store, channel(installed, store) as owned:
        assert owned.read_result(frozen) == result
        with monkeypatch.context() as patch:
            patch.setattr(slots, '_now_ms', lambda: frozen['deadline_unix_ms'])
            with pytest.raises(RepositoryError, match='expired'):
                owned.read_result(frozen)
        assert transact(installed, store) == replace(spent, expired=True)
        with pytest.raises(RepositoryError, match='expired'):
            owned.read_result(frozen)
        assert store.enroll_prevalidated(private._encode(frozen)) == replace(spent, expired=True)

    assert protected_snapshot(coordinator) == before
    assert [path.read_bytes() for path in app_files] == raw
    assert all(path.parent != evidence for path in (coordinator.path, *app_files))


def test_wrong_binding_or_selection_cannot_enroll_or_update(installed):
    coordinator, evidence, frozen = installed
    enroll(installed)
    changed = deepcopy(frozen)
    changed['candidate']['source_manifest_sha256'] = '1' * 64
    with opened(installed, frozen=changed) as store:
        with pytest.raises(RepositoryError, match='different enrollment'):
            store.enroll_prevalidated(private._encode(changed))
        with pytest.raises(RepositoryError, match='no exact enrolled'):
            store.admission().transact(changed['dispatch_sha256'], slots._digest(changed), identity(evidence), lambda s: s)
    with opened(installed) as store:
        with pytest.raises(RepositoryError, match='independent selection'):
            store.enroll_prevalidated(private._encode(changed))
        with pytest.raises(RepositoryError, match='independent selection'):
            store.admission().transact(frozen['dispatch_sha256'], slots._digest(frozen), identity(coordinator.path), lambda s: s)
        assert transact(installed, store) == slots.IssuanceAdmissionState()


def test_selection_requires_separate_private_roots_and_exact_code(installed):
    coordinator, evidence, frozen = installed
    for invalid in (coordinator.base, coordinator.base / 'nested'):
        invalid.mkdir(mode=0o700, exist_ok=True)
        raw = selection_bytes(coordinator.path, invalid, frozen)
        with pytest.raises(RepositoryError, match='physically separate'), opened(installed, raw=raw):
            pytest.fail('a coordinator path was accepted as its own evidence domain')

    aliases = evidence.with_name('evidence-symlink')
    aliases.symlink_to(evidence, target_is_directory=True)
    raw = selection_bytes(coordinator.path, aliases, frozen)
    with pytest.raises(RepositoryError, match='authority is unavailable'), opened(installed, raw=raw):
        pytest.fail('a symlink evidence root was accepted')

    raw = selection_bytes(coordinator.path, evidence, frozen)
    with pytest.raises(RepositoryError, match='independent issuance selection'):
        with authority._open_issuance_store(raw, approved_selection_sha256='9' * 64):
            pytest.fail('an unapproved selection was accepted')
    wrong = json.loads(raw)
    wrong['source_sha256']['slot'] = '1' * 64
    with pytest.raises(RepositoryError, match='source bytes'), opened(installed, raw=private._encode(wrong)):
        pytest.fail('a substituted source pin was accepted')


@pytest.mark.parametrize('problem', ['missing', 'copied', 'hardlink', 'wal_symlink', 'wrong_journal', 'wrong_schema'])
def test_unavailable_or_substituted_existing_database_holds(installed, problem):
    coordinator, evidence, frozen = installed
    enroll(installed)
    raw = selection_bytes(coordinator.path, evidence, frozen)
    path = coordinator.path
    if problem == 'missing':
        path.rename(path.with_name('removed.sqlite3'))
    elif problem == 'copied':
        replacement = path.with_name('replacement.sqlite3')
        shutil.copy2(path, replacement)
        replacement.replace(path)
    elif problem == 'hardlink':
        os.link(path, path.with_name('extra-link'))
    elif problem == 'wal_symlink':
        fake = path.with_name(path.name + '-wal')
        fake.symlink_to(path)
    else:
        with coordinator.connect() as db:
            if problem == 'wrong_journal':
                assert db.execute('PRAGMA journal_mode=DELETE').fetchone() == ('delete',)
            else:
                db.execute(f'ALTER TABLE main.{authority._TABLE} ADD COLUMN alternate TEXT')
    with pytest.raises(RepositoryError):
        with opened(installed, raw=raw) as store:
            transact(installed, store)
    if problem == 'missing':
        assert not path.exists()


def test_absorbing_state_and_callback_rollback(installed):
    enroll(installed)
    _, _, frozen = installed
    start = frozen['deadline_unix_ms'] - 60_000
    window = slots.IssuanceWindow(slots._boot_id(), start, 0, 60_000_000_000)
    spend = slots.IssuanceAdmissionState(window, '3' * 64)
    ok = replace(spend, commit_sha256='4' * 64)
    expired = replace(ok, expired=True)
    with opened(installed) as store:
        with pytest.raises(RepositoryError, match='requires its one'):
            transact(installed, store, lambda previous: ok)
        assert transact(installed, store) == slots.IssuanceAdmissionState()
        assert transact(installed, store, lambda previous: spend) == spend
        for change in (slots.IssuanceAdmissionState(), replace(spend, reservation_sha256='5' * 64)):
            with pytest.raises(RepositoryError, match='cannot change'):
                transact(installed, store, lambda previous: change)
        with pytest.raises(RepositoryError, match='Invalid retained issuance window'):
            transact(installed, store, lambda previous: replace(previous, window=replace(window, deadline_elapsed_ns=1)))

        def fail(previous):
            raise RepositoryError('The authority callback failed.')

        with pytest.raises(RepositoryError, match='callback failed'):
            transact(installed, store, fail)
        assert transact(installed, store) == spend
        assert transact(installed, store, lambda previous: ok) == ok
        with pytest.raises(RepositoryError, match='requires its one'):
            transact(installed, store, lambda previous: replace(previous, commit_sha256='5' * 64))
        assert transact(installed, store, lambda previous: expired) == expired
        with pytest.raises(RepositoryError, match='terminal'):
            transact(installed, store, lambda previous: ok)
        assert transact(installed, store) == expired


def test_wrong_source_after_selection_and_noncanonical_binding_hold(installed, tmp_path, monkeypatch):
    coordinator, evidence, frozen = installed
    raw = selection_bytes(coordinator.path, evidence, frozen)
    copy = tmp_path / 'coordinator_store_review.py'
    copy.write_bytes(authority._SOURCE_FILES['coordinator_store'].read_bytes())
    with monkeypatch.context() as patch:
        patch.setitem(authority._SOURCE_FILES, 'coordinator_store', copy)
        with opened(installed, raw=raw):
            pass
        copy.write_bytes(copy.read_bytes() + b'\n')
        with pytest.raises(RepositoryError, match='source bytes'), opened(installed, raw=raw):
            pytest.fail('changed measured file was accepted')

    malformed = private._encode(frozen) + b'\n'
    selected = selection_bytes(coordinator.path, evidence, frozen, binding_sha256=sha256(malformed).hexdigest())
    with opened(installed, raw=selected) as store:
        store.migrate()
        with pytest.raises(RepositoryError):
            store.enroll_prevalidated(malformed)


def test_busy_existing_writer_preserves_unchanged_retained_state(installed):
    enroll(installed)
    coordinator, _, _ = installed
    with opened(installed) as store:
        with coordinator.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            with pytest.raises(RepositoryError, match='authority is unavailable'):
                transact(installed, store, lambda state: replace(state, expired=True))
        assert transact(installed, store) == slots.IssuanceAdmissionState()


def test_custody_drift_during_callback_rolls_back_transition(installed):
    enroll(installed)
    _, evidence, _ = installed
    parked = evidence.with_name('parked-evidence')
    with opened(installed) as store:
        def replace_root(state):
            evidence.rename(parked)
            evidence.mkdir(mode=0o700)
            return replace(state, expired=True)

        try:
            with pytest.raises(RepositoryError, match='directory changed'):
                transact(installed, store, replace_root)
        finally:
            evidence.rmdir()
            parked.rename(evidence)
    with opened(installed) as store:
        assert transact(installed, store) == slots.IssuanceAdmissionState()


def test_sqlite_serializes_competing_spends(installed):
    enroll(installed)
    _, _, frozen = installed
    start = frozen['deadline_unix_ms'] - 60_000
    window = slots.IssuanceWindow(slots._boot_id(), start, 0, 60_000_000_000)
    ready = Barrier(6)

    def spend(index):
        value = slots.IssuanceAdmissionState(window, f'{index:064x}')
        with opened(installed) as store:
            ready.wait(timeout=10)

            def claim(previous):
                if previous.window is not None:
                    raise RepositoryError('Already spent.')
                return value

            try:
                return transact(installed, store, claim)
            except RepositoryError as error:
                assert str(error) == 'Already spent.'
                return None

    with ThreadPoolExecutor(max_workers=6) as workers:
        checks = list(workers.map(spend, range(1, 7)))
    winner, = (record for record in checks if record is not None)
    with opened(installed) as store:
        assert transact(installed, store) == winner


_CHILD = '''
import json
import os
from pathlib import Path
import sys
import time
from hashlib import sha256
from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper.repository import RepositoryError
import coordinator_issuance_admission as authority

raw, phase = json.loads(sys.argv[1])
raw = raw.encode()
selection = json.loads(raw)
frozen = json.loads(sys.argv[2])
root = Path(selection['evidence_root'])
dispatch, binding = selection['dispatch_sha256'], selection['binding_sha256']
with authority._open_issuance_store(raw, approved_selection_sha256=sha256(raw).hexdigest()) as store:
    if phase == 'compete':
        gate = Path(sys.argv[3])
        index = int(sys.argv[4])
        gate.with_name(f'ready-{index}').touch()
        limit = time.monotonic() + 5
        while not gate.exists() and time.monotonic() < limit:
            time.sleep(0.01)
        assert gate.exists()
        start = frozen['deadline_unix_ms'] - 60_000
        window = slots.IssuanceWindow(slots._boot_id(), start, 0, 60_000_000_000)
        proposed = slots.IssuanceAdmissionState(window, f'{index:064x}')
        def claim(previous):
            return previous if previous.reservation_sha256 else proposed

        state = store.admission().transact(dispatch, binding, selection['evidence_root_identity'], claim)
        print(state.reservation_sha256)
        sys.exit(0)
    if phase in ('precommit', 'postcommit'):
        check = store._check_connection
        at_boundary = 2 if phase == 'precommit' else 3
        calls = 0

        def cut(handle):
            global calls
            calls += 1
            check(handle)
            if calls == at_boundary:
                os._exit(31)

        store._check_connection = cut
        def spend_for_fixture(previous):
            # The parent fixture configured a deadline of now+60 seconds.
            start = frozen['deadline_unix_ms'] - 60_000
            window = slots.IssuanceWindow(slots._boot_id(), start, 0, 60_000_000_000)
            return slots.IssuanceAdmissionState(window, '6' * 64)

        store.admission().transact(dispatch, binding, selection['evidence_root_identity'], spend_for_fixture)
    else:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        admission = store.admission()
        if phase in ('before_confirmation', 'after_confirmation'):
            apply = admission.transact

            def confirmation_cut(dispatch, binding, identity, transition):
                def cut(current):
                    updated = transition(current)
                    if phase == 'before_confirmation' and not current.commit_sha256 and updated.commit_sha256:
                        os._exit(31)
                    return updated

                state = apply(dispatch, binding, identity, cut)
                if phase == 'after_confirmation' and state.commit_sha256:
                    os._exit(31)
                return state

            admission.transact = confirmation_cut
        with slots.open_issuance_slots(root, descriptor, expected_owner_identity=selection['evidence_root_identity'],
                                       reviewed_tools_sha256=frozen['reviewed_tools_sha256'],
                                       admission=admission) as owned:
            try:
                if phase == 'refuse_resume':
                    owned.read_result(frozen)
                else:
                    with owned.reserve(frozen) as ticket:
                        if phase == 'work_death':
                            os._exit(31)
                        ticket.commit(frozen, json.loads(sys.argv[3]))
            except RepositoryError:
                if phase == 'refuse_resume':
                    try:
                        with owned.reserve(frozen):
                            sys.exit(68)
                    except RepositoryError:
                        sys.exit(31)
sys.exit(66)
'''


def subprocess_check(installed, action):
    coordinator, evidence, frozen = installed
    raw = selection_bytes(coordinator.path, evidence, frozen).decode()
    completed = subprocess.run([sys.executable, '-B', '-c', _CHILD, json.dumps([raw, action]),
                                json.dumps(frozen), json.dumps(_EVIDENCE)],
                               capture_output=True, text=True, timeout=15)
    assert completed.returncode == 31, (completed.stdout, completed.stderr)


def test_independent_processes_observe_one_sqlite_spend(installed, tmp_path):
    enroll(installed)
    coordinator, evidence, frozen = installed
    raw = selection_bytes(coordinator.path, evidence, frozen).decode()
    gate = tmp_path / 'start-contenders'
    contenders = []
    try:
        for index in range(1, 5):
            contenders.append(subprocess.Popen(
                [sys.executable, '-B', '-c', _CHILD, json.dumps([raw, 'compete']),
                 json.dumps(frozen), str(gate), str(index)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        limit = time.monotonic() + 5
        while len(list(tmp_path.glob('ready-*'))) < len(contenders) and time.monotonic() < limit:
            time.sleep(0.01)
        assert len(list(tmp_path.glob('ready-*'))) == len(contenders)
        gate.touch()
        observations = []
        for child in contenders:
            output, error = child.communicate(timeout=8)
            assert child.returncode == 0, error
            observations.append(output.strip())
    finally:
        for child in contenders:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
    winner, = set(observations)
    assert winner in {f'{index:064x}' for index in range(1, 5)}
    with opened(installed) as store:
        assert transact(installed, store).reservation_sha256 == winner


@pytest.mark.parametrize('phase', ['precommit', 'postcommit'])
def test_sqlite_process_death_at_exact_commit_boundary(installed, phase):
    enroll(installed)
    subprocess_check(installed, phase)
    with opened(installed) as store:
        state = transact(installed, store)
    assert state.reservation_sha256 == ('6' * 64 if phase == 'postcommit' else None)
    assert state.commit_sha256 is None and not state.expired


@pytest.mark.parametrize('phase', ['before_confirmation', 'after_confirmation'])
def test_slot_process_death_at_independent_confirmation(installed, phase):
    enroll(installed)
    subprocess_check(installed, phase)
    _, evidence, frozen = installed
    assert (evidence / (frozen['dispatch_sha256'] + '.commit.json')).is_file()
    with opened(installed) as store, channel(installed, store) as owned:
        state = transact(installed, store)
        assert state.reservation_sha256 and bool(state.commit_sha256) == (phase == 'after_confirmation')
        if phase == 'after_confirmation':
            assert owned.read_result(frozen)['evidence'] == _EVIDENCE
        else:
            with pytest.raises(RepositoryError, match='lacks exact independent confirmation'):
                owned.read_result(frozen)
        with pytest.raises(RepositoryError, match='already reserved'):
            with owned.reserve(frozen):
                pytest.fail('independent confirmation interruption reopened its spent allowance')


def test_process_death_and_complete_evidence_root_rollback_cannot_reissue(installed):
    enroll(installed)
    subprocess_check(installed, 'work_death')
    _, evidence, _ = installed
    moved = evidence.with_name('old-evidence')
    moved.mkdir(mode=0o700)
    was = identity(evidence)
    for entry in evidence.iterdir():
        entry.rename(moved / entry.name)
    assert identity(evidence) == was and not list(evidence.iterdir())
    subprocess_check(installed, 'refuse_resume')
    with opened(installed) as store:
        state = transact(installed, store)
    assert state.reservation_sha256 and state.commit_sha256 is None
