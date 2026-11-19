"""Exact saved-inventory planning stays local, bounded, and recoverable."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.engine import Engine, State, inventory_payload
from job_search_helper.exact_cycle_planner import (
    _digest, _project_operations, _publication_schema,
    freeze_exact_cycle_plans,
)
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository, SCHEMAS
from job_search_helper.core import job_key
from job_search_helper.sheet_profile import COMPACT_PROFILE


def company(cid='COMP-1'):
    return {
        'Company': 'Fixture Co', 'Company ID': cid, 'Company Status': 'Active',
        'Official Careers URL': 'https://boards.example.test/fixture',
        'ATS / Source': 'Greenhouse', 'Scan State': 'Queued',
    }


def payload():
    return inventory_payload(Inventory('complete', [{
        'title': 'Implementation Manager', 'posting_id': '42',
        'url': 'https://boards.example.test/fixture/jobs/42', 'location': 'Remote',
        'description': 'Customer-facing implementation and deployment work.', 'ats': 'Greenhouse',
    }], source_url='https://boards.example.test/fixture', ats='Greenhouse'), company())


class ExactCyclePlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        schemas = copy.deepcopy(SCHEMAS)
        schemas['Opportunities'].append('Opportunity ID')
        self.repo = MemoryRepository({'Companies': [company()]}, schemas=schemas)
        self.state = State(self.root / 'state.db')
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(self.root / 'inbox.db', 'fixture')
        self.addCleanup(self.inbox.close)
        self.engine = Engine(self.repo, self.state, inbox=self.inbox, error_log_path=self.root / 'errors.jsonl')
        self.cycle = 'CYC-EXACT'
        self.state.save_cycle({'id': self.cycle, 'status': 'In Progress', 'started_at': '2026-11-19T00:00:00Z',
                               'companies': {'COMP-1': {'company': 'Fixture Co', 'stage': 'queued'}}})
        self.saved_payload = payload()
        self.inbox.save(self.cycle, 'COMP-1', self.saved_payload)
        self.guards = []

    def guard(self, cid, requested_url):
        self.guards.append((cid, requested_url))
        return {'company_id': cid, 'requested_url': requested_url,
                'official_careers_url': requested_url, 'company_status': 'Active',
                'claimed_by': '', 'claim_token': ''}

    def test_freezes_selected_payload_without_fetch_publish_or_local_commit(self):
        before = copy.deepcopy(self.repo.tables)
        self.engine.fetcher = lambda *args: self.fail('planner must not fetch')
        self.repo.commit = lambda _ops: self.fail('planner must not commit local cache')

        with patch('job_search_helper.local_pipeline.LocalPipeline.run', side_effect=AssertionError('global pipeline')), \
                patch('job_search_helper.run_sync.run_scoped_sync', side_effect=AssertionError('global sync')), \
                patch('job_search_helper.sheets_sync.SheetsSynchronizer.pull', side_effect=AssertionError('sheet pull')):
            result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard,
                                              stamp='2026-11-19T01:00:00Z')

        self.assertEqual(result['planned'], ['COMP-1'])
        self.assertEqual(result['held'], [])
        self.assertEqual(self.guards, [('COMP-1', self.saved_payload['requested_url'])])
        plan, cursor = self.inbox.plan(self.cycle, 'COMP-1')
        self.assertEqual(cursor, 0)
        self.assertTrue(plan['operations'])
        self.assertIn('Opportunity ID', self.repo.schemas['Opportunities'])
        self.assertEqual(self.repo.tables, before)
        self.assertEqual(self.inbox.get(self.cycle, 'COMP-1')[0], self.saved_payload)
        checkpoint = self.state.cycle(self.cycle)['companies']['COMP-1']
        self.assertEqual(checkpoint['stage'], 'inventory')
        self.assertTrue(checkpoint['durable_inventory'])

    def test_frozen_plan_records_remote_control_evidence(self):
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['planned'], ['COMP-1'])
        plan, _ = self.inbox.plan(self.cycle, 'COMP-1')
        self.assertEqual(plan['control_evidence']['company_id'], 'COMP-1')
        self.assertEqual(plan['control_evidence']['requested_url'], self.saved_payload['requested_url'])
        # A later publisher can compare this digest to a fresh bounded guard.
        self.assertTrue(plan['control_evidence_digest'])

    def test_manual_review_and_legacy_job_identity_guards_are_frozen(self):
        posting = self.saved_payload['jobs'][0]
        legacy = 'legacy-board-key'
        self.repo.commit([{
            'tab': 'Job History', 'identity': {'Job Key': legacy}, 'append_if_missing': True,
            'values': {'Company': 'Fixture Co', 'Job Title': posting['title'], 'Job Key': legacy,
                       'Official Job URL': posting['url'], 'Added to Opportunities?': 'Manual Review',
                       'Review Status': 'Manual Review', 'Source Hash': 'old-source'},
        }])
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['planned'], ['COMP-1'])
        plan, _ = self.inbox.plan(self.cycle, 'COMP-1')
        history = next(op for op in plan['operations'] if op['tab'] == 'Job History')
        self.assertEqual(history['expected']['Added to Opportunities?'], 'Manual Review')
        self.assertEqual(history['expected']['Review Status'], 'Manual Review')
        self.assertEqual(history['expected']['Source Hash'], 'old-source')
        self.assertEqual(history['expected']['Job Key'], legacy)
        self.assertEqual(history['values']['Job Key'], job_key('COMP-1', 'Greenhouse', '42', posting['url']))

    def test_guard_failure_and_blocked_payload_leave_no_plan_or_checkpoint_change(self):
        before = self.state.cycle(self.cycle)
        result = freeze_exact_cycle_plans(
            self.engine, self.cycle, ['COMP-1'],
            company_guard=lambda *_: (_ for _ in ()).throw(ValueError('company_paused')),
        )
        self.assertEqual(result['planned'], [])
        self.assertEqual(result['held'][0]['reason'], 'company_paused')
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))
        self.assertEqual(self.state.cycle(self.cycle), before)

        self.inbox.block(self.cycle, 'COMP-1')
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['held'][0]['reason'], 'durable_inventory_blocked')
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))

    def test_existing_plan_recovers_checkpoint_after_crash_between_databases(self):
        original = self.state.save_cycle
        calls = 0
        def crash_once(value):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError('checkpoint disk interruption')
            return original(value)
        self.state.save_cycle = crash_once
        first = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(first['planned'], [])
        self.assertEqual(first['held'][0]['reason'], 'checkpoint disk interruption')
        self.assertIsNotNone(self.inbox.plan(self.cycle, 'COMP-1'))
        self.assertEqual(self.state.cycle(self.cycle)['companies']['COMP-1']['stage'], 'queued')

        self.state.save_cycle = original
        second = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(second['recovered'], ['COMP-1'])
        self.assertEqual(self.state.cycle(self.cycle)['companies']['COMP-1']['stage'], 'inventory')

    def test_control_evidence_change_holds_existing_plan(self):
        self.assertEqual(freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)['planned'], ['COMP-1'])
        changed = lambda cid, url: {'company_id': cid, 'requested_url': url,
                                    'official_careers_url': url,
                                    'company_status': 'ACTIVE', 'claimed_by': '', 'claim_token': ''}
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=changed)
        self.assertEqual(result['held'][0]['reason'], 'company_control_evidence_changed')

    def test_invalid_existing_plan_or_payload_mismatch_is_held_without_replacement(self):
        bad = {'operations': [], 'final': {}, 'requested_url': 'https://wrong.example',
               'control_evidence': {}, 'control_evidence_digest': 'wrong'}
        self.inbox.save_plan(self.cycle, 'COMP-1', bad)
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['held'][0]['reason'], 'existing_frozen_plan_projection_incompatible')
        self.assertEqual(self.inbox.plan(self.cycle, 'COMP-1')[0], bad)

    def test_compact_empty_inventory_company_projection_keeps_only_visible_final_fields(self):
        self.repo.get_meta = lambda key: COMPACT_PROFILE if key == 'sheets_profile' else None
        profile, publication = _publication_schema(self.repo)
        operations = [{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Scan State': 'Complete', 'Active Cycle ID': self.cycle,
                       'Last Inventory Count': 0, 'Last Checked': '2026-11-19',
                       'Next Action': 'Official inventory saved'},
        }]
        projected = _project_operations(operations, publication)
        self.assertEqual(profile, COMPACT_PROFILE)
        self.assertEqual(projected, [{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Last Checked': '2026-11-19',
                       'Next Action': 'Official inventory saved'},
        }])

    def test_compact_job_history_projection_prunes_local_only_delivery(self):
        self.repo.get_meta = lambda key: COMPACT_PROFILE if key == 'sheets_profile' else None
        _, publication = _publication_schema(self.repo)
        operation = {
            'tab': 'Job History', 'identity': {'Job Key': 'comp-1:greenhouse:42'},
            'values': {'Job Title': 'Implementation Manager', 'Salary / Range': '$120k-$140k',
                       'Source Hash': 'source-a', 'Job Description': 'local evidence',
                       'Record Updated': 'local timestamp'},
            'on_insert': {'Requisition ID': '42', 'Source Hash': 'source-a'},
            'expected': {'Added to Opportunities?': 'Manual Review',
                         'Salary / Range': '$120k-$140k', 'Source Hash': 'source-old'},
        }
        projected = _project_operations([operation], publication)[0]
        self.assertEqual(projected['values'], {
            'Job Title': 'Implementation Manager', 'Salary / Range': '$120k-$140k'})
        self.assertEqual(projected['expected'], {
            'Added to Opportunities?': 'Manual Review', 'Salary / Range': '$120k-$140k'})
        self.assertEqual(projected['on_insert'], {'Requisition ID': '42'})
        self.assertNotIn('Source Hash', projected['values'])
        # The exact local evidence digest still changes when its local-only
        # source-hash guard changes, even though Google cannot accept the field.
        altered = copy.deepcopy(operation)
        altered['expected']['Source Hash'] = 'different-source'
        self.assertNotEqual(_digest([operation]), _digest([altered]))

    def test_full_profile_projection_is_operation_compatible_and_sealed(self):
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['planned'], ['COMP-1'])
        plan, _ = self.inbox.plan(self.cycle, 'COMP-1')
        self.assertEqual(plan['publication_profile'], 'full')
        self.assertEqual(plan['remote_operations_digest'], _digest(plan['operations']))
        self.assertTrue(plan['local_operations_digest'])
        self.assertTrue(plan['local_finalization_digest'])
        self.assertTrue(plan['remote_projection_digest'])

    def test_unknown_profile_holds_without_plan_or_checkpoint_mutation(self):
        self.repo.get_meta = lambda key: 'future-v9' if key == 'sheets_profile' else None
        before = self.state.cycle(self.cycle)
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertIn('Unknown Sheets publication profile', result['held'][0]['reason'])
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))
        self.assertEqual(self.state.cycle(self.cycle), before)

    def test_compact_identity_removal_and_empty_operation_fail_closed(self):
        self.repo.get_meta = lambda key: COMPACT_PROFILE if key == 'sheets_profile' else None
        _, publication = _publication_schema(self.repo)
        with self.assertRaisesRegex(ValueError, 'remove_identity'):
            _project_operations([{
                'tab': 'Job History', 'identity': {'Source Hash': 'local-only'},
                'values': {'Job Title': 'Role'},
            }], publication)
        with self.assertRaisesRegex(ValueError, 'operation_empty'):
            _project_operations([{
                'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                'values': {'Scan State': 'Complete'},
            }], publication)
        with self.assertRaisesRegex(ValueError, 'unknown_tab'):
            _project_operations([{
                'tab': 'Untrusted Tab', 'identity': {'Company ID': 'COMP-1'},
                'values': {'Company ID': 'COMP-1'},
            }], publication)

    def test_projection_and_schema_digests_are_deterministic(self):
        self.repo.get_meta = lambda key: COMPACT_PROFILE if key == 'sheets_profile' else None
        _, publication = _publication_schema(self.repo)
        operations = [{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
            'values': {'Last Checked': '2026-11-19', 'Scan State': 'Complete'},
        }]
        first = _project_operations(copy.deepcopy(operations), publication)
        second = _project_operations(copy.deepcopy(operations), publication)
        self.assertEqual(first, second)
        self.assertEqual(_digest(first), _digest(second))
        schema_a = {tab: list(headers) for tab, headers in sorted(publication.items())}
        schema_b = {tab: list(publication[tab]) for tab in reversed(list(publication))}
        self.assertEqual(_digest(schema_a), _digest(schema_b))

    def test_compact_new_plan_requires_dual_durable_local_remote_journal(self):
        self.repo.get_meta = lambda key: COMPACT_PROFILE if key == 'sheets_profile' else None
        before = self.state.cycle(self.cycle)
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['held'], [{
            'company_id': 'COMP-1',
            'reason': 'compact_exact_plan_requires_durable_local_commit_journal',
        }])
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))
        self.assertEqual(self.state.cycle(self.cycle), before)

    def test_nonzero_cursor_legacy_plan_holds_without_mutation(self):
        legacy = {'operations': [{'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                                  'values': {'Last Checked': '2026-11-19'}}],
                  'final': {'stage': 'complete'}, 'requested_url': self.saved_payload['requested_url']}
        self.inbox.save_plan(self.cycle, 'COMP-1', legacy)
        self.inbox.advance(self.cycle, {'COMP-1': 1}, expected={'COMP-1': 0})
        before_cycle = self.state.cycle(self.cycle)
        before_plan = self.inbox.plan(self.cycle, 'COMP-1')
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['held'], [{
            'company_id': 'COMP-1',
            'reason': 'existing_frozen_plan_projection_incompatible_nonzero_cursor',
        }])
        self.assertEqual(self.inbox.plan(self.cycle, 'COMP-1'), before_plan)
        self.assertEqual(self.state.cycle(self.cycle), before_cycle)

    def test_same_url_plan_without_exact_receipt_or_with_altered_payload_holds_queued(self):
        self.assertEqual(freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)['planned'], ['COMP-1'])
        queued = self.state.cycle(self.cycle)
        queued['companies']['COMP-1']['stage'] = 'queued'
        self.state.save_cycle(queued)
        with self.inbox.connection:
            self.inbox.connection.execute('DELETE FROM publication_receipts')
        missing = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(missing['held'][0]['reason'], 'existing_frozen_plan_receipt_missing')
        self.assertEqual(self.state.cycle(self.cycle)['companies']['COMP-1']['stage'], 'queued')

        # A receipt for the same records but a different immutable binding is
        # not evidence for this plan/checkpoint split.
        plan, _ = self.inbox.plan(self.cycle, 'COMP-1')
        wrong = __import__('job_search_helper.exact_cycle_planner', fromlist=['_receipt'])._receipt(
            self.state.cycle(self.cycle), 'COMP-1', self.saved_payload, plan, 'fixture')
        wrong['binding']['request_id'] = 'other-request'
        self.inbox.ensure_receipt(wrong)
        mismatched = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(mismatched['held'][0]['reason'], 'existing_frozen_plan_receipt_mismatch')

        # A syntactically valid plan is still bound to its exact saved payload.
        receipt = __import__('job_search_helper.exact_cycle_planner', fromlist=['_receipt'])._receipt(
            self.state.cycle(self.cycle), 'COMP-1', self.saved_payload, plan, 'fixture')
        self.inbox.ensure_receipt(receipt)
        altered = copy.deepcopy(self.saved_payload); altered['reason'] = 'altered after freeze'
        with self.inbox.connection:
            self.inbox.connection.execute('UPDATE inventories SET payload=? WHERE cycle=? AND company=?',
                                        (json.dumps(altered), self.cycle, 'COMP-1'))
        changed = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(changed['held'][0]['reason'], 'existing_frozen_plan_invalid')
        self.assertEqual(self.state.cycle(self.cycle)['companies']['COMP-1']['stage'], 'queued')

    def test_rejects_unbounded_or_invalid_scope_without_mutation(self):
        before = self.state.cycle(self.cycle)
        with self.assertRaises(ValueError):
            freeze_exact_cycle_plans(self.engine, self.cycle, [], company_guard=self.guard)
        with self.assertRaises(ValueError):
            freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1', 'COMP-1'], company_guard=self.guard)
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-MISSING'], company_guard=self.guard)
        self.assertEqual(result['held'][0]['reason'], 'company_not_in_exact_cycle')
        self.assertEqual(self.state.cycle(self.cycle), before)
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))

    def test_local_hold_and_unplannable_payload_are_preserved(self):
        self.repo.commit([{'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                           'values': {'Company Status': 'Paused'}}])
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['held'][0]['reason'], 'local_company_paused')
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))

        self.repo.commit([{'tab': 'Companies', 'identity': {'Company ID': 'COMP-1'},
                           'values': {'Company Status': 'Active'}}])
        self.inbox.acknowledge(self.cycle, 'COMP-1')
        failed = payload(); failed['inventory_status'] = 'failed'
        self.inbox.save(self.cycle, 'COMP-1', failed)
        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        self.assertEqual(result['held'][0]['reason'], 'inventory_status_not_plannable')
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))

    def test_planning_exception_leaves_payload_and_checkpoint_unmodified(self):
        self.inbox.acknowledge(self.cycle, 'COMP-1')
        malformed = copy.deepcopy(self.saved_payload)
        malformed['jobs'] = [{'title': 'Implementation Manager'}]
        self.inbox.save(self.cycle, 'COMP-1', malformed)
        before = self.state.cycle(self.cycle)

        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)

        self.assertEqual(result['planned'], [])
        self.assertTrue(result['held'][0]['reason'])
        self.assertIsNone(self.inbox.plan(self.cycle, 'COMP-1'))
        self.assertEqual(self.inbox.get(self.cycle, 'COMP-1')[0], malformed)
        self.assertEqual(self.state.cycle(self.cycle), before)

    def test_partial_payload_freezes_partial_final_without_touching_another_cycle(self):
        self.state.save_cycle({'id': 'CYC-OTHER', 'status': 'In Progress',
                               'companies': {'COMP-OTHER': {'company': 'Other', 'stage': 'queued'}}})
        other = copy.deepcopy(self.saved_payload)
        self.inbox.save('CYC-OTHER', 'COMP-OTHER', other)
        before_other = self.state.cycle('CYC-OTHER')
        partial = copy.deepcopy(self.saved_payload)
        partial['inventory_status'] = 'partial'
        self.inbox.acknowledge(self.cycle, 'COMP-1')
        self.inbox.save(self.cycle, 'COMP-1', partial)

        result = freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)

        self.assertEqual(result['planned'], ['COMP-1'])
        plan, _ = self.inbox.plan(self.cycle, 'COMP-1')
        self.assertEqual(plan['final']['stage'], 'partial')
        self.assertEqual(self.state.cycle('CYC-OTHER'), before_other)
        self.assertEqual(self.inbox.get('CYC-OTHER', 'COMP-OTHER')[0], other)
        self.assertIsNone(self.inbox.plan('CYC-OTHER', 'COMP-OTHER'))

    def test_completed_and_superseded_cycles_are_refused_before_guard(self):
        cycle = self.state.cycle(self.cycle); cycle['status'] = 'Complete'; self.state.save_cycle(cycle)
        with self.assertRaises(ValueError):
            freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
        cycle['status'] = 'In Progress'; self.state.save_cycle(cycle)
        self.state.save_cycle({'id': 'CYC-NEW', 'status': 'In Progress', 'Notes':
                               '{"supersedes":["CYC-EXACT"]}', 'companies': {}})
        with self.assertRaises(ValueError):
            freeze_exact_cycle_plans(self.engine, self.cycle, ['COMP-1'], company_guard=self.guard)
