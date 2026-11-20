from pathlib import Path
from datetime import datetime, timezone
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository
from job_search_helper.runner import active_inbox_cycles
from job_search_helper.runner import _print_run_status
from contextlib import nullcontext, redirect_stdout
from io import StringIO


class DummyInbox:
    def cycles(self, include_blocked=False):
        return ["CYC-DONE", "CYC-ACTIVE", "CYC-ORPHAN"]


class CompanyQueueStatusTests(unittest.TestCase):
    def test_unfinished_invocation_keeps_final_company_event_in_outbox(self):
        from job_search_helper import runner
        from job_search_helper.company_events import CompanyEventBridge
        from job_search_helper.repository import SCHEMAS
        from job_search_helper.sqlite_repository import SQLiteRepository

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        database = root / 'state' / 'state.db'
        repo = SQLiteRepository(root / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(repo.close)
        company = {'Company ID': 'COMP-1', 'Company': 'Fixture', 'Company Status': 'Active',
                   'ATS / Source': 'Greenhouse', 'Official Careers URL': 'https://jobs.example.test/fixture'}
        for tab in SCHEMAS:
            repo.import_rows(tab, [(2, company)] if tab == 'Companies' else [])

        class FinalIntake:
            totals = {}
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                if not self.closed:
                    repo.mutate_company_with_event({
                        'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                        'values': {'ATS / Source': 'Lever'},
                    })
                    self.closed = True

        with (
            patch.dict('os.environ', {'JOB_STORAGE_BACKEND': 'sqlite'}),
            patch.object(runner, '_load_environment'),
            patch.object(runner, 'load_title_blacklist'),
            patch.object(runner, 'load_title_review_list'),
            patch.object(runner, 'state_path', return_value=database),
            patch.object(runner, 'get_repository', return_value=repo),
            patch.object(runner, '_refresh_review_queue'),
            patch.object(runner, '_run_scan_with_retries', return_value={'run_counts': {}}),
            patch('job_search_helper.run_sync.run_scoped_sync', return_value=FinalIntake()),
        ):
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False), 0)

        state = State(database, readonly=True)
        self.addCleanup(state.close)
        cycle, = state.cycles()
        self.assertEqual(cycle['status'], 'In Progress')
        self.assertEqual(cycle['companies']['COMP-1']['stage'], 'queued')
        self.assertFalse((database.parent / 'next-scan.json').exists())
        bridge = CompanyEventBridge(repo, database.parent)
        event, = repo.pending_company_events(bridge.consumer)
        self.assertEqual(event['company_id'], 'COMP-1')

    def test_local_status_reports_waiting_request_without_mutation(self):
        from job_search_helper import runner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'state.db'
            state = State(database)
            self.addCleanup(state.close)
            repo = MemoryRepository({'Companies': [
                {'Company ID': 'C-0', 'Company': 'First', 'Company Status': 'Active'},
                {'Company ID': 'C-1', 'Company': 'Second', 'Company Status': 'Active'},
            ]})
            active = Engine(repo, state).start_cycle(company_ids=['C-0'])
            request = {
                'mode': 'company-only', 'request_id': 'waiting-request',
                'company_ids': ['C-1'], 'source_revision': 'revision-1',
                'enqueued_at': '2026-11-18T00:00:00Z', 'start_last': [],
                'company_event': {'schema': 'company-event-scan-request-v1',
                    'event_id': 'event-1', 'company_id': 'C-1', 'revision': 1,
                    'source_revision': 'revision-1'},
            }
            path = root / 'next-scan.json'
            path.write_text(json.dumps(request))
            before = state.cycle(active)

            with patch.object(runner, 'state_path', return_value=database), \
                    patch.object(runner, 'get_repository') as get_repository:
                self.assertEqual(runner.main(['company-queue-status', '--local-only']), 0)

            get_repository.assert_not_called()
            self.assertEqual(state.cycle(active), before)
            self.assertEqual(json.loads(path.read_text()), request)
            status = runner.company_only_queue_status(
                Engine(repo, state), state, database,
                observed_at=datetime(2026, 11, 18, 0, 1, tzinfo=timezone.utc),
            )
            self.assertEqual(status['state'], 'WAITING_SAFE_BOUNDARY')
            self.assertEqual(status['queue_age_seconds'], 60)
            self.assertEqual(status['blocking_cycle_ids'], [active])
            self.assertIn('do not delete locks', status['recovery'])


