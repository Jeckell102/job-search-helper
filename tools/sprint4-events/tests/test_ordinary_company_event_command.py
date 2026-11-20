"""Offline command, factory ownership and launcher checks for ordinary events."""
from contextlib import closing, contextmanager
import fcntl
import json
import os
from pathlib import Path
import socket
from subprocess import run
from unittest.mock import Mock

import pytest

import release_admission_bootstrap as bootstrap
from job_search_helper import ats, cli, runner
from job_search_helper import ordinary_company_event_command as command
from job_search_helper import ordinary_company_event_publication as publication
from job_search_helper.company_events import CompanyEventBridge, _json_digest
from job_search_helper.engine import State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import GoogleRepository
from job_search_helper.scan_request import request_fingerprint
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets
from test_ordinary_company_event_fetch import BOARD, COMPANY, OBSERVED, RUNTIME


POSTING = {
    'posting_id': '42', 'title': 'Implementation Manager', 'ats': 'Lever',
    'url': 'https://jobs.eu.lever.co/acme/42', 'location': 'Berlin, Germany',
    'description': 'Customer-facing implementation and deployment work.',
}
OLD = 'CYC-000000000001'


@pytest.fixture
def queued(tmp_path, monkeypatch, request):
    def network(*args, **kwargs):
        pytest.fail('command fixture attempted a network connection')

    monkeypatch.setattr(socket.socket, 'connect', network)
    monkeypatch.setattr(socket.socket, 'connect_ex', network)
    greenhouse = getattr(request, 'param', None) == 'greenhouse'
    company = ({**COMPANY, 'ATS / Source': 'Greenhouse',
                'Official Careers URL': 'https://job-boards.greenhouse.io/previous'}
               if greenhouse else COMPANY)
    board = 'https://job-boards.greenhouse.io/fixture' if greenhouse else BOARD
    paths = (tmp_path / 'state.db', tmp_path / 'jobs.sqlite3', RUNTIME)
    monkeypatch.setenv('STATE_DB_FILE', str(paths[0]))
    monkeypatch.setenv('JOB_DB_FILE', str(paths[1]))
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    monkeypatch.setenv('SPREADSHEET_ID', 'sheet')
    with (closing(State(str(paths[0]))), closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet')),
          closing(SQLiteRepository(paths[1], 'sheet', initialize=True)) as local):
        local.set_meta('ready', 'yes')
        local.set_meta('sheets_profile', COMPACT_PROFILE)
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        local.import_rows('Companies', [(2, company), (3, {**company, 'Company ID': 'COMP-2', 'Company': 'Other'})])
        local.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Official Careers URL': board},
        })
        CompanyEventBridge(local, tmp_path).process_pending()
    request = json.loads((tmp_path / 'next-scan.json').read_bytes())
    provider = Mock(return_value=ats.Inventory('complete', jobs=[POSTING], source_url=OBSERVED, ats='Lever'))
    monkeypatch.setattr(ats, 'fetch_inventory', provider)
    remote = GoogleRepository(
        RangeSheets({'Companies': [{**company, 'Official Careers URL': board}]}, schemas=COMPACT_SCHEMAS),
        'sheet', schemas=COMPACT_SCHEMAS, min_request_interval=0,
    )

    def workbook(*, write, interactive, schemas, evidence_archives):
        assert type(write) is bool
        assert not interactive and not evidence_archives and schemas == COMPACT_SCHEMAS
        for name in ('scraper.lock', 'writer.lock'):
            with pytest.raises(cli.WriterLockBusy):
                with cli.writer_lock(tmp_path / name):
                    pytest.fail('scoped command did not own ' + name)
        return remote

    factory = Mock(side_effect=workbook)
    monkeypatch.setattr(cli, 'get_remote_repository', factory)
    writers = Mock(wraps=command._open_engine)
    monkeypatch.setattr(command, '_open_engine', writers)
    monkeypatch.setattr(runner, '_load_environment', lambda: None)
    return paths, request, _json_digest(request), provider, factory, remote, writers


def execute(queued, action='admit-fetch', *, cycle_id=None, digest=None):
    paths, _, expected, *_ = queued
    with cli.writer_lock(paths[0].parent / 'scraper.lock'):
        return command.execute_ordinary_event(
            action, paths, request_sha256=expected if digest is None else digest, cycle_id=cycle_id,
        )


