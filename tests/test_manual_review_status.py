"""Manual-review outcomes remain distinct from jobs awaiting automated review."""
from copy import deepcopy
import unittest

from job_search_helper.core import POLICY_VERSION, material_hash
from job_search_helper.batching import PlanningRepository
from job_search_helper.repository import GoogleRepository
from job_search_helper.review_queue import build_review_queues
from sheets_fixture import RangeSheets
import test_v3_direct_sheet as fixtures


class ManualReviewStatusTests(unittest.TestCase):
    def setUp(self):
        self.company, self.posting, self.repo, self.state, self.engine = fixtures.DirectSheetWorkflowTests().make()
        self.addCleanup(self.state.close)
        self.engine._stage_posting({"id":"CYC"},self.company,self.posting)
        self.key=self.row()["Job Key"]

    def row(self):
        return self.repo.read("Job History")[0]

    def edit(self,values):
        self.repo.commit([{"tab":"Job History","identity":{"Job Key":self.key},"values":values}])

    def decision(self,kind="needs_info"):
        return {"decision":kind,"narrative":"Human confirmation required.","reviewer":"test",
                "material_change":False,"fit_level":"Strong","base_max_usd":190000}

    def test_direct_needs_info_writes_manual_status_in_both_columns(self):
        claim=self.engine.claim_next_review()
        self.assertEqual(self.engine.apply_ai_decision(claim,self.decision()),"manual_review")
        row=self.row()
        self.assertEqual((row["Added to Opportunities?"],row["Review Status"],row["Decision"]),
                         ("Manual Review","Manual Review","Needs Info"))
        self.assertIsNone(self.engine.claim_next_review())
        self.assertEqual(self.repo.read("Opportunities"),[])

    def test_unchanged_source_preserves_manual_result_and_human_notes(self):
        self.edit({"Added to Opportunities?":"Manual Review","Review Status":"Manual Review",
                   "Decision":"Needs Info","Review Notes":"Human confirmation required."})
        before=self.row()
        self.engine._stage_posting({"id":"CYC"},self.company,deepcopy(self.posting))
        row=self.row()
        for field in ("Added to Opportunities?","Review Status","Decision","Review Notes","Source Hash"):
            self.assertEqual(row[field],before[field])
        self.assertIsNone(self.engine.claim_next_review())
        queued=build_review_queues(self.repo)
        self.assertFalse(queued["first_pass"] or queued["second_pass"])

    def test_changed_source_reopens_manual_outcome_for_fresh_review(self):
        self.edit({"Added to Opportunities?":"Manual Review","Review Status":"Manual Review","Decision":"Needs Info"})
        before=self.row()
        self.engine._stage_posting({"id":"CYC"},self.company,fixtures.posting(description="Materially changed responsibilities"))
        row=self.row()
        self.assertNotEqual(row["Source Hash"],before["Source Hash"])
        self.assertEqual((row["Added to Opportunities?"],row["Review Status"],row["Decision"]),("Pending","Needs Review",""))
        self.assertIsNotNone(self.engine.claim_next_review())

    def test_narrow_planning_snapshot_keeps_hash_for_manual_reassessment(self):
        self.edit({"Added to Opportunities?":"Manual Review","Review Status":"Manual Review","Decision":"Needs Info"})
        old=self.row()
        service=RangeSheets({"Companies":[self.company],"Job History":[old]})
        planner=PlanningRepository(GoogleRepository(service,"fixture",min_request_interval=0))
        self.assertEqual(planner.rows["Job History"][0]["Source Hash"],old["Source Hash"])
        planner.begin()
        self.engine.repo=planner
        self.engine._stage_posting({"id":"CYC"},self.company,fixtures.posting(description="Changed source duties"))
        operation=next(op for op in planner.operations if op["tab"]=="Job History")
        self.assertEqual(operation["values"]["Added to Opportunities?"],"Pending")
        self.assertEqual(operation["expected"]["Source Hash"],old["Source Hash"])

    def test_manual_choice_prevents_claim_even_if_review_status_is_stale(self):
        self.edit({"Added to Opportunities?":"Manual Review"})
        self.assertIsNone(self.engine.claim_next_review())
        self.assertFalse(self.engine.last_review_queue_pending)

    def test_manual_choice_during_active_review_prevents_commit(self):
        claim=self.engine.claim_next_review()
        self.edit({"Added to Opportunities?":"Manual Review","Review Status":"In Progress"})
        before=self.row()
        with self.assertRaisesRegex(ValueError,"Manual .*choice"):
            self.engine.apply_ai_decision(claim,self.decision("accept"))
        self.assertEqual(self.row(),before)
        self.assertEqual(self.repo.read("Opportunities"),[])

    def test_user_no_during_review_prevents_needs_info_from_overwriting_choice(self):
        claim=self.engine.claim_next_review()
        self.edit({"Added to Opportunities?":"No","Review Status":"In Progress"})
        before=self.row()
        with self.assertRaisesRegex(ValueError,"Manual opportunity choice"):
            self.engine.apply_ai_decision(claim,self.decision())
        self.assertEqual(self.row(),before)

    def test_needs_info_preserves_existing_yes_and_no_during_reassessment(self):
        for added in ("Yes","No"):
            with self.subTest(added=added):
                self.edit({"Added to Opportunities?":added,"Review Status":"Needs Review"})
                claim=self.engine.claim_next_review()
                self.assertEqual(self.engine.apply_ai_decision(claim,self.decision()),"manual_review")
                self.assertEqual(self.row()["Added to Opportunities?"],added)
                self.assertEqual(self.row()["Review Status"],"Manual Review")

    def test_missing_snapshot_preserves_existing_yes_and_no(self):
        for added in ("Yes","No"):
            with self.subTest(added=added):
                self.edit({"Added to Opportunities?":added,"Review Status":"Needs Review","Current Snapshot":""})
                self.assertIsNone(self.engine.claim_next_review())
                self.assertEqual(self.row()["Added to Opportunities?"],added)
                self.assertEqual(self.row()["Review Status"],"Manual Review")

    def test_missing_source_snapshot_sets_manual_status_in_both_columns(self):
        self.edit({"Current Snapshot":""})
        self.assertIsNone(self.engine.claim_next_review())
        self.assertEqual((self.row()["Added to Opportunities?"],self.row()["Review Status"]),("Manual Review","Manual Review"))

    def test_legacy_import_sets_manual_status_without_reconsideration(self):
        review={"job_key":self.key,"company_id":self.company["Company ID"],"posting":self.posting,
                "description_hash":material_hash(self.posting)}
        self.state.save_cycle({"id":"CYC","status":"In Progress","companies":{},"all":False,"started_at":"2026-09-28T00:00:00+00:00"})
        self.state.put_review("CYC",self.key,review)
        decision={**self.decision(),"job_key":self.key,"description_hash":review["description_hash"],"policy_version":POLICY_VERSION}
        self.engine._import_decision_records("CYC",[decision])
        self.assertEqual((self.row()["Added to Opportunities?"],self.row()["Review Status"]),("Manual Review","Manual Review"))
        self.assertEqual(self.row()["Reconsideration Count"],0)


if __name__=="__main__":
    unittest.main()
