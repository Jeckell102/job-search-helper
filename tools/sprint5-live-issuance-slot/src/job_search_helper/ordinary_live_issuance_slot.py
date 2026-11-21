"""One private evidence attempt for an exact, already published ordinary dispatch.

The application owner supplies the measured binding again at commit and readback.
This channel preserves that binding and the evidence digests. Dispatch attestation,
evidence validation, and verdict approval belong to the application owner.

The retained authority advances from enrolled to spent to confirmed. Expiry can
latch at any stage and preserves the spend and confirmation already recorded.
Handoff freshness is decided in a final serialized authority transaction after
custody checks and descriptor cleanup. That decision checks the exact retained
record and samples the boot, wall and elapsed clocks. Later use revalidates.
"""

from abc import ABC, abstractmethod
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
import fcntl
import os
from pathlib import Path
from threading import Lock
import time
from typing import NamedTuple
from uuid import UUID, uuid4

from . import ordinary_raw_capture as private
from .repository import RepositoryError


_BINDING_DIGESTS = {
    'dispatch_sha256', 'publication_sha256', 'verifier_input_sha256',
    'raw_capture_manifest_sha256', 'raw_response_sha256', 'inventory_sha256',
    'runtime_binding_sha256', 'company_projection_sha256', 'company_source_revision',
    'control_projection_sha256', 'control_source_revision', 'reviewed_tools_sha256',
    'collector_policy_sha256', 'worker_source_sha256', 'measurement_tool_sha256',
}
_CANDIDATE_DIGESTS = {'source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256'}
_LIMITS = {'live_request_limit': 128, 'replay_request_limit': 128, 'capsule_bytes_limit': 64 * 1024 * 1024}
_MAX_DURATION_MS = 120_000
_EVIDENCE_DIGESTS = {
    'live_capture_sha256', 'candidate_validation_sha256', 'authority_extraction_digest',
    'candidate_inventory_digest', 'regression_inventory_digest',
}
_RESERVATION = 'ordinary-live-issuance-reservation-v2'
_ANCHOR = 'ordinary-live-issuance-owner-v1'
_RESULT = 'ordinary-live-issuance-result-v1'
_COMMIT = 'ordinary-live-issuance-commit-v1'


class _ReservationStamp(NamedTuple):
    reservation: tuple
    anchor: tuple
    window: 'IssuanceWindow'


class _ResultReadback(NamedTuple):
    result: dict
    commit_sha256: str
    result_stamp: tuple
    commit_stamp: tuple
    slot_stamp: tuple


@dataclass(frozen=True)
class IssuanceWindow:
    boot_id: str
    started_unix_ms: int
    started_elapsed_ns: int
    deadline_elapsed_ns: int


@dataclass(frozen=True)
class IssuanceAdmissionState:
    window: IssuanceWindow | None = None
    reservation_sha256: str | None = None
    commit_sha256: str | None = None
    expired: bool = False


class IssuanceAdmission(ABC):
    """An enrolled authority that survives rollback of the separate evidence root."""

    @abstractmethod
    def transact(self, dispatch_sha256, binding_sha256, root_identity, transition):
        """Atomically apply a transition to one independently enrolled dispatch.

        Require exact preexisting enrollment of all three keys. Supply the current
        IssuanceAdmissionState to transition under the owner's serial transaction,
        durably persist its returned state, and return it only after commit. A
        missing, changed, or unavailable authority must raise RepositoryError.
        The evidence channel has no enrollment, reset, or deletion operation.
        """


def _require(condition, reason):
    if not condition:
        raise RepositoryError(reason)


@contextmanager
def _private_files():
    try:
        yield
    except (OSError, private.CaptureError):
        raise RepositoryError('The live issuance slot custody is unavailable or changed.') from None


def _read(directory, name):
    raw, identity, stamp = private._read_file(directory, name, private._METADATA_LIMIT)
    return private._decode(raw), identity, stamp, private._hash(raw)


