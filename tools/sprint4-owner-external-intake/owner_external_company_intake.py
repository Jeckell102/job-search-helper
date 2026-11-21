"""Observe one independently approved manual Company edit without writing to Sheets."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import time

from job_search_helper.repository import RepositoryError
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from scoped_manual_pilot_intake_v2 import (
    _BOARD, _SHA, _TAB, _canonical, _check_custody, _has_history, _legacy_token,
    _local_number, _owned, _remote_row, _require, _required_event, _row, _stamp,
)


_SCOPE = 'scoped-owner-external-company-v1'
_PRE = 'scoped-owner-external-absence-v1'
_OWNER = 'scoped-owner-external-confirmed-edit-v1'
_RECEIPT = 'scoped-owner-external-observed-intake-v1'
_ABSENCE = 'owner-edit-absence.json'
_ORIGIN = 'sheets-reconciliation'


def _hash(raw):
    return sha256(raw).hexdigest()


def _approved(raw, pin, reason):
    _require(type(raw) is bytes and 0 < len(raw) <= 8192 and type(pin) is str
             and _SHA.fullmatch(pin) and _hash(raw) == pin, reason)
    try:
        value = json.loads(raw)
        _require(type(value) is dict and _canonical(value) == raw, reason)
    except (ValueError, TypeError, RecursionError):
        raise RepositoryError(reason) from None
    return value


def _scope(raw, pin):
    value = _approved(raw, pin, 'An independent exact owner-external scope is required.')
    try:
        _require(set(value) == {
            'schema', 'owner_sha256', 'company_name', 'company_id', 'board_url', 'added_on',
            'workbook_sha256', 'sheet_id', 'table_id', 'headers', 'database', 'pristine_custody',
        } and value['schema'] == _SCOPE, 'The owner-external selection schema differs.')
        name = value['company_name']
        board = _BOARD.fullmatch(value['board_url'])
        _require(type(name) is str and 0 < len(name) <= 160 and name == name.strip() and name.isprintable()
                 and board and re.fullmatch(r'COMP-[A-F0-9]{12}', value['company_id'])
                 and date.fromisoformat(value['added_on']).isoformat() == value['added_on'],
                 'The selected literal Company or canonical Greenhouse board differs.')
        _require(_legacy_token(name) != 'atomicmachines' and _legacy_token(board[1]) != 'atomicmachines',
                 'The unresolved legacy Atomic Machines identity or board is excluded.')
        _require(_SHA.fullmatch(value['workbook_sha256']) and _SHA.fullmatch(value['owner_sha256'])
                 and type(value['sheet_id']) is int and 0 <= value['sheet_id'] <= 2**31 - 1
                 and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['table_id'])
                 and type(value['headers']) is list and len(value['headers']) == len(COMPACT_SCHEMAS[_TAB])
                 and set(value['headers']) == set(COMPACT_SCHEMAS[_TAB]),
                 'The exact owner, workbook, native table, or ordered header scope differs.')
        for field, length in (('database', 2), ('pristine_custody', 4)):
            pin_tuple = value[field]
            _require(type(pin_tuple) is list and len(pin_tuple) == length
                     and all(type(part) is int and part > 0 for part in pin_tuple),
                     'The owner-external scope requires exact physical Jobs and custody pins.')
    except (TypeError, ValueError, RecursionError):
        raise RepositoryError('The owner-external scope is malformed.') from None
    return value


def _binding(scope, scope_sha256):
    return {
        'scope_sha256': scope_sha256, 'owner_sha256': scope['owner_sha256'],
        'workbook_sha256': scope['workbook_sha256'], 'sheet_id': scope['sheet_id'],
        'table_id': scope['table_id'], 'headers_sha256': _hash(_canonical(scope['headers'])),
        'row': _row(scope), 'database': scope['database'],
    }


@dataclass(frozen=True)
class _OpenedJobs:
    path: Path
    connection: object
    descriptor: int
    identity: tuple[int, int]


def _named_jobs_identity(path):
    if path.resolve(strict=True) != path:
        raise ValueError('Noncanonical Jobs path')
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('Jobs file is not ordinary and single-link')
    return info.st_dev, info.st_ino


def _jobs_descriptors(identity):
    matching = set()
    for entry in Path('/proc/self/fd').iterdir():
        try:
            fd = int(entry.name)
            info = os.fstat(fd)
        except (OSError, ValueError):
            continue
        if (info.st_dev, info.st_ino) == identity and stat.S_ISREG(info.st_mode):
            matching.add(fd)
    return matching


def _opened_jobs_identity(local):
    opened = getattr(local, '_owner_external_opened_jobs', None)
    if type(opened) is not _OpenedJobs or opened.connection is not local.db:
        raise ValueError('Expected the managed owner-external Jobs connection')
    databases = local.db.execute('PRAGMA database_list').fetchall()
    names = [(schema, name) for _, schema, name in databases if schema != 'temp']
    info = os.fstat(opened.descriptor)
    if (Path(local.path).absolute() != opened.path or names != [('main', str(opened.path))]
            or os.readlink(f'/proc/self/fd/{opened.descriptor}') != str(opened.path)
            or (info.st_dev, info.st_ino) != opened.identity
            or _named_jobs_identity(opened.path) != opened.identity):
        raise ValueError('The opened Jobs identity changed')
    return list(opened.identity)


@contextmanager
def open_jobs_for_external_intake(jobs_path, workbook_id):
    """Open the existing Sprint 4 repository and pin SQLite's actual main-file descriptor."""
    path = Path(jobs_path).absolute()
    try:
        identity = _named_jobs_identity(path)
        before = _jobs_descriptors(identity)
    except (OSError, ValueError):
        raise RepositoryError('The exact physical Jobs file could not be prepared for intake.') from None
    with closing(SQLiteRepository(path, workbook_id)) as local:
        local.db.execute('SELECT 1 FROM main.sqlite_master LIMIT 1').fetchone()
        try:
            (descriptor,) = _jobs_descriptors(identity) - before
            local._owner_external_opened_jobs = _OpenedJobs(path, local.db, descriptor, identity)
            _opened_jobs_identity(local)
        except (OSError, ValueError):
            raise RepositoryError('The opened Jobs connection could not be pinned to its physical file.') from None
        yield local


