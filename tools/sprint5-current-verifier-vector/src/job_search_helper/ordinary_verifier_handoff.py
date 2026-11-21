"""Bind one published scrape to the independently reviewed offline verifier."""

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import os
from pathlib import Path
import re
import shutil
import time
from uuid import uuid4

from . import ordinary_raw_capture as private
from . import ordinary_verification_pending as pending
from .engine import Engine
from .ordinary_verification_outcome import existing_outcome
from .ordinary_verification_publication import _require_owned_leases
from .ordinary_verification_publisher import read_captured_ordinary_response
from .ordinary_verification_terminal import _published_marker
from .repository import RepositoryError


_MODE = 'offline_saved_captures'
_MANIFEST = 'ordinary-verifier-offline-work-v1'
_VERIFIER = 'ae39cb34ab229eee22b66f34dbe2d1486d2f08f0e1de0acc43970a8d15bbff14'
_TOOLS = '86723e7fdc0e4e8acdae2dbdc9516c93f0e4557c60ef3b75d17f20869bd3eac0'
_META_LIMIT = 16 * 1024
_CORPUS_LIMIT = 64 * 1024 * 1024
_VECTOR_FIELDS = {'source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256'}
_TERMINAL = {'VERIFIED_MISMATCH', 'HOLD', 'TIMEOUT', 'BUDGET_EXHAUSTED', 'CHANGED_INPUT'}


def _require(condition, reason):
    if not condition:
        raise RepositoryError(reason)


def _sha(raw):
    return sha256(raw).hexdigest()


def _object(raw):
    return private._decode(raw)


def _read(directory, name, limit=_META_LIMIT):
    return private._read_file(directory, name, limit)[0]


def _optional(directory, name):
    try:
        return _read(directory, name)
    except FileNotFoundError:
        return None


@contextmanager
def _settled_receipt(slot):
    """Read a finished private attempt without waiting on the verifier."""
    name = 'verifier.lock'
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=slot)
    except FileNotFoundError:
        _require(_optional(slot, 'reservation.json') is None and _optional(slot, 'receipt.json') is None,
                 'The offline verifier records have no private supervisor lease.')
        yield False
        return
    try:
        stamp = private._stamp(private._file(os.fstat(descriptor)))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        private._named_file(slot, name, stamp)
        yield True
        private._named_file(slot, name, stamp)
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class OfflineWork:
    """Exact local input pins and the assigned physical worker slot."""

    slot: Path
    pending_sha256: str
    job_sha256: str
    owner_slot: str


def _binding(stores, runtime, cycle_id, company_id, capture):
    _require_owned_leases(stores)
    cycle, original, marker, publication = _published_marker(stores, cycle_id, company_id)
    Engine.validate_cycle_runtime_binding(cycle, runtime)
    _require(existing_outcome(stores.jobs, marker['owner']) is None,
             'The enrolled scrape already has its immutable outcome.')
    _require(marker['observation'] is not None and publication['final_stage'] == 'partial',
             'Offline verification requires the archived typed mismatch.')
    captured = read_captured_ordinary_response(stores, cycle_id, company_id, capture)
    selected = {key: marker[key] for key in ('schema', 'owner', 'admission', 'observation')}
    _require(captured.dispatch_sha256 == marker['dispatch_sha256']
             and captured.inventory_sha256 == marker['inventory_sha256']
             and captured.response_sha256 == marker['observation']['response_sha256']
             and captured.response_sha256 == _sha(captured.body)
             and pending._read_cycle(stores.state, cycle_id)[1] == original,
             'The saved verifier input changed during exact readback.')
    return selected, captured, pending.digest(publication)


def _approved_pin(raw, expected, selected):
    _require(isinstance(raw, bytes) and 0 < len(raw) <= _META_LIMIT and _sha(raw) == expected,
             'The approved replay pin changed.')
    pin = _object(raw)
    owner, admission = selected['owner'], selected['admission']
    _require(set(pin) == {'schema', 'candidate', 'measurement_tool_sha256', 'capture_sha256', 'scope'}
             and pin['schema'] == 'company-candidate-validation-pin-v1'
             and isinstance(pin['candidate'], dict) and set(pin['candidate']) == _VECTOR_FIELDS
             and all(pending._is_digest(value) for value in (
                 *pin['candidate'].values(), pin['measurement_tool_sha256'], pin['capture_sha256']))
             and isinstance(pin['scope'], list) and len(pin['scope']) == 2
             and all(isinstance(item, dict) for item in pin['scope']),
             'The approved replay pin is malformed.')
    target, control = pin['scope']
    _require(owner['company_id'] == 'COMP-0066'
             and admission['authority_url'] == 'https://www.forterra.com/careers'
             and target.get('role') == 'target' and target.get('company_id') == owner['company_id']
             and target.get('authority_url') == admission['authority_url']
             and target.get('source_revision') == owner['source_revision']
             and target.get('company_row_sha256') == owner['company_source_sha256']
             and control.get('role') == 'regression'
             and control.get('board_url') == 'https://ats.rippling.com/pdwcareers/jobs',
             'The approved replay scope differs from the enrolled Company and control.')
    return pin


