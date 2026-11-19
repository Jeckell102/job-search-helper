import sqlite3
import unittest

from job_search_helper.publication_receipts import (
    LOCAL_COMMITTED, SYNC_CONFIRMED, SYNC_PENDING, initialize, local_committed,
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


if __name__ == "__main__":
    unittest.main()
