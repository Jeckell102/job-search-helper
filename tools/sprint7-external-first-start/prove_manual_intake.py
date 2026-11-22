"""Exercise the copied public shell and ordinary intake with private stores."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import sys
from time import monotonic

from job_search_helper.company_events import BRIDGE_CONSUMER
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import source_tree_digest
from job_search_helper.repository import RepositoryError
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'candidate-source'
LIVE = Path('/home/chris/job-search-helper_old')
EXPECTED_SOURCE = '6790d8b388045ef6b32736944c6f78007ff158099d574d66e982825ab749cde5'
WORKBOOK = 'private-manual-intake-canary'
GUARD = ROOT / 'manual_intake_child.py'
HOLDS = {'multiple': ('Multiple new eligible Companies', 1),
         'stale_external': ('changed during manual discovery', 2),
         'alias': ('current or historical Company name', 1),
         'duplicate_name': ('current or historical Company name', 1),
         'blank_status': ('explicit Active status', 1),
         'missing_id': ('stable Company ID', 1)}


def run(scenario):
    project = ROOT / 'reviewed' / scenario / 'project'
    project.mkdir(parents=True)
    shutil.copytree(SOURCE / 'src', project / 'src')
    for name in ('release_admission_bootstrap.py', 'title-blacklist.txt', 'title-review-list.txt'):
        shutil.copy2(SOURCE / name, project / name)
    shutil.copy2(SOURCE / 'job-search-scraper', project / 'job-search-scraper')
    for name in ('sheets_fixture.py', 'test_batching.py', 'test_engine.py',
                 'test_repository.py', 'test_concurrent_review.py'):
        shutil.copy2(LIVE / 'tests' / name, project / name)
    (project / '.storage-backend').write_text('sqlite\n')
    assert source_tree_digest(project) == EXPECTED_SOURCE
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', project / '.venv'], check=True)
    site = next((project / '.venv/lib').glob('python*/site-packages'))
    shutil.copy2(GUARD, site / GUARD.name)
    (site / 'manual_scope_fixture.pth').write_text('import manual_intake_child\n')
    root = project / '.state'
    root.mkdir()
    database, jobs, inbox = [root / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3')]
    with closing(State(database)), closing(InventoryInbox(inbox, WORKBOOK)):
        pass

    def company(number):
        name = f'Manual intake fixture {number}'
        return {'Company': name, 'Company ID': f'COMP-900{number}', 'Company Status': 'Active',
                'Official Careers URL': f'https://boards.greenhouse.io/manual-intake-{number}', 'ATS / Source': 'Greenhouse'}

    with closing(SQLiteRepository(jobs, WORKBOOK, initialize=True)) as repo:
        repo.set_meta('ready', 'yes')
        repo.set_meta('sheets_profile', COMPACT_PROFILE)
        repo.ensure_columns('Opportunities', ['Opportunity ID'])
        old_cycle = None
        if scenario == 'busy_then_idle':
            [old] = repo.import_companies_with_events([(2, company(1))], origin='private-fixture')['company_events']
            repo.acknowledge_company_event(old['event_id'], BRIDGE_CONSUMER, source_revision=old['source_revision'])
            with closing(State(database)) as state:
                old_cycle = Engine(repo, state).start_cycle(company_ids=[old['company_id']])
        if scenario in HOLDS or scenario in {'sheets_only', 'sheets_only_jobs', 'no_addition'}:
            if scenario in {'no_addition', 'alias', 'duplicate_name'}:
                repo.import_rows('Companies', [(2, company(2 if scenario == 'no_addition' else 1))])
            if scenario == 'alias':
                [(rid, _)] = repo.matches('Companies', {'Company ID': company(1)['Company ID']})
                SheetsSynchronizer(repo, SimpleNamespace(spreadsheet_id=WORKBOOK))._remember_company_names(
                    rid, company(2)['Company'], company(1)['Company'])
                try:
                    repo.import_companies_with_events([(3, company(2))], require_new=True)
                except RepositoryError as exc:
                    assert 'already exists' in str(exc)
                else:
                    raise AssertionError('A direct insert-only import accepted a historical alias.')
            repo.bootstrap_company_event_reconciliation()
            assert repo.get_meta('company_event_external_baseline') == 'yes'
            assert repo.pending_latest_company_events(BRIDGE_CONSUMER) == []
        else:
            [event] = repo.import_companies_with_events([(3, company(2))], origin='private-fixture')['company_events']
            assert repo.pending_latest_company_events(BRIDGE_CONSUMER) == [event]

    (project / 'scenario').write_text(scenario)
    (project / 'private-company-fixture.json').write_text(json.dumps(company(2)))
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'SPREADSHEET_ID': WORKBOOK,
           'JOB_STORAGE_BACKEND': 'sqlite', 'JOB_DB_FILE': '.state/jobs.sqlite3', 'STATE_DB_FILE': '.state/state.db'}

    def launch():
        begin = monotonic()
        process = subprocess.run([project / 'job-search-scraper', 'start'], cwd=project,
                                 env=env, capture_output=True, text=True, timeout=12)
        assert not process.stderr, process.stderr
        [result] = [json.loads(line.removeprefix('Ordinary Company event: ')) for line in process.stdout.splitlines()
                    if line.startswith('Ordinary Company event: ')]
        return process.returncode, result, round(monotonic() - begin, 3)

    if scenario == 'no_addition' or scenario in HOLDS:
        process = subprocess.run([project / 'job-search-scraper', 'start'], cwd=project,
                                 env=env, capture_output=True, text=True, timeout=12)
        status, message, count = (0, 'PRESERVED_NORMAL_START', 1) if scenario == 'no_addition' else (1, *HOLDS[scenario])
        assert process.returncode == status and message in process.stdout + process.stderr, (
            process.stdout, process.stderr)
        assert not any((root / name).exists() for name in ('next-scan.json', 'provider-once'))
        assert (root / 'workbook-read').read_text().splitlines() == ['READ_ONLY'] * count
        with closing(SQLiteRepository(jobs, WORKBOOK, readonly=True)) as repo, closing(State(database, readonly=True)) as state:
            assert not repo.pending_latest_company_events(BRIDGE_CONSUMER)
            assert not repo.scrape_outcomes()
            assert len(repo.read('Companies')) == int(scenario in {'no_addition', 'alias', 'duplicate_name'})
            assert not state.cycles()
        return {'state': message, 'workbook_fixture_reads': count, 'provider_calls': 0, 'local_event_count': 0,
                'source_sha256': source_tree_digest(project)}

    evidence = {}
    if scenario in {'sheets_only', 'sheets_only_jobs'}:
        assert not (root / 'next-scan.json').exists()
        evidence['event_first_discovered_from_workbook'] = True
    if old_cycle is not None:
        status, result, elapsed = launch()
        assert status == 1 and result['bridge']['state'] == 'WAITING_FOR_UNFINISHED_CYCLE'
        assert not (root / 'next-scan.json').exists() and not (root / 'provider-once').exists()
        with (closing(SQLiteRepository(jobs, WORKBOOK)) as repo, closing(State(database)) as state):
            assert repo.pending_latest_company_events(BRIDGE_CONSUMER) == [event]
            assert not repo.scrape_outcomes(company_id=event['company_id'])
            previous = state.cycle(old_cycle)
            assert len(state.cycles()) == 1 and previous['status'] == 'In Progress'
            for item in previous['companies'].values():
                item['stage'] = 'complete'
            Engine(repo, state)._sync_cycle(previous)
            assert state.cycle(old_cycle)['status'] == 'Complete'
        evidence = {'busy_status': result['bridge']['state'], 'busy_elapsed_seconds': elapsed,
                    'fixture_blocking_cycle': old_cycle, 'event_preserved_while_busy': True}

    status, result, elapsed = launch()
    with_jobs = scenario == 'sheets_only_jobs'
    assert status == 0 and result['state'] == ('SYNC_CONFIRMED' if with_jobs else 'VERIFIED_ZERO'), result
    assert (root / 'provider-once').read_text() == company(2)['Company ID']
    workbook_reads = (root / 'workbook-read').read_text().splitlines()
    if with_jobs:
        assert workbook_reads.count('WRITE_FIXTURE') == 1
    else:
        assert workbook_reads == ['READ_ONLY'] * (4 if scenario == 'sheets_only' else 2)
    assert not (root / 'next-scan.json').exists()
    with (closing(SQLiteRepository(jobs, WORKBOOK, readonly=True)) as repo, closing(State(database, readonly=True)) as state):
        assert not repo.pending_latest_company_events(BRIDGE_CONSUMER)
        jobs_saved = repo.read('Job History')
        if with_jobs:
            assert len(jobs_saved) == len(repo.read('Job Evidence')) == 1
            publication = json.loads((root / 'fixture-publication.json').read_bytes())
            assert publication['batches'] == 1
            assert publication['job_keys'] == [jobs_saved[0]['Job Key']]
            assert result['binding']['cycle_id'] == result['cycle_id']
        else:
            assert jobs_saved == []
        [outcome] = repo.scrape_outcomes(company_id=company(2)['Company ID'])
        assert outcome['outcome'] == 'COMPLETE'
        assert outcome['identity']['request_id'].startswith('company-event:')
        cycle = state.cycle(outcome['identity']['cycle_id'])
        assert set(cycle['companies']) == {company(2)['Company ID']}
        assert cycle['runtime_binding']['source_manifest_sha256'] == EXPECTED_SOURCE
        if scenario in {'sheets_only', 'sheets_only_jobs'}:
            event = cycle['company_event']
            assert event['event_id'] == outcome['identity']['request_id'].removeprefix('company-event:')
            assert len(repo.read('Companies')) == 1 and repo.read('Companies')[0]['Company ID'] == company(2)['Company ID']
        if old_cycle is not None:
            assert state.cycle(old_cycle) == previous
    return {**evidence, 'manual_start_status': result['state'], 'manual_start_elapsed_seconds': elapsed,
            'event_id': event['event_id'], 'outcome_id': outcome['outcome_id'], 'cycle_id': cycle['id'],
            'company_count': 1, 'provider_fixture_calls': 1, 'workbook_fixture_reads': workbook_reads.count('READ_ONLY'),
            'workbook_fixture_writes': workbook_reads.count('WRITE_FIXTURE'), 'saved_job_count': len(jobs_saved),
            'source_sha256': source_tree_digest(project), 'launcher_sha256': sha256((project/'job-search-scraper').read_bytes()).hexdigest()}


if __name__ == '__main__':
    cases = ('sheets_only', 'sheets_only_jobs', 'no_addition', 'idle', 'busy_then_idle', *HOLDS)
    scenarios = sys.argv[1:] or cases
    assert set(scenarios) <= set(cases)
    report = {scenario: run(scenario) for scenario in scenarios}
    (ROOT / ('SHELL_RESULT_' + '_'.join(scenarios) + '.json')).write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps(report, sort_keys=True))
