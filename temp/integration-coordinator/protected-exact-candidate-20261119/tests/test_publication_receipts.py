import sqlite3
import unittest

from job_search_helper.publication_receipts import (
    LOCAL_COMMITTED, SYNC_CONFIRMED, SYNC_PENDING, discard_preflight_rejected, initialize, local_committed,
    mark_sync_pending, reconcile_sync, receipt,
)


class PublicationReceiptTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        initialize(self.db)
        self.binding = {"request_id": "REQ-1", "company_id": "COMP-1",
                        "source_revision": "source-sha", "release_id": "release-sha"}
        self.records = {"job:one": "record-sha-1", "job:two": "record-sha-2"}
        self.schedule = {"boundary": "after_cycle", "blocking_cycle_id": "CYC-9",
                         "enqueued_at": "2026-11-18T18:00:00Z"}

    def test_exact_three_state_lifecycle_is_bound_to_request_company_source_release_and_records(self):
        local_committed(self.db, self.binding, self.records, self.schedule, timestamp="t1")
        saved = receipt(self.db, self.binding)
        self.assertEqual(saved["state"], LOCAL_COMMITTED)
        self.assertEqual(saved["binding"], self.binding)
        self.assertEqual(saved["records"], self.records)
        self.assertEqual(saved["schedule"], self.schedule)
        mark_sync_pending(self.db, self.binding, timestamp="t2")
        self.assertEqual(receipt(self.db, self.binding)["state"], SYNC_PENDING)
        self.assertTrue(reconcile_sync(self.db, self.binding, self.records, "sheet-write-1", timestamp="t3"))
        self.assertEqual(receipt(self.db, self.binding)["state"], SYNC_CONFIRMED)

    def test_lost_acknowledgement_stays_pending_for_reconciliation_without_refetch_or_overwrite(self):
        local_committed(self.db, self.binding, self.records, self.schedule, timestamp="t1")
        mark_sync_pending(self.db, self.binding, timestamp="t2")
        self.assertFalse(reconcile_sync(self.db, self.binding, {"job:one": "changed"}, "lost", timestamp="t3"))
        saved = receipt(self.db, self.binding)
        self.assertEqual(saved["state"], SYNC_PENDING)
        self.assertEqual(saved["records"], self.records)
        self.assertIsNone(saved["acknowledgement_id"])

    def test_receipt_is_idempotent_but_rejects_changed_records_or_unsafely_hidden_queue(self):
        local_committed(self.db, self.binding, self.records, self.schedule, timestamp="t1")
        local_committed(self.db, self.binding, self.records, self.schedule, timestamp="t2")
        with self.assertRaisesRegex(ValueError, "different records"):
            local_committed(self.db, self.binding, {"job:one": "replacement"}, self.schedule, timestamp="t3")
        with self.assertRaisesRegex(ValueError, "blocking_cycle_id"):
            local_committed(self.db, {**self.binding, "request_id": "REQ-2"}, self.records,
                            {"boundary": "after_cycle", "enqueued_at": "t"}, timestamp="t")

    def test_confirmed_receipt_cannot_be_moved_back_to_pending(self):
        local_committed(self.db, self.binding, self.records, self.schedule, timestamp="t1")
        mark_sync_pending(self.db, self.binding, timestamp="t2")
        reconcile_sync(self.db, self.binding, self.records, "sheet-write-1", timestamp="t3")
        with self.assertRaisesRegex(ValueError, "confirmed receipt"):
            mark_sync_pending(self.db, self.binding, timestamp="t4")

    def test_typed_preflight_rejection_can_replace_only_an_unstarted_exact_plan(self):
        local_committed(self.db, self.binding, self.records, self.schedule, timestamp="t1")
        mark_sync_pending(self.db, self.binding, timestamp="t2")
        with self.assertRaisesRegex(ValueError, "partial publication"):
            discard_preflight_rejected(self.db, self.binding, self.records, cursor=1)
        self.assertIsNotNone(receipt(self.db, self.binding))
        discard_preflight_rejected(self.db, self.binding, self.records, cursor=0)
        self.assertIsNone(receipt(self.db, self.binding))

    def test_public_reconcile_cannot_confirm_an_enrolled_exact_receipt(self):
        receipt_id = local_committed(
            self.db, self.binding, self.records, self.schedule, timestamp="t1")
        mark_sync_pending(self.db, self.binding, timestamp="t2")
        self.db.execute('CREATE TABLE exact_remote_plans(receipt_id TEXT NOT NULL)')
        self.db.execute('INSERT INTO exact_remote_plans VALUES (?)', (receipt_id,))
        with self.assertRaisesRegex(ValueError, 'trusted Sheets confirmation'):
            reconcile_sync(
                self.db, self.binding, self.records, 'forged', timestamp='t3')
        self.assertEqual(receipt(self.db, self.binding)['state'], SYNC_PENDING)


if __name__ == "__main__":
    unittest.main()
