"""Read-only proof that the real ATS restarts did not replay or change settled work."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
EVIDENCE = Path('/tmp/jsh-ats-classifier-release')
RELEASE = 'REL-4141919bb885000b0e7244c2'
CASES = (
    ('operator-ats-20261122-01', 'CYC-F0E884647EDC', 'OUT-8b214610d53e23115e70da5f',
     'WRAP-9db6388719', '22a2ecf17cf744298a39f10418af7f5c'),
    ('operator-ats-20261122-02', 'CYC-A9627ACE6C09', 'OUT-0f9f42286193d7caa8d22f98',
     'WRAP-9546a1473a', '4ca2e279ef434046b627d1c4c956235f'),
)


def read(path):
    return json.loads(path.read_bytes())


def open_read(path):
    return sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)


def rows_sha(rows):
    recorded = sha256()
    for row in rows:
        recorded.update(json.dumps(row, separators=(',', ':'), ensure_ascii=True).encode()+b'\n')
    return recorded.hexdigest()


def main():
    sys.path[:0] = [str(PROJECT),str(PROJECT/'src')]
    from release_admission_bootstrap import _load_environment, _validate_runtime
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.ordinary_event_settlement import _has_publication_evidence
    from job_search_helper.sqlite_repository import SQLiteRepository

    app = PROJECT/'.state'
    _load_environment(PROJECT/'.env')
    runtime = _validate_runtime(PROJECT,app)
    journal_path = app/'integration-release-journal.json'
    journal = journal_path.read_bytes()
    saved = read(EVIDENCE/'COORDINATOR_BEFORE.json')
    native = read(EVIDENCE/'active-window/native-window.json')
    quiet = read(EVIDENCE/'active-window/operator-quiet-window.json')
    activation = read(EVIDENCE/'activation/LIVE_ARM.json')
    assert runtime['state'] == 'COMPLETE' and runtime['release_id'] == RELEASE
    assert native['phase'] == quiet['phase'] == 'RESTORED' and native['terminal']['release_id'] == RELEASE
    assert activation == {'state':'ATS_PILOT_ARMED','wrapper_pid':803684}

    store = PROJECT/'dev/wrapper-coder/tasks/tasks.sqlite3'
    with closing(open_read(store)) as db:
        db.execute('BEGIN')
        cases = []
        exact_preserved = {}
        for table in ('tasks','receipts','inference_receipts'):
            prior = saved['tables'][table]
            prefix = db.execute(f'SELECT * FROM {table} ORDER BY rowid LIMIT ?', (prior['row_count'],)).fetchall()
            assert len(prefix) == prior['row_count'] and rows_sha(prefix) == prior['rows_sha256'], table
            exact_preserved[table] = prior
        for request_id, cycle_id, outcome_id, task_id, inference_id in CASES:
            [(task_row,)] = db.execute('SELECT state FROM tasks WHERE id=?',(task_id,)).fetchall()
            task = json.loads(task_row)
            assert task['status'] == 'PAUSED_TEST_FAILURE' and task['calls'] == task['sessions'] == 1
            assert task['repair_provenance']['outcome_id'] == outcome_id
            rows = db.execute('SELECT * FROM inference_receipts WHERE task=?',(task_id,)).fetchall()
            assert len(rows) == 1 and rows[0][:3] == (inference_id,task_id,'COMPLETED')
            assert db.execute('SELECT 1 FROM tasks WHERE id!=? AND json_extract(state,\'$.repair_provenance.outcome_id\')=?',(task_id,outcome_id)).fetchone() is None
            cases.append({'request_id':request_id,'cycle_id':cycle_id,'outcome_id':outcome_id,
                          'task_id':task_id,'task_sha256':sha256(task_row.encode()).hexdigest(),
                          'inference_id':inference_id,'inference_row_sha256':rows_sha(rows),'tokens':task['tokens'],
                          'terminal_status':task['status']})
        unresolved = db.execute("SELECT count(*) FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN')").fetchone()[0]
        controls = {k:json.loads(v) for k,v in db.execute("SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task')")}
        assert unresolved == 0 and controls == {'queue_enabled':False,'campaign_enabled':False,
                                               'autopilot_enabled':False,'pilot_task':CASES[1][3]}
    destination = InventoryInbox.destination_id(app/'inventories.sqlite3')
    with (closing(open_read(app/'inventories.sqlite3')) as inbox,
          closing(SQLiteRepository(app/'jobs.sqlite3',destination,readonly=True)) as jobs):
        for case in cases:
            assert not _has_publication_evidence(inbox,jobs,case['cycle_id'],case['request_id'])
            retry = jobs.db.execute(
                "SELECT 1 FROM scrape_outcomes WHERE json_extract(payload,'$.identity.failed_request_id')=? LIMIT 1",
                (case['request_id'],)).fetchone()
            assert retry is None
            case['publication_or_completed_retry'] = False
    assert journal_path.read_bytes() == journal
    print(json.dumps({'state':'VERIFIED_COMPLETED_RECEIPT_RESTART_CUSTODY','application_release':RELEASE,
                      'source_sha256':runtime['source_manifest_sha256'],'journal_sha256':sha256(journal).hexdigest(),
                      'activation_wrapper_pid':activation['wrapper_pid'],'completed_calls':cases,
                      'preserved_preinstall_table_prefixes':exact_preserved,'unresolved_calls':unresolved,
                      'controls':controls,'observational_only':True},sort_keys=True))


if __name__ == '__main__':
    main()
