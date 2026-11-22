"""Inspect the exact current #03 owner and staged source without authorizing work."""

import json
import sqlite3
import sys
import argparse
from contextlib import closing
from hashlib import sha256
from pathlib import Path


PROJECT = Path('/home/chris/job-search-helper_old')
WRAPPER = PROJECT / 'dev/wrapper-coder'
STAGED = Path('/tmp/jsh-embraer-03-continuation')
REPORTS = Path('/tmp/job-search-helper-integration-automation/temp/integration-coordinator')
PARENT = 'WRAP-250158dc79'


def inspect(*, installed_staged=False):
    sys.path[:0] = [str(WRAPPER / 'tools'), str(PROJECT / 'src')]
    from coordinator_store import Store, task_state_digest
    from embraer_operator_pilot import ENV, EmbraerOperatorEnrollment
    from job_search_helper.cli import job_database_path, load_environment
    from job_search_helper.inbox import InventoryInbox

    saved = json.loads((STAGED / 'PRIVATE_SAVED_FIXTURE.json').read_text())
    proof = json.loads((REPORTS / 'S6_EMBRAER_03_ISOLATED_CONTINUATION_PROOF_20261122.json').read_text())
    enrollment = EmbraerOperatorEnrollment.from_process_environment({ENV: json.dumps(saved['enrollment'])})
    load_environment(PROJECT / '.env')
    jobs = job_database_path()
    destination = InventoryInbox.destination_id(jobs.parent / 'inventories.sqlite3')
    actual = enrollment._source(jobs, destination)
    if (actual is None or not actual['acknowledged']
            or any(actual[key] != saved['sender'][key] for key in ('record', 'digest', 'proof', 'company'))
            or enrollment.request_id != 'operator-embraer-20261122-03'
            or sha256((PROJECT / 'src/job_search_helper/shared_boards.py').read_bytes()).hexdigest()
            != enrollment.shared_boards_sha256
            or sha256((PROJECT / 'src/job_search_helper/ats.py').read_bytes()).hexdigest()
            != enrollment.ats_sha256):
        raise ValueError('The approved-scope source or acknowledged #03 sender changed.')

    with closing(sqlite3.connect((WRAPPER / 'tasks/tasks.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        controls = {key: json.loads(raw) for key, raw in db.execute('SELECT key,value FROM settings')}
        if (controls.get('pilot_task') != PARENT or controls.get('queue_enabled', True)
                or controls.get('campaign_enabled') or controls.get('autopilot_enabled')
                or db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN')").fetchone()
                or db.execute('SELECT 1 FROM receipts WHERE result IS NULL').fetchone()
                or any(json.loads(raw)['status'] in ('RUNNING', 'QUEUED', 'PAUSING')
                       for raw, in db.execute('SELECT state FROM tasks'))):
            raise ValueError('The exact quiet #03 pilot no longer owns the lane.')
        [raw] = db.execute('SELECT state FROM tasks WHERE id=?', (PARENT,)).fetchone()
        parent = json.loads(raw)
        for table, key in (('tasks', 'id'), ('receipts', 'task'), ('inference_receipts', 'task')):
            order = 'request_id' if table == 'inference_receipts' else 'id'
            rows = db.execute(f'SELECT * FROM {table} WHERE {key}=? ORDER BY {order}', (PARENT,)).fetchall()
            if rows != [tuple(row) for row in saved['rows'][table]]:
                raise ValueError('The previously reviewed parent or its receipts changed.')
        [receiver] = db.execute(
            'SELECT * FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
            (saved['rows']['scrape_outcome_delivery_receipts'][0][0], proof['outcome_id'])).fetchall()
        ack = Store._validate_delivery_receipt(
            receiver[2:7], consumer=receiver[0], canonical=actual['record'], record_sha256=actual['digest'])
        if json.loads(actual['row'][6]) != ack or list(receiver) != saved['rows']['scrape_outcome_delivery_receipts'][0]:
            raise ValueError('The paired acknowledgment changed.')
        generation = Store._control_generation(db)
        continuation_table = db.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name='embraer_03_continuations'").fetchone()
        if installed_staged and (
                not continuation_table or db.execute('SELECT 1 FROM embraer_03_continuations LIMIT 1').fetchone()):
            raise ValueError('The source-only restart must create an empty continuation table.')

    installed = {}
    for name, pins in proof['source_pins'].items():
        staged = STAGED / name
        if sha256(staged.read_bytes()).hexdigest() != pins['staged_sha256']:
            raise ValueError('A staged source image changed after isolated QA.')
        if not name.startswith('tools/'):
            continue
        current = WRAPPER / name
        prior = sha256(current.read_bytes()).hexdigest() if current.is_file() else None
        expected = pins['staged_sha256'] if installed_staged else pins['prior_sha256']
        if current.is_symlink() or prior != expected:
            raise ValueError('An installed source image differs from the proposed predecessor.')
        installed[name] = pins
    return {
        'read_only': True, 'state': ('STAGED_WRAPPER_INSTALLED_AND_EXACT_PARENT_HELD' if installed_staged
                                    else 'EXACT_HELD_PARENT_AND_STAGED_SOURCE_MATCH'),
        'authorization_issued': False, 'parent_task_id': PARENT,
        'parent_state_sha256': task_state_digest(parent), 'outcome_id': proof['outcome_id'],
        'request_id': enrollment.request_id, 'baseline_sha256': enrollment.baseline_sha256,
        'repair_key': parent['held_repair_key'], 'record_sha256': actual['digest'],
        'source_revision': enrollment.source_revision,
        'failure_fingerprint': actual['record']['failure_fingerprint'],
        'receipt_sha256': receiver[5], 'control_generation': generation,
        'settled_calls': 15, 'tokens_consumed': 118059, 'tokens_remaining': 1941,
        'staged_wrapper_files': installed,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-staged', action='store_true')
    args = parser.parse_args()
    print(json.dumps(inspect(installed_staged=args.installed_staged), indent=2, sort_keys=True))