def _present(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _publish(directory, name, content):
    staging = '.issuance-record-' + uuid4().hex
    remove_staging = True
    try:
        stamp = private._write_file(directory, staging, content)
        private._named_file(directory, staging, stamp)
        # This helper uses renameat2(RENAME_NOREPLACE) for files as well as directories.
        private._publish_directory(directory, staging, name)
    except FileExistsError:
        remove_staging = False
        raise
    finally:
        if remove_staging:
            try:
                os.unlink(staging, dir_fd=directory)
            except FileNotFoundError:
                pass


@contextmanager
def _reservation_lock(slot, mode):
    name = 'reservation.json'
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=slot)
    try:
        stamp = private._stamp(private._file(os.fstat(descriptor)))
        try:
            fcntl.flock(descriptor, mode | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
        else:
            private._named_file(slot, name, stamp)
            yield stamp
    finally:
        os.close(descriptor)


def _now_ms():
    return time.time_ns() // 1_000_000


def _boot_id():
    try:
        with open('/proc/sys/kernel/random/boot_id', encoding='ascii') as stream:
            return str(UUID(stream.read(64).strip()))
    except (OSError, ValueError):
        raise RepositoryError('The boot identity for live issuance is unavailable.') from None


def _elapsed_ns():
    return time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def _fresh(window, deadline, completed_ms=None):
    if window is None:
        return _now_ms() < deadline
    earliest = window.started_unix_ms if completed_ms is None else completed_ms
    return (_boot_id() == window.boot_id and earliest <= _now_ms() < deadline
            and window.started_elapsed_ns <= _elapsed_ns() < window.deadline_elapsed_ns)


def _digest(value):
    return private._hash(private._encode(value))


def _reservation_digest(frozen):
    return _digest({'reservation': frozen.reservation, 'anchor': frozen.anchor, 'window': asdict(frozen.window)})


def _commit_record(dispatch, identity, frozen, slot_stamp, result_stamp, result_sha):
    return {'schema': _COMMIT, 'commit_identity': identity, 'dispatch_sha256': dispatch,
            'reservation_stamp': list(frozen.reservation), 'anchor_stamp': list(frozen.anchor),
            'slot_stamp': list(slot_stamp), 'result_stamp': list(result_stamp), 'result_sha256': result_sha}


class _IssuanceSlots:
    def __init__(self, path, directory, identity, reviewed_tools_sha256, admission):
        self._path = path
        self._directory = directory
        self._identity = identity
        self._reviewed_tools = reviewed_tools_sha256
        self._admission = admission

    def _check_root(self):
        _require(private._directory(os.fstat(self._directory)) == self._identity
                 and private._named_path_identity(self._path) == self._identity,
                 'The configured live issuance directory changed.')

    def _binding(self, binding):
        fields = _BINDING_DIGESTS | _LIMITS.keys() | {'candidate', 'deadline_unix_ms'}
        _require(isinstance(binding, dict) and set(binding) == fields,
                 'The live issuance binding must contain the exact reviewed fields.')
        binding = dict(binding)
        candidate = binding['candidate']
        _require(isinstance(candidate, dict) and set(candidate) == _CANDIDATE_DIGESTS,
                 'The live issuance candidate vector is incomplete.')
        binding['candidate'] = dict(candidate)
        _require(all(private._is_digest(binding[key]) for key in _BINDING_DIGESTS)
                 and all(private._is_digest(value) for value in binding['candidate'].values())
                 and binding['reviewed_tools_sha256'] == self._reviewed_tools
                 and type(binding['deadline_unix_ms']) is int
                 and 0 < binding['deadline_unix_ms'] < 2**63
                 and all(type(binding[key]) is int and 0 < binding[key] <= cap for key, cap in _LIMITS.items()),
                 'The live issuance pins or budget are invalid.')
        return binding

    def _admitted(self, binding, *, reservation=None, confirm=None, completed_ms=None, observed_expiry=False):
        dispatch = binding['dispatch_sha256']
        binding_sha = _digest(binding)
        identity = tuple(self._identity)
        deadline = binding['deadline_unix_ms']

        def transition(state):
            _require(type(state) is IssuanceAdmissionState, 'The live issuance admission record is invalid.')
            if state.expired:
                return state
            if reservation is not None:
                _require(state == IssuanceAdmissionState(),
                         'This live issuance dispatch already reserved its work allowance.')
                state = IssuanceAdmissionState(reservation.window, _reservation_digest(reservation))
            if observed_expiry or not _fresh(state.window, deadline, completed_ms):
                return replace(state, expired=True)
            if confirm is not None:
                frozen, commit_sha = confirm
                self._check_reservation(state, frozen)
                _require(state.commit_sha256 is None, 'The live issuance commit was already confirmed.')
                return replace(state, commit_sha256=commit_sha)
            return state

        state = self._admission.transact(dispatch, binding_sha, identity, transition)
        _require(type(state) is IssuanceAdmissionState, 'The live issuance admission record is unavailable.')
        _require(not observed_expiry or state.expired,
                 'The live issuance expiry did not read back from its admission authority.')
        if not state.expired and not _fresh(state.window, deadline, completed_ms):
            # An independent commit may finish after its transaction's clock read.
            def expire(current):
                _require(state.window is None or (current.window == state.window
                         and current.reservation_sha256 == state.reservation_sha256),
                         'The live issuance admission changed during expiry confirmation.')
                return replace(current, expired=True)

            state = self._admission.transact(dispatch, binding_sha, identity, expire)
            _require(type(state) is IssuanceAdmissionState and state.expired,
                     'The live issuance expiry did not read back from its admission authority.')
        _require(not state.expired, 'The live issuance work allowance expired and its evidence is stale.')
        return state

    def _require_fresh_handoff(self, binding, frozen, *, saved=None):
        expected = IssuanceAdmissionState(frozen.window, _reservation_digest(frozen),
                                          commit_sha256=saved.commit_sha256 if saved else None)
        completed_ms = saved.result['completed_unix_ms'] if saved else None

        def decide(state):
            _require(type(state) is IssuanceAdmissionState, 'The live issuance admission record is invalid.')
            if state.expired:
                return state
            _require(state == expected, 'The live issuance admission changed before handoff.')
            if not _fresh(state.window, binding['deadline_unix_ms'], completed_ms):
                return replace(state, expired=True)
            return state

        with _private_files():
            state = self._admission.transact(binding['dispatch_sha256'], _digest(binding), tuple(self._identity), decide)
        _require(type(state) is IssuanceAdmissionState, 'The live issuance admission record is unavailable.')
        _require(not state.expired, 'The live issuance work allowance expired and its evidence is stale.')
        _require(state == expected, 'The live issuance admission changed before handoff.')

    def _new_window(self, binding):
        boot, started, elapsed = _boot_id(), _now_ms(), _elapsed_ns()
        duration = binding['deadline_unix_ms'] - started
        if duration <= 0:
            self._admitted(binding, observed_expiry=True)
        _require(0 < duration <= _MAX_DURATION_MS, 'The live issuance deadline is out of bounds.')
        return IssuanceWindow(boot, started, elapsed, elapsed + duration * 1_000_000)

    @staticmethod
    def _check_reservation(state, frozen):
        _require(state.window == frozen.window and state.reservation_sha256 == _reservation_digest(frozen),
                 'The live issuance slot differs from its independent reservation.')

    def _stamp_slot(self, slot, binding):
        self._check_root()
        dispatch = binding['dispatch_sha256']
        slot_identity = private._check_dir(self._directory, dispatch, slot)
        record, _, reservation_stamp, _ = _read(slot, 'reservation.json')
        anchor_name = dispatch + '.reservation.json'
        anchor, anchor_identity, anchor_stamp, _ = _read(self._directory, anchor_name)
        window_data = record.get('window')
        try:
            window = IssuanceWindow(**window_data)
        except TypeError:
            raise RepositoryError('The live issuance slot has no exact boot-scoped window.') from None
        _require(type(window.started_unix_ms) is int and type(window.started_elapsed_ns) is int
                 and type(window.deadline_elapsed_ns) is int and window.started_elapsed_ns >= 0
                 and isinstance(window.boot_id, str)
                 and 0 < binding['deadline_unix_ms'] - window.started_unix_ms <= _MAX_DURATION_MS
                 and window.deadline_elapsed_ns == window.started_elapsed_ns
                 + (binding['deadline_unix_ms'] - window.started_unix_ms) * 1_000_000
                 and record == {'schema': _RESERVATION, 'binding': binding, 'root_identity': self._identity,
                                'slot_identity': slot_identity, 'window': asdict(window)}
                 and anchor == {'schema': _ANCHOR, 'anchor_identity': anchor_identity,
                                'dispatch_sha256': dispatch, 'reservation_stamp': list(reservation_stamp)},
                 'The reserved live issuance binding or physical slot changed.')
        private._named_file(slot, 'reservation.json', reservation_stamp)
        private._named_file(self._directory, anchor_name, anchor_stamp)
        _require(private._check_dir(self._directory, dispatch, slot) == slot_identity,
                 'The live issuance slot was replaced.')
        self._check_root()
        return _ReservationStamp(reservation_stamp, anchor_stamp, window)

    @contextmanager
    def reserve(self, binding):
        """Durably consume this dispatch's single work allowance before yielding."""
        binding = self._binding(binding)
        dispatch = binding['dispatch_sha256']
        anchor_name = dispatch + '.reservation.json'
        commit_name = dispatch + '.commit.json'
        staging = '.issuance-slot-' + uuid4().hex
        with ExitStack() as resources:
            with _private_files():
                self._check_root()
                _require(self._admitted(binding) == IssuanceAdmissionState()
                         and not any(_present(self._directory, name) for name in (dispatch, anchor_name, commit_name)),
                         'This live issuance dispatch already reserved its work allowance.')
                window = self._new_window(binding)
                os.mkdir(staging, 0o700, dir_fd=self._directory)
                slot = resources.enter_context(private._opened_dir(self._directory, staging))
                try:
                    slot_identity = private._check_dir(self._directory, staging, slot)
                    record = {'schema': _RESERVATION, 'binding': binding, 'root_identity': self._identity,
                              'slot_identity': slot_identity, 'window': asdict(window)}
                    stamp = private._write_file(slot, 'reservation.json', private._encode(record))
                    locked = resources.enter_context(_reservation_lock(slot, fcntl.LOCK_EX))
                    _require(stamp == locked, 'The live issuance reservation could not be locked.')
                    os.fsync(slot)
                    self._check_root()
                    private._check_dir(self._directory, staging, slot)
                    private._named_file(slot, 'reservation.json', stamp)
                    private._publish_directory(self._directory, staging, dispatch)
                    _publish(self._directory, anchor_name, lambda identity: private._encode({
                        'schema': _ANCHOR, 'anchor_identity': identity, 'dispatch_sha256': dispatch,
                        'reservation_stamp': list(stamp),
                    }))
                    frozen = self._stamp_slot(slot, binding)
                    self._check_reservation(self._admitted(binding, reservation=frozen), frozen)
                finally:
                    # A named slot always survives failure. Remove only our unpublished staging directory.
                    if _present(self._directory, staging):
                        private._check_dir(self._directory, staging, slot)
                        if _present(slot, 'reservation.json'):
                            os.unlink('reservation.json', dir_fd=slot)
                        os.rmdir(staging, dir_fd=self._directory)
                self._check_reservation(self._admitted(binding), frozen)
                _require(self._stamp_slot(slot, binding) == frozen, 'The live issuance reservation changed.')
            attempt = _Attempt(self, slot, binding, frozen)
            try:
                self._require_fresh_handoff(binding, frozen)
                yield attempt
            finally:
                attempt._close()

    def _read_result(self, slot, binding, frozen):
        dispatch = binding['dispatch_sha256']
        commit_name = dispatch + '.commit.json'
        if not _present(self._directory, commit_name):
            _require(not _present(slot, 'result.json'),
                     'This live issuance result has no durable commit record.')
            return None
        result, _, result_stamp, result_sha = _read(slot, 'result.json')
        commit, identity, commit_stamp, commit_sha = _read(self._directory, commit_name)
        settled = result.get('completed_unix_ms')
        slot_stamp = private._stamp(os.fstat(slot))
        _require(set(result) == {'schema', 'binding_sha256', 'completed_unix_ms', 'evidence'}
                 and result['schema'] == _RESULT
                 and result['binding_sha256'] == _digest(binding)
                 and type(settled) is int and frozen.window.started_unix_ms <= settled < binding['deadline_unix_ms']
                 and commit == _commit_record(dispatch, identity, frozen, slot_stamp, result_stamp, result_sha),
                 'The committed live issuance result does not match its reservation.')
        _checked_evidence(result['evidence'])
        # The first writer could have exited between publishing this name and fsync.
        os.fsync(self._directory)
        proof = _digest({'commit_sha256': commit_sha, 'commit_stamp': commit_stamp})
        saved = _ResultReadback(result, proof, result_stamp, commit_stamp, slot_stamp)
        self._check_result_custody(slot, binding, frozen, saved)
        return saved

    def _check_result_custody(self, slot, binding, frozen, saved):
        private._named_file(slot, 'result.json', saved.result_stamp)
        private._named_file(self._directory, binding['dispatch_sha256'] + '.commit.json', saved.commit_stamp)
        _require(self._stamp_slot(slot, binding) == frozen and private._stamp(os.fstat(slot)) == saved.slot_stamp,
                 'The live issuance reservation changed.')

    def read_result(self, binding):
        """Return only an exact committed evidence record for a fresh owner binding."""
        binding = self._binding(binding)
        dispatch = binding['dispatch_sha256']
        with _private_files():
            self._check_root()
            admission = self._admitted(binding)
            if not _present(self._directory, dispatch):
                _require(admission == IssuanceAdmissionState()
                         and not any(_present(self._directory, dispatch + suffix)
                                 for suffix in ('.reservation.json', '.commit.json')),
                         'The reserved live issuance slot is missing.')
                return None
            with private._opened_dir(self._directory, dispatch) as slot:
                with _reservation_lock(slot, fcntl.LOCK_SH) as stamp:
                    if stamp is None:
                        return None
                    frozen = self._stamp_slot(slot, binding)
                    _require(stamp == frozen.reservation, 'The live issuance reservation lock changed.')
                    self._check_reservation(self._admitted(binding), frozen)
                    saved = self._confirmed_result(slot, binding, frozen)
        if saved is None:
            return None
        self._require_fresh_handoff(binding, frozen, saved=saved)
        return saved.result

    def _confirmed_result(self, slot, binding, frozen):
        saved = self._read_result(slot, binding, frozen)
        admission = self._admitted(binding, completed_ms=saved.result['completed_unix_ms'] if saved else None)
        self._check_reservation(admission, frozen)
        if saved is None:
            _require(admission.commit_sha256 is None, 'The independently confirmed live issuance result is missing.')
            return None
        _require(admission.commit_sha256 == saved.commit_sha256,
                 'The live issuance result lacks exact independent confirmation.')
        self._check_result_custody(slot, binding, frozen, saved)
        return saved


def _checked_evidence(value):
    _require(isinstance(value, dict), 'The retained live issuance evidence must be a closed digest record.')
    evidence = dict(value)
    _require(set(evidence) == _EVIDENCE_DIGESTS and all(private._is_digest(pin) for pin in evidence.values()),
             'The retained live issuance evidence must be a closed digest record.')
    return evidence


class _Attempt:
    def __init__(self, owner, directory, binding, frozen):
        self._owner = owner
        self._directory = directory
        self._binding = binding
        self._frozen = frozen
        self._active = True
        self._lock = Lock()

    def _close(self):
        with self._lock:
            self._active = False

    def commit(self, current_binding, evidence):
        """Commit checked evidence after the application owner rereads its input pins."""
        with self._lock, _private_files():
            _require(self._active, 'The live issuance reservation is no longer active.')
            self._active = False
            owner, slot, binding = self._owner, self._directory, self._binding
            _require(owner._binding(current_binding) == binding and owner._stamp_slot(slot, binding) == self._frozen,
                     'The live issuance inputs changed before commit.')
            owner._check_reservation(owner._admitted(binding), self._frozen)
            evidence = _checked_evidence(evidence)
            dispatch = binding['dispatch_sha256']
            commit_name = dispatch + '.commit.json'
            _require(not _present(slot, 'result.json') and not _present(owner._directory, commit_name),
                     'The live issuance attempt already has a result.')
            result = {'schema': _RESULT, 'binding_sha256': _digest(binding),
                      'completed_unix_ms': _now_ms(), 'evidence': evidence}
            _publish(slot, 'result.json', private._encode(result))
            saved, _, result_stamp, result_sha = _read(slot, 'result.json')
            _require(saved == result and owner._stamp_slot(slot, binding) == self._frozen,
                     'The saved live issuance result or reservation changed before commit.')
            owner._check_reservation(owner._admitted(binding), self._frozen)
            slot_stamp = private._stamp(os.fstat(slot))
            _publish(owner._directory, commit_name, lambda identity: private._encode(
                _commit_record(dispatch, identity, self._frozen, slot_stamp, result_stamp, result_sha)))
            saved = owner._read_result(slot, binding, self._frozen)
            _require(saved is not None and saved.result == result, 'The committed live issuance result is unavailable.')
            owner._admitted(binding, confirm=(self._frozen, saved.commit_sha256),
                            completed_ms=result['completed_unix_ms'])
            settled = owner._confirmed_result(slot, binding, self._frozen)
            _require(settled is not None and settled.result == result,
                     'The confirmed live issuance result is unavailable.')
        owner._require_fresh_handoff(binding, self._frozen, saved=settled)
        return settled.result


@contextmanager
def open_issuance_slots(path, descriptor, *, expected_owner_identity, reviewed_tools_sha256, admission):
    """Open a launcher-selected private evidence directory with independent owner and tools pins."""
    path = Path(path)
    _require(path.is_absolute() and path != Path('/') and '..' not in path.parts
             and isinstance(expected_owner_identity, (tuple, list)) and len(expected_owner_identity) == 2
             and all(type(part) is int and part > 0 for part in expected_owner_identity)
             and private._is_digest(reviewed_tools_sha256) and isinstance(admission, IssuanceAdmission),
             'A configured live issuance owner and tools pin are required.')
    with _private_files():
        directory = os.dup(descriptor)
    slots = _IssuanceSlots(path, directory, list(expected_owner_identity), reviewed_tools_sha256, admission)
    try:
        with _private_files():
            slots._check_root()
        yield slots
    finally:
        slots._directory = -1
        os.close(directory)
