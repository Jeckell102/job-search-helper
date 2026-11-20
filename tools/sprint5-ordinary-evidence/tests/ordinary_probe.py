"""Run the real normal worker against a disposable synthetic employer capture."""
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PIN = 'a69b02cd011f98d5dddde1c6faa10a621b87894829421a24aa60ce8fefcbed0b'
COMPANY_ID = 'COMP-0066'
REQUEST_ID = 's5-ordinary-forterra-fixture'
WORKBOOK_ID = 'S5_offline_fixture_only'
GROUP = ('source_configuration_mapping_fact', 'source_configuration_defect',
         'source_configuration_qualification_evidence')


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def digest(value):
    return sha256(encode(value)).hexdigest()


def run(installed, mode):
    assert installed.is_absolute() and installed.resolve() == installed
    assert installed.is_relative_to(ROOT / 'test-work')
    assert not (installed / '.env').exists()
    state_root = installed / '.state'
    state_root.mkdir(mode=0o700)
    assert not os.listdir(state_root)
    sys.path[:0] = [str(installed / 'src'), str(installed), str(ROOT / 'tests')]
    os.environ.update(JOB_STORAGE_BACKEND='sqlite', SPREADSHEET_ID=WORKBOOK_ID,
                      STATE_DB_FILE=str(state_root / 'state.db'), JOB_DB_FILE=str(state_root / 'jobs.sqlite3'))
    from job_search_helper import cli, runner, shared_boards
    from job_search_helper.ats import HTTPResponse
    from job_search_helper.company_events import source_revision
    from job_search_helper.engine import State
    from job_search_helper.repository import GoogleRepository
    from job_search_helper.run_sync import publish_pending
    from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
    from job_search_helper.sheets_sync import SheetsSynchronizer
    from job_search_helper.source_configuration_snapshot import (
        MAPPING_FACTS_PATH, QUALIFICATION_PATH, qualification_for_snapshot,
        read_source_configuration_mapping_facts, resolve_installed_source_configuration,
    )
    from job_search_helper.sqlite_repository import SQLiteRepository
    from sheets_fixture import RangeSheets

    assert Path(runner.__file__).is_relative_to(installed)
    raw = (ROOT / 'fixture_data/public-rippling.json').read_bytes()
    assert sha256(raw).hexdigest() == PUBLIC_PIN
    evidence = json.loads(raw)
    expected, responses = evidence['expected'], evidence['responses']
    company = {'Company ID': COMPANY_ID, 'Company': 'Forterra', 'Company Status': 'Active',
               'Official Careers URL': expected['employer_source'], 'ATS / Source': 'Rippling'}
    pdw = {'Company ID': 'COMP-0178', 'Company': 'PDW', 'Company Status': 'Active',
           'Official Careers URL': expected['pdw_board'], 'ATS / Source': 'Rippling'}
    network_attempts = []

    def deny_network(*args, **kwargs):
        network_attempts.append('network or OAuth factory attempted')
        raise AssertionError('all network and OAuth factories are forbidden in this fixture')

    class SyntheticHTTP:
        def __init__(self, urls):
            self.urls = urls
            self.calls = []

        def get(self, url):
            self.calls.append(url)
            assert url in self.urls, f'Unexpected offline request: {url}'
            return HTTPResponse(200, responses[url].encode())

    cases = (
        ('candidate', COMPANY_ID, company['Company'], expected['current_board'],
         expected['forterra_posting_id'], expected['forterra_role']),
        ('pdw_regression', pdw['Company ID'], pdw['Company'], expected['pdw_board'],
         expected['pdw_posting_id'], expected['pdw_role']),
    )
    independent = {}
    assert read_source_configuration_mapping_facts() == []
    with closing(SQLiteRepository(state_root / 'jobs.sqlite3', WORKBOOK_ID, initialize=True)) as base:
        base.set_meta('ready', 'yes')
        base.set_meta('sheets_profile', COMPACT_PROFILE)
        base.import_rows('Companies', [(2, company), (3, pdw)])
        installed_snapshot = resolve_installed_source_configuration(base, COMPANY_ID)
    assert installed_snapshot['configured_url'] == expected['stale_board']
    assert installed_snapshot['source_revision'] == source_revision(company)
    assert qualification_for_snapshot(installed_snapshot) is None
    if mode == 'reviewed':
        qualification = {key: installed_snapshot[key] for key in (
            'company_id', 'source_revision', 'capability_id', 'capability_digest',
            'mapping_digest', 'configuration_digest')}
        qualification.update(category='same_provider_source_mapping',
                             evidence_code='rippling_verified_mapping_divergence')
        (installed / QUALIFICATION_PATH).write_bytes(encode({
            'qualifications': [qualification], 'schema': 'source-configuration-qualification-v1'}))
        assert qualification_for_snapshot(installed_snapshot)['qualification'] == qualification
    else:
        assert mode == 'default-off'
    fragments_before = {name: sha256((installed / name).read_bytes()).hexdigest()
                        for name in (QUALIFICATION_PATH, MAPPING_FACTS_PATH)}
    requested = {'mode': 'company-only', 'company_ids': [COMPANY_ID], 'start_last': [],
                 'request_id': REQUEST_ID, 'source_revision': source_revision(company),
                 'enqueued_at': '2026-11-20T19:00:00Z'}
    (state_root / 'next-scan.json').write_bytes(encode(requested))

    pulled = SyntheticHTTP({expected['employer_source']})
    provider = SyntheticHTTP({expected['stale_board']})
    service = RangeSheets({'Companies': [company, pdw]}, schemas=COMPACT_SCHEMAS)
    fake_workbook = GoogleRepository(service, WORKBOOK_ID, schemas=COMPACT_SCHEMAS, min_request_interval=0)
    repo_factory = cli.get_repository
    run_scan = runner._run_scan_with_retries
    sync_stats = []

    class InlineWorkbook:
        totals = {}

        def __enter__(self):
            return self

        def __exit__(self, *error):
            pass

    def scoped_sync(repo, database, **options):
        assert database == state_root / 'state.db'
        assert repo.path == state_root / 'jobs.sqlite3'
        return InlineWorkbook()

    def drain_at_outcome_boundary(engine, cycle_id, **options):
        scanned = run_scan(engine, cycle_id, **options)
        assert scanned['attempted_company_ids'] == [COMPANY_ID]
        pending_before = engine.repo.status()['pending_cells']
        synchronizer = SheetsSynchronizer(engine.repo, fake_workbook)
        with cli.writer_lock(state_root / 'writer.lock'):
            confirmation = publish_pending(synchronizer, max_batches=25)
        assert pending_before > 0
        assert confirmation['pending_cells'] == 0 and confirmation['stop_reason'] == 'drained', confirmation
        assert engine.repo.status()['pending_cells'] == 0
        [(_, mirror)] = engine.repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
        assert mirror['Cycle Status'] == engine.state.cycle(cycle_id)['status']
        [remote_company] = [row for row in fake_workbook.read('Companies') if row['Company ID'] == COMPANY_ID]
        assert source_revision(remote_company) == source_revision(company)
        sync_stats.append({'pending_before': pending_before, 'pending_after': confirmation['pending_cells'],
                           'published_rows': confirmation['published_rows'], 'cycle_id': cycle_id,
                           'local_mirror_status': mirror['Cycle Status'],
                           'workbook_company_source_unchanged': True})
        return scanned

    def capture_repository(*args, **kwargs):
        opened = repo_factory(*args, **kwargs)
        owners.append(opened)
        return opened

    def stale_transport(board):
        boards.append(board.url)
        assert board.url == expected['stale_board'], board
        return provider

    boards, owners = [], []
    with patch.multiple(socket.socket, connect=deny_network, connect_ex=deny_network, bind=deny_network), \
            patch.multiple(socket, getaddrinfo=deny_network, create_connection=deny_network), \
            patch('job_search_helper.cli.authorize', deny_network), \
            patch('job_search_helper.cli.get_remote_repository', deny_network), \
            patch('job_search_helper.run_sync.run_scoped_sync', scoped_sync), \
            patch.object(runner, '_run_scan_with_retries', drain_at_outcome_boundary), \
            patch.object(runner, 'get_repository', side_effect=capture_repository), \
            patch.object(shared_boards, 'Transport', side_effect=stale_transport):
        discovered, ids = shared_boards.discover(expected['employer_source'], pulled)
        assert discovered.url == expected['current_board'] and discovered.name == 'Rippling' and ids is None
        assert pulled.calls == [expected['employer_source']]
        observed_wrong_slug = shared_boards.Scripts(responses[expected['stale_board']]).next()['apiData']['jobBoardSlug']
        assert observed_wrong_slug == expected['foreign_board_slug'] and observed_wrong_slug != discovered.slug
        for label, cid, name, board, posting, description in cases:
            full = board + '/' + posting
            verified = SyntheticHTTP({board, full})
            result = shared_boards.fetch_shared('Rippling', board, cid, name, transport=verified)
            assert result.status == 'complete', result.reason
            [job] = result.jobs
            assert job['posting_id'] == posting and job['url'] == full and description in job['description']
            assert verified.calls == [board, full, board]
            independent[label] = {'company_id': cid, 'board': board, 'posting_id': posting, 'calls': verified.calls,
                                  'inventory_sha256': digest(result.jobs)}
        independent['authority_extraction_sha256'] = digest({
            'employer_source': expected['employer_source'], 'employer_capture_sha256': sha256(
                responses[expected['employer_source']].encode()).hexdigest(), 'provider': discovered.name,
            'verified_board': discovered.url, 'observed_wrong_slug': observed_wrong_slug})
        try:
            status = runner.scrape_main(['start', '--no-browser-fallback', '--fetch-workers', '1',
                                         '--assignment-window', '1', '--partial-retries', '0'])
        finally:
            for repo in owners:
                repo.close()

    assert status == 0, f'normal worker exited {status}'
    assert not network_attempts
    assert boards == provider.calls == [expected['stale_board']]
    assert len(sync_stats) == 1 and sync_stats[0]['published_rows'] > 0
    assert not (state_root / 'next-scan.json').exists()
    assert json.loads((state_root / 'last-scan-request.json').read_bytes()) == requested
    with (closing(State(str(state_root / 'state.db'), readonly=True)) as state,
          closing(SQLiteRepository(state_root / 'jobs.sqlite3', WORKBOOK_ID, readonly=True)) as local):
        [cycle] = state.cycles()
        assert cycle['start_request_id'] == REQUEST_ID and cycle['all'] is False
        assert set(cycle['companies']) == {COMPANY_ID}
        assert not any(cycle.get(name) for name in ('company_event', 'operator_request', 'repair_retry'))
        item = cycle['companies'][COMPANY_ID]
        assert item['installed_source_configuration'] == installed_snapshot
        assert item['inventory_status'] == 'partial' and item.get('outcome_failure') is None, item
        _, current = local.matches('Companies', {'Company ID': COMPANY_ID})[0]
        assert current['Official Careers URL'] == expected['employer_source']
        assert source_revision(current) == source_revision(company)
        assert not local.read('Job History') and not local.read('Job Evidence')
        assert not fake_workbook.read('Job History')
        outcomes = local.scrape_outcomes()
        assert outcomes and all(value['identity']['cycle_id'] == cycle['id'] for value in outcomes)
        assert all(value['identity']['request_id'] == REQUEST_ID for value in outcomes)
        assert all(value['outcome'] != 'STORAGE_OR_SYNC_FAILURE' for value in outcomes)
        report = {'mode': mode, 'cycle_id': cycle['id'], 'runtime_binding': cycle['runtime_binding'],
                  'provider_requests': provider.calls, 'capture_sha256': PUBLIC_PIN,
                  'installed_snapshot': installed_snapshot,
                  'qualification': qualification_for_snapshot(installed_snapshot),
                  'group_fields': sorted(name for name in GROUP if name in item),
                  'mapping_fact_count': len(read_source_configuration_mapping_facts()),
                  'independent_proof': independent, 'outcomes': outcomes, 'fake_publication': sync_stats[0],
                  'descriptors_before': fragments_before, 'descriptors_after': {
                      name: sha256((installed / name).read_bytes()).hexdigest() for name in fragments_before},
                  'offline': {'forbidden_io_attempts': network_attempts, 'real_provider_requests': 0,
                              'real_workbook_requests': 0}}
    (installed / 'probe-evidence.json').write_bytes(encode(report))


if __name__ == '__main__':
    run(Path(sys.argv[1]), sys.argv[2])
