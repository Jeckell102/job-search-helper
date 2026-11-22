"""Small custody layer for the default-off Embraer wrapper pilot."""

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from embraer_pilot_environment import ENROLLMENT_FIELDS, reconcile_enrollment


_HEX = re.compile(r'[0-9a-f]{64}\Z')
_SCHEMA = 'embraer-operator-pilot-enrollment-v1'
_OPERATOR_GATE_STATUSES = frozenset((
    'AWAITING_LIVE_VALIDATION', 'REVIEW_COMPLETE_LIVE_NOT_VALIDATED', 'LIVE_VALIDATED'))
_QUIESCENT_ABORT_STATUSES = frozenset((
    'PAUSED_AUTHORIZATION', 'PAUSED_BLOCKED', 'PAUSED_BUDGET', 'PAUSED_ERROR',
    'PAUSED_FILES_CHANGED', 'PAUSED_NO_PROGRESS', 'PAUSED_TEST_FAILURE'))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def _owner_path(root, request_id):
    return Path(root) / 'operator-company-requests' / 'embraer-pilot' / (sha256(request_id.encode()).hexdigest() + '.json')


def _read_owner(path):
    if (not path.is_file() or path.is_symlink() or path.resolve(strict=True) != path
            or stat.S_IMODE(path.stat().st_mode) != 0o600 or path.stat().st_nlink != 1):
        raise ValueError('embraer_enrollment_custody')
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict) or value.get('schema') != _SCHEMA:
        raise ValueError('embraer_enrollment_custody')
    return value


def _write_new_private(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        raise ValueError('embraer_enrollment_custody')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, _canonical(value))
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_parent(path)


def _replace_private(path, value):
    temporary = path.with_name('.' + path.name + '.new')
    if os.path.lexists(temporary):
        raise ValueError('embraer_enrollment_custody')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, _canonical(value))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, path)
    _fsync_parent(path)


def _fsync_parent(path):
    fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _reached_operator_gate(task):
    """Match the coordinator-store terminal gate without importing its runtime."""
    return (task.get('status') in _OPERATOR_GATE_STATUSES
            or task.get('campaign_disposition') == 'CAMPAIGN_FINISHED'
            and not task.get('campaign_outcome', '').startswith('PAUSED_'))


def _can_disarm_task(task):
    if not isinstance(task, dict):
        return False
    return (_reached_operator_gate(task)
            or task.get('status') in _QUIESCENT_ABORT_STATUSES and task.get('stop_requested') is True)


def reconcile_pilot(*, action, root, request_id, request_sha256=None, read_enrollment=None,
                    terminal_proof=None, system, inspect_wrapper, check_quiescent):
    """Arm or withdraw only one exact pilot and only after its terminal proof.

    All durable authority is injected: the host integration owns the lock and
    native readback.  This function changes only the scoped manager variable
    through ``reconcile_enrollment``; tests supply a fake systemd callback.
    """
    if action not in {'arm', 'disarm'}:
        raise ValueError('embraer_enrollment_action')
    if not isinstance(request_id, str) or not request_id.startswith('operator-embraer-'):
        raise ValueError('embraer_enrollment_request')
    path = _owner_path(root, request_id)
    existing = _read_owner(path) if os.path.lexists(path) else None
    if action == 'arm':
        if not isinstance(request_sha256, str) or not _HEX.fullmatch(request_sha256) or read_enrollment is None:
            raise ValueError('embraer_enrollment_request')
        enrollment, outcome_id = read_enrollment(request_id=request_id, request_sha256=request_sha256)
        if (not isinstance(enrollment, dict) or set(enrollment) != ENROLLMENT_FIELDS
                or enrollment.get('request_id') != request_id or enrollment.get('request_sha256') != request_sha256
                or not isinstance(outcome_id, str) or not re.fullmatch(r'OUT-[0-9a-f]{24}', outcome_id)):
            raise ValueError('embraer_enrollment_authority')
        owner = {'schema': _SCHEMA, 'enrollment': enrollment, 'outcome_id': outcome_id}
        if existing is not None and existing != owner:
            raise ValueError('embraer_enrollment_foreign_scope')
        if existing is None:
            _write_new_private(path, owner)
        result = reconcile_enrollment(enrollment, enabled=True, system=system,
                                      inspect_wrapper=inspect_wrapper, check_quiescent=check_quiescent)
        return {**result, 'outcome_id': outcome_id, 'owner_record': str(path)}
    if existing is None or terminal_proof is None:
        raise ValueError('embraer_enrollment_terminal')
    enrollment = existing.get('enrollment')
    proof = terminal_proof(enrollment=enrollment, outcome_id=existing.get('outcome_id'))
    if (not isinstance(proof, dict) or proof.get('outcome_id') != existing.get('outcome_id')
            or proof.get('request_id') != request_id or proof.get('unresolved_inferences') != 0
            or not _can_disarm_task(proof.get('task'))
            or any(not isinstance(proof.get(key), str) or not _HEX.fullmatch(proof[key])
                   for key in ('sender_receipt_sha256', 'receiver_receipt_sha256'))):
        raise ValueError('embraer_enrollment_terminal')
    closed = {**existing, 'disarm_receipts': {key: proof[key] for key in (
        'sender_receipt_sha256', 'receiver_receipt_sha256')}}
    _replace_private(path, closed)
    result = reconcile_enrollment(enrollment, enabled=False, system=system,
                                  inspect_wrapper=inspect_wrapper, check_quiescent=check_quiescent)
    return {**result, 'outcome_id': existing['outcome_id'], 'owner_record': str(path)}
