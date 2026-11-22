from copy import deepcopy
import unittest

from compare_confirmed_workbook import compare_confirmed_workbook
from job_search_helper.publication_receipts import SYNC_CONFIRMED, record_fingerprints
from job_search_helper.repository import MemoryRepository
from job_search_helper.sheet_profile import COMPACT_SCHEMAS


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
