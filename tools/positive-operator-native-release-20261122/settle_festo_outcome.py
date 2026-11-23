"""Join the one confirmed Festo publication to the existing coordinator receipt."""

from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
TOOLS = PROJECT / 'dev/wrapper-coder/tools'
TASKS = TOOLS.parent / 'tasks'
STAGE = Path(__file__).resolve().parent
RELEASE = 'REL-03cc531d6c60113584d57722'
COMPANY = 'COMP-0560'
CYCLE = 'CYC-570964386014'
REQUEST = 'operator-company:festo-20261122-01'
REQUEST_DIGEST = 'c7ea41b3c1fa975e87babd00435dbfe4eef794a82ecb631fbf3ae496b2e1b3fe'


def no_inference(*args, **kwargs):
    raise RuntimeError('This selected completion has no inference permission.')


def settings_and_work(db):
    controls = {key: json.loads(value) for key, value in db.execute(
        "SELECT key,value FROM settings WHERE key IN ('queue_enabled','campaign_enabled','autopilot_enabled','pilot_task')"
    )}
    if any(controls[key] is not False for key in ('queue_enabled','campaign_enabled','autopilot_enabled')):
        raise ValueError('Expected the broad coordinator controls to remain off.')
    if db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone():
        raise ValueError('The coordinator has an unresolved inference.')
    tasks = db.execute('SELECT * FROM tasks ORDER BY id').fetchall()
    if any(json.loads(raw)['status'] in {'QUEUED','RUNNING','PAUSING'}
           for (raw,) in db.execute('SELECT state FROM tasks')):
        raise ValueError('Coordinator task activity prevents this selected delivery.')
    receipts = db.execute('SELECT * FROM inference_receipts ORDER BY rowid').fetchall()
    return controls, tasks, receipts


def main():
    sys.path[:0] = [str(PROJECT), str(PROJECT/'src'), str(TOOLS)]
    from release_admission_bootstrap import _load_environment, _validate_runtime
    from coordinator import Coordinator
    from coordinator_receipt_host_bridge import ManualReceiptV1HostBridge
    from coordinator_store import Store, canonical_scrape_outcome
    from job_search_helper.cli import writer_lock
    from job_search_helper.engine import State
    from job_search_helper.exact_cycle_receipt import positive_operator_receipt_binding
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.publication_receipts import receipt
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
    from job_search_helper.sqlite_repository import SQLiteRepository

    output = (STAGE/'FESTO_PUBLICATION.log').read_text()
    [line] = [line for line in output.splitlines() if line.startswith('Operator Company: ')]
    result = json.loads(line.removeprefix('Operator Company: '))
    assert (result['state'], result['cycle_id'], result['company_id']) == ('SYNC_CONFIRMED', CYCLE, COMPANY)
    outcome_id = result['outcome_id']
    _load_environment(PROJECT/'.env')
    with writer_lock(ROOT/'scraper.lock'), writer_lock(ROOT/'writer.lock'):
        assert _validate_runtime(PROJECT, ROOT)['release_id'] == RELEASE
        assert not (ROOT/'next-scan.json').exists()
        assert_normal_lifecycle_not_held(ROOT, ROOT/'jobs.sqlite3')
        destination = InventoryInbox.destination_id(ROOT/'inventories.sqlite3')
        with (closing(SQLiteRepository(ROOT/'jobs.sqlite3', destination)) as jobs,
              closing(State(str(ROOT/'state.db'), readonly=True)) as state,
              closing(sqlite3.connect((ROOT/'inventories.sqlite3').as_uri()+'?mode=ro', uri=True)) as inbox,
              closing(sqlite3.connect((TASKS/'tasks.sqlite3').as_uri()+'?mode=ro', uri=True)) as receiver):
            cycle = state.cycle(CYCLE)
            assert (cycle['status'], cycle['start_request_id'], cycle['runtime_binding']['release_id']) == ('Complete', REQUEST, RELEASE)
            assert set(cycle['companies']) == {COMPANY} and cycle.get('company_event') is None
            binding = positive_operator_receipt_binding(cycle, COMPANY)
            confirmation = receipt(inbox, binding)
            assert (confirmation['state'], confirmation['receipt_id']) == ('SYNC_CONFIRMED', result['receipt_id'])
            application = jobs.db.execute(
                'SELECT apply_id,plan_digest FROM exact_local_applications WHERE cycle=? AND company=?',
                (CYCLE, COMPANY),
            ).fetchall()
            [(apply_id, plan_digest)] = application
            InventoryInbox._verify_exact_local_acknowledgement(
                inbox, jobs, CYCLE, COMPANY, plan_digest, confirmation['receipt_id'],
                confirmation['acknowledgement_id'], expected_apply_id=apply_id,
            )
            row = jobs.db.execute(
                'SELECT request_id,company_id,outcome,action,payload FROM scrape_outcomes WHERE outcome_id=?',
                (outcome_id,),
            ).fetchone()
            assert row[:4] == (REQUEST, COMPANY, 'COMPLETE', 'save_without_repair')
            record = json.loads(row[4])
            assert canonical_scrape_outcome(record) == record
            before = settings_and_work(receiver)
            coordinator = Coordinator(base=TASKS, model=no_inference, budget=no_inference)
            bridge = ManualReceiptV1HostBridge(coordinator, lambda: jobs, enabled=True)
            delivered = bridge.manual_drain(outcome_id=outcome_id)
            assert delivered['results'] == [{'outcome_id': outcome_id, 'disposition': 'ACCEPTED'}]
            consumer = 'repair-coordinator'
            raw = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            digest = sha256(raw.encode()).hexdigest()
            sent = jobs.db.execute(
                'SELECT record_sha256,receipt,receipt_sha256 FROM scrape_outcome_delivery_receipts '
                'WHERE consumer=? AND outcome_id=?', (consumer, outcome_id),
            ).fetchone()
            received = receiver.execute(
                'SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
                'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?', (consumer, outcome_id),
            ).fetchone()
            match = Store._validate_delivery_receipt(received, consumer=consumer, canonical=record,
                                                     record_sha256=digest)
            assert sent == (received[0], received[2], received[3])
            assert match['sink_status'] == 'RECORDED_NO_REPAIR'
            assert settings_and_work(receiver) == before
            counts = Counter(label.partition(':')[0] for label in confirmation['records'])
            print(json.dumps({
                'release_id': RELEASE, 'request_id': REQUEST, 'request_sha256': REQUEST_DIGEST,
                'cycle_id': CYCLE, 'company_id': COMPANY, 'outcome_id': outcome_id,
                'source_revision': binding['source_revision'], 'receipt_id': confirmation['receipt_id'],
                'acknowledgement_id': confirmation['acknowledgement_id'],
                'receipt_record_counts': counts, 'receiver_receipt_id': match['sink_receipt_id'],
                'receiver_status': match['sink_status'], 'workbook_confirmation': confirmation['state'],
                'local_plan_digest': plan_digest, 'inference_changed': False,
            }, sort_keys=True))


if __name__ == '__main__':
    main()
