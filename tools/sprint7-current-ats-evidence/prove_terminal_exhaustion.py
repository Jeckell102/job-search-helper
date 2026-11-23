"""One offline exhaustion proof against a temporary SQLite backup of the deployed store."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PROJECT = Path('/home/chris/job-search-helper_old')
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
SOURCE = TOOLS.parent / 'tasks/tasks.sqlite3'
STORE_SHA = 'd65f1e0a37ba49cf6dcf721bd20cfe9f72017d028347f61130c22de25724ea4b'
PRIOR_QA = Path('/tmp/job-search-helper-integration-automation/temp/integration-coordinator/S6_OWNED_REPAIR_BUDGET_RESTART_QA_20261121.md')
PRIOR_QA_SHA = '87b7f4282b3560a7116bb8d5b46b2af9e244849134b01d09431b2242caceab7e'
PRIOR_RESULT = Path('/tmp/jsh-s6-budget-restart-independent.0BhVV9FN/budget-run-ukeuam89/RESULT.json')
PRIOR_RESULT_SHA = 'f32ff18643fa7102fe39bde25f4feafd8dca4478c1660e2be16f13b105ceb382'
COMPANY = 'COMP-0573'
REVISION = '08ecbb56e99f89bbcb63b60c5af1197c7535e9196a997135473370895e695a32'
FINGERPRINT = '9fdcfc10ac7273ab6e71f4e8552aab13397ae19ffcfe1234dbea61ace8d48125'
PINS = {
    'WRAP-9db6388719': {
        'outcome':'OUT-8b214610d53e23115e70da5f', 'key':'0d6846138372a12f8d52398a2124f220a0bf565e2cd16cae13bd6df06e71a5be',
        'state':'64d4ef964e53ea88bdd907d35b22532fceef7512a949217b5380d04382b8d96f',
        'inference':'3c4d4736fb2ae7b0e4bafb5465c747807f4dfe0c171b5f618056188130b4a76e',
        'tools':'33bd00f7e69c7b3372aa2ae6de7a0afeb2eb01564ef053b93a5d633b45b85769',
        'request':'22a2ecf17cf744298a39f10418af7f5c',
        'order':'successfactors-ats-sitemap-parser-v1', 'rejection':'A different operator successor already owns this predecessor repair.',
    },
    'WRAP-9546a1473a': {
        'outcome':'OUT-0f9f42286193d7caa8d22f98', 'key':'77d71a4dbb90ddbd10ee7b5ab7017672cdccd02296718f547fab8660f36c77ae',
        'state':'392db850644639308928460383fe673f1c124f3d634b9fac1cabbac373522f3e',
        'inference':'861893b1e84599435ab7171cd70b9a88eef0f765dccb025ba624e25035355932',
        'tools':'2445818013fe04f9f0ed7ae6237c6392fc4d309cc7f1f4baab5b5014f8f4ff13',
        'request':'4ca2e279ef434046b627d1c4c956235f',
        'order':'successfactors-ats-job-path-v1', 'rejection':'Predecessor task is not the exact stopped counted owner.',
    },
}
PILOT = 'WRAP-9546a1473a'
PROTECTED = ('tasks', 'inference_receipts', 'receipts', 'repair_intake',
             'repair_retry_lineage', 'repair_retry_lifecycles', 'repair_retry_outcome_events')
ADDITIVE = ('repair_intake_evidence', 'scrape_outcome_delivery_receipts', 'scrape_outcome_intake')


def check(value, reason):
    if not value:
        raise ValueError(reason)


def serial(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return sha256(serial(value)).hexdigest()


def offline(event, args):
    if event.startswith('socket.'):
        raise RuntimeError('Socket access forbidden for this proof.')


def snapshot(store, tables):
    result = {}
    with store.connect() as db:
        db.execute('BEGIN')
        for table in tables:
            h = sha256()
            count = 0
            for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid'):
                h.update(serial(row) + b'\n')
                count += 1
            result[table] = [count, h.hexdigest()]
    return result


def verify_history(store):
    from coordinator_store import task_state_digest

    for task, pin in PINS.items():
        state = store.get(task)
        calls = store.inference_receipts(task)
        check(state['status'] == 'PAUSED_TEST_FAILURE' and state['sessions'] == state['calls'] == len(calls) == 1
              and state['phase'] == 'verify' and state['integration']['work_order'] == pin['order']
              and state['held_repair_key'] == pin['key'] and state['repair_provenance']['outcome_id'] == pin['outcome']
              and task_state_digest(state) == pin['state'] and digest(calls) == pin['inference']
              and calls[0]['status'] == 'COMPLETED' and calls[0]['request_id'] == pin['request']
              and digest(store.receipts(task)) == pin['tools'], 'Pinned historical ATS evidence differs.')
    check(not store.unresolved_inferences(), 'Expected settled inference.')


def clone_store(folder):
    from coordinator_store import Store

    check(folder.resolve(strict=True) == folder and folder.parent == HERE and folder.name.startswith('copy-')
          and not folder.stat().st_mode & 0o077 and folder.stat().st_uid == os.geteuid(),
          'Expected a private disposable directory.')
    path = folder / 'tasks.sqlite3'
    check(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1
          and path.stat().st_uid == os.geteuid() and not path.samefile(SOURCE), 'Expected a private copy.')
    return Store(folder)


def controls(store, slot):
    with store.connect() as db:
        vals = {k: json.loads(v) for k,v in db.execute('SELECT key,value FROM settings')}
        check(vals.get('queue_enabled', True) is False and not vals.get('autopilot_enabled', False)
              and not vals.get('campaign_enabled', False) and vals['pilot_task'] == slot,
              'Control posture differs.')
        return vals['control_generation']


def synthetic(store):
    from coordinator_store import canonical_scrape_outcome

    with store.connect() as db:
        (raw,) = db.execute('SELECT payload FROM scrape_outcome_intake WHERE outcome_id=?', (PINS[PILOT]['outcome'],)).fetchone()
    record = canonical_scrape_outcome(json.loads(raw))
    check(record['failure_fingerprint'] == FINGERPRINT and record['identity']['source_revision'] == REVISION
          and record['identity']['company_id'] == COMPANY, 'Wrong original outcome.')
    record['identity'] = {**record['identity'], 'request_id':'operator-ats-disposable-exhaustion-proof-03',
                          'cycle_id':'CYC-D15C0A5E0003'}
    record['outcome_id'] = 'OUT-' + digest({k:v for k,v in record.items() if k not in ('outcome_id','action')})[:24]
    return canonical_scrape_outcome(record)


def evidence_link(store, record):
    with store.connect() as db:
        links = db.execute('SELECT repair_key FROM repair_intake_evidence WHERE outcome_id=?', (record['outcome_id'],)).fetchall()
        check(links == [(PINS['WRAP-9db6388719']['key'],)], 'Expected new evidence attached only to the original repair.')
        checks = db.execute('SELECT repair_key,task_id FROM repair_intake WHERE company_id=? AND source_revision=?',
                            (COMPANY, REVISION)).fetchall()
        check(set(checks) == {(v['key'],t) for t,v in PINS.items()}, 'Additional ATS owner.')


def reopen(folder, expected, attempt):
    from coordinator_store import OUTCOME_DELIVERY_CONSUMER

    store = clone_store(folder)
    verify_history(store)
    generation = controls(store, None)
    record = synthetic(store)
    evidence_link(store,record)
    before = snapshot(store, PROTECTED + ADDITIVE)
    check(digest(before) == expected, 'Store changed across fresh process reopen.')
    blocked = {}
    if attempt:
        receipt = store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, record)
        for task,pin in PINS.items():
            try:
                store.reserve_operator_repair_successor(predecessor_outcome_id=pin['outcome'], outcome_id=record['outcome_id'],
                    source_revision=REVISION, predecessor_repair_key=pin['key'], predecessor_task_id=task,
                    predecessor_task_state_sha256=pin['state'],company_id=COMPANY,failure_fingerprint=FINGERPRINT)
            except ValueError as exc:
                check(str(exc) == pin['rejection'], 'Reservation rejected for a different reason.')
                blocked[task] = str(exc)
            else:
                raise ValueError('Unexpected third repair owner.')
        verify_history(store)
        check(snapshot(store, PROTECTED + ADDITIVE) == before and controls(store,None) == generation,
              'Duplicate delivery or rejected reservations modified protected history.')
        return {'receipt_sha256':digest(receipt), 'refusals':blocked}
    return {'unchanged':True}


def child(folder, expected, mode):
    proc = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()), mode, str(folder), expected],
                          capture_output=True, text=True, check=False)
    if proc.returncode:
        raise RuntimeError('Disposable reopen failed: ' + proc.stderr.splitlines()[-1][:240])
    return json.loads(proc.stdout)


def main():
    from coordinator_store import OUTCOME_DELIVERY_CONSUMER

    for path,pin in ((PRIOR_QA,PRIOR_QA_SHA),(PRIOR_RESULT,PRIOR_RESULT_SHA)):
        check(sha256(path.read_bytes()).hexdigest() == pin, 'Prior distinct-owner proof changed.')
    for task,pin in PINS.items():
        for name,key in (('checkpoint.json','state'),('inference_receipts.json','inference'),('receipts.json','tools')):
            check(digest(json.loads((SOURCE.parent/task/name).read_bytes())) == pin[key], 'Original export differs.')
    with tempfile.TemporaryDirectory(prefix='copy-',dir=HERE) as temp:
        folder = Path(temp)
        check(SOURCE.resolve(strict=True) == SOURCE, 'Store path changed.')
        # SQLite may create a WAL index even for a read-only connection.
        # For a checkpointed database without sidecars, prohibit creation and
        # verify stable physical bytes surrounding the backup.
        sidecars = [Path(str(SOURCE) + suffix) for suffix in ('-wal', '-shm', '-journal')]
        checkpointed = not any(path.exists() for path in sidecars)
        if checkpointed:
            before_file = sha256(SOURCE.read_bytes()).hexdigest()
        else:
            check(sidecars[0].is_file() and sidecars[1].is_file() and not sidecars[2].exists(),
                  'Live WAL has no existing index; no production writes permitted.')
        flags = '?mode=ro&immutable=1' if checkpointed else '?mode=ro'
        with closing(sqlite3.connect(SOURCE.as_uri()+flags, uri=True)) as live:
            live.execute('PRAGMA query_only=ON')
            with closing(sqlite3.connect(folder/'tasks.sqlite3')) as copy:
                live.backup(copy)
        if checkpointed:
            check(not any(path.exists() for path in sidecars) and sha256(SOURCE.read_bytes()).hexdigest() == before_file,
                  'The checkpointed source changed during the immutable read.')
        store = clone_store(folder)
        verify_history(store)
        old_generation = controls(store,PILOT)
        before = snapshot(store, PROTECTED + ADDITIVE)
        stopped = store.stop_pilot()
        check(stopped['id'] == PILOT and controls(store,None) == old_generation+1, 'Unexpected pilot release.')
        record = synthetic(store)
        receipt = store.ingest_scrape_outcome_delivery_v1(OUTCOME_DELIVERY_CONSUMER, record)
        check(receipt['sink_status'] == 'HELD_FOR_REPAIR_TRIAGE', 'Unexpected delivery classification.')
        evidence_link(store,record)
        after = snapshot(store, PROTECTED + ADDITIVE)
        check(all(before[t] == after[t] for t in PROTECTED)
              and all(after[t][0] == before[t][0]+1 for t in ADDITIVE),'Unexpected ledger change.')
        denied = child(folder,digest(after),'attempt')
        check(denied['receipt_sha256'] == digest(receipt), 'Duplicate delivery returned a different receipt.')
        settled = child(folder,digest(after),'readback')
    check(not folder.exists(), 'Disposable store was retained.')
    result = {'state':'ACCEPT_DISPOSABLE_ATS_TERMINAL_EXHAUSTION', 'production_open':flags.lstrip('?'),
              'coordinator_store_sha256':STORE_SHA,'copy_removed':True,
              'pilot_stop':'terminal slot cleared; control generation advanced once',
              'pinned_tasks':{k:{f:v[f] for f in ('state','inference','request','tools')} for k,v in PINS.items()},
              'synthetic_delivery':{'receipt_sha256':digest(receipt),'identical_duplicate':True,
                 'added_rows':{t:1 for t in ADDITIVE}}, 'reservation_refusals':denied['refusals'],
              'protected_ledger_sha256':digest({t:after[t] for t in PROTECTED}),
              'new_repairs':0,'new_tasks':0,'new_inference_requests':0,'fresh_process_reopen':settled['unchanged'],
              'distinct_company_prior_result_sha256':PRIOR_RESULT_SHA,'distinct_company_prior_report':str(PRIOR_QA),
              'production_writes':0,'provider_calls':0,'model_calls':0}
    with (HERE/'RESULT.json').open('x') as out:
        json.dump(result,out,sort_keys=True,indent=2)
        out.write('\n')
    print(result['state'])


if __name__ == '__main__':
    os.umask(0o077)
    sys.addaudithook(offline)
    check(sys.flags.isolated and sys.flags.dont_write_bytecode, 'Run with isolated Python and no bytecode.')
    sys.path[:0] = [str(TOOLS), str(PROJECT/'src')]
    check(sha256((TOOLS/'coordinator_store.py').read_bytes()).hexdigest() == STORE_SHA,'Installed coordinator changed.')
    if len(sys.argv) == 1:
        main()
    elif len(sys.argv) == 4 and sys.argv[1] in ('attempt','readback'):
        print(json.dumps(reopen(Path(sys.argv[2]),sys.argv[3],sys.argv[1]=='attempt')))
    else:
        raise ValueError('Unexpected arguments.')
