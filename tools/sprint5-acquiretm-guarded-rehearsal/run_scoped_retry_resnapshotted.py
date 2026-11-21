"""Run one explicitly enabled public fetch into the disposable retry inbox."""
from contextlib import closing, contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from types import ModuleType
from unittest.mock import patch


ROOT = Path('/tmp/jsh-s5-amphenol-release-rehearsal')
PROJECT = ROOT / 'test-project'
STATE = PROJECT / '.state'
ATTEMPT = 'RTRY-c1e879796b64630e034c7e64'
RELEASE = 'REL-c4bdcec9fadace26ad764349'
OUTCOME = 'OUT-cffecec610203a71e5c23b82'
COMPANY = 'COMP-0490'
BOARD = 'https://amphenol-aerospace.acquiretm.com/home.aspx'
DISPLAY = 'Amphenol Aerospace'
QUEUED_SHA = 'ae7c537ac1add18d617583b21cb23ffac238d3b2c737691a31c025d1fb5ef08f'
ADAPTER_SHA = '895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d'
BOOTSTRAP = Path('/tmp/jsh-s5-amphenol-receipt-choice.aH9Skdfa/release_admission_bootstrap.py')
BOOTSTRAP_SHA = 'c8a915a8311d74454d292a7f89a0f583b199a5a13832a89f00012cb99c0b500f'
MAX_POSTINGS = 75


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(data):
    return sha256(data).hexdigest()


def ordinary_file(path):
    info = path.lstat()
    require(path.resolve(strict=True) == path and stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            f'Unexpected file custody: {path.name}')
    return path


def pinned(path, expected):
    data = ordinary_file(path).read_bytes()
    require(sha(data) == expected, f'Unexpected evidence bytes: {path.name}')
    return data


