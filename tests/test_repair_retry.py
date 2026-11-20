from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.company_events import source_revision
from job_search_helper.ats import Inventory
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA,
    RELEASE_BINDING_SCHEMA,
    RepairRetryBridge,
    retry_attempt_id,
    retry_request,
)
from job_search_helper.integration_release import JOURNAL_SCHEMA
from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.repository import MemoryRepository
from job_search_helper.scan_request import _read_request, request_fingerprint
from test_fetch_pool import company


ACTIVATED = "2026-11-19T12:00:00Z"


def release(release_id="REL-1"):
    return {
        "schema": RELEASE_BINDING_SCHEMA,
        "release_id": release_id,
        "source_manifest_sha256": "1" * 64,
        "dependency_manifest_sha256": "2" * 64,
        "config_sha256": "3" * 64,
    }


def binding(company_id="C-1", revision="rev-1", release_id="REL-1"):
    value = {
        "schema": REPAIR_RETRY_SCHEMA,
        "failed_request_id": "failed-request-1",
        "company_id": company_id,
        "source_revision": revision,
        "release": release(release_id),
        "activated_at": ACTIVATED,
    }
    value["attempt_id"] = retry_attempt_id(value)
    return value


class RepairRetryBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "state.db"
        self.revisions = {"C-1": "rev-1"}
        self.bridge = RepairRetryBridge(
            self.database,
            current_source_revision=lambda company_id: self.revisions.get(company_id),
            now=lambda: datetime(2026, 11, 19, 12, 1, tzinfo=timezone.utc),
        )

    def activate(self, value):
        (self.root / "integration-release-journal.json").write_text(json.dumps({
            "schema": JOURNAL_SCHEMA,
            "state": "COMPLETE",
            "release_id": value["release"]["release_id"],
            "release": value["release"],
        }))

    def test_release_intent_is_durable_before_company_only_request(self):
        value = binding()
        self.activate(value)
        result = self.bridge.deliver(value)
        self.assertEqual(result["state"], "REQUEST_WRITTEN")
        request = json.loads((self.root / "next-scan.json").read_text())
        self.assertEqual(request["company_ids"], ["C-1"])
        self.assertEqual(request["request_id"], "company-retry:" + value["attempt_id"])
        self.assertEqual(request["enqueued_at"], ACTIVATED)
        self.assertEqual(request["repair_retry"]["release"], release())
        self.assertEqual(self.bridge.pending_intents(), [value])

    def test_crash_after_intent_recreates_identical_request(self):
        value = binding()
        self.activate(value)
        intent = self.bridge.intent_directory / (value["attempt_id"] + ".json")
        self.bridge._write_atomic_json(intent, value)
        first = self.bridge.deliver(value)
        saved = (self.root / "next-scan.json").read_bytes()
        second = self.bridge.deliver(value)
        self.assertEqual(first["state"], "REQUEST_WRITTEN")
        self.assertEqual(second["state"], "REQUEST_ALREADY_DURABLE")
        self.assertEqual((self.root / "next-scan.json").read_bytes(), saved)
        receipt = json.loads((self.bridge.receipt_directory / (value["attempt_id"] + ".json")).read_text())
        self.assertEqual([item["state"] for item in receipt["history"]],
                         ["REQUEST_WRITTEN", "REQUEST_ALREADY_DURABLE"])

    def test_other_pending_scan_is_never_overwritten(self):
        pending = {"mode": "company-only", "request_id": "other"}
        (self.root / "next-scan.json").write_text(json.dumps(pending))
        value = binding()
        self.activate(value)
        result = self.bridge.deliver(value)
        self.assertEqual(result["state"], "WAITING_SAFE_REQUEST_BOUNDARY")
        self.assertEqual(json.loads((self.root / "next-scan.json").read_text()), pending)
        self.assertEqual(len(self.bridge.pending_intents()), 1)

    def test_stale_company_revision_never_creates_retry_intent_or_request(self):
        self.revisions["C-1"] = "rev-new"
        result = self.bridge.deliver(binding())
        self.assertEqual(result["state"], "STALE_COMPANY_REVISION")
        self.assertEqual(self.bridge.pending_intents(), [])
        self.assertFalse((self.root / "next-scan.json").exists())

    def test_inactive_or_replaced_release_cannot_create_intent_or_request(self):
        value = binding()
        self.activate(value)
        journal = self.root / "integration-release-journal.json"
        for state, active_release in (("ROLLED_BACK", value["release"]),
                                      ("COMPLETE", release("REL-replaced"))):
            with self.subTest(state=state, release=active_release["release_id"]):
                journal.write_text(json.dumps({
                    "schema": JOURNAL_SCHEMA, "state": state,
                    "release_id": active_release["release_id"],
                    "release": active_release,
                }))
                with self.assertRaisesRegex(ValueError, "active COMPLETE release"):
                    self.bridge.deliver(value)
                self.assertEqual(self.bridge.pending_intents(), [])
                self.assertFalse((self.root / "next-scan.json").exists())

    def test_scraper_lock_contention_preserves_no_partial_intent_or_request(self):
        value = binding()
        self.activate(value)
        with writer_lock(self.root / scraper_lock_name()):
            with self.assertRaises(WriterLockBusy):
                self.bridge.deliver(value)
        self.assertEqual(self.bridge.pending_intents(), [])
        self.assertFalse((self.root / "next-scan.json").exists())

    def test_attempt_identity_changes_with_every_release_component(self):
        original = binding()
        for field in ("source_manifest_sha256", "dependency_manifest_sha256", "config_sha256"):
            changed = binding()
            changed["release"][field] = "f" * 64
            changed["attempt_id"] = retry_attempt_id(changed)
            with self.subTest(field=field):
                self.assertNotEqual(changed["attempt_id"], original["attempt_id"])


class RepairRetryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "state.db"
        self.state = State(self.database)
        self.addCleanup(self.state.close)
        self.company = company(1)
        self.revision = source_revision(self.company)
        self.repo = MemoryRepository({"Companies": [self.company]})
        self.inbox = InventoryInbox(self.root / "inbox.db", "fixture")
        self.addCleanup(self.inbox.close)
        self.engine = Engine(self.repo, self.state, inbox=self.inbox,
                             error_log_path=self.root / "errors.jsonl")

    def request(self, revision=None):
        value = binding(company_id="C-1", revision=revision or self.revision)
        return retry_request(value, enqueued_at=ACTIVATED)

    def activate(self, request, *, state="COMPLETE", release=None):
        """Write only the durable activation fact required by intake admission."""
        release = release if release is not None else request["repair_retry"]["release"]
        (self.root / "integration-release-journal.json").write_text(json.dumps({
            "schema": JOURNAL_SCHEMA,
            "state": state,
            "release_id": release["release_id"],
            "release": release,
        }))

    def admitted_cycle(self):
        from job_search_helper.runner import select_start_cycle
        request = self.request()
        self.activate(request)
        (self.root / "next-scan.json").write_text(json.dumps(request))
        return select_start_cycle(self.engine, self.state, self.repo, self.database), request

    def test_normal_admission_carries_full_release_pin_into_recoverable_cycle(self):
        from job_search_helper.runner import select_start_cycle
        request = self.request()
        self.activate(request)
        (self.root / "next-scan.json").write_text(json.dumps(request))
        cycle_id = select_start_cycle(self.engine, self.state, self.repo, self.database)
        cycle = self.state.cycle(cycle_id)
        self.assertEqual(cycle["repair_retry"], request["repair_retry"])
        recovered_state = State(self.root / "recovered.db")
        self.addCleanup(recovered_state.close)
        recovered_engine = Engine(self.repo, recovered_state, inbox=self.inbox,
                                  error_log_path=self.root / "recovered-errors.jsonl")
        recovered = recovered_engine._recover(cycle_id)
        self.assertEqual(recovered["repair_retry"], request["repair_retry"])

    def test_stale_retry_is_rejected_before_cycle_or_request_consumption(self):
        from job_search_helper.runner import select_start_cycle
        request = self.request(revision="stale-revision")
        self.activate(request)
        path = self.root / "next-scan.json"
        path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, "source revision is stale"):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertTrue(path.exists())
        self.assertEqual(self.state.cycles(), [])

    def test_missing_active_release_holds_request_and_saved_inventory(self):
        from job_search_helper.runner import select_start_cycle
        request = self.request()
        path = self.root / "next-scan.json"
        path.write_text(json.dumps(request))
        self.inbox.save("CYC-SAVED", "C-1", {"jobs": [], "cursor": "preserve"})
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "active COMPLETE release"):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.state.cycles(), [])
        self.assertEqual(self.inbox.get("CYC-SAVED", "C-1")[0]["cursor"], "preserve")

    def test_release_mismatch_holds_request_without_cycle_consumption(self):
        from job_search_helper.runner import select_start_cycle
        request = self.request()
        self.activate(request, release=release("REL-other"))
        path = self.root / "next-scan.json"
        path.write_text(json.dumps(request))
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "active COMPLETE release"):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.state.cycles(), [])

    def test_nonterminal_and_rolled_back_release_hold_request_without_cycle_consumption(self):
        from job_search_helper.runner import select_start_cycle
        for state in ("INSTALLING", "ROLLED_BACK"):
            with self.subTest(state=state):
                request = self.request()
                self.activate(request, state=state)
                path = self.root / "next-scan.json"
                path.write_text(json.dumps(request))
                before = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "active COMPLETE release"):
                    select_start_cycle(self.engine, self.state, self.repo, self.database)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(self.state.cycles(), [])

    def test_request_parser_rejects_release_or_attempt_mutation(self):
        request = self.request()
        path = self.root / "request.json"
        path.write_text(json.dumps(request))
        parsed, companies = _read_request(path)
        original = request_fingerprint(parsed, companies)
        for field in ("source_manifest_sha256", "dependency_manifest_sha256", "config_sha256"):
            changed = json.loads(json.dumps(request))
            changed["repair_retry"]["release"][field] = "f" * 64
            path.write_text(json.dumps(changed))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "attempt ID"):
                _read_request(path)
        self.assertEqual(request_fingerprint(parsed, companies), original)

    def test_request_parser_rejects_ambiguous_event_and_retry_provenance(self):
        request = self.request()
        request["company_event"] = {
            "schema": "company-event-scan-request-v1", "event_id": "CEV-1",
            "company_id": "C-1", "revision": 1,
            "source_revision": self.revision,
        }
        path = self.root / "request.json"
        path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            _read_request(path)

    def test_local_retry_resume_revalidates_every_inactive_release_state_before_fetch_or_write(self):
        cycle_id, request = self.admitted_cycle()
        self.inbox.save(cycle_id, "C-1", {"jobs": [], "cursor": "preserve"})
        before_cycle = self.state.cycle(cycle_id)
        before_inbox = self.inbox.get(cycle_id, "C-1")
        before_remote = self.repo.tables
        calls = []
        self.engine.fetcher = lambda *args: calls.append(args) or Inventory("complete")
        for name, release_state, active_release in (
                ("missing", None, None),
                ("mismatch", "COMPLETE", release("REL-other")),
                ("non-complete", "INSTALLING", None),
                ("rolled-back", "ROLLED_BACK", None)):
            with self.subTest(name=name):
                if release_state is None:
                    (self.root / "integration-release-journal.json").unlink()
                else:
                    self.activate(request, state=release_state, release=active_release)
                with self.assertRaisesRegex(ValueError, "active COMPLETE release"):
                    self.engine.resume_local(cycle_id)
                self.assertEqual(calls, [])
                self.assertEqual(self.state.cycle(cycle_id), before_cycle)
                self.assertEqual(self.inbox.get(cycle_id, "C-1"), before_inbox)
                self.assertEqual(self.repo.tables, before_remote)

    def test_remote_reconstruction_revalidates_every_inactive_release_state_before_local_rebuild(self):
        cycle_id, request = self.admitted_cycle()
        self.inbox.save(cycle_id, "C-1", {"jobs": [], "cursor": "preserve"})
        before_remote = self.repo.tables
        before_inbox = self.inbox.get(cycle_id, "C-1")
        for name, release_state, active_release in (
                ("missing", None, None),
                ("mismatch", "COMPLETE", release("REL-other")),
                ("non-complete", "INSTALLING", None),
                ("rolled-back", "ROLLED_BACK", None)):
            with self.subTest(name=name):
                if release_state is None:
                    (self.root / "integration-release-journal.json").unlink()
                else:
                    self.activate(request, state=release_state, release=active_release)
                recovered_state = State(self.root / f"remote-recovered-{name}.db")
                self.addCleanup(recovered_state.close)
                calls = []
                recovered = Engine(self.repo, recovered_state, inbox=self.inbox,
                                   fetcher=lambda *args: calls.append(args) or Inventory("complete"),
                                   error_log_path=self.root / "remote-recovery-errors.jsonl")
                with self.assertRaisesRegex(ValueError, "active COMPLETE release"):
                    recovered._recover(cycle_id)
                self.assertEqual(calls, [])
                self.assertIsNone(recovered_state.cycle(cycle_id))
                self.assertEqual(self.repo.tables, before_remote)
                self.assertEqual(self.inbox.get(cycle_id, "C-1"), before_inbox)

    def test_matching_release_allows_local_pipeline_resume_and_remote_reconstruction(self):
        cycle_id, request = self.admitted_cycle()
        calls = []
        self.engine.fetcher = lambda *args: calls.append(args) or Inventory("complete")
        result = self.engine.resume_local(cycle_id)
        self.assertEqual(result["status"], "Complete")
        self.assertEqual(len(calls), 1)

        remote_state = State(self.root / "matching-remote.db")
        self.addCleanup(remote_state.close)
        remote_engine = Engine(self.repo, remote_state, inbox=self.inbox,
                               error_log_path=self.root / "matching-remote-errors.jsonl")
        recovered = remote_engine._recover(cycle_id)
        self.assertEqual(recovered["repair_retry"], request["repair_retry"])


if __name__ == "__main__":
    unittest.main()
