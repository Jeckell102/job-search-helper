"""Private, dispatch-keyed issuance authority in the existing coordinator database."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
import stat
from threading import Lock
from uuid import UUID

from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper import ordinary_raw_capture as private
from job_search_helper import runtime_mapping_facts as physical
from job_search_helper.repository import RepositoryError


_TABLE = 'ordinary_live_issuance_admissions'
_SCHEMA = 'coordinator-live-issuance-selection-v1'
_SELECTION_FIELDS = {
    'schema', 'coordinator_root', 'coordinator_root_identity', 'database_identity',
    'evidence_root', 'evidence_root_identity', 'dispatch_sha256', 'binding_sha256', 'source_sha256',
}
_SOURCE_FILES = {
    'adapter': Path(__file__),
    'coordinator_store': Path(__file__).with_name('coordinator_store.py'),
    'slot': Path(slots.__file__),
    'private_custody': Path(private.__file__),
    'sqlite_custody': Path(physical.__file__),
}
_COORDINATOR_TABLES = {'tasks', 'settings', 'receipts', 'inference_receipts'}
_ENROLLMENT = ('dispatch_sha256', 'binding_sha256', 'binding_json', 'selection_sha256', 'root_dev', 'root_ino')
_STATE = (
    'boot_id', 'started_unix_ms', 'started_elapsed_ns', 'deadline_elapsed_ns',
    'reservation_sha256', 'commit_sha256', 'expired',
)
_OPEN_LOCK = Lock()

_TABLE_SQL = """CREATE TABLE ordinary_live_issuance_admissions (
    dispatch_sha256 TEXT PRIMARY KEY NOT NULL
        CHECK (length(dispatch_sha256) = 64 AND dispatch_sha256 NOT GLOB '*[^0-9a-f]*'),
    binding_sha256 TEXT NOT NULL
        CHECK (length(binding_sha256) = 64 AND binding_sha256 NOT GLOB '*[^0-9a-f]*'),
    binding_json BLOB NOT NULL
        CHECK (typeof(binding_json) = 'blob' AND length(binding_json) BETWEEN 1 AND 4096),
    selection_sha256 TEXT NOT NULL
        CHECK (length(selection_sha256) = 64 AND selection_sha256 NOT GLOB '*[^0-9a-f]*'),
    root_dev INTEGER NOT NULL CHECK (typeof(root_dev) = 'integer' AND root_dev > 0),
    root_ino INTEGER NOT NULL CHECK (typeof(root_ino) = 'integer' AND root_ino > 0),
    boot_id TEXT,
    started_unix_ms INTEGER,
    started_elapsed_ns INTEGER,
    deadline_elapsed_ns INTEGER,
    reservation_sha256 TEXT CHECK (
        reservation_sha256 IS NULL OR
        (length(reservation_sha256) = 64 AND reservation_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    commit_sha256 TEXT CHECK (
        commit_sha256 IS NULL OR
        (length(commit_sha256) = 64 AND commit_sha256 NOT GLOB '*[^0-9a-f]*')
    ),
    expired INTEGER NOT NULL DEFAULT 0 CHECK (typeof(expired) = 'integer' AND expired IN (0, 1)),
    CHECK (
        (reservation_sha256 IS NULL AND boot_id IS NULL AND started_unix_ms IS NULL
         AND started_elapsed_ns IS NULL AND deadline_elapsed_ns IS NULL AND commit_sha256 IS NULL)
        OR
        (reservation_sha256 IS NOT NULL AND boot_id IS NOT NULL AND length(boot_id) = 36
         AND typeof(started_unix_ms) = 'integer' AND started_unix_ms > 0
         AND typeof(started_elapsed_ns) = 'integer' AND started_elapsed_ns >= 0
         AND typeof(deadline_elapsed_ns) = 'integer' AND deadline_elapsed_ns > started_elapsed_ns)
    )
)"""
_CREATE_TABLE = 'CREATE TABLE IF NOT EXISTS main.' + _TABLE_SQL.removeprefix('CREATE TABLE ')
_READ_ROW = f'SELECT {",".join(_ENROLLMENT + _STATE)} FROM main.{_TABLE} WHERE dispatch_sha256=?'
_UPDATE_ROW = (f'UPDATE main.{_TABLE} SET {",".join(column + "=?" for column in _STATE)} '
               f'WHERE {" AND ".join(column + " IS ?" for column in _ENROLLMENT + _STATE)}')


def _require(condition, message):
    if not condition:
        raise RepositoryError(message)


@contextmanager
def _custody_errors():
    try:
        yield
    except (OSError, sqlite3.Error, ValueError):
        raise RepositoryError('The retained coordinator SQLite authority is unavailable or changed.') from None


def _identity(value):
    _require(type(value) in (list, tuple) and len(value) == 2
             and all(type(part) is int and 0 < part < 2**63 for part in value),
             'Invalid retained coordinator physical identity.')
    return tuple(value)


def _canonical_path(value):
    _require(type(value) is str, 'Invalid retained coordinator path.')
    path = Path(value)
    _require(path.is_absolute() and path != Path('/') and '..' not in path.parts and str(path) == value,
             'Invalid retained coordinator path.')
    return path


def _code_digest(path):
    path = path.absolute()
    _require(path.resolve(strict=True) == path, 'The reviewed issuance source path changed.')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and 0 < info.st_size <= 1_048_576,
                 'The reviewed issuance source file is invalid.')
        raw = stream.read(info.st_size + 1)
        stamp = private._stamp(info)
        _require(len(raw) == info.st_size and private._stamp(os.fstat(stream.fileno())) == stamp
                 and private._stamp(path.lstat()) == stamp, 'The reviewed issuance source file changed.')
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class _Selection:
    coordinator_root: Path
    coordinator_identity: tuple
    database_identity: tuple
    evidence_root: Path
    evidence_identity: tuple
    dispatch_sha256: str
    binding_sha256: str
    selection_sha256: str


def _approved_selection(raw, expected_sha256):
    _require(type(raw) is bytes and 0 < len(raw) <= 4096 and private._is_digest(expected_sha256)
             and sha256(raw).hexdigest() == expected_sha256, 'An exact independent issuance selection is required.')
    record = private._decode(raw)
    _require(set(record) == _SELECTION_FIELDS and record['schema'] == _SCHEMA,
             'The retained issuance selection has the wrong schema.')
    pins = record['source_sha256']
    _require(type(pins) is dict and set(pins) == set(_SOURCE_FILES)
             and all(private._is_digest(pin) for pin in (*pins.values(), record['dispatch_sha256'], record['binding_sha256'])),
             'The retained issuance source or dispatch pin is invalid.')
    _require(all(_code_digest(path) == pins[name] for name, path in _SOURCE_FILES.items()),
             'The reviewed issuance source bytes differ from their selection.')
    coordinator = _canonical_path(record['coordinator_root'])
    evidence = _canonical_path(record['evidence_root'])
    coordinator_identity = _identity(record['coordinator_root_identity'])
    evidence_identity = _identity(record['evidence_root_identity'])
    database_identity = _identity(record['database_identity'])
    _require(not coordinator.is_relative_to(evidence) and not evidence.is_relative_to(coordinator)
             and len({coordinator_identity, evidence_identity, database_identity}) == 3,
             'Coordinator authority must be physically separate from its issuance evidence.')
    return _Selection(coordinator, coordinator_identity, database_identity, evidence, evidence_identity,
                      record['dispatch_sha256'], record['binding_sha256'], expected_sha256)


def _binding(raw, selection):
    _require(type(raw) is bytes and 0 < len(raw) <= 4096 and sha256(raw).hexdigest() == selection.binding_sha256,
             'The issuance binding differs from its independent selection.')
    try:
        value = private._decode(raw)
    except private.CaptureError:
        raise RepositoryError('The retained issuance binding is noncanonical.') from None
    _require(set(value) == slots._BINDING_DIGESTS | slots._LIMITS.keys() | {'candidate', 'deadline_unix_ms'}
             and value['dispatch_sha256'] == selection.dispatch_sha256
             and all(private._is_digest(value[key]) for key in slots._BINDING_DIGESTS)
             and type(value['candidate']) is dict and set(value['candidate']) == slots._CANDIDATE_DIGESTS
             and all(private._is_digest(pin) for pin in value['candidate'].values())
             and type(value['deadline_unix_ms']) is int and 0 < value['deadline_unix_ms'] < 2**63
             and all(type(value[key]) is int and 0 < value[key] <= cap for key, cap in slots._LIMITS.items()),
             'The retained issuance binding has invalid fields.')
    return value


def _valid_boot(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except ValueError:
        return False


def _state_values(state, deadline):
    _require(type(state) is slots.IssuanceAdmissionState and type(state.expired) is bool,
             'The retained issuance state is invalid.')
    window = state.window
    if window is None:
        _require(state.reservation_sha256 is None and state.commit_sha256 is None,
                 'Issuance confirmation requires a retained reservation.')
        clock = (None, None, None, None)
    else:
        _require(type(window) is slots.IssuanceWindow and _valid_boot(window.boot_id)
                 and all(type(part) is int and 0 <= part < 2**63 for part in (
                     window.started_unix_ms, window.started_elapsed_ns, window.deadline_elapsed_ns))
                 and 0 < window.started_unix_ms < deadline
                 and deadline - window.started_unix_ms <= slots._MAX_DURATION_MS
                 and window.deadline_elapsed_ns == window.started_elapsed_ns
                 + (deadline - window.started_unix_ms) * 1_000_000
                 and private._is_digest(state.reservation_sha256)
                 and (state.commit_sha256 is None or private._is_digest(state.commit_sha256)),
                 'Invalid retained issuance window or proof.')
        clock = (window.boot_id, window.started_unix_ms, window.started_elapsed_ns, window.deadline_elapsed_ns)
    return (*clock, state.reservation_sha256, state.commit_sha256, int(state.expired))


def _state_readback(values, deadline):
    boot, wall, elapsed, end, reservation, commit, expired = values
    window = slots.IssuanceWindow(boot, wall, elapsed, end) if boot is not None else None
    _require(type(expired) is int and expired in (0, 1), 'Invalid retained issuance expiry.')
    state = slots.IssuanceAdmissionState(window, reservation, commit, bool(expired))
    _require(_state_values(state, deadline) == values, 'The retained issuance state is noncanonical.')
    return state


def _allow_transition(previous, following):
    if previous == following:
        return
    _require(not previous.expired, 'Retained issuance expiry is terminal.')
    if previous.reservation_sha256 is not None:
        _require((following.window, following.reservation_sha256) == (previous.window, previous.reservation_sha256),
                 'A spent issuance allowance cannot change.')
    if following.commit_sha256 != previous.commit_sha256:
        _require(previous.commit_sha256 is None and previous.reservation_sha256 is not None and not following.expired,
                 'A retained confirmation requires its one unexpired spend.')


class _SQLiteHandle:
    def __init__(self, path):
        self.path = path
        self.connection = sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=1)

    def close(self):
        self.connection.close()


@contextmanager
def _exclusive_descriptor_custody():
    # SQLite can reuse or defer closing descriptors in this process. Keep
    # one managed connection through close so the reused descriptor probe
    # can attribute its opened main file. SQLite serializes across processes.
    _require(_OPEN_LOCK.acquire(timeout=1), 'The local coordinator issuance connection is busy.')
    try:
        yield
    finally:
        _OPEN_LOCK.release()


class _IssuanceStore:
    def __init__(self, selection, coordinator_descriptor, evidence_descriptor):
        self._selection = selection
        self._coordinator_descriptor = coordinator_descriptor
        self._evidence_descriptor = evidence_descriptor
        self._database = selection.coordinator_root / 'tasks.sqlite3'

    def _check_layout(self):
        selection = self._selection
        for path, descriptor, expected in (
            (selection.coordinator_root, self._coordinator_descriptor, selection.coordinator_identity),
            (selection.evidence_root, self._evidence_descriptor, selection.evidence_identity),
        ):
            _require(tuple(private._directory(os.fstat(descriptor))) == expected
                     and tuple(private._named_path_identity(path)) == expected,
                     'The selected coordinator or evidence directory changed.')
        main = self._database.lstat()
        _require((main.st_dev, main.st_ino) == selection.database_identity,
                 'The selected coordinator database changed.')
        for path in (self._database, *(self._database.with_name(self._database.name + suffix)
                                        for suffix in ('-wal', '-shm', '-journal'))):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if path != self._database:
                    continue
                raise
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                     and stat.S_IMODE(info.st_mode) == 0o600,
                     'The coordinator database or its SQLite sidecar lacks private custody.')

    def _check_connection(self, handle):
        self._check_layout()
        _, actual = physical._store_identity(handle, handle.connection)
        _require(tuple(actual) == self._selection.database_identity,
                 'The opened coordinator database differs from its independent selection.')

    @staticmethod
    def _check_schema(db):
        reason = 'The approved retained issuance schema is unavailable or changed.'
        rows = db.execute(
            'SELECT type,name,lower(name),lower(tbl_name),sql FROM main.sqlite_schema '
            'WHERE name COLLATE NOCASE = ? OR tbl_name COLLATE NOCASE = ? ORDER BY type',
            (_TABLE, _TABLE),
        ).fetchall()
        _require(len(rows) == 2, reason)
        index, table = rows
        kind, spelling, name, owner, definition = table
        _require(kind == 'table' and name == owner == _TABLE
                 and (index[0], *index[2:]) == ('index', f'sqlite_autoindex_{_TABLE}_1', _TABLE, None)
                 and db.execute('SELECT 1 FROM temp.sqlite_schema').fetchone() is None, reason)

        # SQLite resolves these identifier spellings to the same ordinary table.
        # Keep the rest of the approved definition byte-for-byte exact.
        body = _TABLE_SQL.removeprefix(f'CREATE TABLE {_TABLE}')
        identifiers = (spelling, f'"{spelling}"', f'[{spelling}]', f'`{spelling}`', f"'{spelling}'")
        _require(any(definition == f'CREATE TABLE {identifier}{body}' for identifier in identifiers), reason)

    @contextmanager
    def _transaction(self, *, migrating=False):
        with _custody_errors(), _exclusive_descriptor_custody(), ExitStack() as resources:
            self._check_layout()
            handle = physical._open_store(resources, self._database, _SQLiteHandle, 'connection')
            db = handle.connection
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            _require(db.execute('PRAGMA journal_mode').fetchone() == ('wal',),
                     'The coordinator issuance authority requires its existing WAL database.')
            with db:
                db.execute('BEGIN IMMEDIATE')
                self._check_connection(handle)
                names = {row[0] for row in db.execute(
                    'SELECT lower(name) FROM main.sqlite_schema WHERE type=\'table\'')}
                _require(_COORDINATOR_TABLES <= names, 'The selected file is not an initialized coordinator database.')
                if migrating:
                    db.execute(_CREATE_TABLE)
                self._check_schema(db)
                yield db
                self._check_connection(handle)
            self._check_connection(handle)

    def migrate(self):
        """Install the additive schema under explicit coordinator maintenance ownership."""
        with self._transaction(migrating=True):
            pass

    def _verify_row(self, row):
        selection = self._selection
        _require(row is not None and row[:2] == (selection.dispatch_sha256, selection.binding_sha256)
                 and row[3:6] == (selection.selection_sha256, *selection.evidence_identity),
                 'The retained authority has no exact enrolled dispatch.')
        binding = _binding(row[2], selection)
        return _state_readback(row[6:], binding['deadline_unix_ms']), binding['deadline_unix_ms']

    def enroll_prevalidated(self, binding_json):
        """Record the exact private selection after separate application proof validation."""
        selection = self._selection
        _binding(binding_json, selection)
        enrollment = (selection.dispatch_sha256, selection.binding_sha256, binding_json,
                      selection.selection_sha256, *selection.evidence_identity)
        with self._transaction() as db:
            row = db.execute(_READ_ROW, (selection.dispatch_sha256,)).fetchone()
            if row is None:
                db.execute(f'INSERT INTO main.{_TABLE} ({",".join(_ENROLLMENT)}) VALUES (?,?,?,?,?,?)',
                           enrollment)
                row = db.execute(_READ_ROW, (selection.dispatch_sha256,)).fetchone()
            _require(row is not None and row[:6] == enrollment, 'A different enrollment already owns this dispatch.')
            state, _ = self._verify_row(row)
        return state

    def _apply(self, dispatch_sha256, binding_sha256, root_identity, transition):
        selection = self._selection
        _require((dispatch_sha256, binding_sha256, _identity(root_identity))
                 == (selection.dispatch_sha256, selection.binding_sha256, selection.evidence_identity)
                 and callable(transition), 'The requested issuance differs from its independent selection.')
        with self._transaction() as db:
            row = db.execute(_READ_ROW, (dispatch_sha256,)).fetchone()
            previous, deadline = self._verify_row(row)
            following = transition(previous)
            values = _state_values(following, deadline)
            _allow_transition(previous, following)
            if values != row[6:]:
                count = db.execute(_UPDATE_ROW, (*values, *row)).rowcount
                _require(count == 1, 'The retained issuance row changed before commit.')
            current = db.execute(_READ_ROW, (dispatch_sha256,)).fetchone()
            _require(current == (*row[:6], *values), 'The retained issuance transition did not read back exactly.')
        return following

    def admission(self):
        """Return only the slot-facing capability to operate on an enrolled row."""
        return _CoordinatorIssuanceAdmission(self)


class _CoordinatorIssuanceAdmission(slots.IssuanceAdmission):
    def __init__(self, store):
        self._store = store

    def transact(self, dispatch_sha256, binding_sha256, root_identity, transition):
        return self._store._apply(dispatch_sha256, binding_sha256, root_identity, transition)


@contextmanager
def _open_issuance_store(selection_bytes, *, approved_selection_sha256):
    """Open the exact configured coordinator store in a trusted application owner."""
    with ExitStack() as directories:
        with _custody_errors():
            selection = _approved_selection(selection_bytes, approved_selection_sha256)
            coordinator = os.open(selection.coordinator_root, private._DIR_FLAGS)
            directories.callback(os.close, coordinator)
            evidence = os.open(selection.evidence_root, private._DIR_FLAGS)
            directories.callback(os.close, evidence)
            store = _IssuanceStore(selection, coordinator, evidence)
            store._check_layout()
        try:
            yield store
        finally:
            store._coordinator_descriptor = store._evidence_descriptor = -1
