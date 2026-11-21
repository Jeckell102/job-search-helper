"""Narrow read-only proof for the late-control source transition preview."""
import copy
import tempfile
import unittest
from pathlib import Path

from job_search_helper.core import job_key, material_hash
from job_search_helper.exact_control_before_prefix_recovery import (
    preview_control_before_prefix_source_transition,
)
from job_search_helper.repository import SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


CYCLE = "CYC-test-source-transition"
COMPANY = "COMP-test"
URL = "https://jobs.example.test/board"


def operation(tab, identity, values, *, expected=None, append=False):
    return {"tab": tab, "identity": identity, "values": values,
            "on_insert": {}, "expected": expected or {}, "append_notes": {},
            "append_if_missing": append}


class SourceTransitionPreviewTests(unittest.TestCase):
    def fixture(self, root):
        repo = SQLiteRepository(Path(root) / "jobs.sqlite3", "fixture", initialize=True)
        repo.ensure_columns("Opportunities", ["Opportunity ID"])
        posting = {"ats": "example", "posting_id": "p-1", "url": URL + "/1",
                   "title": "Role", "location": "CA", "work_arrangement": "Hybrid",
                   "compensation": "$100k", "description": "Description"}
        key, new_source = job_key(COMPANY, "example", "p-1", posting["url"]), material_hash(posting)
        rows = {
            "Companies": [{"Company ID": COMPANY, "Company": COMPANY,
                           "Company Status": "Active", "Official Careers URL": URL}],
            "Job History": [{"Job Key": key, "Company": COMPANY,
                             "Official Job URL": posting["url"], "Source Hash": "old-source",
                             "Salary / Range": "$90k", "Decision": "Keep",
                             "Review Status": "Human Reviewed", "Last Checked": "old"}],
            "Job Evidence": [{"Job Key": key, "Source Hash": "old-source",
                              "Company": COMPANY, "Job Title": "Role",
                              "Official Job URL": posting["url"], "Captured At": "old"}],
            "Opportunities": [{"Opportunity ID": "opp-1", "Company": COMPANY,
                                "Job Key": key, "Source Hash": "old-source",
                                "Job URL": posting["url"]}],
        }
        for tab in SCHEMAS:
            repo.import_rows(tab, enumerate(rows.get(tab, []), 2))
        with repo.transaction():
            repo.set_meta("ready", "yes"); repo.set_meta("sheets_profile", "compact-v1")
            history_row_id = repo.matches("Job History", {"Job Key": key})[0][0]
            repo.db.execute("INSERT INTO manual_choices VALUES (?,?,?,?)",
                            ("Job History", history_row_id, "Keep", "fixture"))
        legacy = {"operations": [
            operation("Opportunities", {"Opportunity ID": "opp-1"},
                      {"Company": COMPANY}),
            operation("Job History", {"Job Key": key},
                      {"Company": COMPANY, "Source Hash": new_source,
                       "Salary / Range": "$100k", "Decision": "", "Review Status": ""},
                      expected={"Company": COMPANY, "Source Hash": "old-source",
                                "Salary / Range": "$90k", "Decision": "Keep",
                                "Review Status": "Human Reviewed"}, append=True),
            operation("Job Evidence", {"Job Key": key, "Source Hash": new_source},
                      {"Company": COMPANY, "Job Key": key, "Source Hash": new_source,
                       "Job Title": "Role", "Official Job URL": posting["url"],
                       "Captured At": "now", "Job Description": posting["description"]}, append=True),
            operation("Companies", {"Company ID": COMPANY}, {"Last Checked": "new"}),
        ], "final": {"stage": "complete"}, "requested_url": URL}
        controls = {"company_id": COMPANY, "official_careers_url": URL,
                    "company_status": "Active", "claimed_by": "", "claim_token": ""}
        return repo, posting, legacy, controls, key, new_source

    def test_preview_is_read_only_and_normalizes_one_present_transition(self):
        with tempfile.TemporaryDirectory() as root:
            repo, posting, legacy, controls, key, new_source = self.fixture(root)
            self.addCleanup(repo.close)
            original = copy.deepcopy(legacy)
            result = preview_control_before_prefix_source_transition(
                repo, cycle_id=CYCLE, company_id=COMPANY,
                payload={"inventory_status": "complete", "jobs": [posting],
                         "requested_url": URL}, legacy_plan=legacy, cursor=1,
                controls=controls)
            self.assertEqual(legacy, original)
            self.assertEqual(result["report"]["history_index"], 1)
            self.assertEqual(result["report"]["evidence_index"], 2)
            successor = result["plan"]["operations"][1]
            self.assertIs(successor["append_if_missing"], False)
            self.assertEqual(successor["expected"]["Source Hash"], "old-source")
            self.assertEqual(successor["values"]["Source Hash"], new_source)
            self.assertNotIn("Decision", successor["values"])
            self.assertEqual(successor["expected"]["Decision"], "Keep")
            self.assertNotIn(new_source, str(result["report"]))

    def test_rejects_unpaired_or_wrong_archived_posting(self):
        with tempfile.TemporaryDirectory() as root:
            repo, posting, legacy, controls, _key, _new_source = self.fixture(root)
            self.addCleanup(repo.close)
            broken = copy.deepcopy(legacy)
            broken["operations"][2]["append_if_missing"] = False
            with self.assertRaisesRegex(ValueError, "absent_suffix_not_append_only"):
                preview_control_before_prefix_source_transition(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [posting],
                             "requested_url": URL}, legacy_plan=broken, cursor=1,
                    controls=controls)
            with self.assertRaisesRegex(ValueError, "archived_posting_not_unique"):
                preview_control_before_prefix_source_transition(
                    repo, cycle_id=CYCLE, company_id=COMPANY,
                    payload={"inventory_status": "complete", "jobs": [],
                             "requested_url": URL}, legacy_plan=legacy, cursor=1,
                    controls=controls)
