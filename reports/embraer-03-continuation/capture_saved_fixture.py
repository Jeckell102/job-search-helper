"""Copy the exact settled #03 evidence into a private disposable fixture."""

import json
import os
import sqlite3
import sys
from contextlib import closing
from hashlib import sha256
from pathlib import Path


PROJECT = Path('/home/chris/job-search-helper_old')
WRAPPER = PROJECT / 'dev/wrapper-coder'
PARENT = 'WRAP-250158dc79'
OUTCOME = 'OUT-89a8561a79f99e2b3c3eb243'
REQUEST = 'operator-embraer-20261122-03'
ARM_INSPECT = Path('/tmp/jsh-embraer-owned-pilot.xXaXrqW0/implementation-recovery/arm-next/LIVE_INSPECT.json')


def main():
    sys.path[:0] = [str(WRAPPER / 'tools'), str(PROJECT / 'src')]
    from embraer_operator_pilot import ENV, EmbraerOperatorEnrollment
    from coordinator_store import Store
    from job_search_helper.cli import job_database_path, load_environment
    from job_search_helper.inbox import InventoryInbox

    selected = json.loads(ARM_INSPECT.read_text())['snapshot']['next_enrollment']
    enrollment = EmbraerOperatorEnrollment.from_process_environment({ENV: json.dumps(selected)})
    load_environment(PROJECT / '.env')
    jobs = job_database_path()
    destination = InventoryInbox.destination_id(jobs.parent / 'inventories.sqlite3')
    source = enrollment._source(jobs, destination)
    if (source is None or not source['acknowledged'] or source['record']['outcome_id'] != OUTCOME
            or enrollment.request_id != REQUEST or source['record']['identity']['request_id'] != REQUEST):
        raise ValueError('Expected one acknowledged #03 sender')
    source['row'] = list(source['row'])
    controls = ('queue_enabled', 'campaign_enabled', 'autopilot_enabled', 'pilot_task', 'control_generation')
    with closing(sqlite3.connect((WRAPPER / 'tasks/tasks.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        data = {}
        data['tasks'] = db.execute('SELECT * FROM tasks WHERE id=?', (PARENT,)).fetchall()
        state = json.loads(data['tasks'][0][1])
        data['receipts'] = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id', (PARENT,)).fetchall()
        data['inference_receipts'] = db.execute(
            'SELECT * FROM inference_receipts WHERE task=? ORDER BY request_id', (PARENT,)).fetchall()
        data['settings'] = db.execute(
            'SELECT * FROM settings WHERE key IN (?,?,?,?,?) ORDER BY key', controls).fetchall()
        for table in ('scrape_outcome_intake', 'scrape_outcome_delivery_receipts'):
            data[table] = db.execute(f'SELECT * FROM {table} WHERE outcome_id=?', (OUTCOME,)).fetchall()
        for table in ('repair_intake', 'repair_intake_evidence'):
            data[table] = db.execute(f'SELECT * FROM {table} WHERE repair_key=?',
                                     (state['held_repair_key'],)).fetchall()
        if (state['status'] != 'PAUSED_BUDGET' or state['inference_session_open']
                or tuple(state[x] for x in ('sessions', 'calls', 'tokens')) != (7, 15, 118059)
                or len(data['inference_receipts']) != 15
                or any(row[2] != 'COMPLETED' for row in data['inference_receipts'])
                or not all(data.values())):
            raise ValueError('Unexpected #03 coordinator checkpoint')
        [receiver] = data['scrape_outcome_delivery_receipts']
        ack = Store._validate_delivery_receipt(
            receiver[2:7], consumer=receiver[0], canonical=source['record'], record_sha256=source['digest'])
        if json.loads(source['row'][6]) != ack:
            raise ValueError('Saved sender and receiver acknowledgements differ')

    capture_baseline(state)
    path = Path(__file__).with_name('PRIVATE_SAVED_FIXTURE.json')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
        json.dump({'rows': data, 'sender': source, 'enrollment': selected}, output)
    print('Saved exact private parent state, acknowledged sender and receiver, and 15 settled inference rows.')


def capture_baseline(parent):
    source = WRAPPER / 'pilot-bases' / ('embraer-' + parent['assignment_baseline']['digest'])
    destination = Path(__file__).with_name('saved-baseline')
    destination.mkdir(mode=0o700, exist_ok=False)
    for name, expected in parent['assignment_baseline']['manifest'].items():
        image = (source / name).read_bytes()
        if sha256(image).hexdigest() != expected:
            raise ValueError('The saved frozen baseline no longer matches')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(image)


if __name__ == '__main__':
    main()
