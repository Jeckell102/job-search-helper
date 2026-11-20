"""Exact selected-scope Sheets planning, delivery, readback, and acknowledgement."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.repository import GoogleRepository, MemoryRepository, SCHEMAS, RepositoryError
from job_search_helper.inbox import InventoryInbox
from job_search_helper.exact_legacy_migration import capture_legacy_delivery_evidence
from job_search_helper.exact_cycle_sync import _company_guard, _validate_controls
from job_search_helper.publication_receipts import record_fingerprints
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets
from test_sqlite_migration import job


def company(company_id='COMP-1', name='Fixture'):
    return {
        'Company ID': company_id, 'Company': name, 'Company Status': 'Active',
        'Official Careers URL': f'https://jobs.example.test/{company_id.lower()}',
        'Scan State': 'Queued', 'Last Checked': '', 'Next Action': '',
    }


def sealed_plan(local_operations, remote_operations):
    plan = {
        'local_operations': copy.deepcopy(local_operations),
        'operations': copy.deepcopy(remote_operations),
        'local_operations_digest': _digest(local_operations),
        'remote_operations_digest': _digest(remote_operations),
        'publication_profile': COMPACT_PROFILE,
    }
    plan['remote_projection_digest'] = _digest({
        'profile': COMPACT_PROFILE, 'operations': remote_operations,
    })
    plan['plan_digest'] = _digest(plan)
    return plan


def _digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


class ExactScopeSheetsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.local = SQLiteRepository(
            Path(self.temporary.name) / 'jobs.sqlite3', 'fixture', initialize=True)
        self.addCleanup(self.local.close)
        self.local.ensure_columns('Opportunities', ['Opportunity ID'])
        with self.local.transaction():
            self.local.set_meta('ready', 'yes')
            self.local.set_meta('sheets_profile', COMPACT_PROFILE)
        self.companies = [company(), company('COMP-2', 'Unrelated')]
        history = job(**{
            'Company': 'Fixture', 'Job Key': 'job-1',
            'Official Job URL': 'https://jobs.example.test/comp-1/1',
            'Added to Opportunities?': 'Manual Review',
            'Salary / Range': '$130,000 estimated', 'Source Hash': 'source-local',
        })
        self.rows = {'Companies': self.companies, 'Job History': [history]}
        full = MemoryRepository(self.rows, schemas=self.local.schemas)
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(full.read(tab), 2))
        self.service = RangeSheets(self.rows, schemas=COMPACT_SCHEMAS)
        self.remote = GoogleRepository(
            self.service, 'fixture', schemas=COMPACT_SCHEMAS,
            min_request_interval=0)
        self.sync = SheetsSynchronizer(self.local, self.remote)
        self.inbox = InventoryInbox(Path(self.temporary.name) / 'inbox.sqlite3', 'fixture')
        self.addCleanup(self.inbox.close)

    def company_plan(self):
        local_operation = {
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Scan State': 'Complete', 'Active Cycle ID': 'CYC-1',
                       'Last Checked': '2026-11-19', 'Next Action': 'Inventory saved'},
            'expected': {'Scan State': 'Queued'},
        }
        remote_operation = {
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Last Checked': '2026-11-19', 'Next Action': 'Inventory saved'},
            'append_if_missing': False, 'on_insert': {},
            'expected': {'Last Checked': '', 'Next Action': ''}, 'append_notes': {},
        }
        plan = sealed_plan([local_operation], [remote_operation])
        scope = [{'tab': 'Companies', 'row_id': 1,
                  'identity': {'Company ID': 'COMP-1'},
                  'fields': ['Last Checked', 'Next Action'],
                  'append_if_missing': False,
                  'expected': {'Last Checked': '', 'Next Action': ''}}]
        self.apply_verified_local('CYC-1', 'COMP-1', plan, scope)
        return plan, scope, remote_operation

    def review_guard_plan(self, cycle_id, status):
        current = self.local.read('Job History')[0]
        if current.get('Review Status', '') != status:
            current['Review Status'] = status
            self.local.import_rows('Job History', [(2, current)])
        local_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19'},
            'expected': {'Review Status': status,
                         'Added to Opportunities?': 'Manual Review',
                         'Source Hash': 'source-local'},
        }
        remote_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19'},
            'append_if_missing': False, 'on_insert': {},
            'expected': {'Last Checked': '', 'Review Status': status,
                         'Added to Opportunities?': 'Manual Review'},
            'append_notes': {},
        }
        plan = sealed_plan([local_operation], [remote_operation])
        plan.pop('plan_digest')
        plan['record_fingerprint_version'] = 2
        plan['plan_digest'] = _digest(plan)
        scope = [{
            'tab': 'Job History', 'row_id': 1,
            'identity': {'Job Key': 'job-1'},
            'fields': ['Last Checked'], 'append_if_missing': False,
            'guards': {'Review Status': status,
                       'Added to Opportunities?': 'Manual Review',
                       'Source Hash': 'source-local'},
            'expected': copy.deepcopy(remote_operation['expected']),
        }]
        self.apply_verified_local(cycle_id, 'COMP-1', plan, scope)
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            cycle_id, 'COMP-1', plan, exact, intent_id='intent-' + cycle_id)
        return plan, exact, receipt_id, intent_id

    def remote_authority(self, cycle_id, company_id, plan, exact,
                         intent_id='intent-1', delivery_mode='write_once'):
        self.inbox.save(cycle_id, company_id, {'jobs': []})
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                'INSERT OR IGNORE INTO sync_plans VALUES (?,?,?,0)',
                (cycle_id, company_id, json.dumps(plan)))
            self.inbox.connection.execute(
                'INSERT OR IGNORE INTO exact_plan_local_state VALUES '
                '(?,?,?,?,?,?,?,?,?,?)',
                (cycle_id, company_id, plan['plan_digest'],
                 plan['local_operations_digest'], plan['remote_projection_digest'],
                 'LOCAL_VERIFIED', 'APPLY-' + cycle_id, 'records-digest',
                 '2026-11-19T00:00:00Z', '2026-11-19T00:00:01Z'))
            if delivery_mode == 'observation_only':
                evidence = capture_legacy_delivery_evidence(
                    self.local, exact['operations'])
                self.inbox.connection.execute(
                    'INSERT INTO exact_legacy_delivery_evidence VALUES '
                    '(?,?,?,?,?,?,?,?,?,?,?)',
                    (cycle_id, company_id, evidence['version'], delivery_mode,
                     plan['plan_digest'], 'legacy-digest',
                     evidence['evidence_digest'], json.dumps(evidence), 'BOUND',
                     '2026-11-19T00:00:00Z', '2026-11-19T00:00:01Z'))
        receipt = {
            'binding': {'request_id': cycle_id, 'company_id': company_id,
                        'source_revision': plan['plan_digest'], 'release_id': 'test'},
            'records': record_fingerprints(
                exact['operations'],
                include_guard_only=plan.get('record_fingerprint_version', 1) == 2),
            'schedule': {'boundary': 'idle', 'enqueued_at': '2026-11-19T00:00:00Z'},
            'timestamp': '2026-11-19T00:00:00Z',
        }
        receipt_id = self.inbox.ensure_receipt(receipt)
        self.inbox.freeze_exact_remote_plan(
            cycle_id, company_id, local_plan_digest=plan['plan_digest'],
            projection=exact['operations'], projection_digest=exact['projection_digest'],
            receipt_id=receipt_id, intent_id=intent_id,
            timestamp='2026-11-19T00:00:01Z',
            delivery_mode=delivery_mode)
        return receipt_id, intent_id

    def make_company_observation(self):
        plan, scope, remote_operation = self.company_plan()
        row_id, current = self.local.matches(
            'Companies', {'Company ID': 'COMP-1'})[0]
        baseline = self.local.baseline('Companies', row_id)
        for header in ('Last Checked', 'Next Action'):
            baseline[header] = current[header]
        with self.local.transaction():
            self.local._baseline('Companies', row_id, baseline)
            self.local.db.execute(
                "DELETE FROM dirty WHERE tab='Companies' AND row_id=? "
                "AND header IN ('Last Checked','Next Action')", (row_id,))
        exact = self.sync.plan_exact_scope(
            scope, [remote_operation], delivery_mode='observation_only')
        return plan, scope, remote_operation, exact

    @staticmethod
    def observation_guard():
        """Stand-in for the higher-level post-read Company control guard."""
        return None

    def confirm_remote(self, cycle_id, company_id, plan, exact, readback,
                       receipt_id, intent_id):
        return self.sync.confirm_exact_scope(
            inbox=self.inbox, cycle_id=cycle_id, company_id=company_id,
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)

    def apply_verified_local(self, cycle_id, company_id, plan, row_scope):
        self.local.commit(plan['local_operations'])
        with self.local.transaction():
            self.local.db.execute(
                'INSERT INTO exact_local_applications VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('APPLY-' + cycle_id, cycle_id, company_id, plan['plan_digest'],
                 'inventory-digest', plan['local_operations_digest'],
                 plan['remote_projection_digest'], json.dumps(row_scope),
                 '2026-11-19T00:00:00Z', '2026-11-19T00:00:01Z', 'VERIFIED'))

    def test_planning_uses_only_explicit_scope_and_requires_frozen_equality(self):
        plan, scope, remote_operation = self.company_plan()
        self.local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-2'},
            'values': {'Next Action': 'Unrelated work'},
        }])
        before_dirty = list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header'))
        with patch.object(self.sync, '_operations', side_effect=AssertionError('global discovery')), \
                patch.object(self.sync, 'pull', side_effect=AssertionError('pull')), \
                patch.object(self.sync, 'once', side_effect=AssertionError('once')), \
                patch.object(self.sync, 'publish_batch', side_effect=AssertionError('global publish')), \
                patch('job_search_helper.sheets_sync.prune_local_only_delivery',
                      side_effect=AssertionError('global prune')):
            exact = self.sync.plan_exact_scope(scope, [remote_operation])
        self.assertEqual(exact['operations'], [remote_operation])
        without_hint = copy.deepcopy(scope)
        without_hint[0].pop('row_id')
        self.assertEqual(
            self.sync.plan_exact_scope(without_hint, [remote_operation])['operations'],
            [remote_operation])
        self.assertEqual(len(self.service.batches), 0)
        self.assertEqual(list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header')), before_dirty)

        changed = copy.deepcopy(remote_operation)
        changed['values']['Next Action'] = 'Mutable replan'
        with self.assertRaisesRegex(ValueError, 'differs from the frozen projection'):
            self.sync.plan_exact_scope(scope, [changed])
        self.assertEqual(len(self.service.batches), 0)

    def test_durable_claim_allows_one_commit_and_duplicate_is_readback_only(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority('CYC-1', 'COMP-1', plan, exact)

        original = self.remote.commit
        commits = []
        def recording_commit(operations):
            commits.append(copy.deepcopy(operations))
            return original(operations)
        with patch.object(self.remote, 'commit', side_effect=recording_commit):
            first = self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)
            second = self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)
        self.assertTrue(first['first_attempt'])
        self.assertFalse(second['first_attempt'])
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(self.service.batches), 1)
        self.assertEqual(first['readback']['acknowledgement_id'],
                         second['readback']['acknowledgement_id'])

        with self.assertRaisesRegex(ValueError, 'real durable inventory inbox'):
            self.sync.publish_exact_scope(
                exact, inbox=object(), cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)
        remote = self.remote.read('Companies')
        self.assertEqual(remote[0]['Next Action'], 'Inventory saved')
        self.assertEqual(remote[1]['Next Action'], '')

    def test_observation_only_matching_remote_confirms_without_commit(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        matching_rows = copy.deepcopy(self.rows)
        matching_rows['Companies'][0].update({
            'Last Checked': '2026-11-19',
            'Next Action': 'Inventory saved',
        })
        service = RangeSheets(matching_rows, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(
            service, 'fixture', schemas=COMPACT_SCHEMAS,
            min_request_interval=0)
        sync = SheetsSynchronizer(self.local, remote)
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        guard_calls = []
        def post_read_guard():
            guard_calls.append('checked')
        with patch.object(
                remote, 'commit', side_effect=AssertionError('must not write')):
            delivered = sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                post_observation_read_guard=post_read_guard)
            acknowledged = sync.confirm_and_acknowledge_exact_scope(
                inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                post_observation_read_guard=post_read_guard)
            repeated = sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                post_observation_read_guard=post_read_guard)
        self.assertTrue(delivered['observation_only'])
        self.assertFalse(delivered['first_attempt'])
        self.assertIsNone(delivered['commit'])
        self.assertEqual(len(service.batches), 0)
        self.assertEqual(acknowledged['acknowledged_rows'], 1)
        self.assertFalse(repeated['first_attempt'])
        self.assertEqual(guard_calls, ['checked', 'checked', 'checked'])
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['delivery_mode'], 'observation_only')
        self.assertFalse(state['first_attempt_claimed'])
        self.assertEqual(state['state'], 'SYNC_CONFIRMED')

    def test_observation_without_post_read_company_guard_refuses_before_remote_read(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        with patch.object(
                self.remote, 'read_columns',
                side_effect=AssertionError('must not read remote')), \
                patch.object(
                    self.remote, 'commit',
                    side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(
                    ValueError, 'post-read Company guard'):
                self.sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id)
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['state'], 'FROZEN')
        self.assertEqual(state['remote_cursor'], 0)
        self.assertEqual(self.inbox.connection.execute(
            'SELECT count(*) FROM exact_sync_chunks').fetchone()[0], 0)

    def test_direct_observation_confirmation_paths_require_guard_before_remote_read(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        calls = (
            lambda: self.sync._readback_and_confirm_chunk(
                exact, self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                remote_projection_digest=exact['projection_digest'],
                remote_cursor=0),
            lambda: self.sync._readback_and_confirm_full(
                inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id),
            lambda: self.sync.confirm_and_acknowledge_exact_scope(
                inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id),
        )
        with patch.object(
                self.remote, 'read_columns',
                side_effect=AssertionError('must not read remote')), \
                patch.object(
                    self.remote, 'read_row',
                    side_effect=AssertionError('must not read remote')):
            for invoke in calls:
                with self.subTest(invoke=invoke), self.assertRaisesRegex(
                        ValueError, 'post-read Company guard'):
                    invoke()
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['state'], 'FROZEN')
        self.assertEqual(state['remote_cursor'], 0)
        self.assertEqual(self.inbox.connection.execute(
            'SELECT count(*) FROM exact_sync_chunks').fetchone()[0], 0)
        self.assertEqual(self.local.db.execute(
            'SELECT count(*) FROM exact_local_acknowledgements').fetchone()[0], 0)

    def test_observation_company_control_change_during_read_holds_before_confirmation(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        matching_rows = copy.deepcopy(self.rows)
        matching_rows['Companies'][0].update({
            'Last Checked': '2026-11-19',
            'Next Action': 'Inventory saved',
        })
        service = RangeSheets(matching_rows, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(
            service, 'fixture', schemas=COMPACT_SCHEMAS,
            min_request_interval=0)
        sync = SheetsSynchronizer(self.local, remote)
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        control_evidence = {
            'company_id': 'COMP-1',
            'requested_url': 'https://jobs.example.test/comp-1',
            'official_careers_url': 'https://jobs.example.test/comp-1',
            'company_status': 'Active',
            'claimed_by': '',
            'claim_token': '',
        }
        guarded_plan = {
            'control_evidence_version': 1,
            'control_evidence': control_evidence,
            'control_evidence_digest': _digest(control_evidence),
        }
        original_read_row = remote.read_row

        def change_control_after_observation_read(tab, row_number):
            observed = original_read_row(tab, row_number)
            service.set_cell('Companies', 1, 'Company Status', 'Paused')
            return observed

        def post_read_guard():
            _validate_controls(guarded_plan, _company_guard(
                self.local, remote, 'COMP-1',
                'https://jobs.example.test/comp-1'))

        with patch.object(
                remote, 'commit', side_effect=AssertionError('must not write')), \
                patch.object(remote, 'read_row',
                             side_effect=change_control_after_observation_read):
            with self.assertRaisesRegex(
                    ValueError, 'local_remote_company_controls_changed'):
                sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=post_read_guard)

        self.assertEqual(len(service.batches), 0)
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['state'], 'SYNC_PENDING')
        self.assertEqual(state['remote_cursor'], 0)
        self.assertIsNone(state['acknowledgement_id'])
        self.assertEqual(self.inbox.connection.execute(
            'SELECT state FROM exact_sync_chunks WHERE cycle=? AND company=?',
            ('CYC-1', 'COMP-1')).fetchone(), ('PENDING',))
        self.assertNotEqual(self.inbox.connection.execute(
            'SELECT state FROM publication_receipts WHERE receipt_id=?',
            (receipt_id,)).fetchone(), ('SYNC_CONFIRMED',))
        self.assertEqual(self.local.db.execute(
            'SELECT count(*) FROM exact_local_acknowledgements').fetchone()[0], 0)

    def test_observation_only_blank_missing_baseline_confirms_without_commit(self):
        cycle_id = 'CYC-BLANK-MISSING'
        local_operation = {
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Last Checked': '', 'Next Action': ''},
            'expected': {'Scan State': 'Queued'},
        }
        remote_operation = {
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Last Checked': '', 'Next Action': ''},
            'append_if_missing': False, 'on_insert': {},
            'expected': {'Last Checked': '', 'Next Action': ''},
            'append_notes': {},
        }
        plan = sealed_plan([local_operation], [remote_operation])
        scope = [{
            'tab': 'Companies', 'row_id': 1,
            'identity': {'Company ID': 'COMP-1'},
            'fields': ['Last Checked', 'Next Action'],
            'append_if_missing': False,
            'expected': copy.deepcopy(remote_operation['expected']),
        }]
        self.apply_verified_local(cycle_id, 'COMP-1', plan, scope)
        row_id, _current = self.local.matches(
            'Companies', {'Company ID': 'COMP-1'})[0]
        baseline = self.local.baseline('Companies', row_id)
        baseline.pop('Last Checked', None)
        baseline.pop('Next Action', None)
        with self.local.transaction():
            self.local._baseline('Companies', row_id, baseline)
            self.local.db.execute(
                "DELETE FROM dirty WHERE tab='Companies' AND row_id=? "
                "AND header IN ('Last Checked','Next Action')", (row_id,))
        exact = self.sync.plan_exact_scope(
            scope, [remote_operation], delivery_mode='observation_only')
        receipt_id, intent_id = self.remote_authority(
            cycle_id, 'COMP-1', plan, exact,
            intent_id='intent-blank-missing',
            delivery_mode='observation_only')
        evidence = self.inbox.exact_legacy_delivery_evidence(
            cycle_id, 'COMP-1')
        self.assertEqual(
            evidence['evidence']['classification_counts']['baseline_missing'],
            2)
        with patch.object(
                self.remote, 'commit',
                side_effect=AssertionError('must not write')):
            delivered = self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id=cycle_id,
                company_id='COMP-1', plan_digest=plan['plan_digest'],
                receipt_id=receipt_id, intent_id=intent_id,
                post_observation_read_guard=self.observation_guard)
            acknowledged = self.sync.confirm_and_acknowledge_exact_scope(
                inbox=self.inbox, cycle_id=cycle_id, company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                post_observation_read_guard=self.observation_guard)
        self.assertTrue(delivered['observation_only'])
        self.assertFalse(delivered['first_attempt'])
        self.assertIsNone(delivered['commit'])
        self.assertEqual(len(self.service.batches), 0)
        self.assertEqual(acknowledged['acknowledged_rows'], 1)
        state = self.inbox.exact_remote_state(cycle_id, 'COMP-1')
        self.assertEqual(state['state'], 'SYNC_CONFIRMED')
        self.assertFalse(state['first_attempt_claimed'])

    def test_observation_only_mismatch_holds_without_commit_or_confirmation(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        with patch.object(
                self.remote, 'commit', side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(ValueError, 'readback differs'):
                self.sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=self.observation_guard)
        self.assertEqual(len(self.service.batches), 0)
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['state'], 'SYNC_PENDING')
        self.assertFalse(state['first_attempt_claimed'])
        self.assertEqual(state['remote_cursor'], 0)
        self.assertIsNone(state['acknowledgement_id'])

    def test_observation_only_pending_restart_retries_readback_without_commit(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        with patch.object(
                self.remote, 'commit', side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(ValueError, 'readback differs'):
                self.sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=self.observation_guard)
        evidence_before = self.inbox.exact_legacy_delivery_evidence(
            'CYC-1', 'COMP-1')
        inbox_path = Path(self.temporary.name) / 'inbox.sqlite3'
        self.inbox.close()
        self.inbox = InventoryInbox(inbox_path, 'fixture')
        self.service.set_cell('Companies', 1, 'Last Checked', '2026-11-19')
        self.service.set_cell('Companies', 1, 'Next Action', 'Inventory saved')
        restarted = SheetsSynchronizer(self.local, self.remote)
        with patch.object(
                self.remote, 'commit', side_effect=AssertionError('must not write')):
            delivered = restarted.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1',
                company_id='COMP-1', plan_digest=plan['plan_digest'],
                receipt_id=receipt_id, intent_id=intent_id,
                post_observation_read_guard=self.observation_guard)
        self.assertTrue(delivered['observation_only'])
        self.assertFalse(delivered['first_attempt'])
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['remote_cursor'], 1)
        self.assertFalse(state['first_attempt_claimed'])
        self.assertEqual(
            self.inbox.exact_legacy_delivery_evidence('CYC-1', 'COMP-1'),
            evidence_before)

    def test_observation_only_refuses_changed_bound_local_evidence(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        row_id, _current = self.local.matches(
            'Companies', {'Company ID': 'COMP-1'})[0]
        baseline = self.local.baseline('Companies', row_id)
        baseline['Next Action'] = 'changed evidence'
        with self.local.transaction():
            self.local._baseline('Companies', row_id, baseline)
        with patch.object(
                self.remote, 'commit', side_effect=AssertionError('must not write')):
            with self.assertRaisesRegex(
                    ValueError, 'delivery_evidence_changed|lost its delivery evidence'):
                self.sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=self.observation_guard)
        self.assertEqual(len(self.service.batches), 0)
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['state'], 'FROZEN')
        self.assertFalse(state['first_attempt_claimed'])

    def test_observation_only_refuses_changed_delivery_attempt_contents(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        row_id = self.local.matches(
            'Companies', {'Company ID': 'COMP-1'})[0][0]
        with self.local.transaction():
            self.local.db.execute(
                'INSERT OR REPLACE INTO delivery_attempts(tab,row_id,data) '
                'VALUES (?,?,?)', ('Companies', row_id, 'attempt-before-bind'))
        # Refresh the exact evidence binding after the attempt exists.
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        with self.local.transaction():
            self.local.db.execute(
                'UPDATE delivery_attempts SET data=? WHERE tab=? AND row_id=?',
                ('attempt-changed-after-bind', 'Companies', row_id))
        with patch.object(
                self.remote, 'commit', side_effect=AssertionError('must not write')), \
                patch.object(
                    self.remote, 'read_columns',
                    side_effect=AssertionError('must not read remote')):
            with self.assertRaisesRegex(ValueError, 'delivery_evidence_changed'):
                self.sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=self.observation_guard)
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['remote_cursor'], 0)
        self.assertIsNone(state['acknowledgement_id'])

    def test_observation_evidence_change_during_read_cannot_advance_cursor(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        matching_rows = copy.deepcopy(self.rows)
        matching_rows['Companies'][0].update({
            'Last Checked': '2026-11-19',
            'Next Action': 'Inventory saved',
        })
        service = RangeSheets(matching_rows, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(
            service, 'fixture', schemas=COMPACT_SCHEMAS,
            min_request_interval=0)
        sync = SheetsSynchronizer(self.local, remote)
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        original = remote.read_row

        def change_evidence_during_read(tab, row_number):
            row_id = self.local.matches(
                'Companies', {'Company ID': 'COMP-1'})[0][0]
            baseline = self.local.baseline('Companies', row_id)
            baseline['Next Action'] = 'changed-during-read'
            with self.local.transaction():
                self.local._baseline('Companies', row_id, baseline)
            return original(tab, row_number)

        with patch.object(
                remote, 'commit', side_effect=AssertionError('must not write')), \
                patch.object(remote, 'read_row', side_effect=change_evidence_during_read):
            with self.assertRaisesRegex(
                    ValueError, 'delivery_evidence_changed|lost its delivery evidence'):
                sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=self.observation_guard)
        state = self.inbox.exact_remote_state('CYC-1', 'COMP-1')
        self.assertEqual(state['remote_cursor'], 0)
        self.assertEqual(state['state'], 'SYNC_PENDING')
        self.assertIsNone(state['acknowledgement_id'])

    def test_observation_manual_guard_change_during_read_cannot_confirm(self):
        current = self.local.read('Job History')[0]
        current['Decision'] = 'Keep'
        self.local.import_rows('Job History', [(2, current)])
        local_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19'},
            'expected': {'Decision': 'Keep',
                         'Added to Opportunities?': 'Manual Review',
                         'Source Hash': 'source-local'},
        }
        remote_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19'},
            'append_if_missing': False, 'on_insert': {},
            'expected': {'Last Checked': '',
                         'Added to Opportunities?': 'Manual Review'},
            'append_notes': {},
        }
        plan = sealed_plan([local_operation], [remote_operation])
        plan.pop('plan_digest')
        plan['record_fingerprint_version'] = 2
        plan['plan_digest'] = _digest(plan)
        scope = [{
            'tab': 'Job History', 'row_id': 1,
            'identity': {'Job Key': 'job-1'}, 'fields': ['Last Checked'],
            'append_if_missing': False,
            'guards': {'Decision': 'Keep',
                       'Added to Opportunities?': 'Manual Review',
                       'Source Hash': 'source-local'},
            'expected': copy.deepcopy(remote_operation['expected']),
        }]
        self.apply_verified_local('CYC-MANUAL-RACE', 'COMP-1', plan, scope)
        row_id, current = self.local.matches(
            'Job History', {'Job Key': 'job-1'})[0]
        baseline = self.local.baseline('Job History', row_id)
        baseline['Last Checked'] = current['Last Checked']
        with self.local.transaction():
            self.local._baseline('Job History', row_id, baseline)
            self.local.db.execute(
                "DELETE FROM dirty WHERE tab='Job History' AND row_id=? "
                "AND header='Last Checked'", (row_id,))
        exact = self.sync.plan_exact_scope(
            scope, [remote_operation], delivery_mode='observation_only')
        self.service.set_cell('Job History', 1, 'Last Checked', '2026-11-19')
        receipt_id, intent_id = self.remote_authority(
            'CYC-MANUAL-RACE', 'COMP-1', plan, exact,
            intent_id='intent-manual-race', delivery_mode='observation_only')
        original = self.remote.read_row

        def change_manual_guard_during_read(tab, row_number):
            self.local.commit([{
                'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
                'values': {'Decision': 'Reject'},
            }])
            return original(tab, row_number)

        with patch.object(
                self.remote, 'commit', side_effect=AssertionError('must not write')), \
                patch.object(
                    self.remote, 'read_row',
                    side_effect=change_manual_guard_during_read):
            with self.assertRaisesRegex(ValueError, 'guard changed'):
                self.sync.publish_exact_scope(
                    exact, inbox=self.inbox, cycle_id='CYC-MANUAL-RACE',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id,
                    post_observation_read_guard=self.observation_guard)
        state = self.inbox.exact_remote_state('CYC-MANUAL-RACE', 'COMP-1')
        self.assertEqual(state['remote_cursor'], 0)
        self.assertEqual(state['state'], 'SYNC_PENDING')
        self.assertIsNone(state['acknowledgement_id'])

    def test_observation_evidence_archives_only_after_confirmed_local_ack(self):
        plan, _scope, _operation, exact = self.make_company_observation()
        matching_rows = copy.deepcopy(self.rows)
        matching_rows['Companies'][0].update({
            'Last Checked': '2026-11-19',
            'Next Action': 'Inventory saved',
        })
        service = RangeSheets(matching_rows, schemas=COMPACT_SCHEMAS)
        remote = GoogleRepository(
            service, 'fixture', schemas=COMPACT_SCHEMAS,
            min_request_interval=0)
        sync = SheetsSynchronizer(self.local, remote)
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact,
            delivery_mode='observation_only')
        with self.inbox.lock, self.inbox.connection:
            self.inbox.connection.execute(
                'INSERT INTO exact_legacy_plan_migrations('
                'cycle,company,legacy_plan_digest,inventory_payload_digest,'
                'operation_count,original_local_cursor,verified_local_cursor,'
                'state,created_at,updated_at,successor_plan_digest) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('CYC-1', 'COMP-1', 'legacy-digest', 'inventory-digest',
                 1, 1, 1, 'REMOTE_PLAN_FROZEN',
                 '2026-11-19T00:00:00Z', '2026-11-19T00:00:01Z',
                 plan['plan_digest']))
        with self.assertRaisesRegex(ValueError, 'locally acknowledged'):
            self.inbox.acknowledge('CYC-1', 'COMP-1', local=self.local)
        with patch.object(
                remote, 'commit', side_effect=AssertionError('must not write')):
            sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                post_observation_read_guard=self.observation_guard)
            acknowledged = sync.confirm_and_acknowledge_exact_scope(
                inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                post_observation_read_guard=self.observation_guard)
        with self.assertRaisesRegex(ValueError, 'locally acknowledged'):
            self.inbox.acknowledge('CYC-1', 'COMP-1', local=self.local)
        remote_state = self.inbox.mark_exact_remote_locally_acknowledged(
            'CYC-1', 'COMP-1', local=self.local,
            local_plan_digest=plan['plan_digest'],
            projection_digest=exact['projection_digest'],
            receipt_id=receipt_id, intent_id=intent_id,
            acknowledgement_id=acknowledged['acknowledgement_id'],
            timestamp='2026-11-19T00:00:03Z')
        self.assertEqual(remote_state['state'], 'LOCAL_ACKNOWLEDGED')
        self.inbox.acknowledge('CYC-1', 'COMP-1', local=self.local)
        self.assertIsNone(self.inbox.exact_legacy_delivery_evidence(
            'CYC-1', 'COMP-1'))
        archived = self.inbox.connection.execute(
            'SELECT evidence FROM exact_legacy_delivery_evidence_archive '
            'WHERE cycle=? AND company=?', ('CYC-1', 'COMP-1')).fetchone()
        self.assertIsNotNone(archived)
        self.assertEqual(json.loads(archived[0])['delivery_mode'],
                         'observation_only')

    def test_scoped_ack_preserves_newer_edit_local_only_data_and_unrelated_state(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority('CYC-1', 'COMP-1', plan, exact)
        result = self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        self.local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Next Action': 'Newer local decision'},
        }, {
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-2'},
            'values': {'Next Action': 'Unrelated work'},
        }])
        with self.local.transaction():
            self.local.db.execute(
                'INSERT INTO delivery_attempts VALUES (?,?,?)',
                ('Companies', 1, json.dumps({
                    'Last Checked': '2026-11-19', 'Next Action': 'Inventory saved',
                    'Notes': 'unrelated attempt'}, sort_keys=True)))
            self.local.db.execute(
                'INSERT INTO delivery_attempts VALUES (?,?,?)',
                ('Companies', 2, json.dumps({'Next Action': 'Unrelated work'}, sort_keys=True)))
        unrelated_before = list(self.local.db.execute(
            'SELECT * FROM delivery_attempts WHERE row_id=2'))

        acknowledged = self.sync.confirm_and_acknowledge_exact_scope(
            inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        self.assertFalse(acknowledged['recovered'])
        dirty = set(self.local.db.execute('SELECT tab,row_id,header FROM dirty'))
        self.assertNotIn(('Companies', 1, 'Last Checked'), dirty)
        self.assertIn(('Companies', 1, 'Next Action'), dirty)
        self.assertIn(('Companies', 2, 'Next Action'), dirty)
        self.assertEqual(self.local.read('Companies')[0]['Scan State'], 'Complete')
        self.assertEqual(self.local.baseline('Companies', 1)['Scan State'], 'Queued')
        self.assertEqual(self.local.baseline('Companies', 1)['Next Action'], 'Inventory saved')
        attempt = json.loads(self.local.db.execute(
            'SELECT data FROM delivery_attempts WHERE tab=? AND row_id=?',
            ('Companies', 1)).fetchone()[0])
        self.assertEqual(attempt, {
            'Last Checked': '2026-11-19', 'Next Action': 'Inventory saved',
            'Notes': 'unrelated attempt'})
        self.assertEqual(list(self.local.db.execute(
            'SELECT * FROM delivery_attempts WHERE row_id=2')), unrelated_before)
        repeated = self.sync.confirm_and_acknowledge_exact_scope(
            inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        self.assertTrue(repeated['recovered'])

    def test_caller_row_metadata_cannot_redirect_exact_acknowledgement(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact, intent_id='intent-forged-row')
        delivered = self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        self.local.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-2'},
            'values': {'Last Checked': '2026-11-19',
                       'Next Action': 'Unrelated work'},
        }])
        forged = copy.deepcopy(exact)
        forged['rows'][0].update({
            'row_id': 2,
            'identity': {'Company ID': 'COMP-2'},
            'sent': {'Last Checked': '2026-11-19',
                     'Next Action': 'Unrelated work'},
        })
        forged_readback = copy.deepcopy(delivered['readback'])
        forged_readback['rows'][0].update({
            'row_id': 2,
            'identity': {'Company ID': 'COMP-2'},
            'sent': {'Last Checked': '2026-11-19',
                     'Next Action': 'Unrelated work'},
        })
        before = set(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty'))
        with self.assertRaises(TypeError):
            self.sync._readback_and_confirm_full(
                forged, self.inbox, cycle_id='CYC-1',
                company_id='COMP-1', plan_digest=plan['plan_digest'],
                receipt_id=receipt_id, intent_id=intent_id)
        with self.assertRaises(TypeError):
            self.sync._acknowledge_exact_readback(
                forged, forged_readback, inbox=self.inbox,
                cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                acknowledgement_id=forged_readback['acknowledgement_id'])
        with self.assertRaises(TypeError):
            self.sync.confirm_and_acknowledge_exact_scope(
                forged, inbox=self.inbox, cycle_id='CYC-1',
                company_id='COMP-1', plan_digest=plan['plan_digest'],
                receipt_id=receipt_id, intent_id=intent_id)
        self.assertEqual(set(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty')), before)

        acknowledged = self.sync.confirm_and_acknowledge_exact_scope(
            inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        self.assertEqual(acknowledged['acknowledged_rows'], 1)
        dirty = set(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty'))
        self.assertIn(('Companies', 2, 'Last Checked'), dirty)
        self.assertIn(('Companies', 2, 'Next Action'), dirty)

    def test_tampered_readback_or_missing_local_journal_cannot_acknowledge(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority('CYC-1', 'COMP-1', plan, exact)

        # A structurally valid fabricated readback cannot clear anything when
        # the real inbox has never confirmed a Google write/readback receipt.
        fabricated_rows = [{
            'tab': evidence['tab'], 'row_id': evidence['row_id'],
            'identity': copy.deepcopy(evidence['identity']),
            'fields': list(evidence['fields']),
            'sent': copy.deepcopy(evidence['sent']),
            'actual': {header: evidence['sent'].get(header, '')
                       for header in evidence['fields']},
        } for evidence in exact['rows']]
        fabricated_ack = _digest({
            'receipt_id': receipt_id, 'intent_id': intent_id,
            'projection_digest': exact['projection_digest'],
            'observed': fabricated_rows,
        })
        fabricated = {
            'receipt_id': receipt_id, 'intent_id': intent_id,
            'intent_projection_digest': exact['projection_digest'],
            'projection_digest': exact['projection_digest'],
            'rows': fabricated_rows, 'acknowledgement_id': fabricated_ack,
        }
        before = list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header'))
        self.assertFalse(hasattr(self.sync, 'acknowledge_exact_scope'))
        self.assertEqual(len(self.service.batches), 0)
        self.assertEqual(list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header')), before)

        delivered = self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        with self.local.transaction():
            self.local.db.execute('DELETE FROM exact_local_applications')
        with self.assertRaisesRegex(ValueError, 'durable row scope'):
            self.sync.confirm_and_acknowledge_exact_scope(
                inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)

    def test_claim_without_remote_write_cannot_forge_confirmation_or_clear_dirty(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact, intent_id='intent-zero-write')
        claim = self.inbox.claim_exact_remote_attempt(
            'CYC-1', 'COMP-1', local_plan_digest=plan['plan_digest'],
            projection_digest=exact['projection_digest'], receipt_id=receipt_id,
            intent_id=intent_id, cursor=0, count=len(exact['operations']),
            chunk_digest=exact['projection_digest'],
            timestamp='2026-11-19T00:00:02Z')
        self.assertTrue(claim['first_attempt'])
        import job_search_helper.inbox as inbox_module
        self.assertEqual(
            [name for name in dir(inbox_module) if 'confirm_exact_remote' in name], [])
        self.assertEqual(
            [name for name in dir(self.inbox) if 'confirm_exact_remote' in name], [])

        fabricated_rows = [{
            'tab': evidence['tab'], 'row_id': evidence['row_id'],
            'identity': copy.deepcopy(evidence['identity']),
            'fields': list(evidence['fields']),
            'sent': copy.deepcopy(evidence['sent']),
            'actual': {header: evidence['sent'].get(header, '')
                       for header in evidence['fields']},
        } for evidence in exact['rows']]
        fabricated_ack = _digest({
            'receipt_id': receipt_id, 'intent_id': intent_id,
            'projection_digest': exact['projection_digest'],
            'observed': fabricated_rows,
        })
        fabricated = {
            'receipt_id': receipt_id, 'intent_id': intent_id,
            'intent_projection_digest': exact['projection_digest'],
            'projection_digest': exact['projection_digest'],
            'rows': fabricated_rows, 'acknowledgement_id': fabricated_ack,
        }
        before = list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header'))
        with self.assertRaisesRegex(ValueError, 'readback'):
            self.sync.confirm_and_acknowledge_exact_scope(
                inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)
        self.assertEqual(len(self.service.batches), 0)
        self.assertEqual(list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header')), before)
        self.assertEqual(self.inbox.exact_remote_state(
            'CYC-1', 'COMP-1')['state'], 'SYNC_PENDING')

    def test_remote_confirmation_cannot_skip_durable_local_acknowledgement(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact, intent_id='intent-no-local-ack')
        self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        confirmed = self.sync.confirm_exact_scope(
            inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        before_dirty = list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header'))
        with self.assertRaisesRegex(ValueError, 'selected local evidence'):
            self.inbox.mark_exact_remote_locally_acknowledged(
                'CYC-1', 'COMP-1', local=self.local,
                local_plan_digest=plan['plan_digest'],
                projection_digest=exact['projection_digest'],
                receipt_id=receipt_id, intent_id=intent_id,
                acknowledgement_id=confirmed['acknowledgement_id'],
                timestamp='2026-11-19T00:00:03Z')
        with self.assertRaisesRegex(ValueError, 'locally acknowledged'):
            self.inbox.acknowledge('CYC-1', 'COMP-1', local=self.local)
        self.assertEqual(self.inbox.exact_remote_state(
            'CYC-1', 'COMP-1')['state'], 'SYNC_CONFIRMED')
        self.assertIsNotNone(self.inbox.get('CYC-1', 'COMP-1'))
        self.assertIsNotNone(self.inbox.plan('CYC-1', 'COMP-1'))
        self.assertEqual(list(self.local.db.execute(
            'SELECT tab,row_id,header FROM dirty ORDER BY tab,row_id,header')),
            before_dirty)
        self.assertEqual(self.local.db.execute(
            'SELECT COUNT(*) FROM exact_local_acknowledgements').fetchone()[0], 0)

    def test_final_readback_rejects_remote_row_move(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact, intent_id='intent-row-move')
        self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        original = self.remote.read_row

        def moved_row(tab, row_number):
            row = original(tab, row_number)
            return {**row, 'Company ID': 'COMP-MOVED'}

        with patch.object(self.remote, 'read_row', side_effect=moved_row):
            with self.assertRaisesRegex(ValueError, 'row moved'):
                self.sync.confirm_and_acknowledge_exact_scope(
                    inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id)
        self.assertEqual(self.inbox.receipt({
            'binding': {'request_id': 'CYC-1', 'company_id': 'COMP-1',
                        'source_revision': plan['plan_digest'], 'release_id': 'test'},
        })['state'], 'SYNC_PENDING')

    def test_binding_change_during_remote_read_cannot_confirm(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            'CYC-1', 'COMP-1', plan, exact, intent_id='intent-binding-drift')
        self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
            plan_digest=plan['plan_digest'], receipt_id=receipt_id,
            intent_id=intent_id)
        original = self.remote.read_row

        def drift_binding(tab, row_number):
            with self.inbox.lock, self.inbox.connection:
                self.inbox.connection.execute(
                    'UPDATE exact_remote_plans SET intent_id=? '
                    'WHERE cycle=? AND company=?',
                    ('intent-changed-during-read', 'CYC-1', 'COMP-1'))
            return original(tab, row_number)

        with patch.object(self.remote, 'read_row', side_effect=drift_binding):
            with self.assertRaisesRegex(ValueError, 'durable remote binding'):
                self.sync.confirm_and_acknowledge_exact_scope(
                    inbox=self.inbox, cycle_id='CYC-1',
                    company_id='COMP-1', plan_digest=plan['plan_digest'],
                    receipt_id=receipt_id, intent_id=intent_id)
        with self.inbox.lock:
            state = self.inbox.connection.execute(
                'SELECT state FROM publication_receipts WHERE receipt_id=?',
                (receipt_id,)).fetchone()[0]
        self.assertEqual(state, 'SYNC_PENDING')

    def test_manual_source_and_salary_controls_are_not_weakened(self):
        local_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19', 'Salary / Range': '$150,000',
                       'Source Hash': 'source-new'},
            'expected': {'Added to Opportunities?': 'Manual Review',
                         'Source Hash': 'source-local'},
        }
        remote_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19', 'Salary / Range': '$150,000'},
            'append_if_missing': False, 'on_insert': {},
            'expected': {'Last Checked': '', 'Salary / Range': '$130,000 estimated',
                         'Added to Opportunities?': 'Manual Review'},
            'append_notes': {},
        }
        plan = sealed_plan([local_operation], [remote_operation])
        scope = [{'tab': 'Job History', 'row_id': 1,
                  'identity': {'Job Key': 'job-1'},
                  'fields': ['Last Checked', 'Salary / Range'],
                  'append_if_missing': False,
                  'guards': {'Added to Opportunities?': 'Manual Review',
                             'Source Hash': 'source-new'},
                  'expected': {'Last Checked': '',
                               'Salary / Range': '$130,000 estimated',
                               'Added to Opportunities?': 'Manual Review'}}]
        self.apply_verified_local('CYC-SALARY', 'COMP-1', plan, scope)
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority(
            'CYC-SALARY', 'COMP-1', plan, exact, intent_id='intent-salary')
        self.assertNotIn('Source Hash', exact['operations'][0]['values'])
        self.assertEqual(self.local.read('Job History')[0]['Source Hash'], 'source-new')
        self.local.commit([{
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Source Hash': 'source-after-freeze'},
        }])
        with self.assertRaisesRegex(ValueError, 'guard changed'):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-SALARY', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)
        self.assertEqual(len(self.service.batches), 0)
        self.local.commit([{
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Source Hash': 'source-new'},
        }])
        self.service.set_cell('Job History', 1, 'Salary / Range', '$175,000 user estimate')
        with self.assertRaises(RepositoryError):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-SALARY', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id)
        self.assertEqual(self.remote.read('Job History')[0]['Salary / Range'],
                         '$175,000 user estimate')

        # A plausible estimate that remains current and was not selected is
        # absent from the exact operation and remains untouched.
        self.assertEqual(self.local.read('Job History')[0]['Salary / Range'], '$150,000')
        self.assertEqual(self.local.read('Job History')[0]['Added to Opportunities?'],
                         'Manual Review')

    def test_missing_receipt_binding_and_oversize_fail_before_remote_write(self):
        plan, scope, remote_operation = self.company_plan()
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        receipt_id, intent_id = self.remote_authority('CYC-1', 'COMP-1', plan, exact)
        with self.assertRaisesRegex(ValueError, 'receipt ID'):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id='', intent_id=intent_id)
        with self.assertRaisesRegex(ValueError, 'exceeds'):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest=plan['plan_digest'], receipt_id=receipt_id,
                intent_id=intent_id,
                max_bytes=1)
        with self.assertRaisesRegex(ValueError, 'frozen intent'):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-1', company_id='COMP-1',
                plan_digest='wrong-plan', receipt_id=receipt_id, intent_id=intent_id)
        self.assertEqual(len(self.service.batches), 0)

    def test_blank_extracted_salary_keeps_remote_estimate_as_expected_guard(self):
        empty_salary = json.dumps({
            'compensationTierSummary': None, 'compensationTiers': [],
            'scrapeableCompensationSalarySummary': None, 'summaryComponents': [],
        }, sort_keys=True)
        local_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19',
                       'Salary / Range': empty_salary},
            'expected': {'Added to Opportunities?': 'Manual Review',
                         'Source Hash': 'source-local'},
        }
        remote_operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-1'},
            'values': {'Last Checked': '2026-11-19'},
            'append_if_missing': False, 'on_insert': {},
            'expected': {'Last Checked': '',
                         'Salary / Range': '$130,000 estimated',
                         'Added to Opportunities?': 'Manual Review'},
            'append_notes': {},
        }
        plan = sealed_plan([local_operation], [remote_operation])
        scope = [{
            'tab': 'Job History', 'row_id': 1,
            'identity': {'Job Key': 'job-1'},
            'fields': ['Last Checked', 'Salary / Range'],
            'append_if_missing': False,
            'guards': {'Added to Opportunities?': 'Manual Review',
                       'Source Hash': 'source-local'},
            'expected': {'Last Checked': '',
                         'Salary / Range': '$130,000 estimated',
                         'Added to Opportunities?': 'Manual Review'},
        }]
        self.apply_verified_local('CYC-BLANK-SALARY', 'COMP-1', plan, scope)
        exact = self.sync.plan_exact_scope(scope, [remote_operation])
        self.assertEqual(exact['operations'], [remote_operation])
        self.assertEqual(exact['operations'][0]['expected']['Salary / Range'],
                         '$130,000 estimated')
        self.assertNotIn('Source Hash', exact['operations'][0]['expected'])
        self.assertNotIn('Salary / Range', exact['operations'][0]['values'])

    def test_blank_guard_mismatch_stays_pending_across_retry(self):
        self.service.set_cell('Job History', 1, 'Review Status', 'Different')
        self.service.set_cell('Job History', 1, 'Last Checked', '2026-11-19')
        plan, exact, receipt_id, intent_id = self.review_guard_plan(
            'CYC-BLANK-GUARD', '')
        with self.assertRaises(RepositoryError):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-BLANK-GUARD',
                company_id='COMP-1', plan_digest=plan['plan_digest'],
                receipt_id=receipt_id, intent_id=intent_id)
        with self.assertRaisesRegex(ValueError, 'remote guard differs'):
            self.sync.publish_exact_scope(
                exact, inbox=self.inbox, cycle_id='CYC-BLANK-GUARD',
                company_id='COMP-1', plan_digest=plan['plan_digest'],
                receipt_id=receipt_id, intent_id=intent_id)
        self.assertEqual(self.inbox.exact_remote_state(
            'CYC-BLANK-GUARD', 'COMP-1')['state'], 'SYNC_PENDING')
        self.assertEqual(self.inbox.exact_chunk(
            'CYC-BLANK-GUARD', 'COMP-1', 0)['state'], 'PENDING')

    def test_nonblank_matching_guard_can_confirm(self):
        self.service.set_cell('Job History', 1, 'Review Status', 'Human Reviewed')
        plan, exact, receipt_id, intent_id = self.review_guard_plan(
            'CYC-MATCHING-GUARD', 'Human Reviewed')
        delivered = self.sync.publish_exact_scope(
            exact, inbox=self.inbox, cycle_id='CYC-MATCHING-GUARD',
            company_id='COMP-1', plan_digest=plan['plan_digest'],
            receipt_id=receipt_id, intent_id=intent_id)
        self.assertTrue(delivered['first_attempt'])
        confirmed = self.sync.confirm_exact_scope(
            inbox=self.inbox, cycle_id='CYC-MATCHING-GUARD',
            company_id='COMP-1', plan_digest=plan['plan_digest'],
            receipt_id=receipt_id, intent_id=intent_id)
        self.assertEqual(self.inbox.exact_remote_state(
            'CYC-MATCHING-GUARD', 'COMP-1')['state'], 'SYNC_CONFIRMED')
        self.assertTrue(confirmed['rows'][0]['remote_guards'])

    def test_new_local_row_preserves_sealed_remote_insert_semantics(self):
        local_insert = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-new'},
            'values': {}, 'append_if_missing': True,
            'on_insert': {
                'Job Key': 'job-new', 'Company': 'Fixture',
                'Job Title': 'New Fixture Role',
                'Official Job URL': 'https://jobs.example.test/comp-1/new',
                'Added to Opportunities?': 'Manual Review',
                'Source Hash': 'source-new-row',
            },
            'expected': {}, 'append_notes': {},
        }
        self.local.commit([local_insert])
        remote_insert = {
            'tab': 'Job History', 'identity': {'Job Key': 'job-new'},
            'values': {}, 'append_if_missing': True,
            'on_insert': {
                'Job Key': 'job-new', 'Company': 'Fixture',
                'Job Title': 'New Fixture Role',
                'Official Job URL': 'https://jobs.example.test/comp-1/new',
                'Added to Opportunities?': 'Manual Review',
            },
            'expected': {}, 'append_notes': {},
        }
        scope = [{
            'tab': 'Job History', 'identity': {'Job Key': 'job-new'},
            'fields': sorted(remote_insert['on_insert']),
            'append_if_missing': True,
            'guards': {'Source Hash': 'source-new-row',
                       'Added to Opportunities?': 'Manual Review'},
            'expected': {},
        }]
        exact = self.sync.plan_exact_scope(scope, [remote_insert])
        self.assertEqual(exact['operations'], [remote_insert])

        forged = copy.deepcopy(scope)
        forged[0]['append_if_missing'] = False
        with self.assertRaisesRegex(ValueError, 'sealed insert semantics'):
            self.sync.plan_exact_scope(forged, [remote_insert])


if __name__ == '__main__':
    unittest.main()
