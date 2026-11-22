"""Consume exact owner approval only after a verified source-only forward."""

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path

from inspect_saved_parent import PROJECT, WRAPPER, inspect
from preview_exact_child import FIELDS


UNIT = 'wrapper-development-host.service'
ROOT = Path('/tmp/jsh-embraer-03-continuation-release/transaction')
CONTROL_ENV = (
    'WRAPPER_EMBRAER_OPERATOR_PILOT_ENROLLMENT',
    'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT',
    'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT',
    'WRAPPER_AMPHENOL_RETRY_APPROVAL',
    'WRAPPER_AMPHENOL_ACTIVATE_APPROVED_RELEASE',
)


def private_json(path, pin):
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError('The pinned private evidence requires its exact physical path.')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_size > 200000):
            raise ValueError('The pinned evidence must be a private regular file.')
        raw = handle.read(200001)
    if sha256(raw).hexdigest() != pin:
        raise ValueError('Approved evidence bytes differ.')
    return json.loads(raw)


def wrapper_facts():
    properties = subprocess.check_output(
        ['/usr/bin/systemctl', '--user', 'show', UNIT, '-p', 'MainPID', '-p',
         'ActiveState', '-p', 'ExecMainStartTimestampMonotonic'], text=True, timeout=15)
    facts = dict(line.split('=', 1) for line in properties.splitlines())
    if facts['ActiveState'] != 'active' or int(facts['MainPID']) <= 0:
        raise ValueError('The measured wrapper host is unavailable.')
    return int(facts['MainPID']), int(facts['ExecMainStartTimestampMonotonic'])


def selected_enrollment(pid):
    expected = set(CONTROL_ENV)
    selected = {}
    for entry in (Path('/proc') / str(pid) / 'environ').read_bytes().split(b'\x00'):
        key, _, value = entry.partition(b'=')
        name = key.decode()
        if name in expected:
            if name in selected:
                raise ValueError('Duplicate enrollment in the wrapper process.')
            selected[name] = value.decode()
    return selected


def authorize(approval, receipt):
    if (receipt.get('status') != 'INSTALLED' or receipt.get('schema') != 'embraer-03-five-tool-forward-v1'
            or receipt.get('transition', {}).get('parent_task_id') != 'WRAP-250158dc79'
            or receipt.get('restart', {}).get('authorization_issued') is not False):
        raise ValueError('A completed source-only installed receipt is required.')
    restart = receipt['restart']
    exact_facts = (restart['pid'], restart['started_monotonic_us'])
    if wrapper_facts() != exact_facts:
        raise ValueError('The wrapper process changed after the approved source-only forward.')
    held = inspect(installed_staged=True)
    authorization = approval['authorization']
    expected = {key: held[key] for key in FIELDS if key != 'parent_state_sha256'}
    expected['parent_task_state_sha256'] = held['parent_state_sha256']
    if (approval.get('status') != 'OWNER_APPROVED' or approval.get('additional_call_cap') != 1
            or approval.get('remaining_token_allowance') != 1941 or approval.get('original_token_ceiling') != 120000
            or approval.get('control_generation') != held['control_generation']
            or any(authorization.get(key) != value for key, value in expected.items())
            or not authorization['issued_at'] <= time.time() < authorization['expires_at']):
        raise ValueError('The exact owner-approved one-call scope is absent, expired or stale.')

    from coordinator_store import Store, _canonical_json, _sha256_text
    from host_server import build_coordinator, recipe_enrollment_from_process_environment

    normalized = Store._embraer_03_authorization(authorization)
    authorization_id = _sha256_text(_canonical_json(normalized))
    if approval['authorization_sha256'] != authorization_id or approval['child_task_id'] != 'WRAP-' + authorization_id[:10]:
        raise ValueError('The owner approval differs from the exact derived child.')
    selected = selected_enrollment(restart['pid'])
    enrollment = recipe_enrollment_from_process_environment(selected)
    if (enrollment is None or enrollment.request_id != held['request_id']
            or enrollment.source_revision != held['source_revision']
            or enrollment.baseline_sha256 != held['baseline_sha256']
            or wrapper_facts() != exact_facts):
        raise ValueError('The measured wrapper no longer carries the same #03 enrollment.')
    coordinator = build_coordinator(enrollment)
    result = enrollment.authorize_continuation(
        coordinator, normalized, expected_control_generation=held['control_generation'])
    if result['task_id'] != approval['child_task_id']:
        raise RuntimeError('Unexpected outcome from the exact one-use authorization.')
    return {'state': 'EMBRAER_CHILD_AUTHORIZED', 'child_task_id': result['task_id'],
            'expires_at': result['expires_at'], 'additional_call_cap': 1,
            'original_token_ceiling': 120000}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    parser.add_argument('--owner-approval', type=Path, required=True)
    parser.add_argument('--owner-approval-sha256', required=True)
    parser.add_argument('--installed-receipt-sha256', required=True)
    args = parser.parse_args()
    if not sys.flags.dont_write_bytecode or Path(sys.prefix).resolve() != PROJECT / '.venv':
        raise ValueError('Use the installed scraper Python with -B.')
    approved = private_json(args.owner_approval, args.owner_approval_sha256)
    if approved.get('installed_receipt_sha256') != args.installed_receipt_sha256:
        raise ValueError('The owner approval must name the exact source-forward receipt.')
    receipt = private_json(ROOT / 'receipt.json', args.installed_receipt_sha256)
    print(json.dumps(authorize(approved, receipt), sort_keys=True))


if __name__ == '__main__':
    main()