def test_idle_exact_admission_freezes_once_and_preserves_new_queue_on_replay(queued):
    paths, request, digest, provider, factory, remote, writers = queued
    root = paths[0].parent
    result = execute(queued)
    cycle_id = result['cycle_id']
    assert result['state'] == 'INVENTORY_FROZEN'
    assert result['request_sha256'] == digest
    assert not (root / 'next-scan.json').exists()
    assert json.loads((root / 'last-scan-request.json').read_bytes()) == request
    assert json.loads((root / 'company-event-bridge/ordinary-admissions' / f'{digest}.json').read_bytes()) == request
    with closing(State(str(paths[0]), readonly=True)) as state:
        assert [cycle['id'] for cycle in state.cycles()] == [cycle_id]
        assert set(state.cycle(cycle_id)['companies']) == {'COMP-1'}
    provider.assert_called_once_with('Lever', BOARD, 'COMP-1', 'Fixture')
    factory.assert_called_once_with(write=False, interactive=False, schemas=COMPACT_SCHEMAS, evidence_archives=False)
    writers.assert_called_once()
    assert not remote.service.batches
    assert not (root / 'scrape-first-pass').exists()
    (root / 'last-scan-request.json').write_text('{}')
    competing = b'{"mode":"fresh-full-scan","request_id":"COMPETING"}\n'
    (root / 'next-scan.json').write_bytes(competing)
    assert execute(queued, cycle_id=cycle_id) == {**result, 'recovered': True}
    assert execute(queued) == {**result, 'recovered': True}
    assert (root / 'next-scan.json').read_bytes() == competing
    assert (root / 'last-scan-request.json').read_bytes() == b'{}'
    provider.assert_called_once()
    factory.assert_called_once()
    writers.assert_called_once()


@pytest.mark.parametrize('blocking', ['state', 'mirror', 'writer'])
def test_busy_and_foreign_scopes_hold_before_any_factory(queued, blocking):
    paths, request, _, provider, factory, _, writers = queued
    root = paths[0].parent
    with pytest.raises(ValueError, match='matches the exact digest'):
        execute(queued, digest='0' * 64)
    with pytest.raises(ValueError, match='conflicting cycle evidence'):
        execute(queued, cycle_id=OLD)
    with pytest.raises(ValueError, match='exact request digest and cycle'):
        execute(queued, 'publish', cycle_id='CYC-RFOREIGN0000')
    if blocking == 'state':
        with closing(State(str(paths[0]))) as state:
            state.save_cycle({'id': OLD, 'status': 'In Progress', 'companies': {'COMP-2': {'stage': 'queued'}}})
        with pytest.raises(ValueError, match='held behind unfinished'):
            execute(queued)
    elif blocking == 'mirror':
        with closing(SQLiteRepository(paths[1], 'sheet')) as local:
            local.import_rows('Scan Cycles', [(2, {'Cycle ID': OLD, 'Cycle Status': 'In Progress'})])
        with pytest.raises(ValueError, match='held behind unfinished'):
            execute(queued)
    else:
        with cli.writer_lock(root / 'writer.lock'), pytest.raises(cli.WriterLockBusy):
            execute(queued)
    assert json.loads((root / 'next-scan.json').read_bytes()) == request
    provider.assert_not_called()
    factory.assert_not_called()
    writers.assert_not_called()


def test_after_admission_before_queue_consumption_restart_reuses_same_cycle(queued, monkeypatch):
    paths, request, _, provider, factory, _, writers = queued
    original = command.requested_scan

    def interrupt_after_membership(engine, state, database):
        event_request = {**request, 'request_fingerprint': request_fingerprint(request, ['COMP-1'])}
        engine.start_cycle(company_ids=['COMP-1'], new_scan_request=event_request)
        raise RuntimeError('synthetic interruption before archive')

    with monkeypatch.context() as interrupted:
        interrupted.setattr(command, 'requested_scan', interrupt_after_membership)
        with pytest.raises(RuntimeError, match='before archive'):
            execute(queued)
    assert command.requested_scan is original
    with closing(State(str(paths[0]), readonly=True)) as state:
        [cycle_id] = [cycle['id'] for cycle in state.cycles()]
    provider.assert_not_called()
    factory.assert_not_called()
    with closing(State(str(paths[0]))) as state:
        saved = state.cycle(cycle_id)
        forged = state.cycle(cycle_id)
        forged['companies']['COMP-1']['outcome_source_fact']['ats_source'] = 'other'
        state.save_cycle(forged)
    with pytest.raises(ValueError, match='requires reconciliation'):
        execute(queued, cycle_id=cycle_id)
    assert writers.call_count == 1
    provider.assert_not_called()
    factory.assert_not_called()
    with closing(State(str(paths[0]))) as state:
        state.save_cycle(saved)
    result = execute(queued, cycle_id=cycle_id)
    assert result['cycle_id'] == cycle_id
    assert result['state'] == 'INVENTORY_FROZEN'
    with closing(State(str(paths[0]), readonly=True)) as state:
        assert [cycle['id'] for cycle in state.cycles()] == [cycle_id]
    provider.assert_called_once()
    factory.assert_called_once()
    assert writers.call_count == 2


