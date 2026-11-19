import copy
import os
import tempfile
import unittest
from pathlib import Path

from job_search_helper.engine import State
from job_search_helper.exact_recovery_pause import (
    PauseJournalStore,
    freeze_exact_pause_journal,
    revalidate_pause_journal,
)
from job_search_helper.exact_recovery_terminal import (
    qualify_terminal_holds,
    revalidate_terminal_manifest,
)
from job_search_helper.inbox import InventoryInbox


class PauseJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = State(self.root / "state.db")
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(self.root / "inbox.db", "fixture")
        self.addCleanup(self.inbox.close)
        self.store = PauseJournalStore(self.root / "pause.db")
        self.addCleanup(self.store.close)
        self.cycle_id = "CYCLE"
        self.state.save_cycle({
            "id": self.cycle_id,
            "status": "In Progress",
            "source_revision": "source-1",
            "companies": {
                "HOLD": {"stage": "blocked"},
                "QUEUED": {"stage": "queued"},
                "INVENTORY": {"stage": "inventory"},
            },
        })
        self.inbox.save(self.cycle_id, "HOLD", {"jobs": [], "marker": "hold"})
        self.inbox.block(self.cycle_id, "HOLD")
        report = qualify_terminal_holds(
            self.state, self.inbox, self.cycle_id, ["HOLD"],
        )
        self.manifests = report["qualified"]
        self.assertEqual(report["held"], [])
        self.next_scan = self.root / "next-scan.json"
        self.next_scan.write_bytes(b"keep-request-bytes")

    def revalidator(self, manifest):
        return revalidate_terminal_manifest(self.state, self.inbox, manifest)

    def freeze(self, **overrides):
        arguments = {
            "state": self.state,
            "inbox": self.inbox,
            "store": self.store,
            "cycle_id": self.cycle_id,
            "manifests": self.manifests,
            "manifest_revalidator": self.revalidator,
            "reason": "operator recovery boundary",
            "timestamp": "2026-11-19T12:00:00Z",
            "next_scan_path": self.next_scan,
        }
        arguments.update(overrides)
        return freeze_exact_pause_journal(**arguments)

    def revalidate(self, **overrides):
        arguments = {
            "state": self.state,
            "inbox": self.inbox,
            "store": self.store,
            "cycle_id": self.cycle_id,
            "manifests": self.manifests,
            "manifest_revalidator": self.revalidator,
            "next_scan_path": self.next_scan,
        }
        arguments.update(overrides)
        return revalidate_pause_journal(**arguments)

    def test_freeze_is_immutable_idempotent_ordered_and_preserves_request(self):
        before = self.next_scan.read_bytes()
        first = self.freeze()
        second = self.freeze()

        self.assertEqual(first, second)
        self.assertEqual(first["candidate_ids"], ["QUEUED", "INVENTORY"])
        self.assertEqual(first["candidate_pre_stages"], {
            "QUEUED": "queued", "INVENTORY": "inventory",
        })
        self.assertEqual(self.next_scan.read_bytes(), before)
        self.assertEqual(os.stat(self.store.path).st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(ValueError, "journal_changed"):
            self.freeze(reason="different recovery boundary")

    def test_rejects_invalid_reason_timestamp_cycle_and_revalidator(self):
        for reason in ("", "   ", "x" * 257):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, "reason_invalid"):
                    self.freeze(reason=reason)
        with self.assertRaisesRegex(ValueError, "timestamp_invalid"):
            self.freeze(timestamp=" ")
        with self.assertRaisesRegex(ValueError, "cycle_id_required"):
            self.freeze(cycle_id=" CYCLE ")
        with self.assertRaisesRegex(ValueError, "revalidator_required"):
            self.freeze(manifest_revalidator=None)

    def test_rejects_fabricated_duplicate_wrong_or_stale_terminal_manifests(self):
        fabricated = copy.deepcopy(self.manifests)
        fabricated[0]["manifest_digest"] = "fabricated"
        with self.assertRaisesRegex(ValueError, "manifest_invalid"):
            self.freeze(manifests=fabricated)

        with self.assertRaisesRegex(ValueError, "coverage_invalid"):
            self.freeze(manifests=self.manifests + self.manifests)

        wrong = copy.deepcopy(self.manifests)
        wrong[0]["cycle_id"] = "OTHER"
        with self.assertRaisesRegex(ValueError, "manifest_invalid"):
            self.freeze(manifests=wrong)

        def changed(_manifest):
            fresh = copy.deepcopy(self.manifests[0])
            fresh["manifest_digest"] = "different"
            return fresh

        with self.assertRaises(ValueError):
            self.freeze(manifest_revalidator=changed)

    def test_rejects_residual_saved_work_missing_coverage_and_no_candidates(self):
        self.inbox.save(self.cycle_id, "QUEUED", {"jobs": []})
        with self.assertRaisesRegex(ValueError, "unblocked_saved_work_remains"):
            self.freeze()
        self.inbox.acknowledge(self.cycle_id, "QUEUED")

        with self.assertRaisesRegex(ValueError, "coverage_incomplete"):
            self.freeze(manifests=[])

        cycle = self.state.cycle(self.cycle_id)
        cycle["companies"]["QUEUED"]["stage"] = "complete"
        cycle["companies"]["INVENTORY"]["stage"] = "partial"
        self.state.save_cycle(cycle)
        with self.assertRaisesRegex(ValueError, "no_candidates"):
            self.freeze()

    def test_revalidation_is_read_only_and_detects_request_and_cycle_drift(self):
        journal = self.freeze()
        row_before = self.store.db.execute(
            "SELECT payload,digest FROM exact_recovery_pause_journals"
        ).fetchall()
        mtime_before = self.store.path.stat().st_mtime_ns
        self.assertEqual(self.revalidate()["journal_digest"], journal["journal_digest"])
        self.assertEqual(self.store.db.execute(
            "SELECT payload,digest FROM exact_recovery_pause_journals"
        ).fetchall(), row_before)
        self.assertEqual(self.store.path.stat().st_mtime_ns, mtime_before)

        self.next_scan.write_bytes(b"changed-request")
        with self.assertRaisesRegex(ValueError, "changed_before_apply"):
            self.revalidate()
        self.next_scan.write_bytes(b"keep-request-bytes")

        cycle = self.state.cycle(self.cycle_id)
        cycle["new_top_level_control"] = "changed"
        self.state.save_cycle(cycle)
        with self.assertRaisesRegex(ValueError, "changed_before_apply"):
            self.revalidate()

    def test_revalidation_detects_new_inbox_work_and_manifest_drift(self):
        self.freeze()
        self.inbox.save(self.cycle_id, "QUEUED", {"jobs": []})
        with self.assertRaisesRegex(ValueError, "unblocked_saved_work_remains"):
            self.revalidate()
        self.inbox.acknowledge(self.cycle_id, "QUEUED")

        changed = copy.deepcopy(self.manifests)
        changed[0]["inventory_digest"] = "changed"
        with self.assertRaisesRegex(ValueError, "manifest_invalid"):
            self.revalidate(manifests=changed)

    def test_store_detects_payload_and_digest_corruption(self):
        self.freeze()
        with self.store.db:
            self.store.db.execute(
                "UPDATE exact_recovery_pause_journals SET digest='bad' WHERE cycle=?",
                (self.cycle_id,),
            )
        with self.assertRaisesRegex(ValueError, "journal_corrupt"):
            self.store.read(self.cycle_id)

        with self.store.db:
            self.store.db.execute(
                "UPDATE exact_recovery_pause_journals SET payload='not-json' WHERE cycle=?",
                (self.cycle_id,),
            )
        with self.assertRaisesRegex(ValueError, "journal_corrupt"):
            self.store.read(self.cycle_id)


if __name__ == "__main__":
    unittest.main()
