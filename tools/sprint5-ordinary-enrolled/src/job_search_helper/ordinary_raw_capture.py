"""Private one-shot custody for an enrolled ordinary Rippling response."""

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
import errno
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from threading import Lock
from uuid import uuid4

from .ats import Inventory, RipplingTenantMismatch, validate_rippling_tenant_mismatch
from .ordinary_verification_pending import SCHEMA as PENDING_SCHEMA, _ADMISSION_FIELDS, _OWNER_FIELDS, digest


MAX_CAPTURE_BYTES = 6 * 1024 * 1024
_METADATA_LIMIT = 16 * 1024
_RESERVATION = 'ordinary-rippling-raw-reservation-v1'
_MANIFEST = 'ordinary-rippling-raw-capture-v1'
_DIGEST = re.compile(r'[0-9a-f]{64}')
_CONFIGURED = re.compile(r'https://ats\.rippling\.com/[a-z0-9][a-z0-9-]{0,99}/jobs')
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_F6_FIELDS = {'jobs', 'inventory_status', 'reason', 'source_url', 'ats', 'browser_pending_urls',
              'browser_discovery_incomplete', 'fetched_at', 'requested_url'}


class CaptureError(ValueError):
    """The selected private raw response is unavailable or lacks exact custody."""


def _require(condition, code):
    if not condition:
        raise CaptureError(code)


def _hash(value):
    return sha256(value).hexdigest()


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def _decode(raw):
    def unique(items):
        result = dict(items)
        _require(len(result) == len(items), 'duplicate_capture_metadata')
        return result

    try:
        value = json.loads(raw, object_pairs_hook=unique)
        _require(isinstance(value, dict) and _encode(value) == raw, 'noncanonical_capture_metadata')
    except (ValueError, TypeError, RecursionError) as error:
        if isinstance(error, CaptureError):
            raise
        raise CaptureError('invalid_capture_metadata') from None
    return value


def _is_digest(value):
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _identity(info):
    return [info.st_dev, info.st_ino]


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _directory(info):
    _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
             and info.st_uid == os.geteuid(), 'unsafe_capture_directory')
    return _identity(info)


@contextmanager
def _filesystem():
    try:
        yield
    except OSError:
        # Do not disclose private filenames or paths to a generic worker log.
        raise CaptureError('private_capture_filesystem_unavailable') from None


@contextmanager
def _opened_dir(parent, name):
    with _filesystem():
        descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
    try:
        with _filesystem():
            _directory(os.fstat(descriptor))
        yield descriptor
    finally:
        os.close(descriptor)


