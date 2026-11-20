import copy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.control_before_prefix_authorization import (
    ACTION, required_control_before_prefix_claims,
    verify_control_before_prefix_authorization,
)
from job_search_helper.control_before_prefix_runner import (
    apply_control_before_prefix_recovery,
    preview_control_before_prefix_recovery,
)
from job_search_helper.exact_cycle_sync import _publish_exact_v2
from job_search_helper.exact_control_before_prefix_recovery import (
    CONTROL_BEFORE_PREFIX_VERSION, build_control_before_prefix_v2_plan,
    preview_control_before_prefix_binding,
)
from job_search_helper.repository import SCHEMAS
from job_search_helper.inbox import InventoryInbox
from job_search_helper.selected_recovery_authorization import TestAuthorizationVerifier
from job_search_helper.sqlite_repository import SQLiteRepository


CYCLE = "CYC-B639C6D864EC"
COMPANY = "COMP-0054"
URL = "https://jobs.example.test/board"


def operation(tab, identity, values):
    return {"tab": tab, "identity": identity, "values": values,
            "on_insert": {}, "expected": {}, "append_notes": {},
            "append_if_missing": False}


class ControlBeforePrefixRecoveryTests(unittest.TestCase):
    def fixture(self, root):
        repo = SQLiteRepository(Path(root) / "jobs.sqlite3", "fixture", initialize=True)
        repo.ensure_columns("Opportunities", ["Opportunity ID"])
        rows = {
            "Companies": [{"Company ID": COMPANY, "Company": COMPANY,
                           "Company Status": "Active", "Official Careers URL": URL,
                           "Last Checked": "new"}],
            "Job History": [{"Job Key": "job-1", "Company": COMPANY,
                             "Official Job URL": URL + "/1", "Source Hash": "source-1",
                             "Review Status": "Human Reviewed", "Decision": "Keep",
                             "Last Checked": "new"}],
            "Job Evidence": [{"Job Key": "job-1", "Source Hash": "source-1",
                              "Company": COMPANY, "Job Title": "Role",
                              "Official Job URL": URL + "/1", "Captured At": "now",
                              "Job Description": "evidence"}],
            "Opportunities": [{"Opportunity ID": "opp-1", "Company": COMPANY,
                               "Job Key": "job-1", "Source Hash": "source-1",
                               "Status": "Open"}],
        }
        for tab in SCHEMAS:
            repo.import_rows(tab, enumerate(rows.get(tab, []), 2))
        with repo.transaction():
            repo.set_meta("ready", "yes"); repo.set_meta("sheets_profile", "compact-v1")
        for tab, identity, fields in (
            ("Companies", {"Company ID": COMPANY}, {"Last Checked"}),
            ("Job History", {"Job Key": "job-1"}, {"Company", "Source Hash", "Last Checked"}),
            ("Job Evidence", {"Job Key": "job-1", "Source Hash": "source-1"}, {"Company", "Job Description"}),
            ("Opportunities", {"Opportunity ID": "opp-1"}, {"Company"}),
        ):
            row_id = repo.matches(tab, identity)[0][0]
            repo.mark_dirty(tab, row_id, fields)
        legacy = {"operations": [
            operation("Job History", {"Job Key": "job-1"},
                      {"Company": COMPANY, "Source Hash": "source-1", "Last Checked": "new"}),
            operation("Job Evidence", {"Job Key": "job-1", "Source Hash": "source-1"},
                      {"Company": COMPANY, "Job Description": "evidence"}),
            operation("Opportunities", {"Opportunity ID": "opp-1"},
                      {"Company": COMPANY}),
            operation("Companies", {"Company ID": COMPANY}, {"Last Checked": "new"}),
        ], "final": {"stage": "complete"}, "requested_url": URL}
        return repo, legacy

    def controls(self):
        return {"company_id": COMPANY, "requested_url": URL,
                "official_careers_url": URL, "company_status": "Active",
                "claimed_by": "", "claim_token": ""}

    def build(self, repo, legacy, binding):
        return build_control_before_prefix_v2_plan(
            repo, cycle_id=CYCLE, company_id=COMPANY,
            payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
            legacy_plan=legacy, cursor=3, controls=self.controls(), binding=binding)

    def durable_fixture(self, root):
        repo, legacy = self.fixture(root)
        inbox_path = Path(root) / "inventories.sqlite3"
        inbox = InventoryInbox(inbox_path, "fixture")
        inbox.save(CYCLE, COMPANY, {"inventory_status": "complete", "jobs": [],
                                    "requested_url": URL})
        with inbox.connection:
            inbox.connection.execute("INSERT INTO sync_plans VALUES (?,?,?,?)",
                                   (CYCLE, COMPANY, json.dumps(legacy), 3))
        inbox.close()
        return repo, str(inbox_path), str(Path(root) / "jobs.sqlite3")

    def append_only_suffix(self, legacy):
        """Add a real-shaped missing History/Evidence pair after Company."""
        result = copy.deepcopy(legacy)
        history = operation("Job History", {"Job Key": "job-absent"}, {
            "Job Key": "job-absent", "Company": COMPANY, "Source Hash": "source-absent",
            "Official Job URL": URL + "/absent", "Last Checked": "new"})
        evidence = operation("Job Evidence", {"Job Key": "job-absent", "Source Hash": "source-absent"}, {
            "Job Key": "job-absent", "Source Hash": "source-absent", "Company": COMPANY,
            "Job Title": "Absent role", "Official Job URL": URL + "/absent",
            "Captured At": "now", "Job Description": "evidence"})
        history["append_if_missing"] = True
        evidence["append_if_missing"] = True
        result["operations"].extend([history, evidence])
        return result

    def test_live_shape_late_control_binds_owned_prefix_and_stays_local_only(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            proof = preview_control_before_prefix_binding(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                legacy_plan=legacy, cursor=3, controls=self.controls())
            plan, report = self.build(repo, legacy, proof)
            recovery = plan["selected_legacy_control_before_prefix_recovery"]
            self.assertNotIn("selected_legacy_recovery", plan)
            self.assertEqual(recovery["version"], CONTROL_BEFORE_PREFIX_VERSION)
            self.assertEqual((recovery["control_original_index"],
                              recovery["original_verified_prefix_cursor"],
                              recovery["transformed_verified_prefix_cursor"]), (3, 3, 4))
            self.assertEqual(plan["local_operations"][0]["tab"], "Companies")
            self.assertFalse(recovery["remote_release_authorized"])
            self.assertEqual((report["mutation_performed"], report["receipt_created"],
                              report["remote_write_performed"]), (False, False, False))
            claims = required_control_before_prefix_claims(
                cycle_id=CYCLE, company_id=COMPANY, plan=plan, recovery=recovery,
                expires_at="2030-01-01T00:00:00+00:00")
            self.assertEqual(claims["action"], ACTION)
            verifier = TestAuthorizationVerifier()
            self.assertIn("authorization_digest", verify_control_before_prefix_authorization(
                verifier.issue(claims), claims, verifier, allow_test_verifier=True))

    def test_foreign_company_control_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            legacy["operations"][-1]["identity"] = {"Company ID": "COMP-FOREIGN"}
            with self.assertRaisesRegex(ValueError, "company_control_foreign"):
                preview_control_before_prefix_binding(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                    legacy_plan=legacy, cursor=3, controls=self.controls())

    def test_absent_append_only_suffix_is_manifested_and_signed(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            legacy = self.append_only_suffix(legacy)
            proof = preview_control_before_prefix_binding(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                legacy_plan=legacy, cursor=3, controls=self.controls())
            self.assertEqual(proof["absent_suffix_count"], 2)
            self.assertEqual([item["original_index"] for item in proof["absent_suffix_manifest"]], [4, 5])
            plan, _ = self.build(repo, legacy, proof)
            claims = required_control_before_prefix_claims(
                cycle_id=CYCLE, company_id=COMPANY, plan=plan,
                recovery=plan["selected_legacy_control_before_prefix_recovery"],
                expires_at="2030-01-01T00:00:00+00:00")
            self.assertEqual(claims["absent_suffix_manifest"], proof["absent_suffix_manifest"])

    def test_absent_suffix_refuses_non_append_and_foreign_materialized_ownership(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            unsafe = self.append_only_suffix(legacy)
            unsafe["operations"][4]["append_if_missing"] = 1
            with self.assertRaisesRegex(ValueError, "absent_suffix_not_append_only"):
                preview_control_before_prefix_binding(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                    legacy_plan=unsafe, cursor=3, controls=self.controls())
            foreign = self.append_only_suffix(legacy)
            foreign["operations"][5]["values"]["Company"] = "Elsewhere"
            with self.assertRaisesRegex(ValueError, "evidence_ownership_mismatch"):
                preview_control_before_prefix_binding(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                    legacy_plan=foreign, cursor=3, controls=self.controls())

    def test_presence_flip_refuses_original_signed_binding(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            legacy = self.append_only_suffix(legacy)
            proof = preview_control_before_prefix_binding(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                legacy_plan=legacy, cursor=3, controls=self.controls())
            row = {"Job Key": "job-absent", "Company": COMPANY, "Source Hash": "source-absent",
                   "Official Job URL": URL + "/absent", "Last Checked": "new"}
            repo.import_rows("Job History", [(3, row)])
            with self.assertRaisesRegex(ValueError, "binding_mismatch"):
                self.build(repo, legacy, proof)

    def test_moved_control_refuses_the_previously_signed_proof(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            proof = preview_control_before_prefix_binding(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                legacy_plan=legacy, cursor=2, controls=self.controls())
            moved = copy.deepcopy(legacy)
            moved["operations"].insert(2, moved["operations"].pop())
            # It remains later than the prefix but the original ordering pin changed.
            with self.assertRaisesRegex(ValueError, "binding_mismatch"):
                build_control_before_prefix_v2_plan(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                    legacy_plan=moved, cursor=2, controls=self.controls(), binding=proof)

    def test_present_metadata_only_history_derives_signed_current_owner_guards(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            metadata = copy.deepcopy(legacy)
            metadata["operations"][0]["values"] = {"Last Checked": "new"}
            proof = preview_control_before_prefix_binding(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                legacy_plan=metadata, cursor=3, controls=self.controls())
            owned = proof["job_ownership_manifest"]
            self.assertEqual(owned[0]["ownership_mode"], "derived_current_guard")
            self.assertEqual(owned[0]["successor_expected_guard"],
                             {"Company": COMPANY, "Source Hash": "source-1"})
            plan, _ = self.build(repo, metadata, proof)
            successor = next(op for op in plan["local_operations"]
                             if op["tab"] == "Job History")
            self.assertEqual(successor["expected"]["Company"], COMPANY)
            self.assertEqual(successor["expected"]["Source Hash"], "source-1")
            claims = required_control_before_prefix_claims(
                cycle_id=CYCLE, company_id=COMPANY, plan=plan,
                recovery=plan["selected_legacy_control_before_prefix_recovery"],
                expires_at="2030-01-01T00:00:00+00:00")
            self.assertEqual(claims["job_ownership_manifest"], owned)
            self.assertEqual(claims["job_ownership_manifest_digest"],
                             proof["job_ownership_manifest_digest"])

    def test_metadata_only_owner_snapshot_change_refuses_signed_binding(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            metadata = copy.deepcopy(legacy)
            metadata["operations"][0]["values"] = {"Last Checked": "new"}
            proof = preview_control_before_prefix_binding(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                legacy_plan=metadata, cursor=3, controls=self.controls())
            repo.commit([{"tab": "Job History", "identity": {"Job Key": "job-1"},
                          "values": {"Last Checked": "changed-after-preview"}}])
            with self.assertRaisesRegex(ValueError, "binding_mismatch"):
                self.build(repo, metadata, proof)

    def test_explicit_append_source_mismatch_at_legacy_index_193_refuses(self):
        with tempfile.TemporaryDirectory() as root:
            repo, legacy = self.fixture(root)
            self.addCleanup(repo.close)
            shaped = copy.deepcopy(legacy)
            company = shaped["operations"].pop()
            shaped["operations"].pop(0)  # remove the normal job row, avoiding a duplicate target
            shaped["operations"].pop(0)  # no Evidence row can mask the history ownership failure
            for number in range(192):
                filler = operation("Opportunities", {"Opportunity ID": "f-%03d" % number},
                                   {"Opportunity ID": "f-%03d" % number, "Company": COMPANY})
                filler["append_if_missing"] = True
                shaped["operations"].append(filler)
            mismatch = operation("Job History", {"Job Key": "job-1"}, {
                "Company": COMPANY, "Source Hash": "source-not-current", "Last Checked": "new"})
            mismatch["append_if_missing"] = True
            shaped["operations"].append(mismatch)
            shaped["operations"].append(company)
            self.assertEqual(shaped["operations"].index(mismatch), 193)
            with self.assertRaisesRegex(ValueError, "job_ownership_mismatch"):
                preview_control_before_prefix_binding(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [], "requested_url": URL},
                    legacy_plan=shaped, cursor=1, controls=self.controls())

    def test_unsigned_apply_refuses_before_durable_hold(self):
        with tempfile.TemporaryDirectory() as root:
            repo, inbox_path, local_path = self.durable_fixture(root)
            self.addCleanup(repo.close)
            preview = preview_control_before_prefix_recovery(
                inbox_path, local_path, CYCLE, COMPANY,
                expires_at="2030-01-01T00:00:00+00:00")
            verifier = TestAuthorizationVerifier()
            forged = verifier.issue({**preview["authorization_claims"],
                                     "control_original_index": 99})
            with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                apply_control_before_prefix_recovery(
                    inbox_path, local_path, CYCLE, COMPANY, forged, verifier,
                    lock_factory=nullcontext, allow_test_verifier=True)
            with __import__('sqlite3').connect(inbox_path) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_control_before_prefix_recoveries").fetchone()[0], 0)

    def test_direct_inbox_forged_verified_metadata_cannot_create_hold(self):
        """The public inbox method must not trust a caller's compact dict."""
        with tempfile.TemporaryDirectory() as root:
            repo, inbox_path, local_path = self.durable_fixture(root)
            self.addCleanup(repo.close)
            (_destination, _payload, _legacy, _cursor, _state, _binding, plan,
             _report) = __import__('job_search_helper.control_before_prefix_runner',
                                    fromlist=['_build_readonly'])._build_readonly(
                                        inbox_path, local_path, CYCLE, COMPANY)
            inbox = InventoryInbox(inbox_path, "fixture")
            self.addCleanup(inbox.close)
            preview = preview_control_before_prefix_recovery(
                inbox_path, local_path, CYCLE, COMPANY,
                expires_at="2030-01-01T00:00:00+00:00")
            forged = {"key_id": "test", "payload": preview["authorization_claims"],
                      "signature": "forged", "test_token": "forged"}
            with self.assertRaisesRegex(ValueError, "signature_invalid"):
                inbox.begin_control_before_prefix_recovery(
                    CYCLE, COMPANY, plan, forged, TestAuthorizationVerifier(),
                    timestamp="now", allow_test_verifier=True)
            self.assertEqual(inbox.connection.execute(
                "SELECT count(*) FROM exact_control_before_prefix_recoveries").fetchone()[0], 0)

    def test_signed_apply_creates_local_only_hold_and_generic_publisher_refuses(self):
        with tempfile.TemporaryDirectory() as root:
            repo, inbox_path, local_path = self.durable_fixture(root)
            self.addCleanup(repo.close)
            preview = preview_control_before_prefix_recovery(
                inbox_path, local_path, CYCLE, COMPANY,
                expires_at="2030-01-01T00:00:00+00:00")
            verifier = TestAuthorizationVerifier()
            result = apply_control_before_prefix_recovery(
                inbox_path, local_path, CYCLE, COMPANY,
                verifier.issue(preview["authorization_claims"]), verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            self.assertEqual(result["state"], "LOCAL_ONLY_FROZEN")
            with __import__('sqlite3').connect(inbox_path) as db:
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM publication_receipts").fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT count(*) FROM exact_remote_plans").fetchone()[0], 0)
            # The generic publisher refuses before opening/using an inbox,
            # receipt, remote client, local store, or synchronizer.
            (_destination, _payload, _legacy, _cursor, _state, _binding, plan,
             _report) = __import__('job_search_helper.control_before_prefix_runner',
                                    fromlist=['_build_readonly'])._build_readonly(
                                        inbox_path, local_path, CYCLE, COMPANY)
            with self.assertRaisesRegex(ValueError, "dedicated_release_gate_required"):
                _publish_exact_v2(None, CYCLE, COMPANY, plan, 0, {}, None, None,
                                  None, None, None)

    def test_acknowledge_and_block_refuse_without_orphaning_local_only_hold(self):
        with tempfile.TemporaryDirectory() as root:
            repo, inbox_path, local_path = self.durable_fixture(root)
            self.addCleanup(repo.close)
            preview = preview_control_before_prefix_recovery(
                inbox_path, local_path, CYCLE, COMPANY,
                expires_at="2030-01-01T00:00:00+00:00")
            verifier = TestAuthorizationVerifier()
            apply_control_before_prefix_recovery(
                inbox_path, local_path, CYCLE, COMPANY,
                verifier.issue(preview["authorization_claims"]), verifier,
                lock_factory=nullcontext, allow_test_verifier=True)
            inbox = InventoryInbox(inbox_path, "fixture")
            self.addCleanup(inbox.close)
            def retained():
                return (
                    inbox.connection.execute(
                        "SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?",
                        (CYCLE, COMPANY)).fetchone(),
                    inbox.connection.execute(
                        "SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?",
                        (CYCLE, COMPANY)).fetchone(),
                    inbox.connection.execute(
                        "SELECT state,candidate,evidence FROM exact_control_before_prefix_recoveries "
                        "WHERE cycle=? AND company=?", (CYCLE, COMPANY)).fetchone(),
                )
            before = retained()
            with self.assertRaisesRegex(ValueError, "cannot be cleaned up"):
                inbox.acknowledge(CYCLE, COMPANY)
            self.assertEqual(retained(), before)
            with self.assertRaisesRegex(ValueError, "inventory state is immutable"):
                inbox.block(CYCLE, COMPANY)
            self.assertEqual(retained(), before)


if __name__ == "__main__":
    unittest.main()
