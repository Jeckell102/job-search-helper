from copy import deepcopy
from types import SimpleNamespace
import unittest

from compare_confirmed_workbook import compare_confirmed_workbook
from job_search_helper.exact_cycle_planner import _seal_exact_plan_v2
from job_search_helper.publication_receipts import SYNC_CONFIRMED, record_fingerprints
from job_search_helper.repository import MemoryRepository
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS


class WorkbookReadbackTests(unittest.TestCase):
    def setUp(self):
        self.operation = {'tab': 'Job History', 'identity': {'Job Key': 'fixture'},
                          'values': {'Job Title': 'Engineer', 'Review Notes': 'History\nReviewed'}}
        self.scope = {'tab': 'Job History', 'identity': self.operation['identity'], 'row_id': 7,
                      'fields': ['Job Title', 'Review Notes'], 'guards': {'Source Hash': 'local-only'}}
        self.application = {'state': 'VERIFIED', 'row_scope': [self.scope]}
        self.baselines = {('Job History', 7): self.operation['values']}
        self.receipt = {'state': SYNC_CONFIRMED, 'acknowledgement_id': 'fixture-ack',
                        'records': record_fingerprints([self.operation])}
        self.row = {**self.operation['identity'], **self.operation['values']}

    def readback(self, rows, receipt=None):
        remote = MemoryRepository({'Job History': rows}, schemas=COMPACT_SCHEMAS)
        return compare_confirmed_workbook(remote, receipt or self.receipt,
                                          self.application, self.baselines)

    def test_exact_published_fields_match_original_fingerprint(self):
        self.assertEqual(self.readback([self.row, {'Job Key': 'other'}]), {
            'matched_rows': {'Job History': 1},
            'matched_original_fingerprints': 1,
            'rows_without_original_fingerprint': 0,
        })

    def test_changed_saved_value_or_duplicate_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'differs from'):
            self.readback([{**self.row, 'Job Title': 'Changed'}])
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.readback([self.row, self.row])

    def test_confirmed_append_note_cannot_recreate_original_fingerprint(self):
        operation = deepcopy(self.operation)
        del operation['values']['Review Notes']
        operation['append_notes'] = {'Review Notes': 'Reviewed'}
        receipt = {**self.receipt, 'records': record_fingerprints([operation])}
        self.assertEqual(self.readback([self.row], receipt), {
            'matched_rows': {'Job History': 1},
            'matched_original_fingerprints': 0,
            'rows_without_original_fingerprint': 1,
        })

    def archived_note_case(self):
        operation = deepcopy(self.operation)
        del operation['values']['Review Notes']
        operation['append_notes'] = {'Review Notes': 'Reviewed'}
        compact = SimpleNamespace(schemas=COMPACT_SCHEMAS, get_meta=lambda _: COMPACT_PROFILE)
        plan = _seal_exact_plan_v2({'operations': [operation], 'final': {}, 'requested_url': 'fixture',
                                    'control_evidence': {}, 'control_evidence_version': 1,
                                    'control_evidence_digest': 'fixture'}, {}, compact, 'cycle', 'company')
        receipt = {**self.receipt, 'records': plan['remote_records']}
        application = {**self.application, **{field: plan[field] for field in
                       ('cycle_id', 'company_id', 'plan_digest', 'remote_projection_digest')}}
        return plan, receipt, application

    def test_archived_projection_proves_appended_note(self):
        plan, receipt, application = self.archived_note_case()
        remote = MemoryRepository({'Job History': [self.row]}, schemas=COMPACT_SCHEMAS)
        result = compare_confirmed_workbook(remote, receipt, application, self.baselines, archived_plan=plan)
        self.assertEqual(result['matched_original_fingerprints'], 1)
        self.assertEqual(result['rows_without_original_fingerprint'], 0)

    def test_archived_projection_rejects_missing_note_even_when_both_rows_match(self):
        plan, receipt, application = self.archived_note_case()
        self.baselines['Job History', 7]['Review Notes'] = 'History'
        remote = MemoryRepository({'Job History': [{**self.row, 'Review Notes': 'History'}]}, schemas=COMPACT_SCHEMAS)
        with self.assertRaisesRegex(ValueError, 'appended notes'):
            compare_confirmed_workbook(remote, receipt, application, self.baselines, archived_plan=plan)

    def test_archived_projection_requires_the_original_baseline_fingerprint(self):
        plan, receipt, application = self.archived_note_case()
        self.baselines['Job History', 7] = {**self.operation['values'], 'Job Title': 'Engineer '}
        remote = MemoryRepository({'Job History': [self.row]}, schemas=COMPACT_SCHEMAS)
        with self.assertRaisesRegex(ValueError, 'Baseline or workbook'):
            compare_confirmed_workbook(remote, receipt, application, self.baselines, archived_plan=plan)

    def test_another_archive_cannot_authorize_any_remote_reads(self):
        plan, receipt, application = self.archived_note_case()
        application['plan_digest'] = 'unrelated'
        with self.assertRaisesRegex(ValueError, 'Archived plan differs'):
            compare_confirmed_workbook(None, receipt, application, self.baselines, archived_plan=plan)

    def test_mismatched_receipt_labels_are_rejected_before_remote_read(self):
        receipt = {**self.receipt, 'records': {'other': 'fingerprint'}}
        with self.assertRaisesRegex(ValueError, 'original receipt'):
            compare_confirmed_workbook(None, receipt, self.application, self.baselines)

    def test_equivalent_identity_drift_does_not_claim_original_hash(self):
        self.operation['values']['Job Key'] = 'fixture'
        self.scope['fields'].append('Job Key')
        self.receipt['records'] = record_fingerprints([self.operation])
        result = self.readback([{**self.row, 'Job Key': 'fixture '}])
        self.assertEqual(result['matched_rows'], {'Job History': 1})
        self.assertEqual(result['matched_original_fingerprints'], 0)
