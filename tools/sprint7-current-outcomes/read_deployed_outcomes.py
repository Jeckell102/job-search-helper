"""Bind saved production outcome records to exact sender/receiver acknowledgements."""
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
STATE = PROJECT/'.state'
TOOLS = PROJECT/'dev/wrapper-coder/tools'
CONSUMER = 'repair-coordinator'
RELEASE = 'REL-4141919bb885000b0e7244c2'


def reader(path):
    return sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)


def main():
    sys.path[:0] = [str(PROJECT),str(PROJECT/'src'),str(TOOLS)]
    from release_admission_bootstrap import _load_environment, _validate_runtime
    from coordinator_store import Store, canonical_scrape_outcome
    from job_search_helper.engine import State

    _load_environment(PROJECT/'.env')
    runtime = _validate_runtime(PROJECT,STATE)
    assert runtime['state'] == 'COMPLETE' and runtime['release_id'] == RELEASE
    journal = STATE/'integration-release-journal.json'
    original = journal.read_bytes()

    with (closing(reader(STATE/'jobs.sqlite3')) as source,
          closing(reader(TOOLS.parent/'tasks/tasks.sqlite3')) as host,
          closing(State(str(STATE/'state.db'),readonly=True)) as state):
        source.execute('BEGIN')
        host.execute('BEGIN')
        rows = source.execute(
            'SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload '
            'FROM scrape_outcomes ORDER BY recorded_at,outcome_id'
        ).fetchall()
        proofs = []
        for outcome_id,request,company,revision,kind,action,raw in rows:
            record = json.loads(raw)
            identity = record['identity']
            assert canonical_scrape_outcome(record) == record
            assert (outcome_id,kind,action) == (record['outcome_id'],record['outcome'],record['action'])
            assert (request,company,revision) == (identity['request_id'],identity['company_id'],identity['source_revision'])
            canonical = json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=False)
            digest = sha256(canonical.encode()).hexdigest()
            sent = source.execute(
                'SELECT record_sha256,receipt,receipt_sha256 FROM scrape_outcome_delivery_receipts '
                'WHERE consumer=? AND outcome_id=?',(CONSUMER,outcome_id),
            ).fetchone()
            received = host.execute(
                'SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
                'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',(CONSUMER,outcome_id),
            ).fetchone()
            intake = host.execute(
                'SELECT company_id,source_revision,outcome,payload FROM scrape_outcome_intake WHERE outcome_id=?',
                (outcome_id,),
            ).fetchone()
            receipt = None
            if sent is not None and received is not None and intake is not None:
                receipt = Store._validate_delivery_receipt(received,consumer=CONSUMER,canonical=record,record_sha256=digest)
                Store._validate_delivery_intake(intake,canonical=record,
                    legacy_text=json.dumps(record,sort_keys=True,separators=(',',':')),record_sha256=digest)
                assert sent == (received[0],received[2],received[3])
            cycle_id = identity.get('cycle_id')
            cycle = state.cycle(cycle_id) if cycle_id else None
            item = (cycle or {}).get('companies',{}).get(company,{})
            zero_openings_flag = item.get('zero_openings_verified') is True
            proofs.append({'outcome_id':outcome_id,'cycle_id':cycle_id,'request_id':request,
                           'type':kind,'action':action,'record_sha256':digest,
                           'paired_receiver_receipt':receipt['sink_receipt_id'] if receipt else None,
                           'receiver_status':receipt['sink_status'] if receipt else None,
                           'cycle_verified_zero_flag':zero_openings_flag,
                           'cycle_runtime_release':(cycle or {}).get('runtime_binding',{}).get('release_id')})
        received_ids = {row[0] for row in host.execute('SELECT outcome_id FROM scrape_outcome_intake')}
    assert journal.read_bytes() == original
    print(json.dumps({'application_release':RELEASE,'source_sha256':runtime['source_manifest_sha256'],
                      'journal_sha256':sha256(original).hexdigest(),'read_only':True,
                      'producer_counts':dict(Counter(p['type'] for p in proofs)),
                      'paired_count':sum(p['paired_receiver_receipt'] is not None for p in proofs),
                      'receiver_orphan_count':len(received_ids-{p['outcome_id'] for p in proofs}),
                      'verified_zero_checkpoint_count':sum(p['cycle_verified_zero_flag'] for p in proofs),
                      'records':proofs},sort_keys=True))


if __name__ == '__main__':
    main()
