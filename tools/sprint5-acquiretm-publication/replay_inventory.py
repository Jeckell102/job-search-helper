"""Admit the fresh test retry and replay one pinned public inventory offline."""
from contextlib import closing
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
archive = Path('/tmp/jsh-s5-amphenol-release-rehearsal/captured-retry-inventory.private.json')
archive_sha = '94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8'
bootstrap_path = Path('/tmp/jsh-s5-amphenol-receipt-choice.aH9Skdfa/release_admission_bootstrap.py')
bootstrap_sha = 'c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f'
source = 'https://amphenol-aerospace.acquiretm.com/home.aspx'
company_id = 'COMP-0490'

if sys.argv[1:] != ['--replay-exact-test-inventory']:
    raise SystemExit('Specify the isolated replay explicitly')
assert root == Path('/tmp/jsh-s5-amphenol-publication-rehearsal')
result = root/'scoped-retry-result.json'
assert not result.exists()
raw = archive.read_bytes()
assert sha256(raw).hexdigest() == archive_sha
payload = json.loads(raw)
assert payload['inventory_status'] == 'complete' and payload['requested_url'] == payload['source_url'] == source
assert payload['ats'] == 'AcquireTM' and not payload['browser_pending_urls'] and not payload['browser_discovery_incomplete']
assert payload['jobs']
assembly = json.loads((root/'rehearsal-result.json').read_text())
assert (assembly['disposition'], assembly['state'], assembly['company_id']) == (
    'DISPOSABLE_RELEASE_AND_SCOPED_RETRY_QUEUE_REHEARSAL', 'REQUEST_WRITTEN', company_id)
project = root/'test-project'
state_root = project/'.state'
state_path = state_root/'state.db'
queue = state_root/'next-scan.json'
queued_bytes = queue.read_bytes()
assert sha256(queued_bytes).hexdigest() == assembly['queued_request_sha256']
request = json.loads(queued_bytes)
assert request['company_ids'] == [company_id] and request['repair_retry']['failed_request_id'] == assembly['failed_request_id']
assert request['repair_retry']['attempt_id'] == assembly['attempt_id']
assert sha256(bootstrap_path.read_bytes()).hexdigest() == bootstrap_sha
os.environ['JOB_STORAGE_BACKEND'] = 'sqlite'
os.environ['SPREADSHEET_ID'] = 'sheet'
bootstrap_spec = importlib.util.spec_from_file_location('checked_release_bootstrap', bootstrap_path)
bootstrap = importlib.util.module_from_spec(bootstrap_spec)
bootstrap_spec.loader.exec_module(bootstrap)
runtime = bootstrap._validate_runtime(project, state_root)
assert runtime['release_id'] == assembly['release_id'] and runtime['state'] == 'COMPLETE'
sys.path.insert(0,str(project/'src'))
from job_search_helper.ats import Inventory
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.ordinary_company_event_command import guard_generic_ordinary_event
from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
from job_search_helper.scan_request import requested_scan
from job_search_helper.sqlite_repository import SQLiteRepository

calls = []


def fetch(provider, url, cid, name):
    assert not calls and (provider, url, cid, name) == ('AcquireTM', source, company_id, 'Amphenol Aerospace')
    calls.append(cid)
    return Inventory('complete', payload['jobs'], payload['reason'], source, 'AcquireTM')


with (writer_lock(state_root/'scraper.lock'), closing(State(str(state_path))) as state,
      closing(InventoryInbox(state_root/'inventories.sqlite3', 'sheet')) as inbox,
      closing(SQLiteRepository(state_root/'jobs.sqlite3', 'sheet')) as jobs):
    assert_normal_lifecycle_not_held(state_root, jobs.path)
    guard_generic_ordinary_event(state_path, fresh=True)
    assert queue.read_bytes() == queued_bytes
    assert not jobs.read('Job History') and not jobs.read('Job Evidence')
    engine = Engine(jobs, state, inbox=inbox, fetcher=fetch, runtime_binding=runtime,
                    error_log_path=state_root/'fixture-replay-errors.jsonl')
    cycle_id = requested_scan(engine, state, state_path)
    cycle = state.cycle(cycle_id)
    assert cycle['all'] is False and cycle['companies'].keys() == {company_id}
    assert cycle['repair_retry'] == request['repair_retry'] and cycle['start_request_id'] == request['request_id']
    progress = engine.resume_local(cycle_id, fetch_workers=1, assignment_window=1,
                                  defer_sync=True, retry_company_ids={company_id})
    saved, blocked = inbox.get(cycle_id, company_id)
    assert not blocked and saved['jobs'] == payload['jobs'] and saved['inventory_status'] == 'complete'
    assert progress['attempted_company_ids'] == calls == [company_id]
    assert state.cycle(cycle_id)['companies'][company_id]['stage'] == 'inventory'
    assert not queue.exists() and (state_root/'last-scan-request.json').read_bytes() == queued_bytes
    record = {'disposition': 'DISPOSABLE_EXACT_RETRY_CAPTURE_REPLAY', 'cycle_id': cycle_id,
              'request_id': request['request_id'], 'inventory_jobs': len(saved['jobs']),
              'captured_payload_sha256': archive_sha, 'remote_provider_calls': 0, 'sheets_sync': 'DEFERRED'}
result.write_text(json.dumps(record, sort_keys=True, indent=2) + '\n')
print(json.dumps(record, sort_keys=True), flush=True)