def _verify_local(local, workbook, physical, scope):
    try:
        identity = _opened_jobs_identity(local)
    except (OSError, ValueError):
        raise RepositoryError('The opened Jobs connection lost its enrolled physical file.') from None
    _require(identity == physical == scope['database'] and local.get_meta('spreadsheet_id') == workbook,
             'The opened Jobs file or workbook differs from the owner-external approval.')


def _private_absence(fd):
    try:
        descriptor = os.open(_ABSENCE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.geteuid()
                     and stat.S_IMODE(info.st_mode) == 0o600, 'The durable absence proof is not owner-private.')
            raw = stream.read(8193)
            current = os.stat(_ABSENCE, dir_fd=fd, follow_symlinks=False)
            _require(0 < len(raw) <= 8192 and _stamp(info) == _stamp(current) == _stamp(os.fstat(stream.fileno())),
                     'The durable absence proof did not remain exact during readback.')
            return raw
    except OSError:
        raise RepositoryError('The durable pre-owner-edit absence proof is unavailable.') from None


def _persist_absence(fd, raw):
    try:
        descriptor = os.open(_ABSENCE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(fd)
    except OSError:
        raise RepositoryError('The exact pre-owner-edit absence proof could not be recorded.') from None
    _require(_private_absence(fd) == raw, 'The pre-owner-edit absence proof did not read back exactly.')


def _receipt_key(scope_sha256):
    return 'scoped_owner_external_intake:' + scope_sha256


def prepare_absence(local, remote, scope_bytes, *, approved_scope_sha256, custody_directory):
    """Fsync one before-owner-edit absence observation under both local writer leases."""
    scope = _scope(scope_bytes, approved_scope_sha256)
    binding = _binding(scope, approved_scope_sha256)
    custody = Path(custody_directory)
    with _owned(local, remote, scope, custody) as (fd, physical, workbook):
        _verify_local(local, workbook, physical, scope)
        _check_custody(custody, fd, scope['pristine_custody'], pristine=True)
        row = binding['row']
        _require(_remote_row(remote, workbook, scope, row) is None,
                 'The selected Company identity already exists in Sheets before owner edit.')
        _verify_local(local, workbook, physical, scope)
        _require(_local_number(local, row) is None and not _has_history(local, row)
                 and local.get_meta(_receipt_key(approved_scope_sha256)) is None,
                 'The Company already has a local row, revision or intake receipt.')
        _check_custody(custody, fd, scope['pristine_custody'], pristine=True)
        proof = _canonical({
            'schema': _PRE, 'binding': binding, 'observed_unix_ns': time.time_ns(),
            'remote': 'exact_identity_absent', 'local': 'exact_identity_and_revision_absent',
        })
        _persist_absence(fd, proof)
        _check_custody(custody, fd, scope['pristine_custody'])
    return {'state': 'OWNER_EDIT_ABSENCE_CONFIRMED', 'absence_sha256': _hash(proof)}


def _check_pre(fd, binding, absence_sha256):
    raw = _private_absence(fd)
    record = _approved(raw, absence_sha256, 'The earlier absence proof differs from the owner-confirmed evidence.')
    _require(set(record) == {'schema', 'binding', 'observed_unix_ns', 'remote', 'local'}
             and record['schema'] == _PRE and _canonical(record['binding']) == _canonical(binding)
             and type(record['observed_unix_ns']) is int and record['observed_unix_ns'] > 0
             and record['remote'] == 'exact_identity_absent'
             and record['local'] == 'exact_identity_and_revision_absent',
             'The earlier absence proof has different selection, owner, source or custody.')
    return raw


def _record_local(local, workbook, physical, scope, binding, confirmation, owner_edit_sha256):
    row = binding['row']
    scope_sha256 = binding['scope_sha256']
    receipt_key = _receipt_key(scope_sha256)
    remote_number = confirmation['sheet_row']
    with local.transaction():
        _verify_local(local, workbook, physical, scope)
        number, saved = _local_number(local, row), local.get_meta(receipt_key)
        if number is None:
            _require(saved is None and not _has_history(local, row),
                     'The selected Company already has local revision or receipt history.')
            imported, events = local._import_rows_in_transaction(
                _TAB, [(remote_number, row)], event_origin=_ORIGIN,
            )
            _require(imported == len(events) == 1,
                     'The external Company readback did not create exactly one local event.')
            number = _local_number(local, row)
        else:
            _require(saved is not None, 'The existing local Company was not imported by this owner-external intake.')
        _require(number is not None, 'The approved external Company did not read back from local Jobs.')
        baseline, current = local.baseline(_TAB, number - 1), local.read_row(_TAB, number)
        _require(baseline is not None and all(baseline.get(key) == current.get(key) == value
                                              for key, value in row.items()),
                 'The current local Company or baseline differs from the exact owner edit.')
        event = _required_event(local, row)
        receipt = {
            'schema': _RECEIPT, 'binding': binding, 'absence_sha256': confirmation['absence_sha256'],
            'owner_edit_sha256': owner_edit_sha256, 'sheet_row': remote_number, 'origin': _ORIGIN,
            'event_id': event['event_id'], 'source_revision': event['source_revision'],
        }
        expected = _canonical(receipt).decode()
        if saved is None:
            local.set_meta(receipt_key, expected)
        else:
            _require(saved == expected, 'The durable owner-external receipt differs from this approved observation.')
        _require(local.get_meta(receipt_key) == expected, 'The exact owner-external receipt did not read back.')
        _verify_local(local, workbook, physical, scope)
    return {'state': 'EXTERNAL_COMPANY_INTAKE_CONFIRMED', 'receipt_sha256': _hash(expected.encode()),
            'event_id': event['event_id'], 'company_id': event['company_id'],
            'source_revision': event['source_revision']}


def confirm_owner_edit(local, remote, scope_bytes, owner_confirmation_bytes, *,
                       approved_scope_sha256, approved_owner_edit_sha256, custody_directory):
    """Consume one independently observed owner edit, or exactly read back its local receipt."""
    scope = _scope(scope_bytes, approved_scope_sha256)
    binding = _binding(scope, approved_scope_sha256)
    approval = _approved(owner_confirmation_bytes, approved_owner_edit_sha256,
                         'An independent exact owner-edit confirmation is required.')
    _require(set(approval) == {'schema', 'binding', 'absence_sha256', 'sheet_row'}
             and approval['schema'] == _OWNER and _canonical(approval['binding']) == _canonical(binding)
             and type(approval['absence_sha256']) is str and _SHA.fullmatch(approval['absence_sha256'])
             and type(approval['sheet_row']) is int and approval['sheet_row'] >= 2,
             'The approved owner edit differs from the exact literal row or selection.')
    custody = Path(custody_directory)
    with _owned(local, remote, scope, custody) as (fd, physical, workbook):
        _verify_local(local, workbook, physical, scope)
        pre = _check_pre(fd, binding, approval['absence_sha256'])
        _require(_remote_row(remote, workbook, scope, binding['row']) == approval['sheet_row'],
                 'The exact owner-edited Company row is absent or moved within the native table.')
        _check_custody(custody, fd, scope['pristine_custody'])
        _require(_private_absence(fd) == pre, 'The pre-owner-edit absence evidence changed during readback.')
        return _record_local(local, workbook, physical, scope, binding, approval, approved_owner_edit_sha256)