def test_fetch_interruption_holds_and_publish_refuses_unfrozen_cycle(queued):
    paths, _, _, provider, factory, _, writers = queued
    provider.side_effect = RuntimeError('synthetic provider interruption')
    with pytest.raises(RuntimeError, match='provider interruption'):
        execute(queued)
    with closing(State(str(paths[0]), readonly=True)) as state:
        [cycle_id] = [cycle['id'] for cycle in state.cycles()]
    result = execute(queued, cycle_id=cycle_id)
    assert result['state'] == 'HELD_FETCH_UNCERTAIN'
    with pytest.raises(ValueError, match='no verified frozen provider observation'):
        execute(queued, 'publish', cycle_id=cycle_id)
    writers.assert_called_once()
    provider.assert_called_once()
    factory.assert_called_once()


def test_explicit_publish_reuses_exact_route_and_never_refetches(queued):
    _, _, _, provider, factory, remote, writers = queued
    observed = execute(queued)
    cycle_id = observed['cycle_id']
    result = execute(queued, 'publish', cycle_id=cycle_id)
    assert result['state'] == 'SYNC_CONFIRMED'
    assert result['outcome']['identity']['cycle_id'] == cycle_id
    assert len(remote.service.batches) == 1
    assert [call.kwargs['write'] for call in factory.call_args_list] == [False, True]
    assert execute(queued, 'publish', cycle_id=cycle_id) == result
    assert len(remote.service.batches) == 1
    assert [call.kwargs['write'] for call in factory.call_args_list] == [False, True]
    assert [call.kwargs.get('publication', False) for call in writers.call_args_list] == [False, True, True]
    provider.assert_called_once()


@pytest.mark.parametrize(('inventory', 'settled'), [
    (ats.Inventory('blocked', jobs=[], source_url=OBSERVED, ats='Lever',
                   outcome_failure=ats.outcome_failure('access_denied', 'public_access_denied')),
     'FETCH_BLOCKED'),
    (ats.Inventory('failed', source_url=OBSERVED, ats='Lever',
                   outcome_failure=ats.outcome_failure('temporary_transport', 'retryable_http_status')),
     'FETCH_TEMPORARY'),
])
def test_terminal_branch_gives_settlement_only_a_compact_reader(queued, monkeypatch, inventory, settled):
    _, _, _, provider, factory, remote, _ = queued
    provider.return_value = inventory
    cycle_id = execute(queued)['cycle_id']

    def fixture_settlement(engine, remote_writer, *, cycle_id, request_sha256, remote_reader):
        assert engine.state.cycle(cycle_id)['start_request_id'].startswith('company-event:')
        with pytest.raises(ValueError, match='has no Sheets writer'):
            remote_writer()
        assert remote_reader() is remote
        return {'state': settled}

    settlement = Mock(side_effect=fixture_settlement)
    monkeypatch.setattr(publication, 'publish_ordinary_event_locked', settlement)
    assert execute(queued, 'publish', cycle_id=cycle_id) == {'state': settled}
    settlement.assert_called_once()
    assert [call.kwargs['write'] for call in factory.call_args_list] == [False, False]
    assert not remote.service.batches
    provider.assert_called_once()