def _named_path_identity(path):
    descriptor = os.open('/', _DIR_FLAGS)
    try:
        for segment in path.parts[1:]:
            child = os.open(segment, _DIR_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return _directory(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def _check_dir(parent, name, descriptor):
    opened = _directory(os.fstat(descriptor))
    named = _directory(os.stat(name, dir_fd=parent, follow_symlinks=False))
    _require(opened == named, 'capture_directory_replaced')
    return opened


def _file(info):
    _require(stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
             and info.st_uid == os.geteuid() and info.st_nlink == 1, 'unsafe_capture_file')
    return info


def _named_file(directory, name, stamp):
    info = _file(os.stat(name, dir_fd=directory, follow_symlinks=False))
    _require(_stamp(info) == stamp, 'capture_file_replaced_or_changed')


def _read_file(directory, name, limit):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    with os.fdopen(descriptor, 'rb') as stream:
        info = _file(os.fstat(stream.fileno()))
        stamp = _stamp(info)
        _require(0 < info.st_size <= limit, 'capture_file_size_out_of_bounds')
        raw = stream.read(limit + 1)
        _require(len(raw) == info.st_size and _stamp(_file(os.fstat(stream.fileno()))) == stamp,
                 'capture_file_replaced_or_changed')
        _named_file(directory, name, stamp)
    return raw, _identity(info), stamp


def _write_file(directory, name, content):
    descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    with os.fdopen(descriptor, 'wb') as stream:
        # Metadata includes its own physical identity, taken from the open file.
        identity = _identity(_file(os.fstat(stream.fileno())))
        data = content(identity) if callable(content) else content
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
        stamp = _stamp(_file(os.fstat(stream.fileno())))
        _named_file(directory, name, stamp)
    return stamp


def _publish_directory(directory, staged, target='capture'):
    # os.rename may overwrite an existing empty directory. This protocol must
    # publish atomically and refuse replacement even if the existing name is empty.
    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, 'renameat2', None)
    _require(rename is not None, 'capture_atomic_no_replace_unavailable')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(directory, os.fsencode(staged), directory, os.fsencode(target), 1) != 0:  # RENAME_NOREPLACE
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            code = 'capture_already_sealed' if target == 'capture' else 'capture_dispatch_already_reserved'
            raise CaptureError(code)
        if number in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
            raise CaptureError('capture_atomic_no_replace_unavailable')
        raise OSError(number, os.strerror(number))
    os.fsync(directory)


def _armed(marker, state):
    armed_fields = {'schema', 'state', 'owner', 'admission'}
    extra = {'dispatch_sha256', 'inventory_sha256', 'observation', 'failure'} if state == 'PREPARED' else set()
    _require(isinstance(marker, dict) and set(marker) == armed_fields | extra
             and marker['schema'] == PENDING_SCHEMA and marker['state'] == state, 'capture_requires_exact_marker')
    owner, admission = marker['owner'], marker['admission']
    _require(isinstance(owner, dict) and isinstance(admission, dict), 'capture_requires_exact_enrollment')
    owner, admission = dict(owner), dict(admission)
    _require(set(owner) == _OWNER_FIELDS and set(admission) == _ADMISSION_FIELDS, 'capture_requires_exact_enrollment')
    names = {'cycle_id', 'cycle_started_at', 'request_id', 'company_id'}
    _require(all(isinstance(owner[name], str) and 0 < len(owner[name]) <= 256 and owner[name].strip() == owner[name]
                 for name in names)
             and type(owner['observation_generation']) is int and 0 < owner['observation_generation'] < 2**63
             and all(_is_digest(owner[key]) for key in _OWNER_FIELDS - names - {'observation_generation'}),
             'capture_requires_exact_owner')
    _require(admission['capability_id'] == 'rippling-shared-v1'
             and isinstance(admission['configured_url'], str) and _CONFIGURED.fullmatch(admission['configured_url'])
             and isinstance(admission['authority_url'], str) and admission['authority_url'].startswith('https://')
             and len(admission['authority_url']) <= 2048
             and all(_is_digest(admission[key]) for key in _ADMISSION_FIELDS - {
                 'capability_id', 'configured_url', 'authority_url'}), 'capture_requires_exact_rippling_admission')
    return {'schema': PENDING_SCHEMA, 'state': 'ARMED', 'owner': owner, 'admission': admission}


def _payload_digest(payload, authority_url, configured_url):
    _require(isinstance(payload, dict) and set(payload) == _F6_FIELDS
             and type(payload['jobs']) is list and not payload['jobs']
             and payload['inventory_status'] == 'partial' and payload['ats'] == 'Rippling'
             and type(payload['browser_pending_urls']) is list and not payload['browser_pending_urls']
             and payload['browser_discovery_incomplete'] is False
             and payload['requested_url'] == authority_url and payload['source_url'] == configured_url
             and isinstance(payload['reason'], str) and len(payload['reason']) <= 4096
             and isinstance(payload['fetched_at'], str) and 0 < len(payload['fetched_at']) <= 64,
             'capture_requires_exact_partial_inventory')
    return digest(payload)


def _reservation(armed, dispatch, source, policy, root_id, slot_id):
    _require(_is_digest(source) and _is_digest(policy), 'capture_requires_source_and_policy_pins')
    return {'schema': _RESERVATION, 'dispatch_sha256': dispatch,
            'observation_generation': armed['owner']['observation_generation'],
            'runtime_binding_sha256': armed['admission']['runtime_binding_sha256'],
            'source_manifest_sha256': source, 'capture_policy_sha256': policy,
            'root_identity': root_id, 'slot_identity': slot_id}


def _manifest(reservation, observation, inventory, folder_id, folder_mtime, manifest_id, body_stamp, reservation_stamp, size):
    url = observation.configured_url
    return {'schema': _MANIFEST, 'reservation_sha256': digest(reservation),
            'dispatch_sha256': reservation['dispatch_sha256'], 'inventory_sha256': inventory,
            'observation': observation.to_record(), 'body_sha256': observation.response_sha256, 'body_bytes': size,
            'request': {'method': 'GET', 'page': 0, 'requested_url': url, 'final_url': url, 'status': 200},
            'capture_identity': folder_id, 'capture_entries_mtime_ns': folder_mtime,
            'manifest_identity': manifest_id, 'body_file_stamp': list(body_stamp),
            'reservation_file_stamp': list(reservation_stamp)}


@dataclass(frozen=True)
class CapturedResponse:
    dispatch_sha256: str
    inventory_sha256: str
    response_sha256: str
    manifest_sha256: str
    body: bytes = field(repr=False)


@dataclass(frozen=True)
class _OwnedSlot:
    root: object
    name: str
    descriptor: int
    reservation: dict

    def check(self):
        self.root._check()
        identity = _check_dir(self.root._descriptor, self.name, self.descriptor)
        _require(identity == self.reservation['slot_identity'], 'capture_slot_replaced')

    def read_reservation(self):
        stored, record_id, stamp = _read_file(self.descriptor, 'reservation.json', _METADATA_LIMIT)
        _require(_decode(stored) == {**self.reservation, 'record_identity': record_id}, 'conflicting_capture_reservation')
        return stamp

    def read(self, observation, inventory):
        self.check()
        reservation_stamp = self.read_reservation()
        with _opened_dir(self.descriptor, 'capture') as capture:
            capture_id = _check_dir(self.descriptor, 'capture', capture)
            capture_mtime = os.fstat(capture).st_mtime_ns
            manifest, manifest_id, manifest_stamp = _read_file(capture, 'manifest.json', _METADATA_LIMIT)
            body, _, body_stamp = _read_file(capture, 'configured-response.html', MAX_CAPTURE_BYTES)
            _require(_decode(manifest) == _manifest(self.reservation, observation, inventory, capture_id, capture_mtime,
                                                   manifest_id, body_stamp, reservation_stamp, len(body)),
                     'conflicting_capture_manifest')
            _require(_hash(body) == observation.response_sha256, 'capture_body_hash_mismatch')
            _named_file(capture, 'manifest.json', manifest_stamp)
            _named_file(capture, 'configured-response.html', body_stamp)
            _check_dir(self.descriptor, 'capture', capture)
            _require(os.fstat(capture).st_mtime_ns == capture_mtime, 'capture_entries_changed')
            _named_file(self.descriptor, 'reservation.json', reservation_stamp)
            self.check()
        return CapturedResponse(self.name, inventory, observation.response_sha256, _hash(manifest), body)


class CaptureTicket:
    def __init__(self, slot, admission, reservation_stamp):
        self._slot = slot
        self._reservation_stamp = reservation_stamp
        self._authority_url = admission['authority_url']
        self._configured_url = admission['configured_url']
        self._candidate = None
        self._offered = False
        self._consumed = False
        self._lock = Lock()

    def offer(self, observation, *, request_url, response_url, status, body):
        """Retain at most one valid direct response in memory. Never raises for rejected bytes."""
        with self._lock:
            if self._consumed or self._offered:
                self._candidate = None
                return False
            self._offered = True
            if (type(observation) is RipplingTenantMismatch
                    and validate_rippling_tenant_mismatch(observation.to_record()) == observation
                    and isinstance(request_url, str) and isinstance(response_url, str)
                    and observation.configured_url == request_url == response_url == self._configured_url
                    and type(status) is int and status == 200 and type(body) is bytes
                    and 0 < len(body) <= MAX_CAPTURE_BYTES and _hash(body) == observation.response_sha256):
                self._candidate = (observation, body)
                return True
            return False

    def seal(self, final_inventory, payload):
        """Return the private manifest digest if selected, with no raw bytes in the result."""
        with self._lock:
            _require(not self._consumed, 'capture_ticket_already_consumed')
            self._consumed = True
            candidate, self._candidate = self._candidate, None
            _require(isinstance(final_inventory, Inventory), 'invalid_capture_final_result')
            observation = final_inventory.rippling_tenant_mismatch
            if observation is None:
                return None
            _require(type(observation) is RipplingTenantMismatch and observation.configured_url == self._configured_url
                     and final_inventory.status == 'partial' and final_inventory.ats == 'Rippling'
                     and final_inventory.source_url == self._configured_url
                     and final_inventory.outcome_failure is None and final_inventory.verified_zero is None
                     and final_inventory.jobs == [] and final_inventory.browser_pending_urls == []
                     and final_inventory.browser_discovery_incomplete is False, 'capture_final_outcome_conflict')
            _require(candidate is not None and candidate[0] == observation, 'capture_final_observation_not_owned')
            inventory = _payload_digest(payload, self._authority_url, self._configured_url)
            _require(payload['reason'] == final_inventory.reason, 'capture_inventory_payload_changed')
            with _filesystem():
                return self._seal(candidate[1], observation, inventory)

    def _seal(self, body, observation, inventory):
        slot = self._slot
        slot.check()
        _require(slot.read_reservation() == self._reservation_stamp, 'capture_reservation_changed')
        staged = '.unsealed-' + uuid4().hex
        os.mkdir(staged, 0o700, dir_fd=slot.descriptor)
        with _opened_dir(slot.descriptor, staged) as stage:
            folder_id = _check_dir(slot.descriptor, staged, stage)
            body_stamp = _write_file(stage, 'configured-response.html', body)
            _write_file(stage, 'manifest.json', lambda manifest_id: _encode(
                _manifest(slot.reservation, observation, inventory, folder_id, os.fstat(stage).st_mtime_ns,
                          manifest_id, body_stamp, self._reservation_stamp, len(body))))
            os.fsync(stage)
            _check_dir(slot.descriptor, staged, stage)
            _named_file(stage, 'configured-response.html', body_stamp)
            slot.check()
            _named_file(slot.descriptor, 'reservation.json', self._reservation_stamp)
            _publish_directory(slot.descriptor, staged)
            _check_dir(slot.descriptor, 'capture', stage)
        return slot.read(observation, inventory).manifest_sha256

    def _close(self):
        with self._lock:
            self._candidate = None
            self._consumed = True


class CaptureCustody:
    def __init__(self, path, descriptor):
        self._path = path
        self._descriptor = descriptor
        self._root_id = _directory(os.fstat(descriptor))
        self._check()

    def _check(self):
        _require(self._descriptor >= 0 and _directory(os.fstat(self._descriptor)) == self._root_id
                 and _named_path_identity(self._path) == self._root_id, 'capture_root_replaced')

    def _slot(self, name, descriptor, armed, source, policy):
        identity = _check_dir(self._descriptor, name, descriptor)
        return _OwnedSlot(self, name, descriptor, _reservation(armed, name, source, policy, self._root_id, identity))

    @contextmanager
    def reserve(self, marker, dispatch_sha256, *, source_manifest_sha256, capture_policy_sha256):
        armed = _armed(marker, 'ARMED')
        _require(_is_digest(dispatch_sha256) and digest(armed) == dispatch_sha256, 'capture_dispatch_digest_mismatch')
        _require(_is_digest(source_manifest_sha256) and _is_digest(capture_policy_sha256), 'capture_requires_source_and_policy_pins')
        staged = '.reservation-' + uuid4().hex
        with _filesystem():
            self._check()
            try:
                os.stat(dispatch_sha256, dir_fd=self._descriptor, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(staged, 0o700, dir_fd=self._descriptor)
            else:
                raise CaptureError('capture_dispatch_already_reserved')
        with _opened_dir(self._descriptor, staged) as descriptor:
            with _filesystem():
                slot_id = _check_dir(self._descriptor, staged, descriptor)
                reservation = _reservation(armed, dispatch_sha256, source_manifest_sha256,
                                           capture_policy_sha256, self._root_id, slot_id)
                reservation_stamp = _write_file(descriptor, 'reservation.json', lambda record_id: _encode(
                    {**reservation, 'record_identity': record_id}))
                os.fsync(descriptor)
                _check_dir(self._descriptor, staged, descriptor)
                self._check()
                _publish_directory(self._descriptor, staged, dispatch_sha256)
                slot = _OwnedSlot(self, dispatch_sha256, descriptor, reservation)
                slot.check()
                _named_file(descriptor, 'reservation.json', reservation_stamp)
            ticket = CaptureTicket(slot, armed['admission'], reservation_stamp)
            try:
                yield ticket
            finally:
                ticket._close()

    def read_prepared(self, marker, payload, *, blocked, source_manifest_sha256, capture_policy_sha256):
        armed = _armed(marker, 'PREPARED')
        dispatch = digest(armed)
        admission = armed['admission']
        observation = validate_rippling_tenant_mismatch(marker['observation'])
        _require(blocked is False and marker['failure'] is None and marker['dispatch_sha256'] == dispatch
                 and observation is not None and observation.configured_url == admission['configured_url'],
                 'capture_requires_unblocked_prepared_mismatch')
        inventory = _payload_digest(payload, admission['authority_url'], admission['configured_url'])
        _require(marker['inventory_sha256'] == inventory, 'capture_prepared_inventory_changed')
        with _filesystem():
            self._check()
            with _opened_dir(self._descriptor, dispatch) as descriptor:
                slot = self._slot(dispatch, descriptor, armed, source_manifest_sha256, capture_policy_sha256)
                return slot.read(observation, inventory)


@contextmanager
def open_custody(root_path, root_fd):
    """Use a caller-enrolled directory descriptor and recheck its exact named root."""
    path = Path(root_path)
    _require(path.anchor == '/' and path != Path('/') and '..' not in path.parts, 'invalid_named_capture_root')
    with _filesystem():
        duplicate = os.dup(root_fd)
        try:
            custody = CaptureCustody(path, duplicate)
        except BaseException:
            os.close(duplicate)
            raise
    try:
        yield custody
    finally:
        custody._descriptor = -1
        os.close(duplicate)
