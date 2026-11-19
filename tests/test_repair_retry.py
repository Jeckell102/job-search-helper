from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.company_events import source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA,
    RELEASE_BINDING_SCHEMA,
    RepairRetryBridge,
    retry_attempt_id,
    retry_request,
)
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

    def test_release_intent_is_durable_before_company_only_request(self):
        value = binding()
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
        result = self.bridge.deliver(binding())
        self.assertEqual(result["state"], "WAITING_SAFE_REQUEST_BOUNDARY")
        self.assertEqual(json.loads((self.root / "next-scan.json").read_text()), pending)
        self.assertEqual(len(self.bridge.pending_intents()), 1)

    def test_stale_company_revision_never_creates_retry_intent_or_request(self):
        self.revisions["C-1"] = "rev-new"
        result = self.bridge.deliver(binding())
        self.assertEqual(result["state"], "STALE_COMPANY_REVISION")
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

    def test_normal_admission_carries_full_release_pin_into_recoverable_cycle(self):
        from job_search_helper.runner import select_start_cycle
        request = self.request()
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
        path = self.root / "next-scan.json"
        path.write_text(json.dumps(request))
        with self.assertRaisesRegex(ValueError, "source revision is stale"):
            select_start_cycle(self.engine, self.state, self.repo, self.database)
        self.assertTrue(path.exists())
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


if __name__ == "__main__":
    unittest.main()
