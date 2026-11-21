"""A released repair retry carries its actual defer-sync checkpoint into v2."""
from contextlib import closing
import json
from unittest.mock import Mock, patch

import pytest

from job_search_helper.ats import Inventory
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import current_company_source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_planner import freeze_exact_cycle_plans
from job_search_helper.exact_cycle_receipt import derive_receipt
from job_search_helper.exact_cycle_recovery import recover_exact_cycle
from job_search_helper.exact_cycle_sync import _company_guard
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import JOURNAL_SCHEMA
from job_search_helper.publication_receipts import LOCAL_COMMITTED
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RELEASE_BINDING_SCHEMA, RepairRetryBridge, retry_attempt_id,
)
from job_search_helper.scan_request import requested_scan
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository, timestamp
from test_exact_cycle_recovery import RecordingRemote, company


@pytest.mark.parametrize('case', [
    'fresh', 'state-cut', 'foreign-frozen-plan', 'different-request', 'inactive-release', 'payload-drift',
])
def test_deferred_exact_repair_checkpoint(tmp_path, monkeypatch, case):
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    company_id = 'COMP-1'
    row = company(company_id)
    url = row['Official Careers URL']
    posting = {'title': 'Fixture Role', 'posting_id': '123', 'url': url + '/jobs/123',
               'location': 'Remote', 'description': 'Customer-facing implementation and deployment work.',
               'ats': 'Greenhouse'}
    release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-1',
               'source_manifest_sha256': '1' * 64, 'dependency_manifest_sha256': '2' * 64,
               'config_sha256': '3' * 64}
    runtime = {'state': 'COMPLETE', **{key: value for key, value in release.items() if key != 'schema'}}
    journal = tmp_path / 'integration-release-journal.json'
    activation = {'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE', 'release_id': release['release_id'], 'release': release}
    journal.write_text(json.dumps(activation))
    with (closing(SQLiteRepository(tmp_path/'jobs.sqlite3', 'fixture', initialize=True)) as local,
          closing(State(str(tmp_path/'state.db'))) as state,
          closing(InventoryInbox(tmp_path/'inventories.sqlite3', 'fixture')) as inbox):
        local.import_rows('Companies', [(2, row)])
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        local.set_meta('ready', 'yes')
        local.set_meta('sheets_profile', COMPACT_PROFILE)
        revision = current_company_source_revision(local, company_id)
        retry = {'schema': REPAIR_RETRY_SCHEMA, 'company_id': company_id, 'source_revision': revision,
                 'failed_request_id': 'prior-failure', 'release': release, 'activated_at': '2026-11-19T12:00:00Z'}
        retry['attempt_id'] = retry_attempt_id(retry)
        bridge = RepairRetryBridge(tmp_path/'state.db', current_source_revision=lambda cid: current_company_source_revision(local, cid))
        assert bridge.deliver(retry)['state'] == 'REQUEST_WRITTEN'
        fetch = Mock(spec=lambda *_: None, return_value=Inventory('complete', [posting], source_url=url, ats='Greenhouse'))
        engine = Engine(local, state, inbox=inbox, runtime_binding=runtime, fetcher=fetch)
        with writer_lock(tmp_path/'scraper.lock'):
            cycle_id = requested_scan(engine, state, tmp_path/'state.db')
            assert engine.resume_local(cycle_id, fetch_workers=1, assignment_window=1, defer_sync=True)[
                'attempted_company_ids'] == [company_id]
        fetch.assert_called_once_with('Greenhouse', url, company_id, row['Company'])
        fetch.side_effect = AssertionError('Exact recovery must not refetch.')
        item = state.cycle(cycle_id)['companies'][company_id]
        assert item['stage'] == 'inventory' and item['durable_inventory'] is True and 'locally_processed' not in item
        assert inbox.plan(cycle_id, company_id) is None and not local.read('Job History')
        remote = RecordingRemote(local.read('Companies'), schemas=COMPACT_SCHEMAS)

        if case == 'foreign-frozen-plan':
            # A historical frozen v2 plan cannot lend a normal deferred proof
            # to an inventory checkpoint that has lost its actual lineage.
            planned = freeze_exact_cycle_plans(engine, cycle_id, [company_id],
                                               company_guard=lambda cid, url: _company_guard(local, remote, cid, url))
            assert planned['planned'] == [company_id]
            replacement = state.cycle(cycle_id)
            replacement.pop('repair_retry')
            state.save_cycle(replacement)
            with patch.object(local, 'apply_exact_local_plan', side_effect=AssertionError('foreign local apply')):
                result = recover_exact_cycle(engine, remote, cycle_id, [company_id])
            assert result['held'] == [{'company_id': company_id, 'reason': 'exact_v2_inventory_checkpoint_invalid'}]
            assert not remote.commits and not local.read('Job History')
            return

        if case in {'different-request', 'inactive-release', 'payload-drift'}:
            if case == 'different-request':
                last = tmp_path/'last-scan-request.json'
                last.write_text(json.dumps({**json.loads(last.read_bytes()), 'enqueued_at': '2026-11-19T13:00:00Z'}))
                expected = 'exact_v2_deferred_repair_request_changed'
            elif case == 'inactive-release':
                journal.write_text(json.dumps({**activation, 'state': 'ROLLED_BACK'}))
                expected = 'not the active COMPLETE release'
            else:
                changed = state.cycle(cycle_id)
                changed['companies'][company_id]['reason'] = 'different deferred payload'
                state.save_cycle(changed)
                expected = 'exact_v2_deferred_repair_inventory_changed'
            with pytest.raises(ValueError, match=expected):
                recover_exact_cycle(engine, remote, cycle_id, [company_id])
            assert not remote.commits and inbox.plan(cycle_id, company_id) is None and not local.read('Job History')
            return

        local_only = {'company_id': company_id, 'reason': 'fixture stops after verified local recovery'}

        def stop_before_publication(saved_inbox, recovered_cycle, workbook, *, company_ids, **_):
            assert saved_inbox is inbox and recovered_cycle == cycle_id and workbook is remote
            assert company_ids == [company_id]
            plan, cursor = inbox.plan(cycle_id, company_id)
            assert cursor == len(plan['local_operations'])
            proof = inbox.exact_local_state(cycle_id, company_id)
            applied = local.verify_exact_local_plan(cycle_id, company_id, plan, cursor=None)
            assert proof['state'] == 'LOCAL_VERIFIED' and proof['local_apply_id'] == applied['apply_id']
            refreshed = state.cycle(cycle_id)
            assert refreshed['companies'][company_id]['locally_processed'] is True
            payload, _ = inbox.get(cycle_id, company_id)
            receipt = inbox.receipt(derive_receipt(refreshed, company_id, payload, plan, timestamp()))
            assert receipt['state'] == LOCAL_COMMITTED
            assert receipt['binding']['request_id'] == refreshed['start_request_id']
            assert receipt['binding']['release_id'] == release['release_id']
            return {'confirmed': [], 'held': [local_only], 'skipped': []}

        with patch('job_search_helper.exact_cycle_recovery.publish_exact_cycle', side_effect=stop_before_publication) as publish:
            if case == 'state-cut':
                with writer_lock(tmp_path/'scraper.lock'):
                    planned = freeze_exact_cycle_plans(
                        engine, cycle_id, [company_id],
                        company_guard=lambda cid, url: _company_guard(local, remote, cid, url),
                    )
                assert planned['planned'] == [company_id]
                with patch.object(state, 'save_cycle', side_effect=RuntimeError('cut before State commit')):
                    first = recover_exact_cycle(engine, remote, cycle_id, [company_id])
                assert first['planned'] == [] and first['held'] == [
                    {'company_id': company_id, 'reason': 'cut before State commit'},
                ]
                proof = inbox.exact_local_state(cycle_id, company_id)
                assert proof['state'] == 'LOCAL_VERIFIED' and len(local.read('Job History')) == 1
                assert state.cycle(cycle_id)['companies'][company_id] == item and not remote.commits
                publish.assert_not_called()
                with patch.object(local, 'apply_exact_local_plan', side_effect=AssertionError('duplicate local apply')) as apply:
                    result = recover_exact_cycle(engine, remote, cycle_id, [company_id])
                apply.assert_not_called()
                assert result['planned'] == []
            else:
                result = recover_exact_cycle(engine, remote, cycle_id, [company_id])
                assert result['planned'] == [company_id]
        publish.assert_called_once()
        assert result['held'] == [local_only] and result['confirmed'] == []
        assert state.cycle(cycle_id)['companies'][company_id]['locally_processed'] is True
        assert state.cycle(cycle_id)['repair_retry'] == retry
        assert not remote.snapshot('Job History') and len(local.read('Job History')) == 1
        assert not remote.commits
        fetch.assert_called_once()
