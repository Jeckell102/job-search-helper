"""Publication throughput with fresh identity, user-edit and replay guards."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from job_search_helper.repository import GoogleRepository, RepositoryError, UncertainWriteError
from job_search_helper.batching import PlanningRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets
import test_sheet_read_optimization as read_tests
from test_sqlite_migration import job


operation = read_tests.operation


class CompactIdentityReadTests(unittest.TestCase):
    make = read_tests.SheetReadOptimizationTests.make
    bounds = read_tests.SheetReadOptimizationTests.bounds
    def test_planner_retains_fields_omitted_from_targeted_read(self):
        service, repo = self.make(2)
        planner = PlanningRepository(repo)
        before = dict(planner.rows['Job History'][1])
        ops = [operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'today'})]
        planner.commit(ops)
        repo.commit(ops)
        planner.accept_commit()
        self.assertEqual(planner.rows['Job History'][1], {**before, 'Last Checked': 'today'})

    def test_existing_update_detailed_read_omits_unrelated_columns(self):
        service, repo = self.make(100)
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'today'})])
        detailed = [call for call in service.get_calls if call.get('includeGridData')
                    and not call.get('values_api')]
        allowed = {'Job Key', 'Added to Opportunities?', 'Review Status', 'Last Checked'}
        for call in detailed:
            for area in call['ranges']:
                tab, r0, r1, c0, c1 = self.bounds(service, area)
                if r0 == 0:
                    continue  # Headers are validated on every detailed read.
                self.assertLessEqual(r1 - r0, 1)
                self.assertTrue(set(service.schemas[tab][c0:c1]) <= allowed)

    def test_duplicate_added_after_target_read_still_prevents_write(self):
        service, repo = self.make(40)
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'warm'})])
        before = len(service.batches)
        def duplicate(kwargs):
            if service.get_calls[-1].get('values_api'):
                service.set_cell('Job History', 30, 'Job Key', 'j-1')
        service.before_read = duplicate
        with self.assertRaisesRegex(RepositoryError, 'multiple rows'):
            repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'next'})])
        self.assertEqual(len(service.batches), before)

    def test_omitted_identity_range_refuses_write(self):
        service, repo = self.make(2)
        original = repo._execute
        def omit(request, action):
            result = original(request, action)
            if 'valueRanges' in result:
                result['valueRanges'].pop()
            return result
        with patch.object(repo, '_execute', side_effect=omit), self.assertRaisesRegex(RepositoryError, 'omitted identity'):
            repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'next'})])
        self.assertEqual(service.batches, [])

    def test_manual_choice_during_final_key_check_is_preserved(self):
        service, repo = self.make(40)
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'warm'})])
        before = len(service.batches)
        def change(kwargs):
            if service.get_calls[-1].get('values_api'):
                service.set_cell('Job History', 2, 'Added to Opportunities?', 'No')
        service.before_read = change
        with self.assertRaisesRegex(RepositoryError, 'changed since planning'):
            repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'next'},
                                   expected={'Added to Opportunities?': ''})])
        self.assertEqual(len(service.batches), before)


class AdaptivePublicationTests(unittest.TestCase):
    def make(self, count):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        local = SQLiteRepository(Path(temporary.name) / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(local.close)
        rows = [job(f'job-{i}') for i in range(count)]
        local.import_rows('Job History', enumerate(rows, 2))
        with local.transaction():
            local.set_meta('sheets_profile', COMPACT_PROFILE)
        service = RangeSheets({'Job History': rows}, schemas=COMPACT_SCHEMAS)
        service.sheet('Job History')['properties']['gridProperties']['rowCount'] = max(1000, count + 10)
        remote = GoogleRepository(service, 'fixture', schemas=COMPACT_SCHEMAS, min_request_interval=0)
        sync = SheetsSynchronizer(local, remote)
        local.commit([operation('Job History', {'Job Key': row['Job Key']},
                                {'Last Checked': 'today'}) for row in rows])
        return local, service, remote, sync

    def test_backlog_grows_batch_capacity_and_drains_without_duplicates(self):
        local, service, remote, sync = self.make(3600)
        counts = []
        while local.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0]:
            counts.append(sync.publish_batch()['published_rows'])
        self.assertEqual(counts, [500, 1000, 2000, 100])
        self.assertEqual(len(service.batches), 4)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0], 0)
        self.assertEqual(len(remote.read('Job History')), 3600)

    def test_encoded_payload_cap_reduces_batch_before_any_write(self):
        local, service, remote, sync = self.make(100)
        with patch('job_search_helper.repository.MAX_BATCH_UPDATE_BYTES', 5000):
            result = sync.publish_batch()
        self.assertGreater(result['published_rows'], 0)
        self.assertLess(result['published_rows'], 100)
        self.assertEqual(len(service.batches), 1)
        self.assertLessEqual(len(json.dumps(service.batches[0]['body'], ensure_ascii=True).encode()), 5000)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0], 0)
        while local.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0]:
            sync.publish_batch()
        self.assertEqual(len(remote.read('Job History')), 100)

    def test_ambiguous_write_is_not_retried_as_a_smaller_batch(self):
        local, service, remote, sync = self.make(10)
        service.lose_response = True
        with self.assertRaises(UncertainWriteError):
            sync.publish_batch()
        self.assertEqual(len(service.batches), 1)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0], 10)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM delivery_attempts').fetchone()[0], 10)
        self.assertEqual(sync.publish_batch()['published_rows'], 10)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0], 0)

    def test_explicit_review_limit_is_preserved(self):
        local, service, remote, sync = self.make(10)
        self.assertEqual(sync.publish_batch(limit=3)['published_rows'], 3)
        self.assertEqual(sync._publish_limit, 500)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0], 7)

    def test_slow_success_reduces_next_batch_without_replaying_work(self):
        local, service, remote, sync = self.make(501)
        clock = iter((0, 50))
        with patch('job_search_helper.sheets_sync.time', SimpleNamespace(monotonic=lambda: next(clock))):
            self.assertEqual(sync.publish_batch()['published_rows'], 500)
        self.assertEqual(sync._publish_limit, 250)
        self.assertEqual(len(service.batches), 1)
        self.assertEqual(local.db.execute('SELECT COUNT(*) FROM dirty').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