class RunnerCycleSelectionTests(unittest.TestCase):
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

class ExactSyncContainmentTests(unittest.TestCase):
    RUNTIME = {
        'state': 'NO_RELEASE',
        'source_manifest_sha256': '1' * 64,
        'config_sha256': '2' * 64,
        'dependency_manifest_sha256': '3' * 64,
    }

    def test_cli_named_exact_sync_never_enters_normal_lifecycle(self):
        """The named command dispatches before every global lifecycle hook."""
        from job_search_helper import runner

        forbidden = (
            'get_repository', '_review_queue_lifecycle', '_run_scan_with_retries',
            '_save_performance', '_refresh_review_queue', 'selected_sync_cycles',
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / 'state.db'
        with (
            patch.object(runner, '_run_named_exact_cycle_sync', return_value=0) as exact,
            patch.object(runner, 'state_path', return_value=database),
            patch.object(runner, '_scraper_admission', return_value=nullcontext(self.RUNTIME)),
            patch.multiple(runner, **{
                name: MagicMock(side_effect=AssertionError(name + ' is global'))
                for name in forbidden
            }),
            patch('job_search_helper.run_sync.run_scoped_sync',
                  side_effect=AssertionError('global synchronizer')),
            patch('job_search_helper.closed_jobs.stage_closed_pending',
                  side_effect=AssertionError('global cleanup')),
            patch.object(Engine, 'sync_manual_opportunities',
                         side_effect=AssertionError('manual opportunity sync')),
            patch('job_search_helper.scrape_outcome_producer.record_cycle_outcomes',
                  side_effect=AssertionError('outcome delivery')),
        ):
            self.assertEqual(runner.scrape_main([
                'sync', '--cycle-id', 'CYC-EXACT', '--company-id', 'COMP-EXACT',
            ]), 0)
        exact.assert_called_once_with(
            sync_cycle_id='CYC-EXACT', sync_company_ids=['COMP-EXACT'],
            sheet_request_interval=1.1, database=database, runtime_binding=self.RUNTIME,
        )

    def test_named_exact_sync_validates_request_interval_before_dispatch(self):
        from job_search_helper import runner

        with patch.object(runner, '_run_named_exact_cycle_sync') as exact:
            with self.assertRaisesRegex(ValueError, 'request interval'):
                runner.run_start(
                    sync_only=True, sync_cycle_id='CYC-EXACT',
                    sync_company_ids=['COMP-EXACT'],
                    sheet_request_interval=0.49,
                )
        exact.assert_not_called()

    def test_named_exact_local_validation_refuses_before_remote_factory(self):
        """Missing selected durable state cannot even construct a remote client."""
        from job_search_helper import runner

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'state.db'
            database.touch()
            local = MagicMock()
            local.get_meta.return_value = 'full'
            def invoke_factory(_database, factory, _cycle, _companies, **_kwargs):
                with factory():
                    self.fail('missing cycle must fail before yielding dependencies')

            with (
                patch.object(runner, '_load_environment'),
                patch.object(runner, 'state_path', return_value=database),
                patch.object(runner.InventoryInbox, 'destination_id', return_value='fixture'),
                patch('job_search_helper.sqlite_repository.SQLiteRepository', return_value=local),
                patch.object(runner, '_readonly_named_exact_preflight',
                             side_effect=ValueError('missing, finished, or superseded')),
                patch('job_search_helper.sheet_profile.profile_schemas', return_value={}),
                patch('job_search_helper.cli.job_database_path', return_value=database),
                patch('job_search_helper.cli.get_remote_repository') as remote_factory,
                patch('job_search_helper.exact_cycle_recovery.recover_exact_cycle_with_factory',
                      side_effect=invoke_factory),
            ):
                with self.assertRaisesRegex(ValueError, 'missing, finished, or superseded'):
                    runner._run_named_exact_cycle_sync(
                        sync_cycle_id='CYC-EXACT', sync_company_ids=['COMP-EXACT'],
                        sheet_request_interval=1.1,
                    )
            remote_factory.assert_not_called()
            local.close.assert_not_called()

    def test_named_exact_preflight_is_readonly_for_selected_durable_records(self):
        from job_search_helper import runner
        from job_search_helper.inbox import InventoryInbox
        import sqlite3

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'state.db'
            inbox_path = root / 'inventories.sqlite3'
            state = State(database)
            inbox = InventoryInbox(inbox_path, 'fixture')
            try:
                state.save_cycle({
                    'id': 'CYC-EXACT', 'status': 'In Progress',
                    'companies': {'COMP-EXACT': {'stage': 'inventory'}},
                    'runtime_binding': self.RUNTIME,
                })
                inbox.save('CYC-EXACT', 'COMP-EXACT', {'jobs': []})
                inbox.save_plan('CYC-EXACT', 'COMP-EXACT', {'operations': []})
            finally:
                inbox.close()
                state.close()
            with sqlite3.connect(inbox_path) as connection:
                before = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            runner._readonly_named_exact_preflight(
                database, inbox_path, 'CYC-EXACT', ['COMP-EXACT'], runtime_binding=self.RUNTIME)
            with sqlite3.connect(inbox_path) as connection:
                after = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                ).fetchall()
            self.assertEqual(after, before)

    def test_supersession_between_local_open_and_remote_factory_never_authenticates(self):
        """The final exact gate is after writable setup but before Google."""
        from job_search_helper import runner

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / 'state.db'
            database.touch()
            local = MagicMock()
            local.get_meta.return_value = 'full'
            state = MagicMock()
            inbox = MagicMock()

            class FakeInbox:
                @staticmethod
                def destination_id(_path):
                    return 'fixture'

                def __new__(cls, *_args, **_kwargs):
                    return inbox

            def invoke_factory(_database, factory, _cycle, _companies, **_kwargs):
                with factory():
                    self.fail('supersession must reject before yielding remote')

            with (
                patch.object(runner, '_load_environment'),
                patch.object(runner, 'state_path', return_value=database),
                patch.object(runner, 'InventoryInbox', FakeInbox),
                patch.object(runner, 'State', return_value=state),
                patch('job_search_helper.sqlite_repository.SQLiteRepository', return_value=local),
                patch('job_search_helper.sheet_profile.profile_schemas', return_value={}),
                patch('job_search_helper.cli.job_database_path', return_value=database),
                patch('job_search_helper.cli.get_remote_repository') as remote_factory,
                patch('job_search_helper.integration_release.assert_release_settled'),
                patch.object(runner, '_readonly_named_exact_preflight',
                             side_effect=[None, ValueError('cycle superseded')]),
                patch('job_search_helper.exact_cycle_recovery.recover_exact_cycle_with_factory',
                      side_effect=invoke_factory),
            ):
                with self.assertRaisesRegex(ValueError, 'cycle superseded'):
                    runner._run_named_exact_cycle_sync(
                        sync_cycle_id='CYC-EXACT', sync_company_ids=['COMP-EXACT'],
                        sheet_request_interval=1.1,
                    )
            remote_factory.assert_not_called()
            local.close.assert_called_once_with()
            inbox.close.assert_called_once_with()
            state.close.assert_called_once_with()

    def test_named_sync_holds_after_local_validation_before_repository_access(self):
        """A selected cycle may not start the global Sheets synchronizer."""
        from job_search_helper import runner
        from job_search_helper.inbox import InventoryInbox

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / 'state.db'
            state = State(database)
            try:
                state.save_cycle({
                    'id': 'CYC-EXACT', 'started_at': '2026-11-19T00:00:00+00:00',
                    'status': 'In Progress', 'all': False, 'companies': {},
                })
            finally:
                state.close()
            inbox = InventoryInbox(root / 'inventories.sqlite3', 'fixture')
            try:
                inbox.save('CYC-EXACT', 'COMP-EXACT', {'jobs': [], 'marker': 'held'})
            finally:
                inbox.close()
            output = StringIO()
            with patch.object(runner, '_load_environment'), \
                 patch.object(runner, 'state_path', return_value=database), \
                 patch.object(runner, 'load_title_blacklist'), \
                 patch.object(runner, 'load_title_review_list'), \
                 patch.object(runner, 'get_repository') as get_repository, \
                 redirect_stdout(output):
                self.assertEqual(runner.run_start(
                    sync_only=True, sync_cycle_id='CYC-EXACT', browser_fallback=False,
                ), 0)
            get_repository.assert_not_called()
            self.assertIn('global repository and Sheets sync are disabled', output.getvalue())
            self.assertIn('No inventory, workbook, review, or coordinator changes were applied.', output.getvalue())


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

    def test_runtime_binding_is_durable_and_changed_worker_is_held_before_fetch(self):
        binding = {
            'state': 'COMPLETE', 'release_id': 'REL-reviewed',
            'source_manifest_sha256': '1' * 64,
            'config_sha256': '2' * 64,
            'dependency_manifest_sha256': '3' * 64,
        }
        engine = Engine(self.repo, self.state, inbox=self.inbox, fetcher=self.engine.fetcher,
                        error_log_path=self.root / 'errors.jsonl', runtime_binding=binding)
        cycle_id = engine.start_cycle()
        self.assertEqual(self.state.cycle(cycle_id)['runtime_binding'], binding)
        row = next(row for row in self.repo.read('Scan Cycles') if row['Cycle ID'] == cycle_id)
        self.assertEqual(json.loads(row['Notes'])['runtime_binding'], binding)
        self.assertEqual(engine.assert_runtime_binding(cycle_id), binding)

        changed = dict(binding, source_manifest_sha256='4' * 64)
        changed_engine = Engine(self.repo, self.state, inbox=self.inbox,
                                fetcher=self.engine.fetcher,
                                error_log_path=self.root / 'errors.jsonl',
                                runtime_binding=changed)
        with self.assertRaisesRegex(ValueError, 'runtime differs'):
            changed_engine.assert_runtime_binding(cycle_id)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.state.cycle(cycle_id)['runtime_binding'], binding)

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
            self.assertEqual(runner.scrape_main(['start', '--fetch-workers', '15']), 0)
            self.assertFalse(run.call_args.kwargs['resume'])
            self.assertEqual(runner.scrape_main(['start', '--resume', '--fetch-workers', '15']), 0)
            self.assertTrue(run.call_args.kwargs['resume'])
            run.reset_mock()
            with redirect_stderr(StringIO()):
                self.assertEqual(runner.scrape_main(['sync', '--resume']), 2)
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
            self.assertRegex(self.output.getvalue(), r'Companies skipped: \nTotal run time: [^\n]+\n$')
            self.output.truncate(0); self.output.seek(0)
            self.assertEqual(runner.run_start(fetch_workers=1, browser_fallback=False), 0)
        self.assertEqual(self.calls, ['C-0', 'C-1', 'C-1', 'C-0', 'C-1', 'C-1'])
        self.assertIn('New jobs downloaded (new Job History rows): 0', self.output.getvalue())
        self.assertRegex(self.output.getvalue(), r'Companies skipped: \nTotal run time: [^\n]+\n$')

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
