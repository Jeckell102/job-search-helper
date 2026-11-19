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
from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


class RecordingRemote(MemoryRepository):
    def __init__(self, companies=None):
        companies = companies or [{
            'Company ID': 'COMP-1', 'Company': 'Fixture',
            'Company Status': 'Active',
            'Official Careers URL': 'https://boards.example.test/fixture',
        }]
        super().__init__({'Companies': companies}, schemas=copy.deepcopy(SCHEMAS))
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

    def test_real_engine_queued_inventory_plans_and_publishes_end_to_end(self):
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
            self.assertEqual(result['confirmed'], ['COMP-1'], result)
            self.assertEqual(inbox.pending('CYC', include_blocked=True), [])

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
        self.assertEqual(recovered['confirmed'], ['COMP-1'], recovered)
        self.assertEqual(inbox.pending('CYC', include_blocked=True), [])

    def test_real_post_state_save_ack_crash_restarts_without_remote_replay(self):
        _root, engine, state, inbox, remote = self.real_fixture()
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
        self.assertEqual(result['confirmed'], ['COMP-A'], result)
        self.assertEqual(result['held'][0]['company_id'], 'COMP-B')
        self.assertEqual(inbox.get('CYC', 'COMP-Z'), unselected_before)
        self.assertEqual(inbox.get('OTHER-CYCLE', 'COMP-Z'), other_before)
        self.assertEqual(remote.snapshot('Companies')[2], remote_z_before)
        self.assertEqual(request.read_bytes(), b'preserve-exact-request')
        self.assertIsNone(inbox.get('CYC', 'COMP-A'))
        self.assertIsNotNone(inbox.get('CYC', 'COMP-B'))
        self.assertEqual(state.cycle('CYC')['companies']['COMP-Z']['stage'], 'queued')

    def test_superseded_cycle_with_existing_plan_is_rejected_without_side_effects(self):
        _root, engine, state, inbox, remote = self.real_fixture()
        planned = freeze_exact_cycle_plans(
            engine, 'CYC', ['COMP-1'],
            company_guard=lambda company_id, requested_url: _company_guard(
                remote, company_id, {'requested_url': requested_url},
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
        self.assertEqual(result['confirmed'], ['COMP-1'], result)
        self.assertEqual(local_snapshot(), before)
        self.assertIsNotNone(inbox.get('CYC', 'COMP-Z'))
        self.assertEqual(state.cycle('CYC')['companies']['COMP-Z']['stage'], 'queued')

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
                    self.assertEqual(inbox.pending('CYC', include_blocked=True), [])
                finally:
                    inbox.close()
                    state.close()
                    events.append('exit')
                    assert_lock_held()

            return dependencies()

        result = recover_exact_cycle_with_factory(
            state_path, factory, 'CYC', ['COMP-1'],
        )
        self.assertEqual(result['confirmed'], ['COMP-1'])
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
