"""Bounded orchestrator tests with both injected fakes and real components."""
from unittest.mock import MagicMock, patch
import unittest
import copy
from contextlib import contextmanager
import sqlite3
import tempfile
from pathlib import Path

from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.exact_cycle_recovery import (
    recover_exact_cycle,
    recover_exact_cycle_with_factory,
)
from job_search_helper.exact_cycle_planner import freeze_exact_cycle_plans
from job_search_helper.exact_cycle_sync import _company_guard
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository, SCHEMAS, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


class RecordingRemote(MemoryRepository):
    def __init__(self, companies=None, *, schemas=None):
        companies = companies or [{
            'Company ID': 'COMP-1', 'Company': 'Fixture',
            'Company Status': 'Active',
            'Official Careers URL': 'https://boards.example.test/fixture',
        }]
        selected_schemas = copy.deepcopy(schemas or SCHEMAS)
        companies = [{key: value for key, value in row.items()
                      if key in selected_schemas['Companies']}
                     for row in companies]
        super().__init__(
            {'Companies': companies},
            schemas=selected_schemas)
        self.spreadsheet_id = 'fixture'
        self.commits = []
        self._inside_commit = False

    def commit(self, operations):
        self.commits.append(copy.deepcopy(operations))
        self._inside_commit = True
        try:
            return super().commit(operations)
        finally:
            self._inside_commit = False

    def read(self, tab):
        if not self._inside_commit:
            raise AssertionError('exact recovery must not use full-tab read')
        return super().read(tab)

    def read_many(self, _tabs):
        raise AssertionError('exact recovery must not use multi-tab read')

    def snapshot(self, tab):
        return copy.deepcopy(super().read(tab))


def company(company_id, *, claimed=False):
    return {
        'Company ID': company_id,
        'Company': 'Fixture ' + company_id,
        'Company Status': 'Active',
        'Official Careers URL': f'https://boards.example.test/{company_id.lower()}',
        'ATS / Source': 'Greenhouse',
        'Scan State': 'Queued',
        'Claimed By': 'other-worker' if claimed else '',
        'Claim Token': 'claim' if claimed else '',
    }


def inventory(company_id):
    return {
        'inventory_status': 'complete',
        'jobs': [],
        'requested_url': f'https://boards.example.test/{company_id.lower()}',
        'fetched_at': '2026-11-19T00:00:00Z',
    }


def engine_for(companies, inventories, plans):
    engine = MagicMock()
    engine.runtime_binding = None
    engine.state.path = None
    engine.state.cycle.return_value = {'id': 'CYC', 'status': 'In Progress', 'companies': companies}
    engine.inbox.get.side_effect = lambda cycle, company: inventories.get(company)
    engine.inbox.plan.side_effect = lambda cycle, company: plans.get(company)
    return engine


class ExactCycleRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fake_state_path = Path(self.temporary.name) / 'state.db'
        self.fake_state_path.touch()

    def fake_engine(self, companies, inventories, plans):
        engine = engine_for(companies, inventories, plans)
        engine.state.path = str(self.fake_state_path)
        return engine

    def real_fixture(self, company_ids=('COMP-1',), *, local_claimed=()):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        local_companies = [company(company_id, claimed=company_id in set(local_claimed))
                           for company_id in company_ids]
        local = MemoryRepository(
            {'Companies': local_companies}, schemas=copy.deepcopy(SCHEMAS),
        )
        state = State(root / 'state.db')
        inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
        state.save_cycle({
            'id': 'CYC', 'status': 'In Progress',
            'started_at': '2026-11-19T00:00:00Z',
            'companies': {
                company_id: {'stage': 'queued'} for company_id in company_ids
            },
        })
        for company_id in company_ids:
            inbox.save('CYC', company_id, inventory(company_id))
        remote_rows = [company(company_id) for company_id in company_ids]
        remote = RecordingRemote(remote_rows)
        return root, engine, state, inbox, remote

    def test_real_engine_holds_new_plan_until_local_apply_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); schemas = copy.deepcopy(SCHEMAS)
            local = MemoryRepository({'Companies': [{'Company ID': 'COMP-1', 'Company': 'Fixture',
                'Company Status': 'Active', 'Official Careers URL': 'https://boards.example.test/fixture',
                'ATS / Source': 'Greenhouse', 'Scan State': 'Queued'}]}, schemas=schemas)
            state = State(root / 'state.db'); inbox = InventoryInbox(root / 'inbox.db', 'fixture')
            self.addCleanup(state.close); self.addCleanup(inbox.close)
            engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
            state.save_cycle({'id': 'CYC', 'status': 'In Progress', 'started_at': '2026-11-19T00:00:00Z',
                              'companies': {'COMP-1': {'stage': 'queued'}}})
            inbox.save('CYC', 'COMP-1', {'inventory_status': 'complete', 'jobs': [],
                       'requested_url': 'https://boards.example.test/fixture', 'fetched_at': '2026-11-19T00:00:00Z'})
            remote = RecordingRemote()
            result = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
            self.assertEqual(result['planned'], ['COMP-1'], result)
            self.assertEqual(result['confirmed'], [], result)
            self.assertEqual(result['held'], [{
                'company_id': 'COMP-1', 'reason': 'local_plan_not_durably_applied',
            }])
            self.assertEqual(inbox.pending('CYC', include_blocked=True), ['COMP-1'])
            self.assertEqual(remote.commits, [])

    def test_real_plan_save_state_split_recovers_then_publishes(self):
        _root, engine, state, inbox, remote = self.real_fixture()
        with patch.object(state, 'save_cycle', side_effect=OSError('checkpoint crash')):
            report = freeze_exact_cycle_plans(
                engine, 'CYC', ['COMP-1'],
                company_guard=lambda company_id, requested_url: _company_guard(
                    engine.repo, remote, company_id, requested_url,
                ),
                max_companies=1,
            )
        self.assertEqual(report['planned'], [])
        self.assertEqual(report['held'][0]['reason'], 'checkpoint crash')
        self.assertIsNotNone(inbox.plan('CYC', 'COMP-1'))
        self.assertEqual(state.cycle('CYC')['companies']['COMP-1']['stage'], 'queued')

        recovered = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(recovered['recovered'], ['COMP-1'], recovered)
        self.assertEqual(recovered['confirmed'], [], recovered)
        self.assertEqual(recovered['held'], [{
            'company_id': 'COMP-1', 'reason': 'local_plan_not_durably_applied',
        }])
        self.assertEqual(inbox.pending('CYC', include_blocked=True), ['COMP-1'])
        self.assertEqual(remote.commits, [])

    def test_real_post_state_save_ack_crash_restarts_without_remote_replay(self):
        _root, engine, state, inbox, remote = self.real_fixture()
        planned = freeze_exact_cycle_plans(
            engine, 'CYC', ['COMP-1'],
            company_guard=lambda company_id, requested_url: _company_guard(
                engine.repo, remote, company_id, requested_url,
            ),
            max_companies=1,
        )
        self.assertEqual(planned['planned'], ['COMP-1'])
        frozen, _ = inbox.plan('CYC', 'COMP-1')
        inbox.advance('CYC', {'COMP-1': len(frozen['operations'])}, expected={'COMP-1': 0})
        original_acknowledge = inbox.acknowledge
        with patch.object(inbox, 'acknowledge', side_effect=OSError('cleanup crash')):
            first = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(first['confirmed'], [])
        self.assertEqual(first['held'][0]['reason'], 'OSError')
        self.assertEqual(state.cycle('CYC')['companies']['COMP-1']['stage'], 'complete')
        self.assertIsNotNone(inbox.plan('CYC', 'COMP-1'))
        commits_before = len(remote.commits)

        with patch.object(inbox, 'acknowledge', side_effect=original_acknowledge):
            second = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(second['confirmed'], ['COMP-1'], second)
        self.assertEqual(len(remote.commits), commits_before)
        self.assertEqual(inbox.pending('CYC', include_blocked=True), [])

    def test_real_second_company_hold_preserves_first_and_unselected(self):
        root, engine, state, inbox, remote = self.real_fixture(
            ('COMP-A', 'COMP-B', 'COMP-Z'), local_claimed=('COMP-B',),
        )
        inbox.save('OTHER-CYCLE', 'COMP-Z', inventory('COMP-Z'))
        request = root / 'next-scan.json'
        request.write_bytes(b'preserve-exact-request')
        unselected_before = copy.deepcopy(inbox.get('CYC', 'COMP-Z'))
        other_before = copy.deepcopy(inbox.get('OTHER-CYCLE', 'COMP-Z'))
        remote_z_before = remote.snapshot('Companies')[2]

        result = recover_exact_cycle(engine, remote, 'CYC', ['COMP-A', 'COMP-B'])
        self.assertEqual(result['confirmed'], [], result)
        self.assertIn({'company_id': 'COMP-A',
                       'reason': 'local_plan_not_durably_applied'}, result['held'])
        self.assertIn({'company_id': 'COMP-B', 'reason': 'local_company_claimed'},
                      result['held'])
        self.assertEqual(inbox.get('CYC', 'COMP-Z'), unselected_before)
        self.assertEqual(inbox.get('OTHER-CYCLE', 'COMP-Z'), other_before)
        self.assertEqual(remote.snapshot('Companies')[2], remote_z_before)
        self.assertEqual(request.read_bytes(), b'preserve-exact-request')
        self.assertIsNotNone(inbox.get('CYC', 'COMP-A'))
        self.assertIsNotNone(inbox.get('CYC', 'COMP-B'))
        self.assertEqual(state.cycle('CYC')['companies']['COMP-Z']['stage'], 'queued')

    def test_superseded_cycle_with_existing_plan_is_rejected_without_side_effects(self):
        _root, engine, state, inbox, remote = self.real_fixture()
        planned = freeze_exact_cycle_plans(
            engine, 'CYC', ['COMP-1'],
            company_guard=lambda company_id, requested_url: _company_guard(
                engine.repo, remote, company_id, requested_url,
            ),
            max_companies=1,
        )
        self.assertEqual(planned['planned'], ['COMP-1'])
        self.assertEqual(state.cycle('CYC')['companies']['COMP-1']['stage'], 'inventory')
        state.save_cycle({
            'id': 'CYC-NEW', 'status': 'In Progress',
            'started_at': '2026-11-19T00:01:00Z',
            'Notes': '{"supersedes":["CYC"]}', 'companies': {},
        })
        cycle_before = state.cycle('CYC')
        inventory_before = copy.deepcopy(inbox.get('CYC', 'COMP-1'))
        plan_before = copy.deepcopy(inbox.plan('CYC', 'COMP-1'))
        remote_before = remote.snapshot('Companies')
        commits_before = len(remote.commits)

        with self.assertRaisesRegex(ValueError, 'cycle_superseded'):
            recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])

        self.assertEqual(state.cycle('CYC'), cycle_before)
        self.assertEqual(inbox.get('CYC', 'COMP-1'), inventory_before)
        self.assertEqual(inbox.plan('CYC', 'COMP-1'), plan_before)
        self.assertEqual(remote.snapshot('Companies'), remote_before)
        self.assertEqual(len(remote.commits), commits_before)

    def test_real_sqlite_orchestration_preserves_unrelated_dirty_and_outbox_rows(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        local = SQLiteRepository(root / 'jobs.db', 'fixture', initialize=True)
        self.addCleanup(local.close)
        local_companies = [company('COMP-1'), company('COMP-Z')]
        for tab in SCHEMAS:
            local.import_rows(tab, enumerate(local_companies if tab == 'Companies' else [], 2))
        local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-Z'},
            'values': {'Notes': 'unrelated dirty publisher value'},
        }])
        local.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-Z'},
            'values': {'Notes': 'unrelated coordinator event value'},
        })
        state = State(root / 'state.db')
        inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
        state.save_cycle({
            'id': 'CYC', 'status': 'In Progress',
            'started_at': '2026-11-19T00:00:00Z',
            'companies': {
                'COMP-1': {'stage': 'queued'},
                'COMP-Z': {'stage': 'queued'},
            },
        })
        inbox.save('CYC', 'COMP-1', inventory('COMP-1'))
        inbox.save('CYC', 'COMP-Z', inventory('COMP-Z'))
        remote = RecordingRemote([company('COMP-1'), company('COMP-Z')])

        def local_snapshot():
            connection = sqlite3.connect(root / 'jobs.db')
            try:
                return {
                    'dirty': list(connection.execute(
                        'SELECT tab,row_id,header FROM dirty '
                        'ORDER BY tab,row_id,header'
                    )),
                    'outbox': list(connection.execute(
                        'SELECT event_id,company_id,revision,source_revision,kind,payload,created_at '
                        'FROM company_event_outbox ORDER BY event_id'
                    )),
                }
            finally:
                connection.close()

        before = local_snapshot()
        result = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(result['confirmed'], [], result)
        self.assertEqual(result['held'], [{
            'company_id': 'COMP-1', 'reason': 'local_plan_not_durably_applied',
        }])
        self.assertEqual(local_snapshot(), before)
        self.assertIsNotNone(inbox.get('CYC', 'COMP-Z'))
        self.assertEqual(state.cycle('CYC')['companies']['COMP-Z']['stage'], 'queued')

    def test_compact_v2_normal_recovery_applies_publishes_and_preserves_unrelated_work(self):
        root = Path(self.temporary.name) / 'compact-v2'
        root.mkdir()
        local = SQLiteRepository(root / 'jobs.db', 'fixture', initialize=True)
        self.addCleanup(local.close)
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        local_companies = [company('COMP-1'), company('COMP-Z')]
        for tab in SCHEMAS:
            local.import_rows(
                tab, enumerate(local_companies if tab == 'Companies' else [], 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-Z'},
            'values': {'Notes': 'unrelated dirty publisher value'},
        }])
        local.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-Z'},
            'values': {'Notes': 'unrelated coordinator event value'},
        })
        unrelated_dirty = list(local.db.execute(
            'SELECT tab,row_id,header FROM dirty WHERE row_id=2 ORDER BY header'))
        unrelated_outbox = list(local.db.execute(
            'SELECT event_id,company_id,revision,source_revision,kind,payload,created_at '
            'FROM company_event_outbox ORDER BY event_id'))
        state = State(root / 'state.db')
        inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
        state.save_cycle({
            'id': 'CYC', 'status': 'In Progress',
            'started_at': '2026-11-19T00:00:00Z',
            'companies': {
                'COMP-1': {'stage': 'queued'},
                'COMP-Z': {'stage': 'queued'},
            },
        })
        inbox.save('CYC', 'COMP-1', inventory('COMP-1'))
        inbox.save('CYC', 'COMP-Z', inventory('COMP-Z'))
        remote = RecordingRemote(
            [company('COMP-1'), company('COMP-Z')], schemas=COMPACT_SCHEMAS)

        result = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])

        self.assertEqual(result['planned'], ['COMP-1'], result)
        self.assertEqual(result['confirmed'], ['COMP-1'], result)
        self.assertEqual(result['held'], [], result)
        self.assertEqual(inbox.pending('CYC', include_blocked=True), ['COMP-Z'])
        self.assertEqual(state.cycle('CYC')['companies']['COMP-1']['stage'], 'complete')
        self.assertEqual(state.cycle('CYC')['companies']['COMP-Z']['stage'], 'queued')
        self.assertEqual(list(local.db.execute(
            'SELECT tab,row_id,header FROM dirty WHERE row_id=2 ORDER BY header')),
            unrelated_dirty)
        self.assertEqual(list(local.db.execute(
            'SELECT event_id,company_id,revision,source_revision,kind,payload,created_at '
            'FROM company_event_outbox ORDER BY event_id')), unrelated_outbox)
        self.assertEqual(len(remote.commits), 1)

    def test_public_sync_dispatch_confirms_one_frozen_selected_plan(self):
        from contextlib import redirect_stdout
        import io
        import json
        from job_search_helper import runner

        root = Path(self.temporary.name) / 'public-exact-sync'
        root.mkdir()
        database = root / 'state.db'
        local_path = root / 'jobs.db'
        inbox_path = root / 'inventories.sqlite3'
        remote = RecordingRemote([company('COMP-1'), company('COMP-Z')],
                                 schemas=COMPACT_SCHEMAS)
        local = SQLiteRepository(local_path, 'fixture', initialize=True)
        state = State(database)
        inbox = InventoryInbox(inbox_path, 'fixture')
        try:
            local.ensure_columns('Opportunities', ['Opportunity ID'])
            for tab in SCHEMAS:
                rows = [company('COMP-1'), company('COMP-Z')] if tab == 'Companies' else []
                local.import_rows(tab, enumerate(rows, 2))
            with local.transaction():
                local.set_meta('ready', 'yes')
                local.set_meta('sheets_profile', COMPACT_PROFILE)
            state.save_cycle({'id': 'CYC', 'status': 'In Progress',
                              'started_at': '2026-11-19T00:00:00Z',
                              'companies': {cid: {'stage': 'queued'} for cid in ('COMP-1', 'COMP-Z')}})
            inbox.save('CYC', 'COMP-1', inventory('COMP-1'))
            inbox.save('CYC', 'COMP-Z', inventory('COMP-Z'))
            engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
            freeze_exact_cycle_plans(engine, 'CYC', ['COMP-1'], company_guard=lambda cid, url:
                                     _company_guard(local, remote, cid, url))
            self.assertIsNotNone(inbox.plan('CYC', 'COMP-1'))
        finally:
            inbox.close()
            state.close()
            local.close()

        def remote_factory(**_options):
            with self.assertRaises(WriterLockBusy):
                with writer_lock(database.parent / scraper_lock_name()):
                    pass
            return remote

        output = io.StringIO()
        with (
            patch.object(runner, '_load_environment'),
            patch.object(runner, 'state_path', return_value=database),
            patch('job_search_helper.cli.job_database_path', return_value=local_path),
            patch('job_search_helper.cli.get_remote_repository', side_effect=remote_factory),
            patch('job_search_helper.run_sync.run_scoped_sync', side_effect=AssertionError('global sync')),
            redirect_stdout(output),
        ):
            self.assertEqual(runner.main(['sync', '--cycle-id', 'CYC', '--company-id', 'COMP-1']), 0)
        report = json.loads(output.getvalue().split('Exact cycle recovery: ', 1)[1])
        self.assertEqual(report['confirmed'], ['COMP-1'])
        self.assertEqual(len(remote.commits), 1)
        reopened = InventoryInbox(inbox_path, 'fixture')
        try:
            self.assertEqual(reopened.pending('CYC', include_blocked=True), ['COMP-Z'])
        finally:
            reopened.close()

    def test_compact_v2_uncertain_write_recovers_by_readback_without_replay(self):
        root = Path(self.temporary.name) / 'compact-v2-uncertain'
        root.mkdir()
        local = SQLiteRepository(root / 'jobs.db', 'fixture', initialize=True)
        self.addCleanup(local.close)
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        for tab in SCHEMAS:
            local.import_rows(
                tab, enumerate([company('COMP-1')] if tab == 'Companies' else [], 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        state = State(root / 'state.db')
        inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
        state.save_cycle({
            'id': 'CYC', 'status': 'In Progress',
            'started_at': '2026-11-19T00:00:00Z',
            'companies': {'COMP-1': {'stage': 'queued'}},
        })
        inbox.save('CYC', 'COMP-1', inventory('COMP-1'))
        remote = RecordingRemote([company('COMP-1')], schemas=COMPACT_SCHEMAS)
        original_commit = remote.commit

        def uncertain_commit(operations):
            original_commit(operations)
            raise UncertainWriteError('synthetic uncertain write')

        with patch.object(remote, 'commit', side_effect=uncertain_commit):
            first = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(first['confirmed'], [], first)
        self.assertEqual(first['held'], [{
            'company_id': 'COMP-1', 'reason': 'uncertain_write',
        }])
        self.assertEqual(len(remote.commits), 1)
        journal = inbox.exact_remote_state('CYC', 'COMP-1')
        self.assertEqual(journal['state'], 'SYNC_PENDING')
        self.assertTrue(journal['first_attempt_claimed'])

        with patch.object(remote, 'commit', side_effect=AssertionError('remote replay')):
            second = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(second['confirmed'], ['COMP-1'], second)
        self.assertEqual(second['held'], [], second)
        self.assertEqual(len(remote.commits), 1)

    def test_compact_v2_post_confirmation_crash_recovers_without_local_or_remote_replay(self):
        root = Path(self.temporary.name) / 'compact-v2-post-confirmation'
        root.mkdir()
        local = SQLiteRepository(root / 'jobs.db', 'fixture', initialize=True)
        self.addCleanup(local.close)
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        for tab in SCHEMAS:
            local.import_rows(
                tab, enumerate([company('COMP-1')] if tab == 'Companies' else [], 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        state = State(root / 'state.db')
        inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
        state.save_cycle({
            'id': 'CYC', 'status': 'In Progress',
            'started_at': '2026-11-19T00:00:00Z',
            'companies': {'COMP-1': {'stage': 'queued'}},
        })
        inbox.save('CYC', 'COMP-1', inventory('COMP-1'))
        remote = RecordingRemote([company('COMP-1')], schemas=COMPACT_SCHEMAS)

        with patch.object(
                inbox, 'mark_exact_remote_locally_acknowledged',
                side_effect=OSError('synthetic post-confirmation crash')):
            first = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(first['confirmed'], [], first)
        self.assertEqual(first['held'], [{
            'company_id': 'COMP-1', 'reason': 'OSError',
        }])
        self.assertEqual(len(remote.commits), 1)
        self.assertEqual(inbox.exact_remote_state('CYC', 'COMP-1')['state'],
                         'SYNC_CONFIRMED')

        with patch.object(
                local, 'apply_exact_local_plan',
                side_effect=AssertionError('local replay')):
            with patch.object(
                    remote, 'commit', side_effect=AssertionError('remote replay')):
                second = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(second['confirmed'], ['COMP-1'], second)
        self.assertEqual(second['held'], [], second)
        self.assertEqual(len(remote.commits), 1)
        self.assertEqual(inbox.pending('CYC', include_blocked=True), [])
        self.assertEqual(state.cycle('CYC')['companies']['COMP-1']['stage'], 'complete')

    def test_compact_v2_large_company_uses_bounded_remote_chunks(self):
        root = Path(self.temporary.name) / 'compact-v2-large-company'
        root.mkdir()
        local = SQLiteRepository(root / 'jobs.db', 'fixture', initialize=True)
        self.addCleanup(local.close)
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        for tab in SCHEMAS:
            local.import_rows(
                tab, enumerate([company('COMP-1')] if tab == 'Companies' else [], 2))
        with local.transaction():
            local.set_meta('ready', 'yes')
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        state = State(root / 'state.db')
        inbox = InventoryInbox(root / 'inbox.db', 'fixture')
        self.addCleanup(state.close)
        self.addCleanup(inbox.close)
        engine = Engine(local, state, inbox=inbox, error_log_path=root / 'errors.jsonl')
        state.save_cycle({
            'id': 'CYC', 'status': 'In Progress',
            'started_at': '2026-11-19T00:00:00Z',
            'companies': {'COMP-1': {'stage': 'queued'}},
        })
        payload = inventory('COMP-1')
        payload['jobs'] = [{
            'title': f'Fixture Role {number}',
            'posting_id': str(number),
            'url': f'https://boards.example.test/comp-1/jobs/{number}',
            'location': 'Remote',
            'description': 'Customer-facing implementation and deployment work.',
            'ats': 'Greenhouse',
        } for number in range(105)]
        inbox.save('CYC', 'COMP-1', payload)
        remote = RecordingRemote([company('COMP-1')], schemas=COMPACT_SCHEMAS)
        original_commit = remote.commit

        def uncertain_second_chunk(operations):
            result = original_commit(operations)
            if len(remote.commits) == 2:
                raise UncertainWriteError('synthetic second-chunk uncertainty')
            return result

        with patch.object(remote, 'commit', side_effect=uncertain_second_chunk):
            first = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])
        self.assertEqual(first['confirmed'], [], first)
        self.assertEqual(first['held'], [{
            'company_id': 'COMP-1', 'reason': 'uncertain_write',
        }])
        self.assertEqual(len(remote.commits), 2)

        first_job = remote.snapshot('Job History')[0]
        expected_last_checked = first_job['Last Checked']
        remote._inside_commit = True
        try:
            MemoryRepository.commit(remote, [{
                'tab': 'Job History', 'identity': {'Job Key': first_job['Job Key']},
                'values': {'Last Checked': 'changed-after-earlier-chunk'},
            }])
        finally:
            remote._inside_commit = False

        with patch.object(remote, 'commit', side_effect=AssertionError('chunk replay')):
            changed = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])

        self.assertEqual(changed['confirmed'], [], changed)
        self.assertIn('readback', changed['held'][0]['reason'].lower())
        self.assertEqual(len(remote.commits), 2)
        self.assertEqual(inbox.exact_remote_state('CYC', 'COMP-1')['state'],
                         'SYNC_PENDING')

        remote._inside_commit = True
        try:
            MemoryRepository.commit(remote, [{
                'tab': 'Job History', 'identity': {'Job Key': first_job['Job Key']},
                'values': {'Last Checked': expected_last_checked},
            }])
        finally:
            remote._inside_commit = False
        with patch.object(remote, 'commit', side_effect=AssertionError('chunk replay')):
            result = recover_exact_cycle(engine, remote, 'CYC', ['COMP-1'])

        self.assertEqual(result['confirmed'], ['COMP-1'], result)
        self.assertEqual(result['held'], [], result)
        self.assertGreater(len(remote.commits), 1)
        self.assertTrue(all(1 <= len(chunk) <= 100 for chunk in remote.commits))
        self.assertEqual(sum(map(len, remote.commits)), 106)

    def test_normal_scraper_lock_contention_prevents_all_state_inbox_remote_access(self):
        engine = MagicMock()
        engine.state.path = str(self.fake_state_path)
        remote = MagicMock()
        lock_path = self.fake_state_path.parent / scraper_lock_name()
        with writer_lock(lock_path):
            with self.assertRaises(WriterLockBusy):
                recover_exact_cycle(engine, remote, 'CYC', ['COMP'])
        engine.state.cycle.assert_not_called()
        engine.inbox.get.assert_not_called()
        engine.inbox.plan.assert_not_called()
        remote.read_columns.assert_not_called()
        remote.read_rows.assert_not_called()
        remote.commit.assert_not_called()

    def test_factory_constructs_dependencies_inside_lock_once_and_closes_first(self):
        root = Path(self.temporary.name) / 'constructed-under-lock'
        root.mkdir()
        state_path = root / 'state.db'
        state_path.touch()
        events = []

        def assert_lock_held():
            with self.assertRaises(WriterLockBusy):
                with writer_lock(root / scraper_lock_name()):
                    pass

        def factory():
            events.append('factory')
            assert_lock_held()

            @contextmanager
            def dependencies():
                events.append('enter')
                local = MemoryRepository(
                    {'Companies': [company('COMP-1')]}, schemas=copy.deepcopy(SCHEMAS),
                )
                state = State(state_path)
                inbox = InventoryInbox(root / 'inbox.db', 'fixture')
                try:
                    engine = Engine(
                        local, state, inbox=inbox, error_log_path=root / 'errors.jsonl',
                    )
                    state.save_cycle({
                        'id': 'CYC', 'status': 'In Progress',
                        'started_at': '2026-11-19T00:00:00Z',
                        'companies': {'COMP-1': {'stage': 'queued'}},
                    })
                    inbox.save('CYC', 'COMP-1', inventory('COMP-1'))
                    yield engine, RecordingRemote([company('COMP-1')])
                    self.assertEqual(inbox.pending('CYC', include_blocked=True), ['COMP-1'])
                finally:
                    inbox.close()
                    state.close()
                    events.append('exit')
                    assert_lock_held()

            return dependencies()

        result = recover_exact_cycle_with_factory(
            state_path, factory, 'CYC', ['COMP-1'],
        )
        self.assertEqual(result['confirmed'], [])
        self.assertEqual(result['held'], [{
            'company_id': 'COMP-1', 'reason': 'local_plan_not_durably_applied',
        }])
        self.assertEqual(events, ['factory', 'enter', 'exit'])
        with writer_lock(root / scraper_lock_name()):
            pass

    def test_invalid_selection_factory_and_contention_never_invoke_factory(self):
        factory = MagicMock()
        for selected in ([], ['A', 'A'], ['C%s' % i for i in range(6)]):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    recover_exact_cycle_with_factory(
                        self.fake_state_path, factory, 'CYC', selected,
                    )
        factory.assert_not_called()

        with self.assertRaisesRegex(ValueError, 'factory_required'):
            recover_exact_cycle_with_factory(
                self.fake_state_path, None, 'CYC', ['COMP'],
            )
        factory.assert_not_called()

        lock_path = self.fake_state_path.parent / scraper_lock_name()
        with writer_lock(lock_path):
            with self.assertRaises(WriterLockBusy):
                recover_exact_cycle_with_factory(
                    self.fake_state_path, factory, 'CYC', ['COMP'],
                )
        factory.assert_not_called()

    def test_factory_wrong_engine_path_rejects_before_protected_access_and_closes(self):
        other_path = self.fake_state_path.parent / 'other-state.db'
        other_path.touch()
        engine = self.fake_engine({'COMP': {'stage': 'queued'}},
                                  {'COMP': ({}, False)}, {'COMP': None})
        engine.state.path = str(other_path)
        remote = MagicMock()
        events = []

        @contextmanager
        def dependencies():
            events.append('enter')
            try:
                yield engine, remote
            finally:
                events.append('exit')

        factory = MagicMock(side_effect=lambda: dependencies())
        with self.assertRaisesRegex(RuntimeError, 'state_path_mismatch'):
            recover_exact_cycle_with_factory(
                self.fake_state_path, factory, 'CYC', ['COMP'],
            )
        factory.assert_called_once_with()
        self.assertEqual(events, ['enter', 'exit'])
        engine.state.cycle.assert_not_called()
        engine.inbox.get.assert_not_called()
        remote.read_columns.assert_not_called()
        remote.read_rows.assert_not_called()
        remote.commit.assert_not_called()

    def test_factory_context_closes_on_recovery_exception_before_lock_release(self):
        engine = self.fake_engine({'COMP': {'stage': 'queued'}},
                                  {'COMP': ({}, False)}, {'COMP': None})
        engine.state.cycle.side_effect = OSError('checkpoint unavailable')
        remote = MagicMock()
        events = []
        lock_path = self.fake_state_path.parent / scraper_lock_name()

        @contextmanager
        def dependencies():
            events.append('enter')
            try:
                yield engine, remote
            finally:
                events.append('exit')
                with self.assertRaises(WriterLockBusy):
                    with writer_lock(lock_path):
                        pass

        factory = MagicMock(side_effect=lambda: dependencies())
        with self.assertRaisesRegex(OSError, 'checkpoint unavailable'):
            recover_exact_cycle_with_factory(
                self.fake_state_path, factory, 'CYC', ['COMP'],
            )
        factory.assert_called_once_with()
        self.assertEqual(events, ['enter', 'exit'])
        with writer_lock(lock_path):
            pass

    def test_file_backed_state_required_before_state_inbox_or_remote_access(self):
        engine = MagicMock()
        engine.state.path = ':memory:'
        remote = MagicMock()
        with self.assertRaisesRegex(RuntimeError, 'file_backed_state'):
            recover_exact_cycle(engine, remote, 'CYC', ['COMP'])
        engine.state.cycle.assert_not_called()
        engine.inbox.get.assert_not_called()
        remote.read_columns.assert_not_called()

        factory = MagicMock()
        for invalid in (self.fake_state_path.parent / 'missing.db',
                        self.fake_state_path.parent):
            with self.subTest(invalid=invalid), \
                    self.assertRaisesRegex(RuntimeError, 'file_backed_state'):
                recover_exact_cycle_with_factory(
                    invalid, factory, 'CYC', ['COMP'],
                )
        factory.assert_not_called()

    def test_callable_lock_assertion_is_not_accepted(self):
        engine = MagicMock()
        remote = MagicMock()
        with self.assertRaisesRegex(TypeError, 'writer_lock_assertion'):
            recover_exact_cycle(
                engine, remote, 'CYC', ['COMP'],
                writer_lock_assertion=lambda: True,
            )
        engine.state.cycle.assert_not_called()
        engine.inbox.get.assert_not_called()
        remote.read_columns.assert_not_called()

    def test_invalid_selection_rejected_before_remote_or_local_access(self):
        engine = MagicMock(); remote = MagicMock()
        for selected in ([], ['A', 'A'], ['C%s' % i for i in range(6)]):
            with self.subTest(selected=selected):
                with self.assertRaises(ValueError):
                    recover_exact_cycle(engine, remote, 'CYC', selected)
        engine.state.cycle.assert_not_called(); remote.read_columns.assert_not_called()

    def test_preflight_all_members_before_first_remote_planner_call(self):
        engine = self.fake_engine({'A': {'stage': 'queued'}, 'B': {'stage': 'queued'}},
                                  {'A': ({}, False), 'B': None}, {'A': None, 'B': None})
        remote = MagicMock()
        with patch('job_search_helper.exact_cycle_recovery.freeze_exact_cycle_plans') as planner:
            with self.assertRaisesRegex(ValueError, 'inventory_missing'):
                recover_exact_cycle(engine, remote, 'CYC', ['A', 'B'])
        planner.assert_not_called(); remote.read_columns.assert_not_called()

    def test_supersession_race_fails_before_remote_or_unrelated_dirty_state(self):
        """A cycle changing after preflight cannot fall back to another cycle."""
        engine = self.fake_engine(
            {'A': {'stage': 'queued'}, 'UNRELATED': {'stage': 'queued'}},
            {'A': ({}, False), 'UNRELATED': ({'dirty': 'local-only'}, False)},
            {'A': None, 'UNRELATED': None},
        )
        remote = MagicMock()
        unrelated_before = copy.deepcopy(engine.inbox.get('CYC', 'UNRELATED'))
        with (
            patch('job_search_helper.scan_request.superseded_cycle_ids',
                  side_effect=[set(), {'CYC'}]),
            patch('job_search_helper.exact_cycle_recovery.freeze_exact_cycle_plans') as planner,
        ):
            with self.assertRaisesRegex(ValueError, 'cycle_superseded'):
                recover_exact_cycle(engine, remote, 'CYC', ['A'])
        planner.assert_not_called()
        remote.read_columns.assert_not_called()
        remote.read_rows.assert_not_called()
        remote.commit.assert_not_called()
        self.assertEqual(engine.inbox.get('CYC', 'UNRELATED'), unrelated_before)

    def test_new_and_existing_selected_plans_are_processed_one_company_at_a_time(self):
        engine = self.fake_engine({'A': {'stage': 'queued'}, 'B': {'stage': 'inventory'}},
                                  {'A': ({}, False), 'B': ({}, False)}, {'A': None, 'B': ({}, 0)})
        remote = MagicMock()
        with patch('job_search_helper.exact_cycle_recovery.freeze_exact_cycle_plans',
                   return_value={'planned': ['A'], 'recovered': [], 'held': []}) as planner, \
             patch('job_search_helper.exact_cycle_recovery.publish_exact_cycle',
                   side_effect=[{'confirmed': ['A'], 'held': [], 'skipped': []},
                                {'confirmed': ['B'], 'held': [], 'skipped': []}]) as publisher:
            result = recover_exact_cycle(engine, remote, 'CYC', ['A', 'B'])
        self.assertEqual(result['planned'], ['A']); self.assertEqual(result['confirmed'], ['A', 'B'])
        self.assertEqual([call.kwargs['company_ids'] for call in publisher.call_args_list], [['A'], ['B']])
        planner.assert_called_once()
        # Planning and every publisher invocation receive the same composite
        # local/compact-remote control reader; neither can silently fall back
        # to remote-only claim fields.
        guard = planner.call_args.kwargs['company_guard']
        self.assertIs(publisher.call_args_list[0].kwargs['company_guard'], guard)
        self.assertIs(publisher.call_args_list[1].kwargs['company_guard'], guard)

    def test_planner_hold_does_not_publish_that_company_and_unselected_is_untouched(self):
        engine = self.fake_engine({'A': {'stage': 'queued'}, 'Z': {'stage': 'queued'}},
                                  {'A': ({}, False), 'Z': ({}, False)}, {'A': None, 'Z': None})
        remote = MagicMock()
        with patch('job_search_helper.exact_cycle_recovery.freeze_exact_cycle_plans',
                   return_value={'planned': [], 'recovered': [], 'held': [{'company_id': 'A', 'reason': 'hold'}]}), \
             patch('job_search_helper.exact_cycle_recovery.publish_exact_cycle') as publisher:
            result = recover_exact_cycle(engine, remote, 'CYC', ['A'])
        self.assertEqual(result['held'][0]['reason'], 'hold'); publisher.assert_not_called()
        self.assertEqual(engine.inbox.get.call_args_list[0].args[1], 'A')

    def test_plan_checkpoint_split_and_post_final_split_route_without_global_work(self):
        engine = self.fake_engine({'A': {'stage': 'queued'}, 'B': {'stage': 'complete'}},
                                  {'A': ({}, False), 'B': ({}, False)}, {'A': ({}, 0), 'B': ({}, 1)})
        remote = MagicMock()
        with patch('job_search_helper.exact_cycle_recovery.freeze_exact_cycle_plans',
                   return_value={'planned': [], 'recovered': ['A'], 'held': []}) as planner, \
             patch('job_search_helper.exact_cycle_recovery.publish_exact_cycle',
                   side_effect=[{'confirmed': ['A'], 'held': [], 'skipped': []},
                                {'confirmed': ['B'], 'held': [], 'skipped': []}]) as publisher:
            result = recover_exact_cycle(engine, remote, 'CYC', ['A', 'B'])
        self.assertEqual(result['recovered'], ['A']); planner.assert_called_once()
        self.assertEqual([call.kwargs['company_ids'] for call in publisher.call_args_list], [['A'], ['B']])


if __name__ == '__main__':
    unittest.main()
