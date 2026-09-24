import unittest
from unittest.mock import patch

from job_search_helper.batching import PlanningRepository
from job_search_helper.repository import GoogleRepository, RepositoryError
from sheets_fixture import RangeSheets


def op(key, **values):
    return {'tab': 'Job History', 'identity': {'Job Key': key}, 'values': values, 'append_if_missing': True}


class TargetedWriterTests(unittest.TestCase):
    def make(self, count=20):
        service = RangeSheets({'Job History': [{'Company': 'Acme', 'Job Key': str(i),
            'Job Description': 'long description ' * 100} for i in range(count)]})
        return service, GoogleRepository(service, 'fixture', min_request_interval=0)

    def test_bulk_insert_and_replay_use_single_atomic_write(self):
        service, repo = self.make()
        batch = [op('new-' + str(i), Company='Acme', **{'Job Title': 'Engineer'}) for i in range(200)]
        result = repo.commit(batch)
        self.assertEqual(result['inserted'], 200)
        self.assertLessEqual(result['requests'], 3)
        before = len(service.batches)
        repo.commit(batch)
        self.assertEqual(len(service.batches), before)
        self.assertEqual(len(repo.read('Job History')), 220)

    def test_warm_commit_reads_only_identities_tail_and_affected_rows(self):
        service, repo = self.make(100)
        repo.commit([op('0', **{'Review Notes': 'one'})])
        service.get_calls.clear()
        result = repo.commit([op('1', **{'Review Notes': 'two'})])
        ranges = [r for call in service.get_calls for r in call.get('ranges', [])]
        self.assertIn("'Job History'!K2:K", ranges)
        self.assertIn("'Job History'!A3:AF3", ranges)
        self.assertNotIn("'Job History'!A1:AF1000", ranges)
        self.assertEqual(result['timings']['read_requests'], 2)
        self.assertEqual(result['timings']['write_requests'], 1)

    def test_tail_preserves_manual_orphan_rows_formulas_and_validation(self):
        service, repo = self.make(1)
        repo.commit([op('0', **{'Review Notes': 'warm'})])
        service.set_cell('Job History', 3, 'Review Notes', 'manual orphan')
        service.set_cell('Job History', 4, 'Job Title', cell={'userEnteredValue': {'formulaValue': '=1'},
                                                           'effectiveValue': {'numberValue': 1}})
        service.set_cell('Job History', 5, 'Job Status', cell={'dataValidation': {'strict': True,
            'condition': {'type': 'ONE_OF_LIST', 'values': [{'userEnteredValue': 'Open'}]}}})
        with self.assertRaises(RepositoryError):
            repo.commit([op('new', **{'Job Status': 'bad'})])
        repo.commit([op('new', **{'Job Status': 'Open'})])
        rows = repo.read('Job History')
        self.assertEqual(rows[-1]['Job Key'], 'new')
        self.assertTrue(any(r['Review Notes'] == 'manual orphan' for r in rows))
        self.assertEqual(service.sheet('Job History')['data'][0]['rowData'][4]['values'][1]['userEnteredValue'], {'formulaValue': '=1'})

    def test_formula_and_manual_review_change_protected_after_cache(self):
        service, repo = self.make(1)
        planner = PlanningRepository(repo)
        repo.commit([op('0', **{'Review Notes': 'warm'})])
        service.set_cell('Job History', 1, 'Review Notes', cell={'userEnteredValue': {'formulaValue': '="mine"'},
                                                               'effectiveValue': {'stringValue': 'mine'}})
        with self.assertRaisesRegex(RepositoryError, 'formula'):
            repo.commit([op('0', **{'Review Notes': 'overwrite'})])
        service.set_cell('Job History', 1, 'Added to Opportunities?', 'No')
        planned = op('0', **{'Added to Opportunities?': 'Pending'})
        planned['expected'] = {'Added to Opportunities?': ''}
        with self.assertRaisesRegex(RepositoryError, 'changed since planning'):
            repo.commit([planned])
        self.assertEqual(planner.rows['Job History'][0]['Added to Opportunities?'], '')

    def test_ambiguous_write_reopens_and_does_not_duplicate(self):
        service, repo = self.make(0)
        service.lose_response = True
        with self.assertRaises(RepositoryError):
            repo.commit([op('new', Company='Acme')])
        restarted = GoogleRepository(service, 'fixture', min_request_interval=0)
        result = restarted.commit([op('new', Company='Acme')])
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(len(restarted.read('Job History')), 1)

    def test_row_move_and_duplicate_after_cache_are_revalidated(self):
        service, repo = self.make(3)
        repo.commit([op('0', **{'Review Notes': 'warm'})])
        rows = service.sheet('Job History')['data'][0]['rowData']
        rows[1], rows[3] = rows[3], rows[1]
        repo.commit([op('0', **{'Review Notes': 'moved'})])
        service.set_cell('Job History', 2, 'Job Key', '0')
        with self.assertRaisesRegex(RepositoryError, 'multiple rows'):
            repo.commit([op('0', **{'Review Notes': 'ambiguous'})])

    def test_sparse_updates_never_clear_gaps(self):
        service, repo = self.make(1)
        service.set_cell('Job History', 1, 'Job Title', 'My title')
        repo.commit([op('0', Company='Different', **{'Added to Opportunities?': 'No'})])
        self.assertEqual(repo.read('Job History')[0]['Job Title'], 'My title')

    def test_new_url_alias_after_cache_cannot_create_duplicate(self):
        service, repo = self.make(1)
        repo.commit([op('0', Company='Acme', **{'Official Job URL': 'https://example.test/job'})])
        with self.assertRaisesRegex(RepositoryError, 'another identity'):
            repo.commit([op('new-key', Company='Acme', **{'Official Job URL': 'https://example.test/job?utm_source=x'})])
        self.assertEqual(len(repo.read('Job History')), 1)

    def test_throttle_and_retry_policy_unchanged(self):
        service, repo = self.make(0)
        repo.min_request_interval = 1.1
        class Request:
            def __init__(self):
                self.calls = []
            def execute(self, **kwargs):
                self.calls.append(kwargs)
                return {}
        request = Request()
        with patch('job_search_helper.repository.time.monotonic', return_value=10), patch('job_search_helper.repository.time.sleep') as sleep:
            repo._execute(request, 'read')
            repo._execute(request, 'write')
        self.assertEqual(request.calls, [{'num_retries': 5}, {}])
        self.assertAlmostEqual(sleep.call_args.args[0], 1.1)


if __name__ == '__main__':
    unittest.main()
