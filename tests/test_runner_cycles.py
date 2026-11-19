from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper.engine import State
from job_search_helper.runner import active_inbox_cycles
from job_search_helper.runner import _print_run_status
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO


class DummyInbox:
    def cycles(self, include_blocked=False):
        return ["CYC-DONE", "CYC-ACTIVE", "CYC-ORPHAN"]


class RunnerCycleSelectionTests(unittest.TestCase):
    def test_recovery_command_requires_explicit_apply(self):
        from job_search_helper.runner import main
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['recover-interrupted-cycle', '--cycle-id', 'CYC-1',
                                   '--reason', 'planned recovery']), 2)

    def test_summary_separates_scrape_completion_from_global_review_backlog(self):
        output = StringIO()
        with redirect_stdout(output):
            _print_run_status({'cycle_id': 'CYC', 'status': 'In Progress', 'pending_reviews': 19672,
                'manual_review': 242, 'companies': {'C-1': {'stage': 'queued'}, 'C-2': {'stage': 'complete'}}})
        self.assertIn('cycle_status=In Progress', output.getvalue())
        self.assertIn('"queued": 1', output.getvalue())
        self.assertIn('Job History (all cycles)', output.getvalue())
        self.assertIn('unfinished scraping', output.getvalue())

    def test_start_ignores_blocked_inbox_work_from_completed_cycles(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = State(Path(temporary) / "state.db")
            self.addCleanup(state.close)
            state.save_cycle({
                "id": "CYC-DONE", "started_at": "2026-09-17T01:00:00+00:00",
                "status": "Complete with exceptions", "all": True, "companies": {},
            })
            state.save_cycle({
                "id": "CYC-ACTIVE", "started_at": "2026-09-17T02:00:00+00:00",
                "status": "In Progress", "all": True, "companies": {},
            })

            self.assertEqual(
                active_inbox_cycles(DummyInbox(), state),
                ["CYC-ACTIVE", "CYC-ORPHAN"],
            )


class ExactSyncRunnerAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'state.db'
        # Exact recovery deliberately requires a present regular State file.
        state = State(self.database)
        state.close()
        from job_search_helper.inbox import InventoryInbox
        inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture')
        inbox.close()

    def seed(self, *, cycle_id='CYC-EXACT', cycle_company='C-1', stage='queued',
             status='In Progress', selected_company='C-1', saved=True,
             blocked=False, plan=None, save_plan=False):
        from job_search_helper.inbox import InventoryInbox
        state = State(self.database)
        state.save_cycle({
            'id': cycle_id,
            'started_at': '2026-11-19T00:00:00+00:00',
            'status': status,
            'all': False,
            'companies': {cycle_company: {'stage': stage}},
        })
        state.close()
        inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture')
        if saved:
            inbox.save(cycle_id, selected_company, {'company_id': selected_company})
        if blocked:
            inbox.block(cycle_id, selected_company)
        if save_plan:
            inbox.save_plan(cycle_id, selected_company, plan)
        inbox.close()

    def exact_runner_stack(self, stack, *, get_remote=None, make_engine=None):
        """Install only external/dependency seams; State and Inbox remain real."""
        from job_search_helper import runner

        local = MagicMock(name='readonly_local')
        local.get_meta.return_value = 'fixture-profile'
        remote = MagicMock(name='remote')
        engines = []
        states = []
        inboxes = []
        real_state = runner.State
        real_inbox = runner.InventoryInbox

        def make_state(path):
            state = real_state(path)
            states.append(state)
            return state

        def make_inbox(path, spreadsheet_id):
            inbox = real_inbox(path, spreadsheet_id)
            inboxes.append(inbox)
            return inbox

        def default_engine(repository, state, **kwargs):
            engine = SimpleNamespace(
                state=state, inbox=kwargs['inbox'],
                sync_manual_opportunities=MagicMock(name='sync_manual_opportunities'))
            engines.append(engine)
            return engine

        stack.enter_context(patch.object(runner, '_load_environment'))
        stack.enter_context(patch.object(runner, 'storage_backend', return_value='sqlite'))
        stack.enter_context(patch.object(runner, 'load_title_blacklist'))
        stack.enter_context(patch.object(runner, 'load_title_review_list'))
        stack.enter_context(patch.object(runner, 'state_path', return_value=self.database))
        stack.enter_context(patch.object(runner, 'State', side_effect=make_state))
        inbox_class = stack.enter_context(patch.object(
            runner, 'InventoryInbox', side_effect=make_inbox))
        inbox_class.destination_id.side_effect = real_inbox.destination_id
        outer_lock = stack.enter_context(patch.object(runner, 'writer_lock'))
        repository = stack.enter_context(patch.object(runner, 'get_repository'))
        engine = stack.enter_context(patch.object(
            runner, 'Engine', side_effect=make_engine or default_engine))
        stack.enter_context(patch('job_search_helper.cli.job_database_path',
                                  return_value=self.root / 'jobs.db'))
        stack.enter_context(patch('job_search_helper.sqlite_repository.SQLiteRepository',
                                  return_value=local))
        stack.enter_context(patch('job_search_helper.sheet_profile.profile_schemas',
                                  return_value={'Companies': object()}))
        get_remote_mock = stack.enter_context(patch(
            'job_search_helper.cli.get_remote_repository', side_effect=get_remote)) \
            if get_remote is not None else stack.enter_context(patch(
                'job_search_helper.cli.get_remote_repository', return_value=remote))
        release = stack.enter_context(patch(
            'job_search_helper.integration_release.assert_release_settled'))
        run_scoped = stack.enter_context(patch(
            'job_search_helper.run_sync.run_scoped_sync'))
        review = stack.enter_context(patch.object(runner, '_refresh_review_queue'))
        review_lifecycle = stack.enter_context(patch.object(runner, '_review_queue_lifecycle'))
        purge_reviews = stack.enter_context(patch.object(real_state, 'purge_reviews'))
        closed_cleanup = stack.enter_context(patch(
            'job_search_helper.closed_jobs.stage_closed_pending'))
        outcomes = stack.enter_context(patch(
            'job_search_helper.scrape_outcome_producer.record_cycle_outcomes'))
        performance = stack.enter_context(patch.object(runner, '_save_performance'))
        return SimpleNamespace(
            local=local, remote=remote, engines=engines, states=states,
            inboxes=inboxes, outer_lock=outer_lock,
            repository=repository, engine=engine, get_remote=get_remote_mock,
            release=release, run_scoped=run_scoped, review=review,
            review_lifecycle=review_lifecycle, purge_reviews=purge_reviews,
            closed_cleanup=closed_cleanup, outcomes=outcomes,
            performance=performance,
        )

    def test_public_cli_requires_cycle_and_one_or_more_repeatable_company_ids(self):
        from job_search_helper import runner

        with redirect_stderr(StringIO()), patch.object(runner, 'run_start') as run:
            self.assertEqual(runner.main(['sync', '--company-id', 'C-1']), 2)
            run.assert_not_called()

        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(runner.main(['sync', '--cycle-id', 'CYC-EXACT']), 1)

        with patch.object(runner, 'run_start', return_value=0) as run:
            self.assertEqual(runner.main([
                'sync', '--cycle-id', 'CYC-EXACT',
                '--company-id', 'C-1', '--company-id', 'C-2',
            ]), 0)
        self.assertEqual(run.call_args.kwargs['sync_cycle_id'], 'CYC-EXACT')
        self.assertEqual(run.call_args.kwargs['sync_company_ids'], ['C-1', 'C-2'])

    def test_invalid_exact_selections_stop_before_factory_or_remote(self):
        from job_search_helper import runner

        invalid = ([], [''], ['   '], ['C-1', 'C-1'],
                   ['C-1', 'C-2', 'C-3', 'C-4', 'C-5', 'C-6'])
        with patch('job_search_helper.exact_cycle_recovery.recover_exact_cycle_with_factory') as recover, \
                patch('job_search_helper.cli.get_remote_repository') as get_remote, \
                patch.object(runner, '_load_environment') as load_environment:
            for selected in invalid:
                with self.subTest(selected=selected), self.assertRaisesRegex(
                        ValueError, 'unique and bounded'):
                    runner.run_start(sync_only=True, sync_cycle_id='CYC-EXACT',
                                     sync_company_ids=selected)
        recover.assert_not_called()
        get_remote.assert_not_called()
        load_environment.assert_not_called()

    def test_exact_run_uses_lock_owned_lazy_factory_orders_release_and_closes_dependencies(self):
        from job_search_helper import runner
        from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
        from job_search_helper import exact_cycle_recovery

        self.seed()
        events = []

        def get_remote(**kwargs):
            events.append('remote')
            with self.assertRaises(WriterLockBusy):
                with writer_lock(self.root / scraper_lock_name()):
                    pass
            return MagicMock(name='remote')

        output = StringIO()
        with ExitStack() as stack:
            seams = self.exact_runner_stack(stack, get_remote=get_remote)
            seams.release.side_effect = lambda directory: events.append('release')
            planner = stack.enter_context(patch.object(
                exact_cycle_recovery, 'freeze_exact_cycle_plans',
                return_value={'planned': ['C-1'], 'recovered': [], 'held': []}))
            publisher = stack.enter_context(patch.object(
                exact_cycle_recovery, 'publish_exact_cycle',
                return_value={'confirmed': ['C-1'], 'held': [], 'skipped': []}))
            with redirect_stdout(output):
                self.assertEqual(runner.run_start(
                    sync_only=True, sync_cycle_id='CYC-EXACT',
                    sync_company_ids=['C-1']), 0)

        seams.outer_lock.assert_not_called()
        seams.repository.assert_not_called()
        seams.release.assert_called_once_with(self.root)
        self.assertEqual(events, ['release', 'remote'])
        seams.local.close.assert_called_once_with()
        self.assertEqual(len(seams.engines), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            seams.engines[0].state.connection.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            seams.engines[0].inbox.connection.execute('SELECT 1')
        planner.assert_called_once()
        publisher.assert_called_once()
        for hook in (seams.run_scoped, seams.review, seams.review_lifecycle,
                     seams.purge_reviews, seams.closed_cleanup, seams.outcomes,
                     seams.performance,
                     seams.engines[0].sync_manual_opportunities):
            hook.assert_not_called()
        text = output.getvalue()
        for field in ('planned', 'recovered', 'confirmed', 'held', 'skipped'):
            self.assertIn(f'"{field}"', text)

    def test_exact_dependency_context_closes_when_remote_construction_raises(self):
        from job_search_helper import runner

        self.seed()
        with ExitStack() as stack:
            seams = self.exact_runner_stack(
                stack, get_remote=RuntimeError('remote construction failed'))
            with redirect_stdout(StringIO()), self.assertRaisesRegex(
                    RuntimeError, 'remote construction failed'):
                runner.run_start(sync_only=True, sync_cycle_id='CYC-EXACT',
                                 sync_company_ids=['C-1'])
        seams.local.close.assert_called_once_with()
        self.assertEqual(len(seams.states), 1)
        self.assertEqual(len(seams.inboxes), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            seams.states[0].connection.execute('SELECT 1')
        with self.assertRaises(sqlite3.ProgrammingError):
            seams.inboxes[0].connection.execute('SELECT 1')
        seams.outer_lock.assert_not_called()
        seams.run_scoped.assert_not_called()

    def test_local_exact_preflight_rejects_before_release_or_remote(self):
        from job_search_helper import runner

        cases = (
            ('unknown', {'cycle_company': 'C-OTHER'}),
            ('blocked', {'blocked': True}),
            ('finished', {'status': 'Complete'}),
            ('invalid-stage-plan', {'stage': 'inventory'}),
        )
        for label, seed_kwargs in cases:
            with self.subTest(label=label):
                # Each subcase gets independent State/inbox files.
                case_root = self.root / label
                case_root.mkdir()
                original_root, original_database = self.root, self.database
                self.root = case_root
                self.database = case_root / 'state.db'
                state = State(self.database)
                state.close()
                from job_search_helper.inbox import InventoryInbox
                inbox = InventoryInbox(case_root / 'inventories.sqlite3', 'fixture')
                inbox.close()
                self.seed(**seed_kwargs)
                try:
                    with ExitStack() as stack:
                        seams = self.exact_runner_stack(stack)
                        with redirect_stdout(StringIO()), self.assertRaises(ValueError):
                            runner.run_start(
                                sync_only=True, sync_cycle_id='CYC-EXACT',
                                sync_company_ids=['C-1'])
                    seams.get_remote.assert_not_called()
                    seams.release.assert_not_called()
                    seams.local.close.assert_called_once_with()
                finally:
                    self.root, self.database = original_root, original_database

    def test_empty_but_present_plan_is_recoverable(self):
        from job_search_helper import runner
        from job_search_helper import exact_cycle_recovery

        self.seed(stage='inventory', plan={}, save_plan=True)
        with ExitStack() as stack:
            seams = self.exact_runner_stack(stack)
            planner = stack.enter_context(patch.object(
                exact_cycle_recovery, 'freeze_exact_cycle_plans'))
            publisher = stack.enter_context(patch.object(
                exact_cycle_recovery, 'publish_exact_cycle',
                return_value={'confirmed': ['C-1'], 'held': [], 'skipped': []}))
            with redirect_stdout(StringIO()):
                self.assertEqual(runner.run_start(
                    sync_only=True, sync_cycle_id='CYC-EXACT',
                    sync_company_ids=['C-1']), 0)
        planner.assert_not_called()
        publisher.assert_called_once()
        seams.get_remote.assert_called_once()

    def test_legacy_direct_exact_sync_remains_contained_and_cli_never_passes_none(self):
        from job_search_helper import runner
        from job_search_helper.inbox import InventoryInbox

        with patch.object(runner, '_load_environment'), \
                patch.object(runner, 'storage_backend', return_value='sqlite'), \
                patch.object(runner, 'load_title_blacklist'), \
                patch.object(runner, 'load_title_review_list'), \
                patch.object(runner, 'state_path', return_value=self.database), \
                patch.object(InventoryInbox, 'has_unblocked_inventory', return_value=True), \
                patch('job_search_helper.integration_release.assert_release_settled'), \
                patch('job_search_helper.exact_cycle_recovery.recover_exact_cycle_with_factory') as recover, \
                patch('job_search_helper.run_sync.run_scoped_sync') as run_scoped, \
                patch.object(runner, 'get_repository') as get_repository, \
                patch.object(runner, '_refresh_review_queue') as review, \
                patch.object(runner, '_save_performance') as performance, \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(runner.run_start(
                sync_only=True, sync_cycle_id='CYC-EXACT',
                sync_company_ids=None), 0)
        self.assertIn('HELD_NO_EXACT_PLANNER', output.getvalue())
        recover.assert_not_called()
        run_scoped.assert_not_called()
        get_repository.assert_not_called()
        review.assert_not_called()
        performance.assert_not_called()

        with patch.object(runner, 'run_start', return_value=0) as run:
            self.assertEqual(runner.main(['sync', '--cycle-id', 'CYC-EXACT']), 0)
        self.assertEqual(run.call_args.kwargs['sync_company_ids'], [])
        self.assertIsNotNone(run.call_args.kwargs['sync_company_ids'])




class FreshStartLifecycleTests(unittest.TestCase):
    def setUp(self):
        from job_search_helper.engine import Engine
        from job_search_helper.inbox import InventoryInbox
        from job_search_helper.repository import MemoryRepository
        from test_fetch_pool import company, inventory
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / 'state.db'
        self.state = State(self.database)
        self.addCleanup(self.state.close)
        self.repo = MemoryRepository({'Companies': [company(0), company(1)]})
        self.repo.spreadsheet_id = 'fixture'
        self.inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture')
        self.addCleanup(self.inbox.close)
        self.calls = []
        def fetch(source, url, cid, name):
            self.calls.append(cid)
            result = inventory(cid, name, url)
            if cid == 'C-1':
                result.status = 'partial'
                result.browser_discovery_incomplete = True
            return result
        self.engine = Engine(self.repo, self.state, inbox=self.inbox, fetcher=fetch,
                             error_log_path=self.root / 'errors.jsonl')
        self.output = StringIO()
        capture = redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def start(self, resume=False):
        from job_search_helper.runner import select_start_cycle
        cycle_id = select_start_cycle(self.engine, self.state, self.repo, self.database, resume=resume)
        result = self.engine.resume_local(cycle_id, fetch_workers=1, retry_partial=resume, retry_blocked=True)
        return cycle_id, result

    def test_repeated_start_rechecks_successes_and_partials_and_adds_new_company(self):
        from test_fetch_pool import company
        first, result = self.start()
        self.assertEqual(result['status'], 'Complete with exceptions')
        self.assertEqual(result['run_counts'], {'new_jobs': 2, 'successful': 1, 'partial': 1,
                                              'failed': 0, 'skipped': 0, 'pending': 0})
        before = self.state.cycle(first)
        self.repo.commit([{'tab': 'Companies', 'identity': {'Company ID': 'C-2'},
                           'values': company(2), 'append_if_missing': True}])
        second, result = self.start()
        self.assertNotEqual(first, second)
        self.assertEqual(self.calls, ['C-0', 'C-1', 'C-0', 'C-1', 'C-2'])
        self.assertEqual(self.state.cycle(first), before)
        self.assertEqual(result['run_counts'], {'new_jobs': 1, 'successful': 2, 'partial': 1,
                                              'failed': 0, 'skipped': 0, 'pending': 0})
        self.assertEqual(len(self.repo.read('Job History')), 3)
        rows = {row['Company ID']: row for row in self.repo.read('Companies')}
        self.assertTrue(rows['C-0']['Last Checked'])
        self.assertFalse(rows['C-1'].get('Last Checked'))
        self.assertEqual(rows['C-1']['Scan State'], 'Partial')

    def test_explicit_resume_retries_partial_without_repeating_complete(self):
        first, _ = self.start()
        self.calls.clear()
        second, result = self.start(resume=True)
        self.assertEqual(first, second)
        self.assertEqual(self.calls, ['C-1'])
        self.assertEqual(result['run_counts']['new_jobs'], 0)
        self.assertEqual(result['run_counts']['successful'], 0)
        self.assertEqual(result['run_counts']['partial'], 1)
        self.assertEqual(result['run_counts']['skipped'], 1)

    def test_fresh_start_supersedes_old_queue_without_deleting_its_payload_or_plan(self):
        from job_search_helper.engine import inventory_payload
        from test_fetch_pool import company, inventory
        old = self.engine.start_cycle()
        c = company(1)
        payload = inventory_payload(inventory('C-1', c['Company'], c['Official Careers URL']), c)
        self.inbox.save(old, 'C-1', payload)
        plan = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': 'C-1'},
                                'values': {'Scan State': 'Complete'}}], 'final': {'stage': 'complete'}}
        self.inbox.save_plan(old, 'C-1', plan)
        before = self.state.cycle(old)
        new, result = self.start()
        self.assertNotEqual(old, new)
        self.assertIn(old, self.state.cycle(new)['supersedes'])
        self.assertEqual(self.state.cycle(old), before)
        self.assertEqual(self.inbox.get(old, 'C-1')[0], payload)
        self.assertEqual(self.inbox.plan(old, 'C-1'), (plan, 0))
        self.assertEqual(self.calls, ['C-0', 'C-1'])

    def test_resume_processes_durable_saved_inventory_without_fetching_it_again(self):
        from job_search_helper.engine import inventory_payload
        from test_fetch_pool import company, inventory
        old = self.engine.start_cycle()
        c = company(0)
        self.inbox.save(old, 'C-0', inventory_payload(inventory('C-0', c['Company'], c['Official Careers URL']), c))
        cycle, result = self.start(resume=True)
        self.assertEqual(cycle, old)
        self.assertEqual(self.calls, ['C-1'])
        self.assertEqual(result['run_counts']['successful'], 1)
        self.assertEqual(result['run_counts']['partial'], 1)
        self.assertEqual(result['status'], 'Complete with exceptions')

    def test_interruption_keeps_unattempted_companies_resumable(self):
        from unittest.mock import patch
        import sqlite3
        from job_search_helper.runner import select_start_cycle
        cycle = select_start_cycle(self.engine, self.state, self.repo, self.database)
        with patch.object(self.inbox, 'save', side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                self.engine.resume_local(cycle, fetch_workers=1)
        self.assertEqual(self.state.cycle(cycle)['status'], 'In Progress')
        self.assertFalse(self.state.cycle(cycle).get('completed_at'))
        self.calls.clear()
        resumed, result = self.start(resume=True)
        self.assertEqual(resumed, cycle)
        self.assertEqual(self.calls, ['C-0', 'C-1'])

    def test_cli_default_and_resume_are_distinct_and_sync_rejects_resume(self):
        from unittest.mock import patch
        from contextlib import redirect_stderr
        from job_search_helper import runner
        with patch.object(runner, 'run_start', return_value=0) as run:
            self.assertEqual(runner.main(['start', '--fetch-workers', '15']), 0)
            self.assertFalse(run.call_args.kwargs['resume'])
            self.assertEqual(runner.main(['start', '--resume', '--fetch-workers', '15']), 0)
            self.assertTrue(run.call_args.kwargs['resume'])
            run.reset_mock()
            with redirect_stderr(StringIO()):
                self.assertEqual(runner.main(['sync', '--resume']), 2)
            run.assert_not_called()

    def test_summary_reports_run_counts_and_leaves_zero_skipped_blank(self):
        from job_search_helper.runner import _print_run_summary
        _, result = self.start()
        self.output.truncate(0); self.output.seek(0)
        _print_run_summary(result['run_counts'])
        text = self.output.getvalue()
        self.assertIn('New jobs downloaded (new Job History rows): 2', text)
        self.assertIn('Companies successfully scanned: 1', text)
        self.assertIn('Companies partially scanned: 1', text)
        self.assertIn('Companies skipped: \n', text)
        self.assertNotIn('Companies blocked or failed:', text)

    def test_actual_runner_finishes_with_summary_and_next_start_scans_again(self):
        from unittest.mock import patch
        from job_search_helper import runner
        from job_search_helper.engine import Engine
        def make_engine(repo, state, **kwargs):
            return Engine(repo, state, fetcher=self.engine.fetcher, error_log_path=self.root / 'errors.jsonl', **kwargs)
        with patch.object(runner, '_load_environment'), \
             patch.object(runner, 'load_title_blacklist'), patch.object(runner, 'load_title_review_list'), \
             patch.object(runner, 'state_path', return_value=self.database), \
             patch.object(runner, 'get_repository', return_value=self.repo), \
             patch.object(runner, 'Engine', side_effect=make_engine), \
             patch.object(runner, '_refresh_review_queue'):
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False), 0)
            self.assertTrue(self.output.getvalue().endswith('Companies skipped: \n'))
            self.output.truncate(0); self.output.seek(0)
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False), 0)
        self.assertEqual(self.calls, ['C-0', 'C-1', 'C-0', 'C-1'])
        self.assertIn('New jobs downloaded (new Job History rows): 0', self.output.getvalue())
        self.assertTrue(self.output.getvalue().endswith('Companies skipped: \n'))

    def test_actual_runner_processes_company_events_at_the_existing_writer_boundary(self):
        from unittest.mock import patch
        from job_search_helper import runner
        from job_search_helper import company_events
        from job_search_helper.engine import Engine

        calls = []

        class Bridge:
            def __init__(self, repo, directory):
                self.repo = repo
                self.directory = directory

            def process_pending(self, **kwargs):
                calls.append((self.repo, self.directory, kwargs))
                return []

        def make_engine(repo, state, **kwargs):
            return Engine(repo, state, fetcher=self.engine.fetcher,
                          error_log_path=self.root / 'errors.jsonl', **kwargs)

        with patch.object(runner, '_load_environment'), \
             patch.object(runner, 'load_title_blacklist'), patch.object(runner, 'load_title_review_list'), \
             patch.object(runner, 'state_path', return_value=self.database), \
             patch.object(runner, 'get_repository', return_value=self.repo), \
             patch.object(runner, 'Engine', side_effect=make_engine), \
             patch.object(runner, '_refresh_review_queue'), \
             patch.object(self.repo, 'is_local', True, create=True), \
             patch.object(company_events, 'CompanyEventBridge', Bridge):
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False, defer_sync=True), 0)

        self.assertEqual(calls, [(self.repo, self.root, {'writer_lock_held': True})])

    def test_resume_never_falls_back_to_older_unfinished_scan(self):
        from job_search_helper.runner import resolve_cycle
        for cid, date, status in [('OLD', '2026-10-13T00:00:00+00:00', 'In Progress'),
                                  ('NEW', '2026-10-29T00:00:00+00:00', 'Complete')]:
            self.state.save_cycle({'id': cid, 'started_at': date, 'status': status, 'all': True, 'companies': {}})
        with self.assertRaisesRegex(ValueError, 'latest scan is already complete'):
            resolve_cycle(self.engine, self.state, self.repo)
        self.assertEqual(len(self.state.cycles()), 2)

    def test_resume_recovers_latest_remote_scope_and_newest_remote_supersession(self):
        from job_search_helper.runner import resolve_cycle
        from job_search_helper.engine import State, Engine
        old = self.engine.start_cycle()
        new, _ = self.start()
        empty = State()
        self.addCleanup(empty.close)
        engine = Engine(self.repo, empty)
        selected, _ = resolve_cycle(engine, empty, self.repo)
        self.assertEqual(selected, new)
        self.assertIn(old, empty.cycle(new)['supersedes'])
        self.assertEqual(set(empty.cycle(new)['companies']), {'C-0', 'C-1'})

    def test_resume_without_saved_scan_or_with_pending_fresh_request_fails_without_changes(self):
        from job_search_helper.runner import select_start_cycle
        with self.assertRaisesRegex(ValueError, 'No saved scan'):
            select_start_cycle(self.engine, self.state, self.repo, self.database, resume=True)
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"fresh-full-scan","request_id":"pending"}')
        with self.assertRaisesRegex(ValueError, 'fresh next-scan.json request is pending'):
            select_start_cycle(self.engine, self.state, self.repo, self.database, resume=True)
        self.assertTrue(request.exists())
        self.assertEqual(self.state.cycles(), [])

    def test_company_only_request_starts_only_declared_company(self):
        from job_search_helper.runner import select_start_cycle
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"company-only","request_id":"one-company","company_ids":["C-1"],"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')

        cycle = select_start_cycle(self.engine, self.state, self.repo, self.database)

        self.assertEqual(set(self.state.cycle(cycle)['companies']), {'C-1'})
        self.assertFalse(self.state.cycle(cycle)['all'])
        self.assertFalse(request.exists())
        self.assertTrue((self.root / 'last-scan-request.json').exists())

    def test_company_only_request_id_reuses_started_cycle_after_interrupted_receipt(self):
        from job_search_helper.runner import select_start_cycle
        request = self.root / 'next-scan.json'
        payload = '{"mode":"company-only","request_id":"deduplicate","company_ids":["C-1"],"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}'
        request.write_text(payload)
        first = select_start_cycle(self.engine, self.state, self.repo, self.database)

        # Models a crash after cycle creation but before the request receipt
        # rename: retrying the same durable request cannot create another run.
        request.write_text(payload)
        second = select_start_cycle(self.engine, self.state, self.repo, self.database)

        self.assertEqual(first, second)
        self.assertEqual(len(self.state.cycles()), 1)
        self.assertEqual(set(self.state.cycle(first)['companies']), {'C-1'})

    def test_company_only_request_id_rejects_changed_scope_or_source_revision(self):
        from job_search_helper.runner import select_start_cycle
        request = self.root / 'next-scan.json'
        original = ('{"mode":"company-only","request_id":"immutable","company_ids":["C-1"],'
                    '"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')
        request.write_text(original)
        select_start_cycle(self.engine, self.state, self.repo, self.database)
        request.write_text(original.replace('rev-1', 'rev-2'))
        with self.assertRaisesRegex(ValueError, 'different immutable request content'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)

    def test_company_only_request_id_rejects_changed_company_set_replay(self):
        from job_search_helper.runner import select_start_cycle
        request = self.root / 'next-scan.json'
        original = ('{"mode":"company-only","request_id":"immutable-scope","company_ids":["C-1"],'
                    '"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')
        request.write_text(original)
        cycle = select_start_cycle(self.engine, self.state, self.repo, self.database)

        request.write_text(original.replace('["C-1"]', '["C-0","C-1"]'))
        with self.assertRaisesRegex(ValueError, 'different immutable request content'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)

        self.assertEqual(set(self.state.cycle(cycle)['companies']), {'C-1'})
        self.assertTrue(request.exists())

    def test_company_only_request_waits_without_superseding_active_cycle(self):
        from job_search_helper.runner import company_only_queue_status, select_start_cycle
        active = self.engine.start_cycle(company_ids=['C-0'])
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"company-only","request_id":"waiting","company_ids":["C-1"],"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')

        with self.assertRaisesRegex(ValueError, f'safe boundary.*{active}'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)

        self.assertTrue(request.exists())
        self.assertEqual(set(self.state.cycle(active)['companies']), {'C-0'})
        self.assertEqual(len(self.state.cycles()), 1)
        status = company_only_queue_status(
            self.engine, self.state, self.database,
            observed_at=datetime(2026, 11, 18, 0, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(status['queue_age_seconds'], 60)
        self.assertEqual(status['blocking_cycle_ids'], [active])

    def test_company_only_request_keeps_paused_cycle_visible_and_unchanged(self):
        from job_search_helper.runner import select_start_cycle
        paused = self.engine.start_cycle(company_ids=['C-0'])
        cycle = self.state.cycle(paused)
        cycle['status'] = 'Paused'
        self.state.save_cycle(cycle)
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"company-only","request_id":"paused","company_ids":["C-1"],"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')

        with self.assertRaisesRegex(ValueError, f'safe boundary.*{paused}'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)

        self.assertTrue(request.exists())
        self.assertEqual(self.state.cycle(paused)['status'], 'Paused')
        self.assertEqual(set(self.state.cycle(paused)['companies']), {'C-0'})

    def test_company_only_queue_status_reports_age_blocker_and_safe_paused_recovery(self):
        from job_search_helper.runner import company_only_queue_status
        paused = self.engine.start_cycle(company_ids=['C-0'])
        cycle = self.state.cycle(paused)
        cycle['status'] = 'Paused'
        self.state.save_cycle(cycle)
        (self.root / 'next-scan.json').write_text(
            '{"mode":"company-only","request_id":"queued","company_ids":["C-1"],"source_revision":"rev-1",'
            '"enqueued_at":"2026-11-18T00:00:00Z"}'
        )

        status = company_only_queue_status(
            self.engine, self.state, self.database,
            observed_at=datetime(2026, 11, 18, 0, 2, tzinfo=timezone.utc),
        )

        self.assertEqual(status['queue_age_seconds'], 120)
        self.assertEqual(status['blocking_cycle_ids'], [paused])
        self.assertIn('start --resume', status['recovery'])
        self.assertIn('do not delete locks', status['recovery'])
        self.assertTrue((self.root / 'next-scan.json').exists())

    def test_company_queue_status_cli_is_read_only_and_can_degrade_to_local_state(self):
        from unittest.mock import patch
        from job_search_helper import runner
        paused = self.engine.start_cycle(company_ids=['C-0'])
        cycle = self.state.cycle(paused)
        cycle['status'] = 'Paused'
        self.state.save_cycle(cycle)
        before = self.state.cycle(paused)
        request = self.root / 'next-scan.json'
        request.write_text(
            '{"mode":"company-only","request_id":"operator-status","company_ids":["C-1"],'
            '"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}'
        )

        with patch.object(runner, 'state_path', return_value=self.database), \
                patch.object(runner, 'get_repository') as get_repository:
            self.assertEqual(runner.main(['company-queue-status', '--local-only']), 0)

        get_repository.assert_not_called()
        self.assertEqual(self.state.cycle(paused), before)
        self.assertTrue(request.exists())
        output = self.output.getvalue()
        self.assertIn('WAITING_SAFE_BOUNDARY', output)
        self.assertIn('queue_age_seconds', output)
        self.assertIn('local-only', output)

    def test_company_only_request_requires_immutable_enqueue_timestamp(self):
        from job_search_helper.runner import select_start_cycle
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"company-only","request_id":"missing-time","company_ids":["C-1"],"source_revision":"rev-1"}')
        with self.assertRaisesRegex(ValueError, 'immutable enqueued_at is required'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertEqual(self.state.cycles(), [])
        self.assertTrue(request.exists())

    def test_company_only_request_rejects_missing_or_unknown_ids_without_full_scan(self):
        from job_search_helper.runner import select_start_cycle
        request = self.root / 'next-scan.json'
        request.write_text('{"mode":"company-only","request_id":"missing","company_ids":[],"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')
        with self.assertRaisesRegex(ValueError, 'refusing to widen'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertEqual(self.state.cycles(), [])
        self.assertTrue(request.exists())

        request.write_text('{"mode":"company-only","request_id":"unknown","company_ids":["C-404"],"source_revision":"rev-1","enqueued_at":"2026-11-18T00:00:00Z"}')
        with self.assertRaisesRegex(ValueError, 'Unknown Company ID'):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertEqual(self.state.cycles(), [])
        self.assertTrue(request.exists())

    def test_engine_rejects_empty_explicit_company_scope(self):
        with self.assertRaisesRegex(ValueError, 'requires at least one'):
            self.engine.start_cycle(company_ids=[])
        self.assertEqual(self.state.cycles(), [])

    def test_blocked_failures_remain_separate_from_partial_and_skipped_counts(self):
        from job_search_helper.ats import Inventory
        from job_search_helper.runner import _print_run_summary
        self.engine.fetcher = lambda *args: Inventory('blocked', reason='Access denied')
        _, result = self.start()
        self.assertEqual(result['status'], 'Complete with exceptions')
        self.assertEqual(result['run_counts'], {'new_jobs': 0, 'successful': 0, 'partial': 0,
                                              'skipped': 0, 'failed': 2, 'pending': 0})
        _print_run_summary(result['run_counts'])
        self.assertIn('Companies blocked or failed: 2', self.output.getvalue())
        self.assertFalse(any(row.get('Last Checked') for row in self.repo.read('Companies')))


if __name__ == '__main__':
    unittest.main()