def test_public_and_worker_holds_before_generic_workflow_or_writer(queued, monkeypatch, capsys):
    paths, _, _, provider, factory, _, writers = queued
    from job_search_helper import scrape_first_pass

    workflow = Mock(side_effect=AssertionError('generic workflow opened'))
    broad_repo = Mock(side_effect=AssertionError('generic repository opened'))
    monkeypatch.setattr(scrape_first_pass, 'main', workflow)
    monkeypatch.setattr(runner, 'get_repository', broad_repo)
    monkeypatch.setattr(bootstrap, '_validate_runtime', lambda *args: RUNTIME)
    assert runner.main(['start']) == 1
    assert runner.main(['--admitted-workflow', 'run']) == 1
    assert 'ordinary-company-event --help' in capsys.readouterr().err
    with pytest.raises(ValueError, match='ordinary-company-event'):
        runner.run_start()
    admitted = execute(queued)
    assert runner.main(['start']) == 1
    with pytest.raises(ValueError, match='ordinary-company-event'):
        runner.run_start(sync_only=True, sync_cycle_id=admitted['cycle_id'], sync_company_ids=['COMP-1'])
    workflow.assert_not_called()
    broad_repo.assert_not_called()
    provider.assert_called_once()
    factory.assert_called_once()
    writers.assert_called_once()


def test_generic_guard_preserves_manual_full_and_exact_prior_resume(queued):
    paths, _, _, _, _, _, _ = queued
    database = paths[0]
    root = database.parent
    command.guard_generic_ordinary_event(database, allow_queued=True)
    manual = {'mode': 'company-only', 'request_id': 'manual-scope',
              'company_ids': ['COMP-2'], 'operator_request': {'explicit': True}}
    (root / 'next-scan.json').write_text(json.dumps(manual))
    command.guard_generic_ordinary_event(database, fresh=True)
    (root / 'next-scan.json').write_text('{"mode":"fresh-full-scan","request_id":"EXPLICIT"}')
    command.guard_generic_ordinary_event(database, fresh=True)
    (root / 'next-scan.json').unlink()
    command.guard_generic_ordinary_event(database, fresh=True)


def test_cli_parses_exact_arguments_before_inherited_lease(queued, monkeypatch, capsys):
    paths, _, digest, *_ = queued
    acquire = Mock()
    monkeypatch.setattr(runner, '_retained_operator_admission', acquire)
    with pytest.raises(SystemExit) as invalid:
        runner.main(['ordinary-company-event', 'publish', '--request-sha256', digest])
    assert invalid.value.code == 2
    with pytest.raises(SystemExit) as invalid:
        runner.main(['ordinary-company-event', 'admit-fetch', '--request-sha256', 'not-a-digest'])
    assert invalid.value.code == 2
    with pytest.raises(SystemExit) as invalid:
        runner.main(['ordinary-company-event', 'admit-fetch', '--request-sha256', digest,
                     '--request-sha256', digest])
    assert invalid.value.code == 2
    acquire.assert_not_called()
    monkeypatch.undo()
    # Syntactically valid direct module invocation has no inherited lease.
    for name, value in {'STATE_DB_FILE': str(paths[0]), 'JOB_DB_FILE': str(paths[1]),
                        'JOB_STORAGE_BACKEND': 'sqlite'}.items():
        monkeypatch.setenv(name, value)
    assert runner.main(['ordinary-company-event', 'admit-fetch', '--request-sha256', digest]) == 1
    assert 'pre-import scraper lease' in capsys.readouterr().err