class _OwnerChannel:
    def __init__(self, root, descriptor, identity, approved_pin_sha256):
        self.root = root
        self.descriptor = descriptor
        self.identity = identity
        self.approved_pin_sha256 = approved_pin_sha256

    def _check_root(self):
        _require(private._directory(os.fstat(self.descriptor)) == self.identity
                 and private._named_path_identity(self.root) == self.identity,
                 'The configured verifier directory was replaced.')

    def _anchor(self, frozen):
        return private._encode({
            'schema': 'ordinary-verifier-offline-owner-v1',
            'dispatch_sha256': frozen['dispatch_sha256'],
            'slot_identity': frozen['slot_identity'],
            'owner_manifest_sha256': pending.digest(frozen),
        })

    def _publish_anchor(self, name, frozen, slot):
        # A committed bundle without a root record may have been interrupted
        # before launch. It can be reused only while no supervisor ever entered.
        for filename in ('verifier.lock', 'reservation.json', 'receipt.json'):
            try:
                os.stat(filename, dir_fd=slot, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise RepositoryError('An unanchored offline verifier slot has prior supervisor state.')
        temp = '.verifier-owner-' + uuid4().hex
        try:
            stamp = private._write_file(self.descriptor, temp, self._anchor(frozen))
            private._named_file(self.descriptor, temp, stamp)
            private._check_dir(self.descriptor, frozen['dispatch_sha256'], slot)
            self._check_root()
            # The no-replace rename works for regular files as well as directories.
            private._publish_directory(self.descriptor, temp, name)
        finally:
            try:
                os.unlink(temp, dir_fd=self.descriptor)
            except FileNotFoundError:
                pass

    def _freeze(self, selected, captured, publication_sha, pin, slot_identity, *, duration, deadline, limit):
        pending_bytes = private._encode(selected)
        job = {
            'schema': 'ordinary-rippling-owned-verification-job-v1',
            'pending_sha256': _sha(pending_bytes),
            'candidate_replay_pin_sha256': self.approved_pin_sha256,
            'mismatch_response_sha256': captured.response_sha256,
            'deadline_unix_ms': deadline,
            'request_limit': limit,
        }
        job_bytes = private._encode(job)
        identity = {
            'pending_sha256': job['pending_sha256'], 'job_sha256': _sha(job_bytes),
            'verifier_sha256': _VERIFIER, 'reviewed_tools_sha256': _TOOLS,
        }
        manifest = {
            'schema': _MANIFEST, 'mode': _MODE, 'identity': identity,
            'dispatch_sha256': captured.dispatch_sha256, 'publication_sha256': publication_sha,
            'raw_manifest_sha256': captured.manifest_sha256,
            'root_identity': self.identity, 'slot_identity': slot_identity,
            'replay_capture_sha256': pin['capture_sha256'], 'candidate_vector': pin['candidate'],
            'duration_seconds': duration, 'job': job,
        }
        return manifest, pending_bytes, job_bytes

    def _open_frozen(self, slot, selected, captured, publication_sha):
        name = captured.dispatch_sha256
        slot_id = private._check_dir(self.descriptor, name, slot)
        saved_raw = _read(slot, 'owner.json')
        saved = _object(saved_raw)
        replay_raw = _read(slot, 'replay-pin.json')
        pin = _approved_pin(replay_raw, self.approved_pin_sha256, selected)
        job = saved.get('job')
        duration = saved.get('duration_seconds')
        _require(isinstance(job, dict) and type(duration) is int and 0 < duration <= 120
                 and type(job.get('deadline_unix_ms')) is int and job['deadline_unix_ms'] > 0
                 and type(job.get('request_limit')) is int and 0 < job['request_limit'] <= 128,
                 'The saved offline verifier budget is malformed.')
        expected, pending_bytes, job_bytes = self._freeze(
            selected, captured, publication_sha, pin, slot_id, duration=duration,
            deadline=job['deadline_unix_ms'], limit=job['request_limit'],
        )
        _require(saved == expected and _read(slot, 'pending.json') == pending_bytes
                 and _read(slot, 'job.json') == job_bytes
                 and _read(slot, 'configured-response.html', private.MAX_CAPTURE_BYTES) == captured.body
                 and _sha(_read(slot, 'public-capture.json', _CORPUS_LIMIT)) == pin['capture_sha256']
                 and _read(slot, 'owner.json') == saved_raw,
                 'The saved offline verifier files differ from the enrolled input.')
        private._check_dir(self.descriptor, name, slot)
        self._check_root()
        return expected

    def stage(self, stores, runtime, cycle_id, company_id, capture, *,
              replay_pin, public_capture, duration_seconds=120, request_limit=128):
        """Commit one exact offline request before returning any launch pins."""
        self._check_root()
        selected, captured, publication = _binding(stores, runtime, cycle_id, company_id, capture)
        pin = _approved_pin(replay_pin, self.approved_pin_sha256, selected)
        _require(type(duration_seconds) is int and 0 < duration_seconds <= 120
                 and type(request_limit) is int and 0 < request_limit <= 128,
                 'Invalid offline verifier budget.')
        _require(isinstance(public_capture, bytes) and 0 < len(public_capture) <= _CORPUS_LIMIT
                 and _sha(public_capture) == pin['capture_sha256'],
                 'The approved replay corpus does not match its pin.')
        name = captured.dispatch_sha256
        anchor_name = name + '.json'
        anchor = _optional(self.descriptor, anchor_name)
        try:
            os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
        except FileNotFoundError:
            _require(anchor is None, 'The assigned offline verifier slot is missing and cannot be replaced.')
            temp = '.verifier-work-' + uuid4().hex
            os.mkdir(temp, mode=0o700, dir_fd=self.descriptor)
            try:
                with private._opened_dir(self.descriptor, temp) as slot:
                    manifest, pending_bytes, job_bytes = self._freeze(
                        selected, captured, publication, pin, private._directory(os.fstat(slot)),
                        duration=duration_seconds, deadline=time.time_ns() // 1_000_000 + duration_seconds * 1000,
                        limit=request_limit,
                    )
                    for filename, data in (
                        ('owner.json', private._encode(manifest)), ('pending.json', pending_bytes),
                        ('job.json', job_bytes), ('configured-response.html', captured.body),
                        ('replay-pin.json', replay_pin), ('public-capture.json', public_capture),
                    ):
                        private._write_file(slot, filename, data)
                    os.fsync(slot)
                    _require_owned_leases(stores)
                    self._check_root()
                    private._check_dir(self.descriptor, temp, slot)
                    private._publish_directory(self.descriptor, temp, name)
                    os.fsync(self.descriptor)
            finally:
                # Use the held descriptor even if the externally named root moved.
                temporary = Path(f'/proc/self/fd/{self.descriptor}') / temp
                if temporary.is_dir():
                    shutil.rmtree(temporary)
                    os.fsync(self.descriptor)
        with private._opened_dir(self.descriptor, name) as slot:
            frozen = self._open_frozen(slot, selected, captured, publication)
            if anchor is None:
                _require_owned_leases(stores)
                self._publish_anchor(anchor_name, frozen, slot)
            _require(_read(self.descriptor, anchor_name) == self._anchor(frozen),
                     'The owner record differs from the assigned offline verifier work.')
        _require(frozen['duration_seconds'] == duration_seconds
                 and frozen['job']['request_limit'] == request_limit,
                 'The original offline verifier budget cannot be replaced.')
        _require(_binding(stores, runtime, cycle_id, company_id, capture) == (selected, captured, publication),
                 'The enrolled scrape changed before returning verifier work.')
        owner_slot = ':'.join(str(value) for value in (
            *self.identity, *frozen['slot_identity'], pending.digest(frozen),
        ))
        return OfflineWork(self.root / name, frozen['identity']['pending_sha256'],
                           frozen['identity']['job_sha256'], owner_slot)

    def read_result(self, stores, runtime, cycle_id, company_id, capture):
        """Read the result from the same owner slot. Offline evidence grants no authority."""
        self._check_root()
        selected, captured, publication = _binding(stores, runtime, cycle_id, company_id, capture)
        with private._opened_dir(self.descriptor, captured.dispatch_sha256) as slot:
            frozen = self._open_frozen(slot, selected, captured, publication)
            anchor_name = captured.dispatch_sha256 + '.json'
            _require(_optional(self.descriptor, anchor_name) == self._anchor(frozen),
                     'The owner record differs from the assigned offline verifier work.')
            with _settled_receipt(slot) as settled:
                if not settled:
                    return None
                reserved_raw = _optional(slot, 'reservation.json')
                receipt_raw = _optional(slot, 'receipt.json')
                _require(reserved_raw is None or _object(reserved_raw) == frozen['identity'],
                         'The offline verifier reservation does not match its owner.')
                if receipt_raw is None:
                    return None
                _require(reserved_raw is not None, 'The offline verifier result has no owned reservation.')
                record = _validate_result(_object(receipt_raw), frozen)
                _require(_read(slot, 'receipt.json') == receipt_raw
                         and _read(slot, 'reservation.json') == reserved_raw,
                         'The offline verifier receipt changed during readback.')
            private._check_dir(self.descriptor, captured.dispatch_sha256, slot)
            _require(_read(self.descriptor, anchor_name) == self._anchor(frozen),
                     'The owner record changed during offline verifier readback.')
            self._check_root()
        _require(_binding(stores, runtime, cycle_id, company_id, capture) == (selected, captured, publication),
                 'The enrolled scrape changed during verifier result readback.')
        return {'mode': _MODE, 'application_authority': False,
                'dispatch_sha256': captured.dispatch_sha256, 'publication_sha256': publication,
                **record}


def _validate_result(record, frozen):
    _require(set(record) == {'receipt', 'receipt_sha256'} and isinstance(record['receipt'], dict)
             and pending.digest(record['receipt']) == record['receipt_sha256'],
             'The offline verifier result checksum differs.')
    receipt = record['receipt']
    job = frozen['job']
    _require(set(receipt) == {'schema', 'mode', 'identity', 'request_limit', 'deadline_unix_ms',
                              'result', 'reason', 'evidence', 'requests_used'}
             and receipt['schema'] == 'ordinary-rippling-verifier-receipt-v1'
             and receipt['mode'] == _MODE and receipt['identity'] == frozen['identity']
             and type(receipt['request_limit']) is int and receipt['request_limit'] == job['request_limit']
             and type(receipt['deadline_unix_ms']) is int and receipt['deadline_unix_ms'] == job['deadline_unix_ms']
             and isinstance(receipt['result'], str) and receipt['result'] in _TERMINAL
             and isinstance(receipt['reason'], str) and re.fullmatch('[a-z_]+', receipt['reason'])
             and (receipt['requests_used'] is None or type(receipt['requests_used']) is int
                  and 0 <= receipt['requests_used'] <= job['request_limit']),
             'The offline verifier receipt differs from its frozen job.')
    evidence = receipt['evidence']
    if receipt['result'] != 'VERIFIED_MISMATCH':
        _require(evidence is None, 'A held verifier receipt cannot contain verified evidence.')
        return record
    digests = {'configured_observation_sha256', 'authority_extraction_digest', 'candidate_inventory_digest',
               'regression_inventory_digest', 'replay_capture_sha256', 'replay_receipt_sha256'}
    _require(isinstance(evidence, dict) and set(evidence) == digests | {'candidate_vector'}
             and all(pending._is_digest(evidence[key]) for key in digests)
             and evidence['configured_observation_sha256'] == job['mismatch_response_sha256']
             and evidence['replay_capture_sha256'] == frozen['replay_capture_sha256']
             and evidence['candidate_vector'] == frozen['candidate_vector']
             and receipt['reason'] == 'exact_pending_observation_and_public_control_verified'
             and type(receipt['requests_used']) is int and receipt['requests_used'] > 0,
             'The verified mismatch evidence differs from the approved replay.')
    return record


@contextmanager
def open_offline_channel(root_path, root_fd, *, expected_owner_identity, approved_pin_sha256):
    """Use an already configured physical owner root and replay approval."""
    root = Path(root_path)
    _require(root.is_absolute() and root != Path('/tmp') and root.is_relative_to('/tmp')
             and '..' not in root.parts and pending._is_digest(approved_pin_sha256)
             and isinstance(expected_owner_identity, (list, tuple)) and len(expected_owner_identity) == 2
             and all(type(number) is int and number > 0 for number in expected_owner_identity),
             'Invalid offline verifier owner configuration.')
    duplicate = os.dup(root_fd)
    try:
        owner = _OwnerChannel(root, duplicate, list(expected_owner_identity), approved_pin_sha256)
        owner._check_root()
        yield owner
    finally:
        os.close(duplicate)
