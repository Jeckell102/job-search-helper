import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.cli import WriterLockBusy, scraper_lock_name, writer_lock
from job_search_helper.integration_release import (
    MANIFEST_SCHEMA,
    JOURNAL_SCHEMA,
    activate_release,
    assert_release_settled,
    manifest_release_id,
    metadata,
    rollback_release,
    source_tree_digest,
    config_tree_digest,
    digest,
)


class IntegrationReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.candidate = self.root / "candidate"
        self.state = self.root / "state"
        self.records = self.root / "records"
        self.database = self.state / "state.db"
        for base in (self.project, self.candidate):
            (base / "src/job_search_helper").mkdir(parents=True)
            (base / "tests").mkdir()
            (base / ".state/integration-configs").mkdir(parents=True)
            (base / "src/job_search_helper/stable.py").write_text("STABLE = True\n")
        self.paths = (
            "src/job_search_helper/provider.py",
            "tests/test_provider.py",
            ".state/integration-configs/C-1.json",
        )
        old = ("OLD_SOURCE = True\n", "OLD_TEST = True\n", '{"version":1}\n')
        new = ("NEW_SOURCE = True\n", "NEW_TEST = True\n", '{"version":2}\n')
        for name, before, after in zip(self.paths, old, new):
            (self.project / name).write_text(before)
            (self.candidate / name).write_text(after)
        files = {name: {"before": metadata(self.project / name),
                        "after": metadata(self.candidate / name)} for name in self.paths}
        self.verification = {"result": "PASS", "tests": 3}
        self.manifest = {
            "schema": MANIFEST_SCHEMA, "failed_request_id": "REQ-failed-1",
            "company_id": "C-1",
            "source_revision": "revision-1", "files": files,
            "before_source_manifest_sha256": source_tree_digest(self.project),
            "source_manifest_sha256": source_tree_digest(self.candidate),
            "dependency_manifest_sha256": "d" * 64,
            "before_config_sha256": config_tree_digest(self.project),
            "config_sha256": config_tree_digest(self.candidate),
            "validation_receipt_sha256": digest(self.verification),
        }
        self.manifest["release_id"] = manifest_release_id(self.manifest)

    def activate(self, **kwargs):
        return activate_release(
            self.project, self.candidate, self.database, self.records, self.manifest,
            current_source_revision=lambda company_id: "revision-1",
            dependency_digest=lambda: "d" * 64,
            verify=lambda project, manifest: self.verification,
            **kwargs,
        )

    def test_complete_activation_is_one_full_version_and_records_binding(self):
        receipt = self.activate()
        self.assertEqual(receipt["state"], "COMPLETE")
        self.assertEqual(receipt["release"]["release_id"], self.manifest["release_id"])
        for name in self.paths:
            self.assertEqual(metadata(self.project / name), metadata(self.candidate / name))
        journal = assert_release_settled(self.state)
        self.assertEqual(journal["state"], "COMPLETE")
        saved = json.loads((self.records / self.manifest["release_id"] / "receipt.json").read_text())
        self.assertEqual(saved, receipt)

    def test_same_normal_scraper_lock_excludes_release_activation(self):
        self.state.mkdir()
        lock = self.state / scraper_lock_name()
        with writer_lock(lock):
            with self.assertRaises(WriterLockBusy):
                self.activate()
        self.assertFalse((self.state / "integration-release-journal.json").exists())
        for name in self.paths:
            self.assertNotEqual(metadata(self.project / name), metadata(self.candidate / name))

    def test_crash_mid_install_blocks_startup_until_exact_rollback(self):
        def fault(stage):
            if stage == "installed:0":
                raise RuntimeError("injected crash")
        with self.assertRaisesRegex(RuntimeError, "injected crash"):
            self.activate(fault=fault)
        with self.assertRaisesRegex(RuntimeError, "interrupted integration release"):
            assert_release_settled(self.state)
        ordered = sorted(self.paths)
        self.assertEqual(metadata(self.project / ordered[0]), metadata(self.candidate / ordered[0]))
        self.assertNotEqual(metadata(self.project / ordered[1]), metadata(self.candidate / ordered[1]))
        receipt = rollback_release(
            self.project, self.database, self.records, self.manifest["release_id"])
        self.assertEqual(receipt["state"], "ROLLED_BACK")
        self.assertEqual(assert_release_settled(self.state)["state"], "ROLLED_BACK")
        for name in self.paths:
            self.assertEqual(metadata(self.project / name), self.manifest["files"][name]["before"])

    def test_failed_installed_verification_stays_blocked_and_rolls_back(self):
        with self.assertRaisesRegex(RuntimeError, "did not pass"):
            activate_release(
                self.project, self.candidate, self.database, self.records, self.manifest,
                current_source_revision=lambda company_id: "revision-1",
                dependency_digest=lambda: "d" * 64,
                verify=lambda project, manifest: {"result": "FAIL"},
            )
        with self.assertRaises(RuntimeError):
            assert_release_settled(self.state)
        rollback_release(self.project, self.database, self.records, self.manifest["release_id"])
        for name in self.paths:
            self.assertEqual(metadata(self.project / name), self.manifest["files"][name]["before"])

    def test_different_pass_receipt_cannot_substitute_for_reviewed_evidence(self):
        with self.assertRaisesRegex(RuntimeError, "did not pass"):
            activate_release(
                self.project, self.candidate, self.database, self.records, self.manifest,
                current_source_revision=lambda company_id: "revision-1",
                dependency_digest=lambda: "d" * 64,
                verify=lambda project, manifest: {"result": "PASS", "tests": 999},
            )
        with self.assertRaises(RuntimeError):
            assert_release_settled(self.state)
        rollback_release(self.project, self.database, self.records, self.manifest["release_id"])

    def test_source_drift_before_activation_changes_nothing(self):
        (self.project / self.paths[0]).write_text("UNREVIEWED = True\n")
        with self.assertRaisesRegex(ValueError, "complete source tree changed"):
            self.activate()
        self.assertFalse((self.state / "integration-release-journal.json").exists())
        self.assertEqual((self.project / self.paths[1]).read_text(), "OLD_TEST = True\n")

    def test_company_revision_drift_changes_nothing(self):
        with self.assertRaisesRegex(ValueError, "source revision changed"):
            activate_release(
                self.project, self.candidate, self.database, self.records, self.manifest,
                current_source_revision=lambda company_id: "revision-2",
                dependency_digest=lambda: "d" * 64,
                verify=lambda project, manifest: {"result": "PASS"},
            )
        self.assertFalse((self.state / "integration-release-journal.json").exists())

    def test_rollback_refuses_third_party_change(self):
        def fault(stage):
            if stage == "installed:0":
                raise RuntimeError("injected crash")
        with self.assertRaises(RuntimeError):
            self.activate(fault=fault)
        (self.project / self.paths[0]).write_text("THIRD_PARTY = True\n")
        with self.assertRaisesRegex(RuntimeError, "changed outside"):
            rollback_release(self.project, self.database, self.records, self.manifest["release_id"])
        with self.assertRaises(RuntimeError):
            assert_release_settled(self.state)

    def test_unlisted_source_drift_is_part_of_complete_version_pin(self):
        (self.project / "src/job_search_helper/stable.py").write_text("DRIFT = True\n")
        with self.assertRaisesRegex(ValueError, "complete source tree changed"):
            self.activate()
        self.assertFalse((self.state / "integration-release-journal.json").exists())

    def test_dependency_drift_is_rejected_before_journal(self):
        with self.assertRaisesRegex(ValueError, "dependency manifest changed"):
            activate_release(
                self.project, self.candidate, self.database, self.records, self.manifest,
                current_source_revision=lambda company_id: "revision-1",
                dependency_digest=lambda: "e" * 64,
                verify=lambda project, manifest: {"result": "PASS"},
            )
        self.assertFalse((self.state / "integration-release-journal.json").exists())

    def test_actual_runner_boundary_refuses_nonterminal_release_journal(self):
        from job_search_helper.runner import pause_interrupted_cycle
        self.state.mkdir()
        (self.state / "integration-release-journal.json").write_text(json.dumps({
            "schema": JOURNAL_SCHEMA, "state": "INSTALLING",
        }))
        with self.assertRaisesRegex(RuntimeError, "interrupted integration release"):
            pause_interrupted_cycle("CYC-1", "test boundary", database=self.database)


if __name__ == "__main__":
    unittest.main()
