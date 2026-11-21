"""Compose the accepted external Company intake and exact retained staging command."""

from contextlib import closing
import json
from pathlib import Path
import socket

import pytest

from job_search_helper import cli
from job_search_helper.company_events import BRIDGE_CONSUMER, MANUAL_RETAINED_HOLD, CompanyEventBridge
from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.retained_operator_command import operator_command
from job_search_helper.retained_work_exception import build_manifest
from job_search_helper.scan_request import _read_request
from job_search_helper.sqlite_repository import SQLiteRepository
from test_owner_external_company_intake import available, confirm, owner_edit, prepare
from test_s4_manual_retained_event_stage import company, forbidden_dispatch, receipt_path, scope


def test_external_owner_event_stages_once_behind_unchanged_retained_work(available, tmp_path, monkeypatch, capsys):
    def unexpected_network(*args, **kwargs):
        pytest.fail('Disposable retained staging attempted network or a real Sheets client')

    monkeypatch.setattr(socket.socket, 'connect', unexpected_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', unexpected_network)
    monkeypatch.setattr(socket, 'getaddrinfo', unexpected_network)
    monkeypatch.setattr(cli, 'get_remote_repository', unexpected_network)
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')

    repo, _, sheets, _, selected = available
    jobs, database = Path(repo.path), tmp_path / 'state.db'
    inbox_path = tmp_path / 'inventories.sqlite3'
    historical = company('HISTORICAL')
    blocker = {'id': 'CYC-HISTORICAL', 'all': False, 'status': 'In Progress',
               'started_at': '2026-11-20T12:00:00+00:00',
               'companies': {'HISTORICAL': {'stage': 'inventory', 'company': historical['Company'],
                                             'requested_url': historical['Official Careers URL'],
                                             'ats': historical['ATS / Source']}}}
    repo.import_rows('Companies', [(4, historical)])
    with closing(State(database)) as state, closing(InventoryInbox(inbox_path, repo.spreadsheet_id)) as inbox:
        Engine(repo, state)._sync_cycle(blocker)
        inbox.save(blocker['id'], historical['Company ID'], {'inventory_status': 'complete', 'jobs': []})
        inbox.save_plan(blocker['id'], historical['Company ID'], [{'historical_fixture_plan': 'leave intact'}])
        prior_state = state.cycle(blocker['id'])
        prior_mirror = repo.matches('Scan Cycles', {'Cycle ID': blocker['id']})
        manifest_args = {'reason': 'disposable held historical cycle',
                         'created_at': '2026-11-20T12:00:05+00:00'}
        manifest = build_manifest(prior_state, inbox_path, jobs, **manifest_args)
        manifest_file = tmp_path / 'historical-manifest.json'
        manifest_file.write_text(json.dumps({'manifest': manifest}), encoding='utf-8')

        prepare(available)
        intake = confirm(available, owner_edit(available))
        event, = repo.pending_company_events(BRIDGE_CONSUMER)
        assert event['origin'] == 'sheets-reconciliation' and event['revision'] == 1
        assert event['event_id'] == intake['event_id']
        assert (event['company_id'], event['source_revision']) == (selected['company_id'], intake['source_revision'])
        bridge = CompanyEventBridge(repo, tmp_path, state_database=database)
        assert not bridge.request_path.exists()

        def local_factory(*, write, interactive):
            assert write is True and interactive is False
            return SQLiteRepository(jobs, repo.spreadsheet_id)

        monkeypatch.setattr(cli, 'get_repository', local_factory)
        arguments = ['stage-event', '--company-event', '--cycle-id', blocker['id'],
                     '--company-id', intake['company_id'], '--request-id', 'company-event:' + intake['event_id'],
                     '--source-revision', intake['source_revision'], '--manifest-file', str(manifest_file)]
        with cli.writer_lock(tmp_path / cli.scraper_lock_name()):
            assert operator_command(arguments, (database, jobs, {})) == 0
            first = json.loads(capsys.readouterr().out)
            raw = bridge.request_path.read_bytes()
            receipt_file = receipt_path(bridge, event)
            bridge_receipt = receipt_file.read_bytes()
            acknowledgement = repo.db.execute('SELECT * FROM main.company_event_deliveries').fetchall()
            assert bridge.verify_manual_retained_event(event['event_id'], **scope(event, blocker)) == first
            assert operator_command(arguments, (database, jobs, {})) == 0
            assert json.loads(capsys.readouterr().out) == first
            assert (bridge.request_path.read_bytes(), receipt_file.read_bytes()) == (raw, bridge_receipt)
            assert repo.db.execute('SELECT * FROM main.company_event_deliveries').fetchall() == acknowledgement

        request, companies = _read_request(bridge.request_path)
        assert first['state'] == 'MANUAL_RETAINED_STAGED'
        assert request['request_id'] == first['request_id'] == 'company-event:' + event['event_id']
        assert companies == [selected['company_id']]
        assert request['manual_retained']['blocking_cycle_id'] == blocker['id']
        assert request['company_event']['source_revision'] == event['source_revision']
        assert request['company_event']['revision'] == 1
        assert repo.db.execute(
            'SELECT revision,eligible,source_revision FROM main.company_revisions WHERE company_id=?',
            (selected['company_id'],),
        ).fetchall() == [(1, 1, event['source_revision'])]
        assert repo.db.execute('SELECT event_id FROM main.company_event_outbox').fetchall() == [(event['event_id'],)]
        assert repo.db.execute('SELECT event_id,consumer FROM main.company_event_deliveries').fetchall() == [
            (event['event_id'], BRIDGE_CONSUMER),
        ]
        assert repo.pending_company_events(BRIDGE_CONSUMER) == []
        dispatch = CompanyIntakeDispatcher(repo, tmp_path, child_runner=forbidden_dispatch,
                                          retained_child_runner=forbidden_dispatch)
        monkeypatch.setattr(dispatch, 'enabled', lambda: True)
        monkeypatch.setattr(dispatch, 'retained_enabled', lambda: True)
        assert dispatch.run_once()['state'] == MANUAL_RETAINED_HOLD
        assert state.cycles() == [prior_state]
        assert repo.matches('Scan Cycles', {'Cycle ID': blocker['id']}) == prior_mirror
        assert build_manifest(state.cycle(blocker['id']), inbox_path, jobs, **manifest_args) == manifest
        assert len(sheets.external_owner_edits) == 1
