import os
import tempfile
import unittest
from pathlib import Path

from job_search_helper.exact_recovery_pause_apply import (
    COMPLETE,
    CONFIRMED,
    FROZEN,
    PauseApplyStore,
    RUN_VERSION,
    _digest,
)


class PauseApplyStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = PauseApplyStore(Path(self.temporary.name) / "pause-apply.db")
        self.addCleanup(self.store.close)
        self.cycle_id = "CYCLE"
        self.chunk_zero = {"operations": [{"company_id": "C-1"}]}
        self.chunk_two = {"operations": [
            {"company_id": "C-2"}, {"company_id": "C-3"},
        ]}
        self.state_payload = {"cycle_id": self.cycle_id, "status": "Complete with exceptions"}
        self.scan_payload = {"cycle_id": self.cycle_id, "row": {"Cycle Status": "Complete with exceptions"}}
        self.run_payload = {
            "version": RUN_VERSION,
            "cycle_id": self.cycle_id,
            "journal_digest": "journal-digest",
            "chunks": [
                {"start": 0, "count": 1, "digest": _digest(self.chunk_zero)},
                {"start": 1, "count": 2, "digest": _digest(self.chunk_two)},
            ],
            "state_finalization_digest": _digest(self.state_payload),
            "scan_cycle_finalization_digest": _digest(self.scan_payload),
        }

    def freeze(self):
        return self.store.freeze_run(self.cycle_id, self.run_payload)

    def confirm_chunk(self, start, payload, acknowledgement):
        intent = self.store.begin(self.cycle_id, "CHUNK", start, payload)
        return self.store.confirm(
            self.cycle_id, "CHUNK", start, intent["digest"], acknowledgement,
        )

    def test_run_freeze_is_secure_immutable_and_idempotent(self):
        first = self.freeze()
        second = self.freeze()
        self.assertEqual(first, second)
        self.assertEqual(first["state"], FROZEN)
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)

        changed = dict(self.run_payload, journal_digest="different")
        with self.assertRaisesRegex(ValueError, "run_changed"):
            self.store.freeze_run(self.cycle_id, changed)

    def test_run_validation_rejects_missing_duplicate_or_unordered_chunks(self):
        invalid = [
            dict(self.run_payload, chunks=[]),
            dict(self.run_payload, chunks=[
                {"start": 0, "count": 1, "digest": "a"},
                {"start": 0, "count": 1, "digest": "b"},
            ]),
            dict(self.run_payload, chunks=[
                {"start": 2, "count": 1, "digest": "a"},
                {"start": 0, "count": 1, "digest": "b"},
            ]),
            dict(self.run_payload, journal_digest=""),
        ]
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ValueError, "run_invalid"):
                    self.store.freeze_run(self.cycle_id, payload)

    def test_phase_order_requires_every_frozen_chunk_before_finalization(self):
        self.freeze()
        with self.assertRaisesRegex(ValueError, "chunks_unconfirmed"):
            self.store.begin(self.cycle_id, "STATE_FINALIZATION", 0, self.state_payload)

        first = self.confirm_chunk(0, self.chunk_zero, "chunk-0-readback")
        self.assertEqual(first["state"], CONFIRMED)
        with self.assertRaisesRegex(ValueError, "chunks_unconfirmed"):
            self.store.begin(self.cycle_id, "STATE_FINALIZATION", 0, self.state_payload)

        self.confirm_chunk(1, self.chunk_two, "chunk-1-readback")
        state = self.store.begin(
            self.cycle_id, "STATE_FINALIZATION", 0, self.state_payload,
        )
        with self.assertRaisesRegex(ValueError, "state_unconfirmed"):
            self.store.begin(
                self.cycle_id, "SCAN_CYCLE_FINALIZATION", 0, self.scan_payload,
            )
        self.store.confirm(
            self.cycle_id, "STATE_FINALIZATION", 0, state["digest"], "state-readback",
        )
        scan = self.store.begin(
            self.cycle_id, "SCAN_CYCLE_FINALIZATION", 0, self.scan_payload,
        )
        self.store.confirm(
            self.cycle_id, "SCAN_CYCLE_FINALIZATION", 0, scan["digest"], "scan-readback",
        )
        self.assertEqual(self.store.run(self.cycle_id)["state"], COMPLETE)
        with self.assertRaisesRegex(ValueError, "run_complete"):
            self.store.begin(self.cycle_id, "CHUNK", 0, self.chunk_zero)

    def test_only_predeclared_exact_intents_can_begin(self):
        self.freeze()
        with self.assertRaisesRegex(ValueError, "chunk_not_frozen"):
            self.store.begin(self.cycle_id, "CHUNK", 99, {"operations": []})
        with self.assertRaisesRegex(ValueError, "intent_not_frozen"):
            self.store.begin(self.cycle_id, "CHUNK", 0, {"operations": ["changed"]})
        with self.assertRaisesRegex(ValueError, "intent_invalid"):
            self.store.begin(self.cycle_id, "UNKNOWN", 0, {})
        with self.assertRaisesRegex(ValueError, "run_missing"):
            self.store.begin("OTHER", "CHUNK", 0, self.chunk_zero)

    def test_confirmation_is_monotonic_and_acknowledgement_bound(self):
        self.freeze()
        intent = self.store.begin(self.cycle_id, "CHUNK", 0, self.chunk_zero)
        with self.assertRaisesRegex(ValueError, "intent_missing"):
            self.store.confirm(self.cycle_id, "CHUNK", 1, "x", "ack")
        with self.assertRaisesRegex(ValueError, "digest_mismatch"):
            self.store.confirm(self.cycle_id, "CHUNK", 0, "wrong", "ack")
        with self.assertRaisesRegex(ValueError, "ack_required"):
            self.store.confirm(self.cycle_id, "CHUNK", 0, intent["digest"], " ")

        first = self.store.confirm(
            self.cycle_id, "CHUNK", 0, intent["digest"], "readback-ack",
        )
        second = self.store.confirm(
            self.cycle_id, "CHUNK", 0, intent["digest"], "readback-ack",
        )
        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, "ack_conflict"):
            self.store.confirm(
                self.cycle_id, "CHUNK", 0, intent["digest"], "different-ack",
            )

    def test_run_and_intent_corruption_are_detected(self):
        self.freeze()
        with self.store.db:
            self.store.db.execute(
                "UPDATE pause_apply_runs SET digest='bad' WHERE cycle=?",
                (self.cycle_id,),
            )
        with self.assertRaisesRegex(ValueError, "store_corrupt"):
            self.store.run(self.cycle_id)

        with self.store.db:
            self.store.db.execute(
                "UPDATE pause_apply_runs SET digest=? WHERE cycle=?",
                (_digest(self.run_payload), self.cycle_id),
            )
        intent = self.store.begin(self.cycle_id, "CHUNK", 0, self.chunk_zero)
        with self.store.db:
            self.store.db.execute(
                "UPDATE pause_apply_intents SET state='BROKEN' "
                "WHERE cycle=? AND kind='CHUNK' AND ordinal=0",
                (self.cycle_id,),
            )
        with self.assertRaisesRegex(ValueError, "store_corrupt"):
            self.store.intent(self.cycle_id, "CHUNK", 0)

    def test_complete_run_requires_the_full_confirmed_finalization_chain(self):
        self.freeze()
        with self.store.db:
            self.store.db.execute(
                "UPDATE pause_apply_runs SET state=? WHERE cycle=?",
                (COMPLETE, self.cycle_id),
            )
        with self.assertRaisesRegex(ValueError, "store_corrupt"):
            self.store.run(self.cycle_id)

    def test_scan_confirmation_rejects_a_raced_run_state_transition(self):
        self.freeze()
        self.confirm_chunk(0, self.chunk_zero, "chunk-zero")
        self.confirm_chunk(1, self.chunk_two, "chunk-one")
        state = self.store.begin(
            self.cycle_id, "STATE_FINALIZATION", 0, self.state_payload,
        )
        self.store.confirm(
            self.cycle_id, "STATE_FINALIZATION", 0, state["digest"], "state-ack",
        )
        scan = self.store.begin(
            self.cycle_id, "SCAN_CYCLE_FINALIZATION", 0, self.scan_payload,
        )
        with self.store.db:
            self.store.db.execute(
                "UPDATE pause_apply_runs SET state=? WHERE cycle=?",
                (COMPLETE, self.cycle_id),
            )
        with self.assertRaisesRegex(ValueError, "run_state_changed"):
            self.store.confirm(
                self.cycle_id, "SCAN_CYCLE_FINALIZATION", 0,
                scan["digest"], "scan-ack",
            )
        # The failed transition rolls the scan confirmation back.
        self.assertEqual(
            self.store.intent(self.cycle_id, "SCAN_CYCLE_FINALIZATION", 0)["state"],
            "INTENT",
        )

        with self.store.db:
            self.store.db.execute(
                "UPDATE pause_apply_intents SET state='CONFIRMED',acknowledgement=NULL "
                "WHERE cycle=? AND kind='CHUNK' AND ordinal=0",
                (self.cycle_id,),
            )
        with self.assertRaisesRegex(ValueError, "store_corrupt"):
            self.store.intent(self.cycle_id, "CHUNK", 0)


if __name__ == "__main__":
    unittest.main()
