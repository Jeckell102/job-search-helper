"""Disposable, synthetic reproductions. No production paths or network clients.

These tests assert the observed defect, so a passing test means the defect
was reproduced; they are not acceptance tests.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_exact_legacy_migration import fixture, controls
from job_search_helper.exact_legacy_migration import build_legacy_v2_plan
from job_search_helper.exact_local_plan import (
    _row_scope, commit_exact_local_plan, exact_local_plan,
)
from job_search_helper.exact_cycle_planner import _digest
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.repository import MemoryRepository, ReviewFieldsChangedError
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository

CYCLE = 'CYC-B639C6D864EC'
COMPANY = 'COMP-0035'


def working_fixture():
    repo, legacy, payload, cursor = fixture()
    # A private mutable snapshot wrapper for deterministic race injection.
    # The current supplied test fixture itself uses read(tab) correctly.
    repo.rows = repo.tables
    repo.matches = lambda tab, identity: [
        (number, copy.deepcopy(row))
        for number, row in enumerate(repo.rows.get(tab, []), 2)
        if all(str(row.get(key, '')) == str(value) for key, value in identity.items())]
    return repo, legacy, payload, cursor


def build(repo, legacy, payload, cursor=3, **kwargs):
    cycle_id = kwargs.get('cycle_id', CYCLE)
    company_id = kwargs.get('company_id', COMPANY)
    binding = {
        'cycle_id': cycle_id, 'company_id': company_id,
        'legacy_plan_digest': _digest(legacy), 'inventory_payload_digest': _digest(payload),
        'legacy_operation_count': len(legacy['operations']), 'original_local_cursor': cursor,
    }
    return build_legacy_v2_plan(
        repo, cycle_id=cycle_id, company_id=company_id,
        payload=payload, legacy_plan=legacy, cursor=cursor,
        controls=kwargs.get('controls', controls()), binding=binding)


class DefectReproductions(unittest.TestCase):
    def test_revised_builder_refuses_changed_expected_only_source_hash(self):
        repo, legacy, payload, cursor = working_fixture()
        legacy['operations'][2]['expected']['Source Hash'] = 'frozen-source'
        repo.rows['Job History'][0]['Source Hash'] = 'unrelated-new-source'
        with self.assertRaisesRegex(ValueError, 'local_readback_mismatch'):
            build(repo, legacy, payload)

    def test_full_record_drift_has_identical_plan_and_local_readback_digest(self):
        repo, legacy, payload, cursor = working_fixture()
        before, _ = build(repo, legacy, payload)
        repo.rows['Job History'][0]['Review Notes'] = 'new unrelated review'
        after, _ = build(repo, legacy, payload)
        self.assertEqual(before['plan_digest'], after['plan_digest'])
        self.assertEqual(before['legacy_migration']['local_readback_digest'],
                         after['legacy_migration']['local_readback_digest'])

    def test_builder_accepts_inactive_current_local_company(self):
        repo, legacy, payload, cursor = working_fixture()
        repo.rows['Companies'][0]['Company Status'] = 'Hold'
        plan, _ = build(repo, legacy, payload)
        self.assertEqual(plan['control_evidence']['company_status'], 'Active')

    def test_builder_rebinds_another_company_and_cycle_without_matching_rows(self):
        repo, legacy, payload, cursor = working_fixture()
        other = controls(); other['company_id'] = 'COMP-OTHER'
        plan, _ = build(repo, legacy, payload, company_id='COMP-OTHER',
                        cycle_id='CYC-OTHER', controls=other)
        self.assertEqual(plan['company_id'], 'COMP-OTHER')
        self.assertEqual(plan['local_operations'][0]['identity']['Company ID'], COMPANY)

    def test_revised_builder_refuses_review_change_between_reads(self):
        repo, legacy, payload, cursor = working_fixture()
        original = repo.matches
        calls = 0
        def racing_matches(tab, identity):
            nonlocal calls
            result = original(tab, identity)
            if tab == 'Job History':
                calls += 1
                if calls == 1:
                    repo.rows[tab][0]['Decision'] = 'Later decision'
            return result
        repo.matches = racing_matches
        with self.assertRaisesRegex(ValueError, 'local_readback_mismatch'):
            build(repo, legacy, payload)
        self.assertEqual(repo.rows['Job History'][0]['Decision'], 'Later decision')


class PositivePlanningChecks(unittest.TestCase):
    def test_nineteen_operations_two_conflicts_and_no_input_mutation(self):
        repo, legacy, payload, _ = working_fixture()
        evidence_template = copy.deepcopy(legacy['operations'][1])
        history_template = copy.deepcopy(legacy['operations'][2])
        evidence_row = copy.deepcopy(repo.rows['Job Evidence'][0])
        history_row = copy.deepcopy(repo.rows['Job History'][0])
        legacy['operations'] = legacy['operations'][:1]
        repo.rows['Job Evidence'] = []
        repo.rows['Job History'] = []
        for number in range(1, 10):
            key = f'job-{number}'
            evidence, history = copy.deepcopy(evidence_template), copy.deepcopy(history_template)
            evidence['identity']['Job Key'] = history['identity']['Job Key'] = key
            local_evidence, local_history = copy.deepcopy(evidence_row), copy.deepcopy(history_row)
            local_evidence['Job Key'] = local_history['Job Key'] = key
            if number > 2:
                local_history.update({'Review Status': 'Pending', 'Decision': 'Old'})
            repo.rows['Job Evidence'].append(local_evidence)
            repo.rows['Job History'].append(local_history)
            legacy['operations'].extend([evidence, history])
        before = copy.deepcopy((repo.rows, legacy, payload))
        plan, report = build(repo, legacy, payload, 19)
        self.assertEqual((len(plan['local_operations']), len(plan['remote_projection']),
                          report['protected_conflict_count']), (19, 10, 2))
        self.assertFalse(any(op['tab'] == 'Job Evidence' for op in plan['remote_projection']))
        self.assertFalse(any('Decision' in op.get(mapping, {})
                             for op in plan['remote_projection']
                             for mapping in ('values', 'on_insert', 'expected')))
        scopes = _row_scope(plan)
        for key in ('job-1', 'job-2'):
            history = next(op for op in plan['remote_projection']
                           if op['tab'] == 'Job History' and op['identity']['Job Key'] == key)
            self.assertNotIn('Review Status', history['values'])
            self.assertEqual(history['expected']['Review Status'], 'Human Reviewed')
            scope = next(item for item in scopes
                         if item['tab'] == 'Job History' and item['identity']['Job Key'] == key)
            self.assertEqual(scope['guards']['Decision'], 'Keep')
        self.assertEqual((repo.rows, legacy, payload), before)


class SQLiteMigrationProbes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = SQLiteRepository(Path(self.tmp.name) / 'jobs.sqlite3',
                                      'synthetic-review', initialize=True)
        self.addCleanup(self.local.close)
        self.local.ensure_columns('Opportunities', ['Opportunity ID'])
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
            self.local.set_meta('sheets_profile', 'compact-v1')
        repo, self.legacy, self.payload, _ = working_fixture()
        for tab, rows in repo.rows.items():
            rows = copy.deepcopy(rows)
            if tab in {'Companies', 'Job History'}:
                rows[0]['Last Checked'] = 'old'
            self.local.import_rows(tab, enumerate(rows, 2))
        for op in self.legacy['operations']:
            if op['tab'] in {'Companies', 'Job History'}:
                op['expected']['Last Checked'] = 'old'
                self.local.commit([{'tab': op['tab'], 'identity': op['identity'],
                                    'values': {'Last Checked': 'now'}}])
        history = self.legacy['operations'][2]
        history['values'].pop('Company')
        history['values'].pop('Official Job URL')
        history['expected']['Added to Opportunities?'] = ''
        self.legacy['operations'] = [self.legacy['operations'][1], history,
                                     self.legacy['operations'][0]]
        self.plan, _ = build(self.local, self.legacy, self.payload)
        self.inbox = InventoryInbox(Path(self.tmp.name) / 'inbox.sqlite3',
                                    'synthetic-review')
        self.addCleanup(self.inbox.close)
        self.inbox.save(CYCLE, COMPANY, self.payload)

    def verified_local(self):
        self.inbox.save_exact_plan(CYCLE, COMPANY, self.plan, timestamp='t0')
        result = commit_exact_local_plan(self.local, CYCLE, COMPANY, self.plan)
        for method in (self.inbox.mark_exact_local_applied,
                       self.inbox.mark_exact_local_verified):
            method(CYCLE, COMPANY, plan_digest=self.plan['plan_digest'],
                   apply_id=result['apply_id'], records_digest=result['records_digest'],
                   timestamp='t1')
        self.inbox.advance_exact_local_cursor(CYCLE, COMPANY, 3, expected=0)
        return result

    def test_revised_local_restart_refuses_guard_only_decision_changes(self):
        self.verified_local()
        self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
                            'values': {'Decision': 'Later decision'}}])
        self.local.close()
        self.local = SQLiteRepository(Path(self.tmp.name) / 'jobs.sqlite3',
                                      'synthetic-review')
        self.addCleanup(self.local.close)
        with patch.object(self.local, '_commit_in_transaction',
                          side_effect=AssertionError('must not replay')):
            with self.assertRaisesRegex(ValueError, 'guard changed after verification'):
                commit_exact_local_plan(self.local, CYCLE, COMPANY, self.plan)
        with self.assertRaisesRegex(ValueError, 'guard changed after verification'):
            exact_local_plan(self.local, CYCLE, COMPANY)
        self.assertEqual(self.local.matches('Job History', {'Job Key': 'job-1'})[0][1]
                         ['Decision'], 'Later decision')

    def test_existing_legacy_plan_cannot_be_adopted_by_save_exact_plan(self):
        self.inbox.save_plan(CYCLE, COMPANY, self.legacy)
        self.inbox.connection.execute('UPDATE sync_plans SET cursor=3')
        self.inbox.connection.commit()
        with self.assertRaisesRegex(ValueError, 'conflicts with existing frozen evidence'):
            self.inbox.save_exact_plan(CYCLE, COMPANY, self.plan, timestamp='t1')
        self.assertEqual(self.inbox.plan(CYCLE, COMPANY), (self.legacy, 3))
        self.assertEqual(self.inbox.connection.execute(
            'SELECT count(*) FROM publication_receipts').fetchone()[0], 0)

    def test_company_first_legacy_order_is_sealed_but_exact_planning_refuses(self):
        self.legacy['operations'] = [self.legacy['operations'][2],
                                     self.legacy['operations'][0],
                                     self.legacy['operations'][1]]
        self.plan, _ = build(self.local, self.legacy, self.payload)
        self.verified_local()
        rows = {tab: [{key: row.get(key, '') for key in headers}
                      for row in self.local.read(tab)]
                for tab, headers in COMPACT_SCHEMAS.items()}
        remote = MemoryRepository(rows, schemas=COMPACT_SCHEMAS)
        remote.spreadsheet_id = 'synthetic-review'
        sync = SheetsSynchronizer(self.local, remote)
        authority = exact_local_plan(self.local, CYCLE, COMPANY)
        with self.assertRaisesRegex(ValueError, 'differs from the frozen projection'):
            sync.plan_exact_scope(authority['row_scope'], self.plan['remote_projection'])

    def test_nonblank_remote_guard_blocks_final_confirmation_but_advances_chunk(self):
        self.remote_retry_case('Human Reviewed', 'Remote later status', False)

    def test_blank_remote_guard_still_confirms_after_rejection_without_any_write(self):
        self.remote_retry_case('', 'Remote later status', True)

    def test_matching_nonblank_remote_guard_cannot_confirm_successful_write(self):
        self.remote_retry_case('Human Reviewed', 'Human Reviewed', False)

    def remote_retry_case(self, frozen_status, remote_status, can_confirm):
        if frozen_status != 'Human Reviewed':
            self.local.commit([{'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
                                'values': {'Review Status': frozen_status}}])
            self.plan, _ = build(self.local, self.legacy, self.payload)
        self.verified_local()
        rows = {tab: [{key: row.get(key, '') for key in headers}
                      for row in self.local.read(tab)]
                for tab, headers in COMPACT_SCHEMAS.items()}
        rows['Job History'][0]['Review Status'] = remote_status
        class Remote(MemoryRepository):
            spreadsheet_id = 'synthetic-review'
            attempts = 0
            successful_writes = 0
            def commit(self, operations):
                self.attempts += 1
                result = super().commit(operations)
                self.successful_writes += 1
                return result
        remote = Remote(rows, schemas=COMPACT_SCHEMAS)
        sync = SheetsSynchronizer(self.local, remote)
        authority = exact_local_plan(self.local, CYCLE, COMPANY)
        exact = sync.plan_exact_scope(authority['row_scope'], self.plan['remote_projection'])
        receipt = {
            'binding': {'request_id': CYCLE, 'company_id': COMPANY,
                        'source_revision': self.plan['plan_digest'], 'release_id': 'review-fixture'},
            'records': record_fingerprints(exact['operations']),
            'schedule': {'boundary': 'idle', 'enqueued_at': 't0'}, 'timestamp': 't0'}
        receipt_id = self.inbox.ensure_receipt(receipt)
        self.inbox.freeze_exact_remote_plan(
            CYCLE, COMPANY, local_plan_digest=self.plan['plan_digest'],
            projection=exact['operations'], projection_digest=exact['projection_digest'],
            receipt_id=receipt_id, intent_id='review-intent', timestamp='t1')
        options = dict(inbox=self.inbox, cycle_id=CYCLE, company_id=COMPANY,
                       plan_digest=self.plan['plan_digest'], receipt_id=receipt_id,
                       intent_id='review-intent')
        if frozen_status != remote_status:
            with self.assertRaises(ReviewFieldsChangedError):
                sync.publish_exact_scope(exact, **options)
        else:
            sync.publish_exact_scope(exact, **options)
        self.inbox.close()
        self.inbox = InventoryInbox(Path(self.tmp.name) / 'inbox.sqlite3',
                                    'synthetic-review')
        self.addCleanup(self.inbox.close)
        self.local.close()
        self.local = SQLiteRepository(Path(self.tmp.name) / 'jobs.sqlite3',
                                      'synthetic-review')
        self.addCleanup(self.local.close)
        sync = SheetsSynchronizer(self.local, remote)
        options['inbox'] = self.inbox
        retry = sync.publish_exact_scope(exact, **options)
        if can_confirm:
            sync.confirm_exact_scope(**options)
        else:
            with self.assertRaisesRegex(ValueError, 'readback does not match its receipt'):
                sync.confirm_exact_scope(**options)
        self.assertFalse(retry['first_attempt'])
        self.assertEqual(remote.attempts, 1)
        self.assertEqual(remote.successful_writes, int(frozen_status == remote_status))
        self.assertEqual(self.inbox.receipt(receipt)['state'],
                         'SYNC_CONFIRMED' if can_confirm else 'SYNC_PENDING')
        self.assertEqual(self.inbox.exact_chunk(CYCLE, COMPANY, 0)['state'], 'CONFIRMED')
        self.assertEqual(remote.read('Job History')[0]['Review Status'], remote_status)
        self.assertEqual(exact['operations'][0]['expected']['Review Status'], frozen_status)


if __name__ == '__main__':
    unittest.main(verbosity=2)
