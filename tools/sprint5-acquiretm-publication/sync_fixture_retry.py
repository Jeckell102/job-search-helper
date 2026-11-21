"""Publish exactly one saved repair-retry scope to the existing offline Sheets fixture."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
project = root/'test-project'
state_path = project/'.state/state.db'
state_root = state_path.parent
stage = Path('/tmp/jsh-s5-amphenol-receipt-choice.aH9Skdfa')
assembly = json.loads((root/'rehearsal-result.json').read_text())
if sys.argv[1:] != ['--sync-test-workbook']:
    raise SystemExit('Specify the isolated test-workbook sync explicitly')
assert (assembly['disposition'], assembly['state'], assembly['company_id']) == (
    'DISPOSABLE_RELEASE_AND_SCOPED_RETRY_QUEUE_REHEARSAL', 'REQUEST_WRITTEN', 'COMP-0490')
assert not (root/'fixture-sync-result.json').exists()
assert not (state_root/'next-scan.json').exists(), 'The exact deferred retry must run first'
raw_request = (state_root/'last-scan-request.json').read_bytes()
assert sha256(raw_request).hexdigest() == assembly['queued_request_sha256']
request = json.loads(raw_request)
assert request['company_ids'] == [assembly['company_id']]
assert request['repair_retry']['failed_request_id'] == assembly['failed_request_id']

os.environ['JOB_STORAGE_BACKEND'] = 'sqlite'
os.environ['SPREADSHEET_ID'] = 'sheet'
sys.path[:0] = [str(project/'src'), str(stage/'tests')]
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_recovery import recover_exact_cycle
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import (
    assert_active_release_binding, config_tree_digest, dependency_manifest_digest, source_tree_digest,
)
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets

release = request['repair_retry']['release']
assert_active_release_binding(state_root, release)
runtime = {'state': 'COMPLETE', 'release_id': release['release_id'],
           'source_manifest_sha256': source_tree_digest(project), 'config_sha256': config_tree_digest(project),
           'dependency_manifest_sha256': dependency_manifest_digest(project)}
assert all(runtime[key] == release[key] for key in ('source_manifest_sha256', 'config_sha256', 'dependency_manifest_sha256'))


def refuse_fetch(*_args, **_kwargs):
    raise RuntimeError('Exact fixture sync cannot fetch or replay the provider')


with (closing(State(str(state_path))) as state, closing(InventoryInbox(state_root/'inventories.sqlite3', 'sheet')) as inbox,
      closing(SQLiteRepository(state_root/'jobs.sqlite3', 'sheet')) as local):
    [cycle] = [item for item in state.cycles() if item.get('start_request_id') == request['request_id']]
    [predecessor] = [item for item in state.cycles() if item.get('start_request_id') == assembly['failed_request_id']]
    company_id = assembly['company_id']
    assert cycle['companies'].keys() == {company_id} and cycle['repair_retry'] == request['repair_retry']
    assert predecessor['status'] == 'Complete with exceptions'
    payload, blocked = inbox.get(cycle['id'], company_id)
    assert not blocked and payload['inventory_status'] == 'complete'
    assert not local.read('Job History') and not local.read('Job Evidence')
    baseline = {tab: local.read(tab) for tab in COMPACT_SCHEMAS if tab in {'Companies', 'Scan Cycles'}}
    fixture = RangeSheets(baseline, schemas=COMPACT_SCHEMAS)
    remote = GoogleRepository(fixture, 'sheet', schemas=COMPACT_SCHEMAS, min_request_interval=0)
    engine = Engine(local, state, inbox=inbox, fetcher=refuse_fetch, runtime_binding=runtime,
                    error_log_path=state_root/'fixture-sync-errors.jsonl')
    assert inbox.plan(cycle['id'], company_id) is None
    try:
        result = recover_exact_cycle(engine, remote, cycle['id'], [company_id])
    finally:
        (root/'fixture-workbook-readback.json').write_text(json.dumps(
            {'sheets': fixture.sheets, 'batches': fixture.batches}, sort_keys=True) + '\n')
    assert not result['held'] and len(result['confirmed']) == 1, json.dumps(result, sort_keys=True)
    assert state.cycle(predecessor['id']) == predecessor
    actual = state.cycle(cycle['id'])
    assert actual['companies'].keys() == {company_id} and actual['repair_retry'] == request['repair_retry']
    local_jobs = local.read('Job History')
    remote_jobs = remote.read('Job History')
    assert all(job['Company'] == 'Amphenol Aerospace' for job in local_jobs + remote_jobs)
    local_keys = {row['Job Key'] for row in local_jobs}
    remote_keys = {row['Job Key'] for row in remote_jobs}
    assert local_keys == remote_keys and len(local_keys) == len(local_jobs) == len(remote_jobs)
    assert local_keys, 'This positive scoped retry must actually save jobs in fixture storage'
    scoped = [(status, json.loads(binding)) for status, binding in inbox.connection.execute(
        "SELECT state,binding FROM publication_receipts WHERE json_extract(binding,'$.request_id')=? AND json_extract(binding,'$.company_id')=?",
        (request['request_id'], company_id))]
    assert len(scoped) == 1 and scoped[0][0] == 'SYNC_CONFIRMED'
    assert scoped[0][1]['release_id'] == release['release_id']
    record = {'disposition': 'DISPOSABLE_TEST_WORKBOOK_SYNC_CONFIRMED', 'cycle_id': cycle['id'],
              'attempt_id': assembly['attempt_id'], 'company_id': company_id,
              'inventory_count': len(payload['jobs']), 'local_jobs': len(local_jobs), 'fixture_sheet_jobs': len(remote_jobs),
              'fixture_write_batches': len(fixture.batches), 'release_id': release['release_id'],
              'predecessor_preserved': True, 'provider_refetched': False, 'publication_receipt_count': len(scoped)}
text = json.dumps(record, indent=2, sort_keys=True) + '\n'
(root/'fixture-sync-result.json').write_text(text)
print(text, end='')
