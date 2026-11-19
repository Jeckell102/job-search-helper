import json
import unittest

from job_search_helper.integration_release import metadata
from job_search_helper.release_controller import release_and_schedule
from test_integration_release import IntegrationReleaseTests


class ReleaseControllerTests(unittest.TestCase):
    def setUp(self):
        fixture = IntegrationReleaseTests("test_complete_activation_is_one_full_version_and_records_binding")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def run_controller(self, **kwargs):
        f = self.fixture
        return release_and_schedule(
            f.project, f.candidate, f.database, f.records, f.manifest,
            current_source_revision=kwargs.pop("current_source_revision", lambda company_id: "revision-1"),
            dependency_digest=lambda: "d" * 64,
            verify=lambda project, manifest: f.verification,
            **kwargs,
        )

    def test_completed_release_creates_one_exact_normal_scraper_request(self):
        result = self.run_controller()
        self.assertEqual(result["state"], "REQUEST_WRITTEN")
        request = json.loads((self.fixture.state / "next-scan.json").read_text())
        self.assertEqual(request["request_id"], "company-retry:" + result["attempt_id"])
        self.assertEqual(request["company_ids"], ["C-1"])
        self.assertEqual(request["repair_retry"]["failed_request_id"], "REQ-failed-1")
        self.assertEqual(request["repair_retry"]["release"]["release_id"], result["release_id"])
        self.assertEqual(request["source_revision"], "revision-1")

    def test_crash_after_activation_recovers_without_reinstall_or_new_attempt(self):
        def crash(stage):
            if stage == "after_activation":
                raise RuntimeError("injected controller crash")
        with self.assertRaisesRegex(RuntimeError, "controller crash"):
            self.run_controller(fault=crash)
        self.assertFalse((self.fixture.state / "next-scan.json").exists())
        before = {name: metadata(self.fixture.project / name) for name in self.fixture.paths}
        release_receipt = (self.fixture.records / self.fixture.manifest["release_id"] / "receipt.json").read_bytes()

        recovered = self.run_controller()
        repeated = self.run_controller()
        self.assertEqual(recovered["state"], "REQUEST_WRITTEN")
        self.assertEqual(repeated["state"], "REQUEST_ALREADY_DURABLE")
        self.assertEqual(recovered["attempt_id"], repeated["attempt_id"])
        self.assertEqual((self.fixture.records / self.fixture.manifest["release_id"] / "receipt.json").read_bytes(),
                         release_receipt)
        self.assertEqual({name: metadata(self.fixture.project / name) for name in self.fixture.paths}, before)

    def test_existing_scan_waits_without_losing_release_or_intent(self):
        pending = {"mode": "company-only", "request_id": "other-request"}
        self.fixture.state.mkdir(exist_ok=True)
        path = self.fixture.state / "next-scan.json"
        path.write_text(json.dumps(pending))
        waiting = self.run_controller()
        self.assertEqual(waiting["state"], "WAITING_SAFE_REQUEST_BOUNDARY")
        self.assertEqual(json.loads(path.read_text()), pending)
        path.unlink()
        delivered = self.run_controller()
        self.assertEqual(delivered["state"], "REQUEST_WRITTEN")
        self.assertEqual(delivered["attempt_id"], waiting["attempt_id"])

    def test_company_change_after_activation_holds_retry(self):
        calls = ["revision-1", "revision-2"]
        result = self.run_controller(current_source_revision=lambda company_id: calls.pop(0))
        self.assertEqual(result["state"], "STALE_COMPANY_REVISION")
        self.assertFalse((self.fixture.state / "next-scan.json").exists())
        receipt = json.loads((self.fixture.records / result["release_id"] / "receipt.json").read_text())
        self.assertEqual(receipt["state"], "COMPLETE")

    def test_release_manifest_fixes_failed_request_identity(self):
        first = self.run_controller()
        request = json.loads((self.fixture.state / "next-scan.json").read_text())
        self.assertEqual(first["failed_request_id"], self.fixture.manifest["failed_request_id"])
        self.assertEqual(request["repair_retry"]["failed_request_id"],
                         self.fixture.manifest["failed_request_id"])


if __name__ == "__main__":
    unittest.main()
