"""One real application continuation, using captured public inventory offline."""
from contextlib import closing, contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import pytest

from job_search_helper.ats import Inventory
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import current_company_source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import JOURNAL_SCHEMA
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RELEASE_BINDING_SCHEMA, RepairRetryBridge, retry_attempt_id,
)
from job_search_helper.release_qualification import open_release_qualification_owner
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.scan_request import requested_scan
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


@pytest.mark.parametrize('case', ['positive', 'missing_intent', 'incomplete_inventory'])
def test_captured_amphenol_normal_continuation_and_replay(tmp_path, monkeypatch, case):
    from job_search_helper.release_controller import continue_qualified_release_retry

    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    archive = Path(__file__).parent / 'captured-retry-inventory.private.json'
    archive_sha = '94250320f27fbf987f417405599f609de6ea965feb41f1b6297cfee57dba5fa8'
    assert sha256(archive.read_bytes()).hexdigest() == archive_sha
    payload = json.loads(archive.read_text())
    assert len(payload['jobs']) == 39 and payload['inventory_status'] == 'complete'
    company_id = 'COMP-0490'
    source = 'https://amphenol-aerospace.acquiretm.com/home.aspx'
    company = {'Company ID': company_id, 'Company': 'Amphenol Aerospace',
               'Company Status': 'Active', 'ATS / Source': 'AcquireTM',
               'Official Careers URL': source}
    other_company = {'Company ID': 'COMP-OTHER', 'Company': 'Unrelated Company',
                     'Company Status': 'Active', 'ATS / Source': 'Greenhouse',
                     'Official Careers URL': 'https://example.test/unrelated'}
    other_job = {'Job Key': 'unrelated-job-key', 'Company': 'Unrelated Company',
                 'Job Title': 'Unrelated saved job', 'Job URL': 'https://example.test/job/1'}
    evidence_root = Path(__file__).parent
    original_request = json.loads((evidence_root / 'original-last-scan-request.json').read_text())
    binding = original_request['repair_retry']
    release = binding['release']
    journal = json.loads((evidence_root / 'original-integration-release-journal.json').read_text())
    journal['record'] = str(evidence_root / 'records' / release['release_id'])
    owner_path = evidence_root / 'fixture-qualification-owner'
    owner_receipt_sha = sha256((owner_path / (release['release_id'] + '.json')).read_bytes()).hexdigest()
    journal_path = tmp_path / 'integration-release-journal.json'
    journal_path.write_text(json.dumps(journal))
    journal_bytes = journal_path.read_bytes()
    fetch_calls, factory_calls = [], []

    def fetch(provider, url, cid, name):
        assert not fetch_calls, 'Replay must not fetch a second time'
        assert (provider, url, cid, name) == ('AcquireTM', source, company_id, 'Amphenol Aerospace')
        fetch_calls.append(cid)
        status = 'partial' if case == 'incomplete_inventory' else 'complete'
        return Inventory(status, deepcopy(payload['jobs']), payload['reason'], source, 'AcquireTM')

    with (closing(State(tmp_path / 'state.db')) as state,
          closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet', initialize=True)) as jobs,
          closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet')) as inbox):
        jobs.set_meta('ready', 'yes')
        jobs.set_meta('sheets_profile', COMPACT_PROFILE)
        jobs.ensure_columns('Opportunities', ['Opportunity ID'])
        jobs.import_rows('Companies', [(2, company), (3, other_company)])
        jobs.import_rows('Job History', [(2, other_job)])
        predecessor = {'id': 'CYC-PRIOR-INDEPENDENT', 'status': 'Complete', 'all': False,
                       'started_at': '2026-11-19T01:00:00Z',
                       'completed_at': '2026-11-19T01:01:00Z',
                       'companies': {'COMP-OTHER': {'stage': 'complete'}}}
        state.save_cycle(deepcopy(predecessor))
        prior_mirror = {'Cycle ID': predecessor['id'], 'Cycle Status': 'Complete',
                        'Started At': predecessor['started_at'], 'Completed At': predecessor['completed_at'],
                        'Notes': json.dumps({'all': False, 'company_ids': ['COMP-OTHER']})}
        jobs.import_rows('Scan Cycles', [(2, prior_mirror)])
        before_other_job = deepcopy(jobs.read('Job History')[0])
        before_other_company = deepcopy(jobs.read('Companies')[1])
        before_prior_mirror = deepcopy(jobs.read('Scan Cycles')[0])
        source_revision = lambda cid: current_company_source_revision(jobs, cid)
        assert source_revision(company_id) == binding['source_revision']
        engine = Engine(jobs, state, inbox=inbox, fetcher=fetch,
                        runtime_binding={'state': 'COMPLETE', **{k: v for k, v in release.items() if k != 'schema'}},
                        error_log_path=tmp_path / 'errors.jsonl')
        bridge = RepairRetryBridge(state.path, current_source_revision=source_revision)
        assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
        queued = (tmp_path / 'next-scan.json').read_bytes()
        fixture = RangeSheets({tab: jobs.read(tab) for tab in COMPACT_SCHEMAS
                               if tab in {'Companies', 'Scan Cycles', 'Job History'}}, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(fixture, 'sheet', schemas=COMPACT_SCHEMAS, min_request_interval=0)
        remote_other_job = deepcopy([r for r in remote.read('Job History')
                                     if r.get('Job Key') == 'unrelated-job-key'])
        remote_other_company = deepcopy([r for r in remote.read('Companies')
                                         if r.get('Company ID') == 'COMP-OTHER'])

        @contextmanager
        def remote_factory():
            factory_calls.append('opened')
            yield remote

        def run_continuation():
            stamp = owner_path.stat()
            descriptor = os.open(owner_path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                with open_release_qualification_owner(
                        owner_path, descriptor, expected_owner_identity=(stamp.st_dev, stamp.st_ino),
                        approved_receipt_sha256=owner_receipt_sha) as owner:
                    return continue_qualified_release_retry(
                        engine, state.path, binding, qualification_owner=owner, remote_factory=remote_factory)
            finally:
                os.close(descriptor)

        if case == 'missing_intent':
            (tmp_path / 'repair-retry/intents' / (binding['attempt_id'] + '.json')).unlink()
            before = (tuple(jobs.db.iterdump()), tuple(inbox.connection.iterdump()), state.cycles(),
                      (tmp_path / 'next-scan.json').read_bytes(), deepcopy(fixture.sheets))
            with pytest.raises(ValueError):
                run_continuation()
            assert (tuple(jobs.db.iterdump()), tuple(inbox.connection.iterdump()), state.cycles(),
                    (tmp_path / 'next-scan.json').read_bytes(), fixture.sheets) == before
            assert not fetch_calls and not factory_calls and not fixture.batches and not jobs.scrape_outcomes()
            return

        if case == 'incomplete_inventory':
            with writer_lock(tmp_path / 'scraper.lock'):
                cid = requested_scan(engine, state, Path(state.path), expected_repair_retry=binding)
                engine.resume_local(cid, defer_sync=True, fetch_workers=1, assignment_window=1)
            saved = inbox.get(cid, company_id)
            assert saved is not None and saved[0]['inventory_status'] == 'partial'
            before = (tuple(jobs.db.iterdump()), tuple(inbox.connection.iterdump()), state.cycles(),
                      deepcopy(fixture.sheets))
            assert run_continuation() == {'state': 'RETRY_INVENTORY_HELD', 'cycle_id': cid}
            assert (tuple(jobs.db.iterdump()), tuple(inbox.connection.iterdump()), state.cycles(),
                    fixture.sheets) == before
            assert fetch_calls == [company_id] and not factory_calls and not fixture.batches
            assert not jobs.scrape_outcomes() and inbox.get(cid, company_id) == saved
            return

        result = run_continuation()
        [cycle] = [c for c in state.cycles() if c['id'] != predecessor['id']]
        assert cycle['status'] == 'Complete' and cycle['repair_retry'] == binding
        assert result['state'] == 'COMPLETE' and result['cycle_id'] == cycle['id']
        assert cycle['companies'].keys() == {company_id}
        assert state.cycle(predecessor['id']) == predecessor
        assert jobs.matches('Scan Cycles', {'Cycle ID': predecessor['id']})[0][1] == before_prior_mirror
        assert jobs.matches('Companies', {'Company ID': 'COMP-OTHER'})[0][1] == before_other_company
        assert jobs.matches('Job History', {'Job Key': 'unrelated-job-key'})[0][1] == before_other_job
        local_selected = [r for r in jobs.read('Job History') if r.get('Company') == 'Amphenol Aerospace']
        remote_selected = [r for r in remote.read('Job History') if r.get('Company') == 'Amphenol Aerospace']
        assert len(local_selected) == len(remote_selected) == 18
        assert {r['Job Key'] for r in local_selected} == {r['Job Key'] for r in remote_selected}
        assert [r for r in remote.read('Job History') if r.get('Job Key') == 'unrelated-job-key'] == remote_other_job
        assert [r for r in remote.read('Companies') if r.get('Company ID') == 'COMP-OTHER'] == remote_other_company
        assert fetch_calls == [company_id] and len(fixture.batches) == 1
        assert (tmp_path / 'last-scan-request.json').read_bytes() == queued
        assert not (tmp_path / 'next-scan.json').exists()
        assert journal_path.read_bytes() == journal_bytes
        outcomes = jobs.scrape_outcomes()
        assert len(outcomes) == 1 and outcomes[0]['outcome'] == 'COMPLETE'
        assert outcomes[0]['identity']['attempt_id'] == binding['attempt_id']
        assert result['outcome'] == outcomes[0]
        receipts = inbox.connection.execute('SELECT state,binding FROM publication_receipts').fetchall()
        assert len(receipts) == 1 and receipts[0][0] == 'SYNC_CONFIRMED'
        receipt_binding = json.loads(receipts[0][1])
        assert receipt_binding['request_id'] == original_request['request_id']
        assert receipt_binding['release_id'] == release['release_id'] and receipt_binding['company_id'] == company_id
        jobs_before, inbox_before, state_before = (tuple(jobs.db.iterdump()),
                                                  tuple(inbox.connection.iterdump()), state.cycles())
        workbook_before = deepcopy(fixture.sheets)
        replay = run_continuation()
        assert replay == result
        assert (tuple(jobs.db.iterdump()), tuple(inbox.connection.iterdump()), state.cycles()) == (
            jobs_before, inbox_before, state_before)
        assert fixture.sheets == workbook_before and len(fixture.batches) == 1
        assert fetch_calls == [company_id] and len(factory_calls) == 1 and not (tmp_path / 'next-scan.json').exists()
        evidence = {'disposition': 'DISPOSABLE_COMPOSED_CONTINUATION_PASS',
                    'captured_inventory_jobs': 39, 'captured_sha256': archive_sha,
                    'filtered_local_jobs': 18, 'fixture_published_jobs': 18,
                    'fixture_remote_batches': 1, 'offline_fetch_calls': 1,
                    'remote_factory_calls': len(factory_calls), 'terminal_outcomes': 1,
                    'prior_cycle_job_company_preserved': True, 'replay_logically_unchanged': True,
                    'cycle_id': cycle['id'], 'attempt_id': binding['attempt_id'],
                    'outcome_id': outcomes[0]['outcome_id'],
                    'native_or_live_qualification': False}
        (Path(__file__).parent / 'COMPOSED_RESULT.json').write_text(json.dumps(evidence, indent=2) + '\n')
