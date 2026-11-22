"""Use only existing authenticated task controls for the expired Embraer attempt."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
from urllib.request import Request, urlopen

BASE = Path('/home/chris/job-search-helper_old/dev/wrapper-coder')
TASK = 'WRAP-fbb9ff24d3'
OUTCOME = 'OUT-719882e9ec8b8ad044885426'
REQUEST = 'operator-embraer-20261122-01'
REQUEST_SHA = '19e7af99bd90d243f9b9f7465d5b6c38455ef99208cade05b7e1cfe5ca7536d2'
SOURCE_REVISION = 'c8e81ca1767c26d84912314b189c0387d855eaf64ee0fc1ae945020e6bcced95'
PAIRED_RECEIPT = 'd3964ed3d2f3d63adb17d0af72ce616a397a3c8e8a62676ed1711b15d5a24afb'
CONSUMER = 'repair-coordinator'
ACTIVATED = 1795373201.1956606
FORWARD_PIN = '9d3798a65d403743a84e4fee3783f86df1e80d9c2f9e5e8e16849aa8ffbcb48b'


def require_paired():
    def row(path):
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
            return db.execute('SELECT receipt,receipt_sha256 FROM scrape_outcome_delivery_receipts '
                              'WHERE outcome_id=? AND consumer=?',(OUTCOME,CONSUMER)).fetchone()
    jobs = BASE.parents[1]/'.state/jobs.sqlite3'
    source, receiver = row(jobs), row(BASE/'tasks/tasks.sqlite3')
    if (source != receiver or not source or source[1] != PAIRED_RECEIPT
            or sha256(source[0].encode()).hexdigest() != PAIRED_RECEIPT):
        raise ValueError('The original sender and receiver receipts do not match.')
    with sqlite3.connect(jobs.as_uri()+'?mode=ro', uri=True) as db:
        if not db.execute('SELECT 1 FROM scrape_outcome_deliveries WHERE outcome_id=? AND consumer=?',
                          (OUTCOME,CONSUMER)).fetchone():
            raise ValueError('The original sender delivery is not acknowledged.')


def snapshot():
    with sqlite3.connect((BASE/'tasks/tasks.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        state = json.loads(db.execute('SELECT state FROM tasks WHERE id=?',(TASK,)).fetchone()[0])
        settings = {key:json.loads(value) for key,value in db.execute(
            "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task')")}
        if (any(settings[key] is not False for key in ('queue_enabled','campaign_enabled','autopilot_enabled'))
                or settings['pilot_task'] not in (TASK,None)
                or db.execute("SELECT 1 FROM tasks WHERE json_extract(state,'$.status') IN ('RUNNING','QUEUED','PAUSING') LIMIT 1").fetchone()
                or db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone()
                or db.execute('SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1').fetchone()):
            raise ValueError('Coordinator is not quiescent under the exact stopped scope.')
        inference = db.execute('SELECT request_id,status,data FROM inference_receipts WHERE task=? ORDER BY request_id',(TASK,)).fetchall()
        tools = db.execute('SELECT * FROM receipts WHERE task=? ORDER BY id',(TASK,)).fetchall()
    provenance = state.get('repair_provenance') or {}
    if (state.get('activated_at') != ACTIVATED or state['phase'] != 'inspect'
            or provenance.get('outcome_id') != OUTCOME or provenance.get('company_id') != 'COMP-0634'
            or provenance.get('source_revision') != SOURCE_REVISION
            or state['mode'] != 'develop' or state['calls'] != 6 or state['sessions'] != 3
            or len(inference) != 6 or any(row[1] != 'COMPLETED' for row in inference)):
        raise ValueError('The original Embraer task or its accounted evidence changed.')
    return state, settings['pilot_task'], sha256(json.dumps([inference,tools],sort_keys=True).encode()).hexdigest()


def action(token, action, task=None):
    command = {'action':action}
    if task is not None:
        command['id'] = task
    request = Request('http://127.0.0.1:18789/coordinator',data=json.dumps(command).encode(),
                      headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urlopen(request, timeout=25) as response:
        value = json.load(response)
    if value.get('ok') is not True:
        raise ValueError('The installed coordinator rejected ' + action)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('operation', choices=('inspect','settle'))
    args = parser.parse_args()
    receipt_path = Path(__file__).resolve().parents[1]/'inspection-recovery/forward/transaction/receipt.json'
    receipt = receipt_path.read_bytes()
    forward = json.loads(receipt)
    transition = forward['transition']
    saved = transition['snapshot']
    enrollment = saved['enrollment']
    if (sha256(receipt).hexdigest() != FORWARD_PIN or forward['status'] != 'INSTALLED'
            or transition['task_id'] != TASK or saved['outcome_id'] != OUTCOME
            or saved['sender_receipt_sha256'] != PAIRED_RECEIPT
            or enrollment['request_id'] != REQUEST or enrollment['request_sha256'] != REQUEST_SHA
            or enrollment['source_revision'] != SOURCE_REVISION
            or sha256((BASE/'tools/coordinator.py').read_bytes()).hexdigest() != transition['after_sha256']):
        raise ValueError('The exact installed Embraer task and enrollment are required.')
    require_paired()
    original, slot, evidence = snapshot()
    if args.operation == 'inspect':
        print(json.dumps({'task':TASK,'status':original['status'],'remaining_seconds':ACTIVATED+3600-time.time(),
                          'pilot_task':slot,'receipt_rows_sha256':evidence},sort_keys=True))
        return
    if time.time() < ACTIVATED + 3600:
        raise ValueError('The exact installed Embraer task has not reached its original deadline.')
    token = (BASE/'bridge-token').read_text().strip()
    if original['status'] == 'PAUSED_BLOCKED' and original['stop_requested'] is False and slot == TASK:
        action(token, 'pause', TASK)
    stopped, slot, interim = snapshot()
    if (stopped['status'] != 'PAUSED' or stopped['stop_requested'] is not True
            or interim != evidence):
        raise ValueError('The authenticated pause did not preserve the original evidence.')
    if slot == TASK:
        action(token, 'pilot-stop')
    final, slot, after = snapshot()
    if final != stopped or slot is not None or after != evidence:
        raise ValueError('The pilot slot did not settle with the exact original attempt preserved.')
    require_paired()
    print(json.dumps({'task':TASK,'status':'PAUSED','stop_requested':True,'pilot_task':None,
                      'receipt_rows_sha256':evidence,'calls':6,'sessions':3,'activated_at':ACTIVATED},
                     sort_keys=True))


if __name__ == '__main__':
    main()
