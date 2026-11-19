import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.exact_local_plan import (
    adopt_verified_legacy_prefix, commit_exact_local_plan,
)
from job_search_helper.exact_selected_legacy_recovery import (
    build_selected_legacy_v2_plan, preview_selected_legacy_binding,
)
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


CYCLE = "CYC-B639C6D864EC"
URL = "https://jobs.example.test/board"


def controls(company_id):
    return {
        "company_id": company_id, "requested_url": URL,
        "official_careers_url": URL, "company_status": "Active",
        "claimed_by": "", "claim_token": "",
    }


def operation(tab, identity, values):
    return {"tab": tab, "identity": identity, "values": values,
            "on_insert": {}, "expected": {}, "append_notes": {},
            "append_if_missing": False}


class SelectedLegacyRecoveryTests(unittest.TestCase):
    def repo(self, root, company_id, count, settled):
        result = SQLiteRepository(Path(root) / "jobs.sqlite3", "fixture", initialize=True)
        result.ensure_columns("Opportunities", ["Opportunity ID"])
        rows = {
            "Companies": [{"Company ID": company_id, "Company": company_id,
                           "Company Status": "Active", "Official Careers URL": URL,
                           "Last Checked": "new"}],
            "Job History": [{"Job Key": f"job-{number}", "Company": company_id,
                             "Official Job URL": f"https://jobs.example.test/{number}",
                             "Source Hash": f"source-{number}",
                             "Review Status": "Human Reviewed",
                             "Decision": "Keep",
                             "Last Checked": "new" if number < settled else "old"}
                            for number in range(1, count)],
        }
        for tab in SCHEMAS:
            result.import_rows(tab, enumerate(rows.get(tab, []), 2))
        with result.transaction():
            result.set_meta("ready", "yes")
            result.set_meta("sheets_profile", "compact-v1")
        # A verified legacy prefix is still locally pending publication.  If a
        # field is clean, the candidate must refuse instead of assuming it was
        # published.
        company_row = result.matches("Companies", {"Company ID": company_id})[0][0]
        result.mark_dirty("Companies", company_row, {"Last Checked"})
        for number in range(1, settled):
            row_id = result.matches("Job History", {"Job Key": f"job-{number}"})[0][0]
            result.mark_dirty("Job History", row_id,
                              {"Company", "Source Hash", "Last Checked"})
        return result

    def legacy(self, company_id, count):
        operations = [operation("Companies", {"Company ID": company_id},
                                {"Last Checked": "new"})]
        operations.extend(
            operation("Job History", {"Job Key": f"job-{number}"},
                      {"Company": company_id, "Source Hash": f"source-{number}",
                       "Last Checked": "new"})
            for number in range(1, count))
        return {"operations": operations, "final": {"stage": "complete"},
                "requested_url": URL}

    def plan(self, repo, company_id, count, cursor):
        legacy = self.legacy(company_id, count)
        payload = {"inventory_status": "complete", "jobs": [], "requested_url": URL}
        approved = preview_selected_legacy_binding(
            repo, cycle_id=CYCLE, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls(company_id))
        return build_selected_legacy_v2_plan(
            repo, cycle_id=CYCLE, company_id=company_id, payload=payload,
            legacy_plan=legacy, cursor=cursor, controls=controls(company_id),
            binding=approved)

    def test_shield_style_one_of_one_prefix_creates_no_replay_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0052", 1, 1)
            self.addCleanup(repo.close)
            plan, report = self.plan(repo, "COMP-0052", 1, 1)
            self.assertEqual((report["verified_prefix_cursor"],
                              report["legacy_operation_count"],
                              report["remaining_operation_count"]), (1, 1, 0))
            adopted = adopt_verified_legacy_prefix(
                repo, CYCLE, "COMP-0052", plan, timestamp_value="2026-11-19T00:00:00Z")
            self.assertEqual(adopted["state"], "VERIFIED")
            with patch.object(repo, "_commit_in_transaction", wraps=repo._commit_in_transaction) as commit:
                committed = commit_exact_local_plan(repo, CYCLE, "COMP-0052", plan)
            self.assertEqual(committed["state"], "VERIFIED")
            commit.assert_not_called()

    def test_saronic_style_sixty_seven_of_208_only_applies_suffix(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0054", 208, 67)
            self.addCleanup(repo.close)
            plan, report = self.plan(repo, "COMP-0054", 208, 67)
            self.assertEqual((report["verified_prefix_cursor"],
                              report["legacy_operation_count"],
                              report["remaining_operation_count"]), (67, 208, 141))
            adopt_verified_legacy_prefix(
                repo, CYCLE, "COMP-0054", plan, timestamp_value="2026-11-19T00:00:00Z")
            calls = []
            original = repo._commit_in_transaction
            def observed(operations):
                calls.append([item["identity"] for item in operations])
                return original(operations)
            with patch.object(repo, "_commit_in_transaction", side_effect=observed):
                committed = commit_exact_local_plan(repo, CYCLE, "COMP-0054", plan)
            self.assertEqual(committed["state"], "VERIFIED")
            self.assertEqual([len(chunk) for chunk in calls], [100, 41])
            self.assertEqual(calls[0][0], {"Job Key": "job-67"})
            self.assertEqual(calls[-1][-1], {"Job Key": "job-207"})

    def test_clean_prefix_refuses_unknown_prior_publication(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0052", 1, 1)
            self.addCleanup(repo.close)
            company_row = repo.matches("Companies", {"Company ID": "COMP-0052"})[0][0]
            with repo.transaction():
                repo.db.execute("DELETE FROM dirty WHERE tab='Companies' AND row_id=?", (company_row,))
            plan, _ = self.plan(repo, "COMP-0052", 1, 1)
            with self.assertRaisesRegex(ValueError, "not pending publication"):
                adopt_verified_legacy_prefix(
                    repo, CYCLE, "COMP-0052", plan,
                    timestamp_value="2026-11-19T00:00:00Z")

    def test_changed_approval_binding_refuses(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0052", 1, 1)
            self.addCleanup(repo.close)
            legacy = self.legacy("COMP-0052", 1)
            payload = {"inventory_status": "complete", "jobs": [], "requested_url": URL}
            approved = preview_selected_legacy_binding(
                repo, cycle_id=CYCLE, company_id="COMP-0052", payload=payload,
                legacy_plan=legacy, cursor=1, controls=controls("COMP-0052"))
            altered = copy.deepcopy(approved)
            altered["verified_prefix_cursor"] = 0
            with self.assertRaisesRegex(ValueError, "binding_mismatch"):
                build_selected_legacy_v2_plan(
                    repo, cycle_id=CYCLE, company_id="COMP-0052", payload=payload,
                    legacy_plan=legacy, cursor=1, controls=controls("COMP-0052"),
                    binding=altered)

    def test_foreign_company_in_suffix_refuses_before_candidate_seal(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0054", 208, 67)
            self.addCleanup(repo.close)
            legacy = self.legacy("COMP-0054", 208)
            # Position 67 is job-67 and is outside the verified 67-operation
            # prefix.  It must receive the same ownership scrutiny as prefix.
            legacy["operations"][67]["values"]["Company"] = "Foreign Company"
            payload = {"inventory_status": "complete", "jobs": [], "requested_url": URL}
            with self.assertRaisesRegex(ValueError, "job_ownership_mismatch"):
                preview_selected_legacy_binding(
                    repo, cycle_id=CYCLE, company_id="COMP-0054", payload=payload,
                    legacy_plan=legacy, cursor=67, controls=controls("COMP-0054"))

    def test_foreign_evidence_in_prefix_refuses_job_key_source_relation(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0054", 2, 2)
            self.addCleanup(repo.close)
            repo.import_rows("Job Evidence", [(2, {
                "Job Key": "job-1", "Source Hash": "source-1",
                "Company": "COMP-0054", "Job Title": "Role",
                "Official Job URL": "https://jobs.example.test/1",
                "Captured At": "now", "Job Description": "evidence",
            })])
            legacy = self.legacy("COMP-0054", 2)
            legacy["operations"].insert(2, operation(
                "Job Evidence", {"Job Key": "job-1", "Source Hash": "source-1"},
                {"Company": "Foreign Company", "Job Description": "evidence"}))
            payload = {"inventory_status": "complete", "jobs": [], "requested_url": URL}
            with self.assertRaisesRegex(ValueError, "evidence_ownership_mismatch"):
                preview_selected_legacy_binding(
                    repo, cycle_id=CYCLE, company_id="COMP-0054", payload=payload,
                    legacy_plan=legacy, cursor=3, controls=controls("COMP-0054"))

    def test_suffix_manual_decision_and_review_status_are_guards_not_writes(self):
        with tempfile.TemporaryDirectory() as root:
            repo = self.repo(root, "COMP-0054", 208, 67)
            self.addCleanup(repo.close)
            legacy = self.legacy("COMP-0054", 208)
            # job-67 is the first unapplied suffix operation.
            legacy["operations"][67]["values"].update({
                "Review Status": "Pending", "Decision": "Reject"})
            payload = {"inventory_status": "complete", "jobs": [], "requested_url": URL}
            approved = preview_selected_legacy_binding(
                repo, cycle_id=CYCLE, company_id="COMP-0054", payload=payload,
                legacy_plan=legacy, cursor=67, controls=controls("COMP-0054"))
            plan, report = build_selected_legacy_v2_plan(
                repo, cycle_id=CYCLE, company_id="COMP-0054", payload=payload,
                legacy_plan=legacy, cursor=67, controls=controls("COMP-0054"),
                binding=approved)
            suffix = next(item for item in plan["local_operations"]
                          if item["identity"] == {"Job Key": "job-67"})
            self.assertNotIn("Review Status", suffix["values"])
            self.assertNotIn("Decision", suffix["values"])
            self.assertEqual(suffix["expected"]["Review Status"], "Human Reviewed")
            self.assertEqual(suffix["expected"]["Decision"], "Keep")
            self.assertEqual(report["protected_conflict_count"], 1)


if __name__ == "__main__":
    unittest.main()