@contextmanager
def scraper_lease():
    path = STATE / 'scraper.lock'
    fd = os.open(ordinary_file(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(os.path.samestat(os.fstat(fd), ordinary_file(path).stat()), 'Scraper lock changed.')
        yield
    finally:
        os.close(fd)


def measured_runtime():
    """Use the existing pre-import runtime checks with the exact rehearsal receipt."""
    journal_path = STATE / 'integration-release-journal.json'
    receipt_root = ROOT / 'records' / RELEASE
    journal = json.loads(pinned(journal_path, '43f7dbe1d301ac4ee1a2abea2dd635fb01f3265a8527edf40f52059d32cdb272'))
    require(journal['record'] == str(receipt_root), 'Release record must remain in this rehearsal.')
    pinned(receipt_root/'receipt.json', '5577b6bb78efafdcdf5716d84063f02d668a0882911879b6164b9cfbd92939ac')
    pinned(PROJECT/'src/job_search_helper/acquiretm.py', ADAPTER_SHA)
    bootstrap = ModuleType('release_admission_bootstrap')
    bootstrap.__file__ = str(BOOTSTRAP)
    exec(compile(pinned(BOOTSTRAP, BOOTSTRAP_SHA), str(BOOTSTRAP), 'exec'), vars(bootstrap))
    return bootstrap._validate_runtime(PROJECT, STATE)


def run_retry():
    for directory in (ROOT, PROJECT, STATE):
        info = directory.lstat()
        require(directory.resolve(strict=True) == directory and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                f'Expected private disposable directory: {directory.name}')
    os.environ['JOB_STORAGE_BACKEND'] = 'sqlite'
    os.environ['SPREADSHEET_ID'] = 'sheet'
    jobs_path, state_path = STATE/'jobs.sqlite3', STATE/'state.db'
    inbox_path = STATE/'inventories.sqlite3'
    queue_path = STATE/'next-scan.json'
    result_path = ROOT/'scoped-retry-result.json'
    with scraper_lease():
        require(not result_path.exists() and not result_path.is_symlink(), 'This retry already has a result.')
        rehearsal = json.loads(pinned(ROOT/'rehearsal-result.json', 'd467cdbc97206cd71b75205db6c2efc0c32e36d3740dcd2cef0d06c8c163e84b'))
        queued = json.loads(pinned(queue_path, QUEUED_SHA))
        intent = json.loads(pinned(STATE/f'repair-retry/intents/{ATTEMPT}.json',
                                   '362b43543abb26e815e52bca19b23219d8ea8a6ecd999a26ca236147b167f60b'))
        queue_receipt = json.loads(pinned(STATE/f'repair-retry/receipts/{ATTEMPT}.json',
                                           '7a303a49ba69ff23b91784353d67a01d974b641b766fadba1ebee3173b7f77dd'))
        runtime = measured_runtime()
        require(runtime['state'] == 'COMPLETE' and runtime['release_id'] == RELEASE
                and runtime['source_manifest_sha256'] == rehearsal['rehearsal_source_digest'],
                'Measured runtime does not match the exact rehearsal release.')

        sys.path.insert(0, str(PROJECT/'src'))
        from job_search_helper import acquiretm, ats, cli
        from job_search_helper.company_events import current_company_repair_snapshot
        from job_search_helper.engine import Engine, State
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.integration_release import assert_active_release_binding, digest
        from job_search_helper.ordinary_company_event_command import guard_generic_ordinary_event
        from job_search_helper.ordinary_event_settlement import ordinary_event_outcome_settled
        from job_search_helper.repair_retry import retry_request, validate_retry_request
        from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
        from job_search_helper.scan_request import requested_scan
        from job_search_helper.sqlite_repository import SQLiteRepository
        from playwright.sync_api import sync_playwright

        require(all(Path(module.__file__).resolve().is_relative_to(PROJECT/'src') for module in (acquiretm, ats, cli))
                and cli.PROJECT_ROOT == PROJECT and acquiretm.SOURCE == BOARD,
                'Provider and repository modules must come from the installed rehearsal.')
        require(callable(sync_playwright), 'The reviewed public adapter needs the installed Playwright runtime.')
        require(queued == retry_request(intent, enqueued_at=intent['activated_at'])
                and validate_retry_request(queued, [COMPANY]) == intent
                and queued['company_ids'] == [COMPANY] and queued['request_id'] == 'company-retry:' + ATTEMPT
                and queue_receipt['history'][-1]['request_sha256'] == digest(queued)
                and queue_receipt['state'] == 'REQUEST_ALREADY_DURABLE'
                and intent['failed_request_id'] == rehearsal['failed_request_id']
                and intent['source_revision'] == rehearsal['source_revision'], 'Exact retry lineage changed.')
        assert_active_release_binding(STATE, intent['release'])
        assert_normal_lifecycle_not_held(STATE, jobs_path)
        guard_generic_ordinary_event(state_path, fresh=True)
        for path in (jobs_path, state_path, inbox_path):
            ordinary_file(path)
        require(InventoryInbox.destination_id(inbox_path) == 'sheet', 'Fixture inbox destination changed.')

        calls = 0
        detail_reads = 0
        observed_totals = []
        parse_listing = acquiretm.parse_listing
        get_detail = acquiretm._DetailClient.get_body

        def bounded_listing(body):
            listing = parse_listing(body)
            total = listing[0]
            observed_totals.append(total)
            if not 1 <= total <= MAX_POSTINGS:
                raise ats.FetchError('partial', 'Public listing total is outside this positive-inventory rehearsal bound.')
            return listing

        def bounded_detail(client, url):
            nonlocal detail_reads
            if detail_reads >= MAX_POSTINGS:
                raise ats.FetchError('partial', 'Public detail work reached the exact scope bound.')
            detail_reads += 1
            return get_detail(client, url)

        def fetch(provider, url, company_id, company):
            nonlocal calls
            require(calls == 0 and (provider, url, company_id, company) == ('AcquireTM', BOARD, COMPANY, DISPLAY),
                    'Fetch must occur once for the exact Amphenol Company and board.')
            require(measured_runtime() == runtime, 'Installed runtime changed before the public fetch.')
            calls += 1
            return ats.fetch_inventory(provider, url, company_id, company)

        with (closing(SQLiteRepository(jobs_path, 'sheet')) as jobs,
              closing(State(str(state_path))) as state,
              closing(InventoryInbox(inbox_path, 'sheet')) as inbox):
            jobs.validate_schema()
            [previous] = jobs.scrape_outcomes()
            require(previous['outcome_id'] == OUTCOME and previous['identity']['request_id'] == intent['failed_request_id']
                    and ordinary_event_outcome_settled(jobs, previous), 'Owned predecessor no longer verifies.')
            company = current_company_repair_snapshot(jobs, COMPANY)
            require(company == {'company_id': COMPANY, 'company': DISPLAY, 'source_revision': intent['source_revision'],
                                'official_careers_url': BOARD, 'ats_source': 'acquiretm'}, 'Company source drifted.')
            require(not any(cycle.get('start_request_id') == queued['request_id'] for cycle in state.cycles()),
                    'Retry was already admitted. Keep the exact saved work for review.')
            require(not jobs.read('Job History') and not jobs.read('Job Evidence'), 'Unexpected pre-existing job rows.')
            engine = Engine(jobs, state, inbox=inbox, fetcher=fetch, runtime_binding=runtime,
                            error_log_path=STATE/'scoped-retry-errors.jsonl')
            cycle_id = requested_scan(engine, state, state_path)
            cycle = state.cycle(cycle_id)
            require(cycle['all'] is False and list(cycle['companies']) == [COMPANY]
                    and cycle['start_request_id'] == queued['request_id'] and cycle['repair_retry'] == intent
                    and cycle['runtime_binding'] == runtime and not queue_path.exists(), 'Admission scope changed.')
            pinned(STATE/'last-scan-request.json', QUEUED_SHA)
            with (patch.object(acquiretm, 'parse_listing', bounded_listing),
                  patch.object(acquiretm._DetailClient, 'get_body', bounded_detail)):
                local = engine.resume_local(cycle_id, fetch_workers=1, assignment_window=1,
                                            defer_sync=True, retry_company_ids={COMPANY})
            require(calls == 1 and local['attempted_company_ids'] == [COMPANY], 'Retry did not attempt the exact scope.')

        with (closing(SQLiteRepository(jobs_path, 'sheet', readonly=True)) as jobs,
              closing(State(str(state_path), readonly=True)) as state,
              closing(sqlite3.connect(inbox_path.as_uri() + '?mode=ro', uri=True)) as inbox):
            [(observed_company, payload_bytes, blocked)] = inbox.execute(
                'SELECT company,payload,blocked FROM inventories WHERE cycle=?', (cycle_id,),
            ).fetchall()
            require(observed_company == COMPANY and not inbox.execute(
                'SELECT 1 FROM sync_plans WHERE cycle=?', (cycle_id,),
            ).fetchone(), 'Deferred inventory does not match the retry scope.')
            require(not inbox.execute(
                "SELECT 1 FROM publication_receipts WHERE json_extract(binding,'$.request_id')=?",
                (queued['request_id'],),
            ).fetchone(), 'Unexpected publication receipt for a deferred run.')
            payload = json.loads(payload_bytes)
            cycle = state.cycle(cycle_id)
            item = cycle['companies'][COMPANY]
            require(not blocked and item.get('durable_inventory') is True and item['stage'] == 'inventory'
                    and payload['requested_url'] == payload['source_url'] == BOARD
                    and cycle['repair_retry'] == intent and cycle['runtime_binding'] == runtime,
                    'Exact inventory does not reopen after the local save.')
            require(not jobs.read('Job History') and not jobs.read('Job Evidence')
                    and jobs.scrape_outcomes() == [previous], 'Deferred run unexpectedly projected jobs or outcomes.')
            advertised_total = observed_totals[0] if observed_totals else None
            full = (payload['inventory_status'] == 'complete' and advertised_total is not None
                    and 0 < len(payload['jobs']) == detail_reads == advertised_total
                    and set(observed_totals) == {advertised_total})
            result = {
                'disposition': 'DISPOSABLE_SCOPED_RETRY_INVENTORY_SAVED' if full else 'DISPOSABLE_SCOPED_RETRY_INCOMPLETE_SAVED',
                'company_ids': [COMPANY], 'cycle_id': cycle_id, 'request_id': queued['request_id'],
                'request_sha256': QUEUED_SHA, 'retry_lineage': intent, 'predecessor_outcome_id': OUTCOME,
                'provider_calls': calls, 'detail_reads': detail_reads, 'inventory_jobs': len(payload['jobs']),
                'advertised_total': advertised_total, 'observed_advertised_totals': sorted(set(observed_totals)),
                'inventory_status': payload['inventory_status'], 'inventory_sha256': sha(payload_bytes.encode('utf-8')),
                'local_stage': item['stage'], 'work_remaining': ['job_filtering', 'job_row_planning', 'workbook_sync', 'publication_receipt'],
                'new_job_rows': 0, 'new_scrape_outcomes': 0, 'sheets_sync': 'DEFERRED',
                'provenance': 'live_public_provider_on_disposable_rehearsal_stores',
            }
        require(measured_runtime() == runtime, 'Installed runtime changed during the deferred retry.')
        with result_path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        print(result_path, flush=True)
        return 0 if full else 2


if __name__ == '__main__':
    if sys.argv[1:] != ['--run-one-public-retry']:
        raise SystemExit('Held by default. --run-one-public-retry explicitly enables one public Company fetch.')
    require(sys.flags.isolated and sys.dont_write_bytecode, 'Use an isolated Python interpreter with -I -B.')
    require(Path(__file__).resolve().parent == ROOT, 'Run this script from its private rehearsal path.')
    os.umask(0o077)
    raise SystemExit(run_retry())
