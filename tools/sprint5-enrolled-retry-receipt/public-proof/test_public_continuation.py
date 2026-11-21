"""One public dispatch through the exact disposable continuation."""
from contextlib import closing, contextmanager
from copy import deepcopy
from hashlib import sha256
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pytest

from job_search_helper import acquiretm, ats
from public_guard import MAX_POSTINGS, one_dispatch
from job_search_helper.company_events import current_company_source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import (JOURNAL_SCHEMA, MANIFEST_SCHEMA, config_tree_digest,
    digest, manifest_release_id, metadata, release_binding, source_tree_digest)
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RepairRetryBridge, retry_attempt_id, retry_request,
)
from job_search_helper.release_qualification import open_release_qualification_owner
from job_search_helper.repository import GoogleRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


def test_one_fresh_public_dispatch_to_exact_disposable_publication(tmp_path, monkeypatch):
    from job_search_helper.release_controller import continue_qualified_release_retry

    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
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
    projection = json.loads((evidence_root / 'SOURCE_PROJECTION.json').read_text())
    adapter_path = 'src/job_search_helper/acquiretm.py'
    source_sha = source_tree_digest(evidence_root)
    adapter_sha = sha256((evidence_root / adapter_path).read_bytes()).hexdigest()
    assert (source_sha, adapter_sha) == (projection['candidate_source_manifest_sha256'],
                                       projection['candidate_sha256'])
    existing_fixture = json.loads((evidence_root / 'original-last-scan-request.json').read_text())['repair_retry']
    verification = {'result': 'PASS', 'provenance': 'disposable-combined-harness-only', 'adapter_sha256': adapter_sha}
    after_file = metadata(evidence_root / adapter_path)
    manifest = {
        'schema': MANIFEST_SCHEMA, 'company_id': company_id,
        'source_revision': existing_fixture['source_revision'],
        'failed_request_id': existing_fixture['failed_request_id'],
        'files': {adapter_path: {'before': {**after_file, 'sha256': projection['before_sha256']}, 'after': after_file}},
        'before_source_manifest_sha256': projection['before_source_manifest_sha256'],
        'source_manifest_sha256': source_sha,
        'before_config_sha256': config_tree_digest(evidence_root),
        'config_sha256': config_tree_digest(evidence_root),
        'dependency_manifest_sha256': digest({'disposable-fixture-dependency-policy': 'system-python-plus-staged-dependencies'}),
        'validation_receipt_sha256': digest(verification),
    }
    manifest['release_id'] = manifest_release_id(manifest)
    release = release_binding(manifest)
    binding = {
        'schema': REPAIR_RETRY_SCHEMA, 'company_id': company_id, 'source_revision': manifest['source_revision'],
        'failed_request_id': manifest['failed_request_id'], 'release': release,
        'activated_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }
    binding['attempt_id'] = retry_attempt_id(binding)
    original_request = retry_request(binding, enqueued_at=binding['activated_at'])
    record = tmp_path / 'record'
    record.mkdir(mode=0o700)
    (record / 'manifest.json').write_text(json.dumps(manifest))
    receipt = {'state': 'COMPLETE', 'release_id': release['release_id'], 'release': release,
               'company_id': company_id, 'source_revision': binding['source_revision'],
               'failed_request_id': binding['failed_request_id'], 'activated_at': binding['activated_at'],
               'manifest_sha256': digest(manifest), 'verification': verification}
    (record / 'receipt.json').write_text(json.dumps(receipt))
    owner_path = tmp_path / 'disposable-qualification-owner'
    owner_path.mkdir(mode=0o700)
    owner_receipt = owner_path / (release['release_id'] + '.json')
    owner_receipt.write_text(json.dumps({
        'schema': 'integration-live-release-qualification-v1', 'result': 'PASS',
        'evidence_class': 'live_normal_dispatch', 'release_qualification': True,
        'manifest_sha256': digest(manifest), 'candidate_validation_sha256': digest(verification),
        'capture_manifest_sha256': digest({'test-only': True}), 'reviewed_tools_sha256': adapter_sha,
    }, sort_keys=True, separators=(',', ':')))
    owner_receipt.chmod(0o600)
    owner_receipt_sha = sha256(owner_receipt.read_bytes()).hexdigest()
    journal_path = tmp_path / 'integration-release-journal.json'
    journal_path.write_text(json.dumps({'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE', 'release_id': release['release_id'],
                                        'release': release, 'record': str(record), 'manifest_sha256': digest(manifest),
                                        'receipt_sha256': digest(receipt)}))
    journal_bytes = journal_path.read_bytes()
    fetch_calls, factory_calls = [], []
    observed = {}

    def fetch(provider, url, cid, name):
        assert not fetch_calls, 'Replay must not fetch a second time'
        assert (provider, url, cid, name) == ('AcquireTM', source, company_id, 'Amphenol Aerospace')
        with (evidence_root / 'PUBLIC_DISPATCH_SPENT').open('x') as attempt:
            attempt.write('One official AcquireTM dispatch admitted.\n')
        fetch_calls.append(cid)
        with one_dispatch(acquiretm, monkeypatch, observed):
            result = ats.fetch_inventory(provider, url, cid, name)
        observed.update(status=result.status, reason=result.reason, jobs=len(result.jobs),
                        source_url=result.source_url, source_manifest_sha256=source_sha)
        (evidence_root / 'PUBLIC_OBSERVATION.json').write_text(json.dumps(observed, indent=2) + '\n')
        if result.status == 'complete':
            assert observed['browser_closed'] and observed['tunnels'] > 0
            assert 1 <= len(result.jobs) <= MAX_POSTINGS
            assert observed['detail_requests'] == len(result.jobs)
            assert set(observed['advertised_totals']) == {len(result.jobs)}
            assert result.source_url == source and result.ats == 'AcquireTM'
            assert len({job['posting_id'] for job in result.jobs}) == len(result.jobs)
            assert all(len(job['description']) >= acquiretm.MIN_DESCRIPTION for job in result.jobs)
            payload = [{k: j[k] for k in ('posting_id', 'url', 'title', 'description')} for j in result.jobs]
            (evidence_root / 'PUBLIC_JOB_DIGEST.json').write_text(json.dumps(
                {'jobs': len(payload), 'full_inventory_projection_sha256': digest(payload)}, indent=2) + '\n')
        return result

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

        result = run_continuation()
        if result['state'] != 'COMPLETE':
            assert fetch_calls == [company_id]
            if observed['status'] != 'complete':
                assert not factory_calls and not fixture.batches and not jobs.scrape_outcomes()
            (evidence_root / 'COMPOSED_RESULT.json').write_text(json.dumps(
                {'disposition': result['state'], 'provider_dispatches': len(fetch_calls),
                 'workbook_factory_calls': len(factory_calls), 'fixture_remote_batches': len(fixture.batches),
                 'native_or_live_qualification': False}, indent=2) + '\n')
            pytest.fail('One scoped continuation held. No repeat was attempted.', pytrace=False)
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
        assert 0 < len(local_selected) == len(remote_selected) <= observed['jobs']
        assert {r['Job Key'] for r in local_selected} == {r['Job Key'] for r in remote_selected}
        assert [r for r in remote.read('Job History') if r.get('Job Key') == 'unrelated-job-key'] == remote_other_job
        assert [r for r in remote.read('Companies') if r.get('Company ID') == 'COMP-OTHER'] == remote_other_company
        assert fetch_calls == [company_id] and len(fixture.batches) >= 1
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
        batch_count = len(fixture.batches)
        replay = run_continuation()
        assert replay == result
        assert (tuple(jobs.db.iterdump()), tuple(inbox.connection.iterdump()), state.cycles()) == (
            jobs_before, inbox_before, state_before)
        assert fixture.sheets == workbook_before and len(fixture.batches) == batch_count
        assert fetch_calls == [company_id] and len(factory_calls) == 1 and not (tmp_path / 'next-scan.json').exists()
        evidence = {'disposition': 'PUBLIC_DISPATCH_DISPOSABLE_COMPOSED_PASS',
                    'public_inventory_jobs': observed['jobs'], 'adapter_sha256': adapter_sha, 'source_manifest_sha256': source_sha,
                    'filtered_local_jobs': len(local_selected), 'fixture_published_jobs': len(remote_selected),
                    'fixture_remote_batches': batch_count, 'public_dispatches': 1, 'browser_closed': observed['browser_closed'],
                    'remote_factory_calls': len(factory_calls), 'terminal_outcomes': 1,
                    'prior_cycle_job_company_preserved': True, 'replay_logically_unchanged': True,
                    'cycle_id': cycle['id'], 'attempt_id': binding['attempt_id'],
                    'outcome_id': outcomes[0]['outcome_id'],
                    'native_or_live_qualification': False}
        (Path(__file__).parent / 'COMPOSED_RESULT.json').write_text(json.dumps(evidence, indent=2) + '\n')
