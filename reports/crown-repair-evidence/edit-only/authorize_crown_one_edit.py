"""Consume exact local authority for Crown's one additional guarded edit."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import stat
import subprocess
import sys
import time


PROJECT = Path('/home/chris/job-search-helper_old')
HERE = Path(__file__).resolve().parent
WRAPPER = PROJECT / 'dev/wrapper-coder'
PIN = '57aa9b63a00351b8e72c66429e70cb783d79162cd3784b91d5c05cce95c592ea'
PINNED_APP_RELEASE = 'REL-ede347339c8faf1806583810'


def read(path):
    if not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError('Expected an exact physical authorization artifact.')
    info = path.stat()
    if info.st_uid != PROJECT.stat().st_uid or info.st_nlink != 1 or info.st_size > 200000:
        raise ValueError('Authorization artifact ownership changed.')
    return path.read_bytes()


def private_value(path):
    raw = read(path)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('Live authorization must be private.')
    return json.loads(raw)


def wrapper_pid():
    fields = subprocess.check_output(
        ['/usr/bin/systemctl', '--user', 'show', 'wrapper-development-host.service',
         '-p', 'MainPID', '-p', 'ActiveState'], text=True, timeout=15,
    )
    data = dict(line.split('=', 1) for line in fields.splitlines())
    if data['ActiveState'] != 'active' or int(data['MainPID']) <= 0:
        raise ValueError('The verified wrapper is no longer active.')
    return int(data['MainPID'])


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('prepare', 'apply'))
    args = parser.parse_args()
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
        raise ValueError('Use isolated production Python without bytecode.')
    pins_raw = read(HERE / 'SOURCE_PINS.json')
    if sha256(pins_raw).hexdigest() != PIN:
        raise ValueError('The reviewed Crown source scope differs.')
    pins = json.loads(pins_raw)
    receipt = private_value(HERE / 'LIVE_FORWARD.json')
    expected = {name: row['staged'] for name, row in pins.items()}
    if (receipt['state'] != 'CROWN_ONE_EDIT_FORWARD_INSTALLED' or receipt['source_sha256'] != expected
            or any(sha256(read(WRAPPER/'tools'/name)).hexdigest() != digest for name,digest in expected.items())
            or receipt['wrapper_pid'] != wrapper_pid()):
        raise ValueError('The exact source-only Crown forward is not installed.')

    sys.path[:0] = [str(PROJECT), str(PROJECT/'src'), str(WRAPPER/'tools')]
    from release_admission_bootstrap import _load_environment, _validate_runtime
    from bounded_continuation import CROWN
    from coordinator_store import task_state_digest
    from crown_operator_pilot import ENV
    from host_server import build_coordinator, recipe_enrollment_from_process_environment

    _load_environment(PROJECT/'.env')
    runtime = _validate_runtime(PROJECT, PROJECT/'.state')
    if runtime.get('state') != 'COMPLETE' or runtime.get('release_id') != PINNED_APP_RELEASE:
        raise ValueError('The settled application release changed.')
    selected = {}
    for item in (Path('/proc')/str(receipt['wrapper_pid'])/'environ').read_bytes().split(b'\x00'):
        key, sep, value = item.partition(b'=')
        if sep and key.startswith(b'WRAPPER_'):
            selected[key.decode()] = value.decode()
    enrollment = recipe_enrollment_from_process_environment(selected)
    if (enrollment is None or ENV not in selected or enrollment.request_id != CROWN.request
            or enrollment.baseline_sha256 != CROWN.baseline or wrapper_pid() != receipt['wrapper_pid']):
        raise ValueError('The exact Crown host enrollment changed.')
    coordinator = build_coordinator(enrollment)
    store = coordinator.store
    parent = store.get(CROWN.parent)
    proof = parent['repair_provenance']
    expires = parent['activated_at'] + 3600
    if time.time() >= expires:
        raise ValueError('The original Crown activation deadline passed.')
    with store.connect() as db:
        db.execute('BEGIN')
        held = db.execute('SELECT payload FROM repair_intake WHERE repair_key=?',(proof['repair_key'],)).fetchone()
        delivery = db.execute(
            'SELECT record_sha256,receipt_sha256,sink_status FROM scrape_outcome_delivery_receipts WHERE outcome_id=?',
            (proof['outcome_id'],),
        ).fetchone()
        if held is None or delivery is None or delivery[2] != 'HELD_FOR_REPAIR_TRIAGE':
            raise ValueError('The exact acknowledged Crown repair intake is unavailable.')
        record = json.loads(held[0])
    stable = {
        'schema': CROWN.schema, 'parent_task_id': CROWN.parent, 'parent_task_state_sha256': task_state_digest(parent),
        'repair_key': proof['repair_key'], 'outcome_id': proof['outcome_id'], 'record_sha256': delivery[0],
        'receipt_sha256': delivery[1], 'failure_fingerprint': record['failure_fingerprint'],
        'source_revision': proof['source_revision'], 'baseline_sha256': CROWN.baseline, 'expires_at': expires,
    }
    path = HERE/'LIVE_ONE_EDIT_AUTHORITY.json'
    if args.action == 'prepare':
        authorization = {**stable, 'issued_at': time.time()}
        document = {'state':'COORDINATOR_BOUNDED_CROWN_ONE_EDIT',
                    'authorization':authorization,'limits':CROWN.limits,
                    'control_generation':store.control_generation(),
                    'wrapper_pid':receipt['wrapper_pid']}
        import os
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps(document, sort_keys=True, indent=2)+'\n')
            handle.flush()
            os.fsync(handle.fileno())
        print(json.dumps({'state':document['state'],'parent_task_id':CROWN.parent,'limits':CROWN.limits,'expires_at':expires},sort_keys=True))
    else:
        document = private_value(path)
        authorization = document['authorization']
        if (document['state'] != 'COORDINATOR_BOUNDED_CROWN_ONE_EDIT' or document['limits'] != CROWN.limits
                or document['wrapper_pid'] != receipt['wrapper_pid']
                or {key:value for key,value in authorization.items() if key != 'issued_at'} != stable
                or wrapper_pid() != receipt['wrapper_pid']):
            raise ValueError('The one-edit authority no longer matches the exact Crown hold.')
        result = enrollment.authorize_continuation(coordinator, authorization,
            expected_control_generation=document['control_generation'])
        print(json.dumps({'state':'CROWN_ONE_EDIT_CHILD_AUTHORIZED','task_id':result['task_id'],
                          'limits':result['limits'],'expires_at':result['expires_at']},sort_keys=True))


if __name__ == '__main__':
    main()
