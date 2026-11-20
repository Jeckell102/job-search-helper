"""Exercise in-flight Sheet reads and guarded local retries without network."""
from contextlib import redirect_stdout
import copy
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from job_search_helper.engine import Engine, State, inventory_payload
from job_search_helper.inbox import InventoryInbox
from job_search_helper.local_pipeline import LocalPipeline
from job_search_helper.repository import MemoryRepository, SCHEMAS, RepositoryError, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_PROFILE
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from test_fetch_pool import company, inventory
from test_sqlite_migration import job, operation


class SyncReadFenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.local = SQLiteRepository(Path(directory.name) / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.remote = MemoryRepository({'Job History': [job()]})
        self.remote.spreadsheet_id = 'fixture'
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(self.remote.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
            self.local.set_meta('sheets_profile', COMPACT_PROFILE)
        self.sync = SheetsSynchronizer(self.local, self.remote)

    def review(self):
        self.local.commit([operation(**{'Added to Opportunities?': 'No', 'Review Status': 'Reviewed',
                                       'Decision': 'Reject', 'Review Notes': 'Completed review'})])

    def test_old_pending_response_cannot_undo_review_published_during_read(self):
        self.review()
        read = self.remote.read_columns
        reads = []
        def delayed(tab, headers):
            rows = read(tab, headers)
            if tab == 'Job History':
                reads.append(True)
                if len(reads) == 1:
                    self.sync.publish_batch()
            return rows
        with patch.object(self.remote, 'read_columns', side_effect=delayed):
            self.sync.pull()
        self.assertEqual(len(reads), 2)
        current = self.local.read('Job History')[0]
        self.assertEqual(current['Added to Opportunities?'], 'No')
        self.assertEqual(current['Review Status'], 'Reviewed')
        self.assertEqual(current['Review Notes'], 'Completed review')
        self.assertEqual(self.local.db.execute('select count(*) from manual_choices').fetchone()[0], 0)
        # A subsequent actual human reset remains authoritative.
        self.remote.commit([operation(**{'Added to Opportunities?': 'Pending'})])
        self.sync.pull()
        self.assertEqual(self.local.read('Job History')[0]['Added to Opportunities?'], 'Pending')
        self.assertEqual(self.local.read('Job History')[0]['Review Status'], 'Needs Review')

    def test_unpublished_review_during_read_is_retained_without_extra_request(self):
        read = self.remote.read_columns
        def delayed(tab, headers):
            rows = read(tab, headers)
            if tab == 'Job History':
                self.review()
            return rows
        with patch.object(self.remote, 'read_columns', side_effect=delayed) as reads:
            self.sync.pull()
        self.assertEqual(sum(c.args[0] == 'Job History' for c in reads.call_args_list), 1)
        self.assertEqual(self.local.read('Job History')[0]['Added to Opportunities?'], 'No')

    def test_continuously_changing_baseline_defers_after_two_reads(self):
        read = self.remote.read_columns
        calls = []
        def delayed(tab, headers):
            rows = read(tab, headers)
            if tab == 'Job History':
                calls.append(True)
                self.local.commit([operation(**{'Review Notes': str(len(calls))})])
                self.sync.publish_batch()
            return rows
        with patch.object(self.remote, 'read_columns', side_effect=delayed):
            with self.assertRaisesRegex(RepositoryError, 'both Sheet reads'):
                self.sync.pull()
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.local.read('Job History')[0]['Review Notes'], '2')

    def test_scoped_fence_contains_only_selected_job_keys(self):
        self.assertEqual(len(self.sync.baseline_tokens('Job History', keys=['job-1'])), 1)
        self.assertEqual(self.sync.baseline_tokens('Job History', keys=['absent']), {})
        self.assertEqual(self.sync.baseline_tokens('Job History', keys=[]), {})


class LocalReplanningTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.local = SQLiteRepository(self.root / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        initial = MemoryRepository({'Companies': [company(0), company(1)]})
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(initial.read(tab), 2))
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
        self.state = State(self.root / 'state.db')
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(self.root / 'inventories.sqlite3', 'fixture')
        self.addCleanup(self.inbox.close)
        self.engine = Engine(self.local, self.state, inbox=self.inbox,
                             error_log_path=self.root / 'errors.jsonl',
                             fetcher=lambda *args: self.fail('Retry must use saved inventory'))
        self.inventories = {}
        for index in range(2):
            comp = company(index)
            result = inventory(comp['Company ID'], comp['Company'], comp['Official Careers URL'])
            self.inventories[comp['Company ID']] = result
            self.engine._stage_posting({'id': 'BASELINE'}, comp, result.jobs[0])
        self.cycle = self.engine.start_cycle()
        for cid, result in self.inventories.items():
            comp = company(int(cid[-1]))
            self.inbox.save(self.cycle, cid, inventory_payload(result, comp))
        self.pipeline = LocalPipeline(self.engine, self.cycle)
        self.pipeline.dashboard = MagicMock()
        self.pipeline.retry_blocked = True

    def stage(self):
        for cid in ('C-0', 'C-1'):
            self.pipeline.stage(cid)

    def update(self, **values):
        row = next(r for r in self.local.read('Job History') if r['Company'] == 'Company 0')
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': row['Job Key']}, 'values': values}])

    def test_current_review_is_preserved_and_other_company_finishes(self):
        self.stage()
        row = next(r for r in self.local.read('Job History') if r['Company'] == 'Company 0')
        self.update(**{'Added to Opportunities?': 'No', 'Review Status': 'Reviewed',
                       'Description Hash': row['Source Hash'], 'Decision': 'Reject',
                       'Review Notes': 'Final reviewer decision'})
        with patch.object(self.local, 'read', wraps=self.local.read) as reads:
            self.pipeline.flush()
        # The reconciled safety path deliberately rereads the guarded records
        # before replacing an unacknowledged plan. This stable reread is what
        # preserves a manual decision made after initial planning.
        self.assertIn('Job History', [call.args[0] for call in reads.call_args_list])
        current = next(r for r in self.local.read('Job History') if r['Company'] == 'Company 0')
        self.assertEqual(current['Added to Opportunities?'], 'No')
        self.assertEqual(current['Review Status'], 'Reviewed')
        self.assertEqual(current['Decision'], 'Reject')
        self.assertEqual(current['Review Notes'], 'Final reviewer decision')
        self.assertEqual(self.engine.performance['review_conflict_replans'], 1)
        self.assertEqual([x['stage'] for x in self.state.cycle(self.cycle)['companies'].values()], ['complete', 'complete'])
        self.assertEqual(self.inbox.pending(self.cycle, include_blocked=True), [])

    def test_changed_notes_with_same_selection_also_require_replanning(self):
        self.stage()
        self.update(**{'Review Notes': 'Latest human note'})
        self.pipeline.flush()
        self.assertEqual(self.engine.performance['review_conflict_replans'], 1)
        current = next(r for r in self.local.read('Job History') if r['Company'] == 'Company 0')
        self.assertEqual(current['Review Notes'], 'Latest human note')

    def test_repeated_conflict_is_bounded_and_retains_inventory(self):
        self.stage()
        commit = self.local.commit
        changes = []
        key = next(r['Job Key'] for r in self.local.read('Job History') if r['Company'] == 'Company 0')
        def racing(operations):
            if any(op['tab'] == 'Job History' and op['identity'].get('Job Key') == key for op in operations):
                changes.append(True)
                commit([{'tab': 'Job History', 'identity': {'Job Key': key},
                         'values': {'Review Notes': 'Concurrent edit ' + str(len(changes))}}])
            return commit(operations)
        with patch.object(self.local, 'commit', side_effect=racing):
            self.pipeline.flush()
        self.assertEqual(len(changes), 4)  # Combined rejection, isolated rejection, two replans.
        self.assertEqual(self.pipeline.replan_attempts['C-0'], 2)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        self.assertEqual(self.state.cycle(self.cycle)['companies']['C-1']['stage'], 'complete')

    def test_uncertain_write_keeps_exact_plan_without_replanning(self):
        self.pipeline.stage('C-0')
        original_plan = copy.deepcopy(self.inbox.plan(self.cycle, 'C-0'))
        commit = self.local.commit
        def lost(operations):
            if any(op['tab'] == 'Job History' for op in operations):
                raise UncertainWriteError('Response lost')
            return commit(operations)
        with patch.object(self.local, 'commit', side_effect=lost):
            self.pipeline.flush()
        self.assertEqual(self.pipeline.replan_attempts, {})
        self.assertEqual(self.inbox.plan(self.cycle, 'C-0'), original_plan)
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])

    def test_review_change_after_acknowledged_batch_retains_exact_plan_and_receipt(self):
        comp = company(0)
        original = self.inventories['C-0'].jobs[0]
        for number in ('2', '3'):
            posting = dict(original, posting_id=number, url=comp['Official Careers URL'] + '/jobs/' + number)
            self.engine._stage_posting({'id': 'BASELINE'}, comp, posting)
        # Reload the planning cache after the additional baseline records exist.
        self.pipeline = LocalPipeline(self.engine, self.cycle)
        self.pipeline.dashboard = MagicMock()
        self.pipeline.retry_blocked = True
        self.engine.batch_size = 1
        self.pipeline.stage('C-0')
        commit = self.local.commit
        changed = []
        third = next(row for row in self.local.read('Job History') if row['Requisition ID'] == '3')
        def intervene(operations):
            result = commit(operations)
            if not changed and any(op['tab'] == 'Job History'
                                   and op.get('values', {}).get('Consecutive Missing Scans') == 1
                                   for op in operations):
                changed.append(True)
                commit([{'tab': 'Job History', 'identity': {'Job Key': third['Job Key']},
                         'values': {'Review Notes': 'Latest note during partial commit'}}])
            return result
        with patch.object(self.local, 'commit', side_effect=intervene):
            self.pipeline.flush()
        self.assertNotIn('review_conflict_replans', self.engine.performance)
        history = self.local.read('Job History')
        self.assertEqual(len(history), 4)  # Three at Company 0, one at Company 1.
        self.assertEqual(len({r['Job Key'] for r in history}), 4)
        missing = [r for r in history if r['Company'] == 'Company 0' and r['Requisition ID'] in {'2', '3'}]
        self.assertIn(1, [r['Consecutive Missing Scans'] for r in missing])
        self.assertIn('Latest note during partial commit', next(r['Review Notes'] for r in missing if r['Requisition ID'] == '3'))
        frozen, cursor = self.inbox.plan(self.cycle, 'C-0')
        self.assertGreater(cursor, 0)
        self.assertLess(cursor, len(frozen['operations']))
        self.assertTrue(self.inbox.get(self.cycle, 'C-0')[1])
        details = self.pipeline._receipt_for_plan('C-0', frozen)
        self.assertEqual(self.inbox.receipt(details)['state'], 'SYNC_PENDING')
        company_row = next(row for row in self.local.read('Companies') if row['Company ID'] == 'C-0')
        self.assertIn('partial publication', company_row['Blocked Reason'])
