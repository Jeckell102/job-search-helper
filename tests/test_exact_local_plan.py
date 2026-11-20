"""Offline proof for exact v2 local durability and isolation."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest
from job_search_helper.exact_local_plan import (
    VERIFIED, apply_exact_local_chunk, commit_exact_local_plan,
    exact_local_plan, verify_exact_local_chunk,
)
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.inbox import InventoryInbox


def company(cid='COMP-1'):
    return {'Company ID': cid, 'Company': 'Fixture ' + cid,
            'Company Status': 'Active',
            'Official Careers URL': f'https://jobs.example.test/{cid}',
            'Scan State': 'Queued', 'Active Cycle ID': '',
            'Last Checked': '', 'Next Action': ''}


def sealed_plan(*, operations=None):
    local = operations or [{
        'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
        'values': {'Scan State': 'Complete', 'Active Cycle ID': 'CYC-1',
                   'Last Checked': '2026-11-19', 'Next Action': 'Inventory saved'},
        'expected': {'Scan State': 'Queued'},
    }]
    remote = [{
        'tab': op['tab'], 'identity': copy.deepcopy(op['identity']),
        'values': {key: value for key, value in op.get('values', {}).items()
                   if key in {'Last Checked', 'Next Action', 'Job Title', 'Salary / Range'}},
        'append_if_missing': bool(op.get('append_if_missing')),
        'on_insert': {}, 'expected': {}, 'append_notes': {},
    } for op in local]
    plan = {
        'exact_plan_version': 2, 'cycle_id': 'CYC-1', 'company_id': 'COMP-1',
        'inventory_payload_digest': _digest({'inventory': 'fixture'}),
        'publication_profile': 'compact-v1',
        'publication_schema': {'Companies': ['Company ID', 'Last Checked', 'Next Action']},
        'local_operations': local, 'remote_projection': remote,
        'final': {'stage': 'complete'}, 'final_projection': {'stage': 'complete'},
    }
    plan['publication_schema_digest'] = _digest(plan['publication_schema'])
    plan['local_operations_digest'] = _digest(local)
    plan['local_expected_records'] = record_fingerprints(local)
    plan['local_expected_records_digest'] = _digest(plan['local_expected_records'])
    plan['remote_projection_digest'] = _digest(remote)
    plan['remote_records'] = record_fingerprints(remote)
    plan['remote_records_digest'] = _digest(plan['remote_records'])
    plan['local_finalization_digest'] = _digest({'operations': local, 'final': plan['final']})
    plan['final_projection_digest'] = _digest(plan['final_projection'])
    plan['plan_digest'] = _exact_plan_digest(plan)
    return plan


class ExactLocalPlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'jobs.sqlite3'
        self.repository = SQLiteRepository(self.path, 'fixture', initialize=True)
        self.addCleanup(self.repository.close)
        for tab in SCHEMAS:
            rows = [company(), company('COMP-2')] if tab == 'Companies' else []
            self.repository.import_rows(tab, enumerate(rows, 2))
        with self.repository.transaction():
            self.repository.set_meta('ready', 'yes')
            self.repository.set_meta('sheets_profile', 'compact-v1')

    def dirty(self):
        return list(self.repository.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header'))

    def test_mutation_and_applied_journal_are_atomic_and_recover_read_only(self):
        plan = sealed_plan()
        first = commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', plan)
        self.assertEqual(first['state'], VERIFIED)
        self.assertFalse(first['recovered'])
        self.assertEqual(self.repository.matches(
            'Companies', {'Company ID': 'COMP-1'})[0][1]['Scan State'], 'Complete')
        before = copy.deepcopy(self.repository.read('Companies')), self.dirty()
        with patch.object(self.repository, '_commit_in_transaction',
                          side_effect=AssertionError('verified work must not replay')):
            recovered = commit_exact_local_plan(
                self.repository, 'CYC-1', 'COMP-1', plan)
        self.assertTrue(recovered['recovered'])
        self.assertEqual((self.repository.read('Companies'), self.dirty()), before)
        self.assertEqual(exact_local_plan(
            self.repository, 'CYC-1', 'COMP-1')['state'], VERIFIED)

    def test_local_failure_rolls_back_parent_chunk_rows_and_dirty(self):
        plan = sealed_plan(); before = copy.deepcopy(self.repository.read('Companies'))
        with patch.object(self.repository, '_commit_in_transaction',
                          side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError, 'disk failure'):
                apply_exact_local_chunk(self.repository, 'CYC-1', 'COMP-1', plan, 0)
        self.assertEqual(self.repository.read('Companies'), before)
        self.assertEqual(self.dirty(), [])
        self.assertIsNone(exact_local_plan(self.repository, 'CYC-1', 'COMP-1'))

    def test_applied_crash_boundary_is_verified_without_reapply(self):
        plan = sealed_plan()
        applied = apply_exact_local_chunk(
            self.repository, 'CYC-1', 'COMP-1', plan, 0)
        self.assertEqual(applied['state'], 'APPLIED')
        with patch.object(self.repository, '_commit_in_transaction',
                          side_effect=AssertionError('APPLIED must not replay')):
            repeated = apply_exact_local_chunk(
                self.repository, 'CYC-1', 'COMP-1', plan, 0)
            verified = verify_exact_local_chunk(
                self.repository, 'CYC-1', 'COMP-1', plan, 0)
        self.assertTrue(repeated['recovered'])
        self.assertEqual(verified['state'], VERIFIED)

    def test_tampered_plan_and_cross_company_reuse_are_refused(self):
        plan = sealed_plan(); altered = copy.deepcopy(plan)
        altered['local_operations'][0]['values']['Next Action'] = 'tampered'
        with self.assertRaisesRegex(ValueError, 'digest'):
            commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', altered)
        with self.assertRaisesRegex(ValueError, 'Company identity mismatch'):
            commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-2', plan)

    def test_source_guard_change_holds_without_journal_or_overwrite(self):
        row = company(); row.update({'Job Key': 'JOB-1', 'Source Hash': 'source-old'})
        self.repository.import_rows('Job History', [(2, row)])
        local = [{
            'tab': 'Job History', 'identity': {'Job Key': 'JOB-1'},
            'values': {'Source Hash': 'source-new', 'Job Title': 'Role'},
            'expected': {'Source Hash': 'source-old'},
        }]
        plan = sealed_plan(operations=local)
        self.repository.commit([{
            'tab': 'Job History', 'identity': {'Job Key': 'JOB-1'},
            'values': {'Source Hash': 'user-newer'},
        }])
        with self.assertRaises(Exception):
            commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', plan)
        current = self.repository.matches('Job History', {'Job Key': 'JOB-1'})[0][1]
        self.assertEqual(current['Source Hash'], 'user-newer')
        self.assertIsNone(exact_local_plan(self.repository, 'CYC-1', 'COMP-1'))

    def test_salary_estimate_is_preserved_by_guarded_nonmutation(self):
        row = company(); row.update({'Job Key': 'JOB-1', 'Salary / Range': '$120k-$140k'})
        self.repository.import_rows('Job History', [(2, row)])
        local = [{
            'tab': 'Job History', 'identity': {'Job Key': 'JOB-1'},
            'values': {'Job Title': 'Role'},
            'expected': {'Salary / Range': '$120k-$140k'},
        }]
        plan = sealed_plan(operations=local)
        commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', plan)
        current = self.repository.matches('Job History', {'Job Key': 'JOB-1'})[0][1]
        self.assertEqual(current['Salary / Range'], '$120k-$140k')

    def test_job_history_scope_retains_local_guards_not_local_only_fields(self):
        row = company(); row.update({
            'Job Key': 'JOB-1', 'Source Hash': 'source-old',
            'Added to Opportunities?': 'Manual Review',
            'Salary / Range': '$120k-$140k', 'Job Title': 'Old Role',
        })
        self.repository.import_rows('Job History', [(2, row)])
        local = [{
            'tab': 'Job History', 'identity': {'Job Key': 'JOB-1'},
            'values': {'Job Title': 'Role'},
            'expected': {'Source Hash': 'source-old',
                         'Added to Opportunities?': 'Manual Review',
                         'Salary / Range': '$120k-$140k'},
        }]
        plan = sealed_plan(operations=local)
        commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', plan)
        scope = exact_local_plan(
            self.repository, 'CYC-1', 'COMP-1')['row_scope'][0]
        self.assertEqual(scope['fields'], ['Job Title'])
        self.assertEqual(scope['guards'], {
            'Source Hash': 'source-old',
            'Added to Opportunities?': 'Manual Review',
            'Salary / Range': '$120k-$140k',
        })
        self.assertNotIn('Source Hash', scope['fields'])

    def test_verified_scope_has_row_hint_and_revalidates_stable_identity(self):
        plan = sealed_plan()
        commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', plan)
        application = exact_local_plan(self.repository, 'CYC-1', 'COMP-1')
        self.assertEqual(application['row_scope'][0]['row_id'], 1)
        self.assertEqual(application['row_scope'][0]['identity'], {'Company ID': 'COMP-1'})
        self.assertEqual(application['row_scope'][0]['fields'],
                         ['Last Checked', 'Next Action'])
        dirty_headers = {header for tab, row_id, header in self.dirty()
                         if tab == 'Companies' and row_id == 1}
        self.assertTrue(set(application['row_scope'][0]['fields']) <= dirty_headers)
        self.assertNotIn('Company ID', application['row_scope'][0]['fields'])
        scope = copy.deepcopy(application['row_scope']); scope[0]['row_id'] = 999
        with self.repository.transaction():
            self.repository.db.execute(
                'UPDATE exact_local_applications SET row_scope=? WHERE apply_id=?',
                (__import__('json').dumps(scope, sort_keys=True, separators=(',', ':')),
                 application['apply_id']))
        with self.assertRaisesRegex(ValueError, 'stable identity'):
            exact_local_plan(self.repository, 'CYC-1', 'COMP-1')

    def test_verified_scope_guards_the_final_local_source_hash(self):
        row = company(); row.update({'Job Key': 'JOB-1', 'Source Hash': 'source-old'})
        self.repository.import_rows('Job History', [(2, row)])
        local = [{
            'tab': 'Job History', 'identity': {'Job Key': 'JOB-1'},
            'values': {'Source Hash': 'source-new', 'Last Checked': '2026-11-19'},
            'expected': {'Source Hash': 'source-old'},
        }]
        plan = sealed_plan(operations=local)
        commit_exact_local_plan(self.repository, 'CYC-1', 'COMP-1', plan)
        scope = exact_local_plan(
            self.repository, 'CYC-1', 'COMP-1')['row_scope'][0]
        self.assertEqual(scope['guards']['Source Hash'], 'source-new')


class ExactInboxPlanStateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.inbox = InventoryInbox(Path(self.temporary.name) / 'inbox.sqlite3', 'fixture')
        self.addCleanup(self.inbox.close)
        self.inbox.save('CYC-1', 'COMP-1', {'inventory_status': 'complete'})
        self.plan = sealed_plan()

    def test_freeze_has_no_receipt_and_local_cursor_is_separate(self):
        self.inbox.save_exact_plan(
            'CYC-1', 'COMP-1', self.plan, timestamp='2026-11-19T00:00:00Z')
        self.assertEqual(self.inbox.exact_local_state(
            'CYC-1', 'COMP-1')['state'], 'FROZEN')
        self.assertEqual(self.inbox.connection.execute(
            'SELECT count(*) FROM publication_receipts').fetchone()[0], 0)
        self.inbox.advance_exact_local_cursor('CYC-1', 'COMP-1', 1, expected=0)
        self.assertEqual(self.inbox.plan('CYC-1', 'COMP-1')[1], 1)

    def test_mirrors_are_monotonic_and_cleanup_is_exact(self):
        self.inbox.save_exact_plan(
            'CYC-1', 'COMP-1', self.plan, timestamp='2026-11-19T00:00:00Z')
        applied = self.inbox.mark_exact_local_applied(
            'CYC-1', 'COMP-1', plan_digest=self.plan['plan_digest'],
            apply_id='APPLY-1', records_digest='records-1', timestamp='t1')
        self.assertEqual(applied['state'], 'LOCAL_APPLIED')
        verified = self.inbox.mark_exact_local_verified(
            'CYC-1', 'COMP-1', plan_digest=self.plan['plan_digest'],
            apply_id='APPLY-1', records_digest='records-1', timestamp='t2')
        self.assertEqual(verified['state'], 'LOCAL_VERIFIED')
        with self.assertRaisesRegex(ValueError, 'immutable'):
            self.inbox.discard_plan('CYC-1', 'COMP-1')
        inventory = self.inbox.get('CYC-1', 'COMP-1')
        sync_plan = self.inbox.plan('CYC-1', 'COMP-1')
        local_state = self.inbox.exact_local_state('CYC-1', 'COMP-1')
        with self.assertRaisesRegex(ValueError, 'registered, terminal remote plan'):
            self.inbox.acknowledge('CYC-1', 'COMP-1')
        self.assertEqual(self.inbox.get('CYC-1', 'COMP-1'), inventory)
        self.assertEqual(self.inbox.plan('CYC-1', 'COMP-1'), sync_plan)
        self.assertEqual(self.inbox.exact_local_state('CYC-1', 'COMP-1'), local_state)


if __name__ == '__main__':
    unittest.main()