def test_real_bootstrap_pins_sqlite_and_passes_existing_lease(queued, monkeypatch, tmp_path):
    paths, _, digest, *_ = queued
    source = tmp_path / 'src/job_search_helper'
    source.mkdir(parents=True)
    (source / '__init__.py').write_text('')
    (tmp_path / 'pyproject.toml').write_text('[project]\nname="ordinary-event-fixture"\n')
    for key in ('JSH_SCRAPER_ADMISSION_FD', 'JSH_SCRAPER_ADMISSION_PATH',
                'JSH_SCRAPER_RUNTIME_BINDING', 'JSH_RETAINED_OPERATOR_SQLITE_LAYOUT'):
        monkeypatch.setenv(key, '')

    def exec_with_lease(executable, argv, env):
        assert argv[-4:] == ['ordinary-company-event', 'admit-fetch', '--request-sha256', digest]
        assert 'job_search_helper.runner' in argv
        assert Path(env['JSH_SCRAPER_ADMISSION_PATH']) == tmp_path / 'scraper.lock'
        fd = int(env['JSH_SCRAPER_ADMISSION_FD'])
        assert os.get_inheritable(fd)
        with (tmp_path / 'scraper.lock').open('a+') as other:
            with pytest.raises(BlockingIOError):
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        layout = json.loads(env['JSH_RETAINED_OPERATOR_SQLITE_LAYOUT'])
        assert [layout[name]['inode'] for name in ('state', 'jobs')] == [path.stat().st_ino for path in paths[:2]]
        assert json.loads(env['JSH_SCRAPER_RUNTIME_BINDING'])['state'] == 'NO_RELEASE'

    check = Mock(side_effect=exec_with_lease)
    monkeypatch.setattr(bootstrap.os, 'execve', check)
    bootstrap.admit_and_exec(tmp_path, ['ordinary-company-event', 'admit-fetch', '--request-sha256', digest])
    check.assert_called_once()

    def exec_pipeline(executable, argv, env):
        assert argv[-4:] == ['--admitted-workflow', 'run', '--scraper-args', '--resume']
        assert 'job_search_helper.runner' in argv
        assert Path(env['JSH_SCRAPER_ADMISSION_PATH']) == tmp_path / 'scraper.lock'
        assert 'JSH_RETAINED_OPERATOR_SQLITE_LAYOUT' not in env

    pipeline = Mock(side_effect=exec_pipeline)
    monkeypatch.setattr(bootstrap.os, 'execve', pipeline)
    bootstrap.admit_and_exec(tmp_path, ['--pipeline', 'run', '--scraper-args', '--resume'])
    pipeline.assert_called_once()


def test_shell_launcher_routes_to_isolated_bootstrap(tmp_path):
    python = tmp_path / 'fixture-python'
    python.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    python.chmod(0o700)
    launcher = Path(command.__file__).resolve().parents[2] / 'job-search-scraper'
    result = run(['bash', str(launcher), 'ordinary-company-event', '--help'],
                 env={**os.environ, 'PYTHON': str(python)}, capture_output=True, text=True, check=True)
    assert result.stdout.splitlines() == [
        '-I', '-S', str(launcher.with_name('release_admission_bootstrap.py')), 'ordinary-company-event', '--help',
    ]


@pytest.mark.parametrize(('queued', 'provider_inventory', 'disposition'), [
    ('greenhouse', ats.Inventory(
        'complete', source_url='https://boards-api.greenhouse.io/v1/boards/fixture/jobs',
        ats='Greenhouse', verified_zero='greenhouse_explicit_total_zero',
    ), 'VERIFIED_ZERO'),
    ('lever', ats.Inventory(
        'failed', source_url=OBSERVED, ats='Lever',
        outcome_failure=ats.outcome_failure('temporary_transport', 'retryable_http_status'),
    ), 'FETCH_TEMPORARY'),
    ('lever', ats.Inventory(
        'blocked', source_url=OBSERVED, ats='Lever',
        outcome_failure=ats.outcome_failure('access_denied', 'public_access_denied'),
    ), 'FETCH_BLOCKED'),
], indirect=['queued'])
def test_command_settles_real_local_only_dispositions_without_a_sheets_writer(queued, provider_inventory, disposition):
    _, _, _, provider, factory, remote, _ = queued
    provider.return_value = provider_inventory
    cycle_id = execute(queued)['cycle_id']
    result = execute(queued, 'publish', cycle_id=cycle_id)
    assert result['state'] == disposition
    assert result['outcome']['identity']['cycle_id'] == cycle_id
    assert execute(queued, 'publish', cycle_id=cycle_id) == result
    assert [call.kwargs['write'] for call in factory.call_args_list] == [False, False]
    assert not remote.service.batches
    provider.assert_called_once()


def test_ambiguous_empty_inventory_holds_before_any_publication_writer(queued):
    paths, _, _, provider, factory, _, writers = queued
    provider.return_value = ats.Inventory('complete', source_url=OBSERVED, ats='Lever')
    cycle_id = execute(queued)['cycle_id']
    protected = (paths[0], paths[1], paths[0].parent / 'inventories.sqlite3')
    before = {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
              for path in protected}
    result = execute(queued, 'publish', cycle_id=cycle_id)
    assert result['state'] == 'HELD_NO_PUBLICATION_SCOPE'
    assert {path: (path.stat().st_ino, path.stat().st_mtime_ns, path.stat().st_ctime_ns)
            for path in protected} == before
    writers.assert_called_once()
    provider.assert_called_once()
    factory.assert_called_once()
