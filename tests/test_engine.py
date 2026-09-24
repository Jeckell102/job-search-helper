"""Offline acceptance tests against the real pipeline and transactional repository."""
from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.core import POLICY_VERSION, job_key, material_hash, pack_snapshot, unpack_snapshot
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository, RepositoryError


def company(name="Acme", company_id="C-1"):
    return {"Company": name, "Company ID": company_id, "Company Status": "Active",
            "ATS / Source": "Greenhouse", "Official Careers URL": "https://boards.greenhouse.io/acme"}


def posting(identifier="123", **changes):
    row = {"company_id": "C-1", "company": "Acme", "ats": "Greenhouse", "posting_id": identifier,
           "req_id": "R-9", "url": f"https://boards.greenhouse.io/acme/jobs/{identifier}",
           "title": "Field Solutions Engineer", "description": "Integrate customer systems and train operators.",
           "location": "Ohio", "work_arrangement": "Remote", "compensation": "USD 140000–180000 annual base",
           "department": "Solutions", "created_at": "", "updated_at": "", "is_listed": True}
    row.update(changes)
    return row


class EngineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.state = State(self.directory / "state.db")
        self.addCleanup(self.state.close)
        self.repo = MemoryRepository({"Companies": [company()]})
        self.inventory = Inventory("complete", [posting()], "offline fixture")
        self.fetch_count = 0
        self.engine = Engine(self.repo, self.state, fetcher=self.fetch)
        self.print_capture = redirect_stdout(io.StringIO())
        self.print_capture.__enter__()
        self.addCleanup(self.print_capture.__exit__, None, None, None)
        self.file_number = 0

    def fetch(self, *args):
        self.fetch_count += 1
        return copy.deepcopy(self.inventory)

    def begin(self, *, all_companies=False):
        cycle = self.engine.start_cycle(None if all_companies else ["C-1"])
        self.engine.resume(cycle)
        return cycle

    def pending(self, cycle):
        return self.state.reviews(cycle, "pending")

    def decision(self, cycle, result="accept", **changes):
        review = self.pending(cycle)[0]
        value = {"job_key": review["job_key"], "description_hash": review["description_hash"],
                 "decision": result, "fit_level": "Strong", "narrative": "Customer integration and training fit; verify travel.",
                 "reviewer": "Offline test reviewer", "policy_version": POLICY_VERSION,
                 "mandatory_clearance": False, "code_authoring_required": False,
                 "primary_test_automation": False, "base_max_usd": 180000, "material_change": True}
        value.update(changes)
        return value

    def import_values(self, cycle, *values):
        self.file_number += 1
        path = self.directory / f"decision-{self.file_number}.jsonl"
        path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")
        return self.engine.import_decisions(cycle, path)

    def accept_initial(self):
        cycle = self.begin()
        self.import_values(cycle, self.decision(cycle))
        return cycle

    def user_edit(self, tab, row_index, **values):
        """Simulate edits by the user, not by the protected scanner writer."""
        tables = self.repo.tables
        tables[tab][row_index].update(values)
        self.repo._sheets = MemoryRepository(tables)._sheets

    def history(self):
        return self.repo.read("Job History")[0]

    def test_inventory_does_not_add_before_assessment(self):
        cycle = self.begin()
        self.assertEqual(self.repo.read("Opportunities"), [])
        self.assertEqual(self.history()["Added to Opportunities?"], "Pending")
        self.assertEqual(self.history()["Last Evaluated"], "")
        self.assertEqual(self.history()["Description Hash"], "")
        self.assertEqual(len(self.pending(cycle)), 1)
        self.assertEqual(self.engine.status(cycle)["status"], "Awaiting Review")

    def test_accept_creates_not_reviewed_and_blank_applied_date(self):
        cycle = self.accept_initial()
        row = self.repo.read("Opportunities")[0]
        self.assertEqual(row["Application Status"], "Not Reviewed")
        self.assertEqual(row["Date Applied"], "")
        self.assertEqual(row["Fit Review"], "Strong Potential Fit")
        self.assertEqual(self.history()["Reconsideration Count"], 0)
        self.assertEqual(self.engine.status(cycle)["status"], "Complete")

    def test_user_decisions_dates_and_notes_survive_changed_review(self):
        self.accept_initial()
        self.user_edit("Opportunities", 0, **{"Application Status": "Applied", "Date Applied": "2026-09-10",
                                             "Notes": "PERSONAL: spoke to Alex; do not remove."})
        self.inventory.jobs[0]["location"] = "Colorado"
        cycle = self.begin()
        self.import_values(cycle, self.decision(cycle))
        row = self.repo.read("Opportunities")[0]
        self.assertEqual(row["Application Status"], "Applied")
        self.assertEqual(row["Date Applied"], "2026-09-10")
        self.assertTrue(row["Notes"].startswith("PERSONAL: spoke to Alex; do not remove."))
        self.assertEqual(row["Location"], "Colorado")
        self.assertEqual(len(self.repo.read("Opportunities")), 1)

    def test_rejection_stored_only_in_history(self):
        cycle = self.begin()
        self.import_values(cycle, self.decision(cycle, "reject", narrative="Requires code authoring."))
        self.assertEqual(self.repo.read("Opportunities"), [])
        self.assertEqual(self.history()["Added to Opportunities?"], "No")
        self.assertEqual(self.history()["Rejection Reason"], "Requires code authoring.")

    def test_title_exclusions_are_recorded_and_queued_for_reviewer(self):
        self.inventory.jobs = [posting("a", title="Software Engineer"), posting("b", title="Payroll Operations Manager")]
        cycle = self.begin()
        self.assertEqual(len(self.repo.read("Job History")), 2)
        self.assertEqual(len(self.pending(cycle)), 2)
        self.assertEqual(self.repo.read("Opportunities"), [])
        self.assertEqual(self.repo.read("Companies")[0]["Last Inventory Count"], 2)
        self.assertEqual(self.engine.status(cycle)["status"], "Awaiting Review")

    def test_new_unlisted_posting_not_queued(self):
        self.inventory.jobs = [posting(is_listed=False)]
        cycle = self.begin()
        self.assertEqual(self.pending(cycle), [])
        self.assertEqual(self.repo.read("Job History"), [])

    def test_partial_inventory_never_increments_absence(self):
        self.accept_initial()
        original = self.history()
        self.inventory = Inventory("partial", [], "Incomplete page")
        for _ in range(2):
            cycle = self.begin()
            self.assertEqual(self.engine.status(cycle)["status"], "Complete with exceptions")
        self.assertEqual(self.history(), original)

    def test_blocked_scan_never_closes_or_updates_verification(self):
        self.accept_initial()
        original = self.history()
        self.inventory = Inventory("blocked", [], "CAPTCHA")
        cycle = self.begin()
        self.assertEqual(self.history(), original)
        row = self.repo.read("Companies")[0]
        self.assertEqual(row["Scan State"], "Blocked / Manual Review")
        self.assertEqual(row["Automatic Retry?"], "No")
        self.assertEqual(self.engine.status(cycle)["status"], "Complete with exceptions")

    def test_failed_and_unsupported_scans_never_close(self):
        self.accept_initial()
        original = self.history()
        self.inventory = Inventory("failed", [], "Timeout")
        self.begin()
        self.assertEqual(self.history(), original)
        self.user_edit("Companies", 0, **{"Automatic Retry?": "Yes"})
        self.inventory = Inventory("unsupported", [], "No adapter")
        self.begin()
        self.assertEqual(self.history(), original)

    def test_two_complete_absences_close_without_false_check_date(self):
        self.accept_initial()
        verified_date = self.history()["Last Checked"]
        self.inventory = Inventory("complete", [])
        self.begin()
        self.assertEqual(self.history()["Consecutive Missing Scans"], 1)
        self.assertEqual(self.history()["Job Status"], "Unable to verify")
        self.begin()
        self.assertEqual(self.history()["Consecutive Missing Scans"], 2)
        self.assertEqual(self.history()["Job Status"], "Closed")
        self.assertEqual(self.history()["Last Checked"], verified_date)
        self.assertIn("not directly verified", self.history()["Material Change Summary"])

    def test_reappearing_posting_resets_missing_count(self):
        self.accept_initial()
        self.inventory = Inventory("complete", [])
        self.begin()
        self.inventory = Inventory("complete", [posting()])
        self.begin()
        self.assertEqual(self.history()["Consecutive Missing Scans"], 0)
        self.assertEqual(self.history()["Job Status"], "Open and verified")

    def test_changed_detection_does_not_increment_reconsideration(self):
        self.accept_initial()
        old_hash = self.history()["Description Hash"]
        old_evaluated = self.history()["Last Evaluated"]
        self.inventory.jobs[0]["location"] = "Florida"
        cycle = self.begin()
        self.assertEqual(self.history()["Reconsideration Count"], 0)
        self.assertEqual(self.history()["Description Hash"], old_hash)
        self.assertEqual(self.history()["Last Evaluated"], old_evaluated)
        self.assertEqual(len(self.pending(cycle)), 1)

    def test_needs_info_is_deferred_and_does_not_consume_limit(self):
        self.accept_initial()
        self.inventory.jobs[0]["location"] = "Florida"
        cycle = self.begin()
        self.import_values(cycle, self.decision(cycle, "needs_info", narrative="Confirm a hard requirement."))
        self.assertEqual(self.history()["Reconsideration Count"], 0)
        self.assertEqual(len(self.pending(cycle)), 0)
        self.assertEqual(len(self.state.reviews(cycle, "deferred")), 1)
        self.assertEqual(self.engine.status(cycle)["status"], "Complete with exceptions")

    def test_second_completed_reconsideration_freezes_all_job_updates(self):
        self.accept_initial()
        for number, location in enumerate(("Colorado", "Florida"), 1):
            self.inventory.jobs[0]["location"] = location
            cycle = self.begin()
            self.assertEqual(self.history()["Reconsideration Count"], number - 1)
            self.import_values(cycle, self.decision(cycle))
            self.assertEqual(self.history()["Reconsideration Count"], number)
        self.assertEqual(self.history()["Reconsideration Status"], "Frozen after 2")
        before_history = self.history()
        before_opportunity = self.repo.read("Opportunities")
        self.inventory.jobs[0]["location"] = "Washington"
        cycle = self.begin()
        self.assertEqual(self.pending(cycle), [])
        self.assertEqual(self.history(), before_history)
        self.assertEqual(self.repo.read("Opportunities"), before_opportunity)
        self.inventory.jobs = []
        self.begin()
        self.begin()
        self.assertEqual(self.history(), before_history)
        self.assertEqual(self.repo.read("Opportunities"), before_opportunity)

    def test_nonmaterial_refresh_does_not_consume_reconsideration(self):
        self.accept_initial()
        self.inventory.jobs[0]["description"] += " Updated company tagline."
        cycle = self.begin()
        self.import_values(cycle, self.decision(cycle, material_change=False))
        self.assertEqual(self.history()["Reconsideration Count"], 0)
        self.assertIn("Nonmaterial source refresh", self.history()["Review Notes"])

    def test_legacy_missing_hash_is_initial_evidence_baseline(self):
        self.repo = MemoryRepository({"Companies": [company()], "Job History": [{
            "Company": "Acme", "Job Title": "Field Solutions Engineer", "Job Key": "LEGACY-123",
            "Official Job URL": posting()["url"], "Reconsideration Count": 0, "Last Evaluated": "2020-01-01"}]})
        self.engine.repo = self.repo
        cycle = self.begin()
        review = self.pending(cycle)[0]
        self.assertEqual(review["job_key"], "LEGACY-123")
        self.assertEqual(review["changed_fields"], ["Initial evidence baseline"])
        self.import_values(cycle, self.decision(cycle))
        self.assertEqual(self.history()["Reconsideration Count"], 0)
        self.assertEqual(len(self.repo.read("Job History")), 1)

    def test_remote_commit_local_checkpoint_crash_recovery_no_duplicate(self):
        cycle = self.begin()
        decision = self.decision(cycle)
        original = self.state.apply_buffer
        def fail_completed(updates, cycles):
            if any(status == "completed" for data, status in updates.values()):
                raise RuntimeError("Injected interruption after remote commit")
            return original(updates, cycles)
        with patch.object(self.state, "apply_buffer", side_effect=fail_completed):
            with self.assertRaises(RuntimeError):
                self.import_values(cycle, decision)
        self.assertEqual(len(self.repo.read("Opportunities")), 1)
        notes_before = self.repo.read("Opportunities")[0]["Notes"]
        self.assertEqual(len(self.pending(cycle)), 1)
        self.import_values(cycle, decision)
        self.assertEqual(len(self.repo.read("Opportunities")), 1)
        self.assertEqual(self.repo.read("Opportunities")[0]["Notes"], notes_before)
        self.assertEqual(self.pending(cycle), [])
        self.assertEqual(self.history()["Reconsideration Count"], 0)

    def test_stale_decision_hash_rejected_without_mutation(self):
        cycle = self.begin()
        before = self.repo.tables
        with self.assertRaisesRegex(ValueError, "Stale assessment"):
            self.import_values(cycle, self.decision(cycle, description_hash="outdated-hash"))
        self.assertEqual(self.repo.tables, before)
        self.assertEqual(len(self.pending(cycle)), 1)

    def test_completed_cycle_resume_never_refetches_or_restarts(self):
        cycle = self.accept_initial()
        self.assertEqual(self.fetch_count, 1)
        self.engine.resume(cycle)
        self.engine.resume(cycle)
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(len(self.state.cycles()), 1)
        self.assertEqual(len(self.repo.read("Scan Cycles")), 1)

    def test_awaiting_review_resume_does_not_refetch_inventory(self):
        cycle = self.begin()
        self.engine.resume(cycle)
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(len(self.pending(cycle)), 1)

    def test_unchanged_posting_not_reassessed(self):
        self.accept_initial()
        evaluated = self.history()["Last Evaluated"]
        cycle = self.begin()
        self.assertEqual(self.pending(cycle), [])
        self.assertEqual(self.history()["Last Evaluated"], evaluated)
        self.assertEqual(self.history()["Reconsideration Count"], 0)

    def test_lost_local_cache_recovers_completed_cycle_without_refetch(self):
        cycle = self.accept_initial()
        recovered = State()
        self.addCleanup(recovered.close)
        engine = Engine(self.repo, recovered, fetcher=self.fetch)
        status = engine.resume(cycle)
        self.assertEqual(status["status"], "Complete")
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(len(self.repo.read("Opportunities")), 1)

    def test_dry_run_isolated_memory_and_sqlite_clone_preserve_originals(self):
        before_db = (self.directory / "state.db").read_bytes()
        before_tables = self.repo.tables
        isolated_state = self.state.clone()
        self.addCleanup(isolated_state.close)
        isolated_repo = MemoryRepository(self.repo.tables)
        engine = Engine(isolated_repo, isolated_state, dry_run=True, fetcher=self.fetch)
        cycle = engine.start_cycle(["C-1"])
        engine.resume(cycle)
        self.assertEqual(self.repo.tables, before_tables)
        self.assertEqual((self.directory / "state.db").read_bytes(), before_db)
        self.assertEqual(self.state.cycles(), [])
        self.assertEqual(len(isolated_state.reviews(cycle, "pending")), 1)

    def test_atomic_job_commit_rolls_back_history_when_opportunity_fails(self):
        cycle = self.begin()
        sheet = self.repo._sheets["Opportunities"]
        col = sheet.headers.index("Fit Review")
        sheet.cells[(1, col)] = {"dataValidation": {"strict": True, "condition": {
            "type": "ONE_OF_LIST", "values": [{"userEnteredValue": "NOT-A-VALID-FIT"}]}}}
        before = self.repo.tables
        with self.assertRaises(RepositoryError):
            self.import_values(cycle, self.decision(cycle))
        self.assertEqual(self.repo.tables, before)
        self.assertEqual(self.repo.read("Opportunities"), [])
        self.assertEqual(len(self.pending(cycle)), 1)
        self.assertEqual(self.history()["Last Evaluated"], "")

    def test_new_company_blank_date_and_id_detected_at_start(self):
        self.repo = MemoryRepository({"Companies": [company(company_id="")]})
        self.engine.repo = self.repo
        cycle = self.begin(all_companies=True)
        row = self.repo.read("Companies")[0]
        self.assertTrue(row["Company ID"].startswith("COMP-"))
        self.assertTrue(row["Date Added"])
        self.assertEqual(len(self.pending(cycle)), 1)

    def test_new_requisition_with_same_title_remains_distinct(self):
        self.accept_initial()
        self.inventory.jobs.append(posting("456"))
        cycle = self.begin()
        self.assertEqual(len(self.pending(cycle)), 1)
        self.import_values(cycle, self.decision(cycle))
        self.assertEqual(len(self.repo.read("Job History")), 2)
        self.assertEqual(len(self.repo.read("Opportunities")), 2)

    def test_tracking_url_change_matches_existing_history_and_opportunity(self):
        self.accept_initial()
        self.inventory.jobs[0]["url"] += "?utm_source=new-search"
        cycle = self.begin()
        self.assertEqual(self.pending(cycle), [])
        self.assertEqual(len(self.repo.read("Job History")), 1)
        self.assertEqual(len(self.repo.read("Opportunities")), 1)

    def test_blocked_company_not_retried_without_explicit_request(self):
        self.inventory = Inventory("blocked", [], "CAPTCHA")
        cycle = self.begin()
        self.engine.resume(cycle)
        self.assertEqual(self.fetch_count, 1)
        self.inventory = Inventory("complete", [])
        self.engine.resume(cycle, retry_blocked=True)
        self.assertEqual(self.fetch_count, 2)
        self.assertEqual(self.engine.status(cycle)["status"], "Complete")

    def test_new_company_without_id_added_midcycle_is_discovered(self):
        self.inventory = Inventory("complete", [])
        def insert_company(*args):
            if self.fetch_count == 0:
                tables = self.repo.tables
                tables["Companies"].append(company("New Employer", ""))
                self.repo._sheets = MemoryRepository(tables)._sheets
            return self.fetch(*args)
        self.engine.fetcher = insert_company
        cycle = self.begin(all_companies=True)
        self.assertEqual(self.fetch_count, 2)
        self.assertEqual(len(self.state.cycle(cycle)["companies"]), 2)

    def test_new_cycle_cache_loss_does_not_reuse_old_company_complete_state(self):
        self.accept_initial()
        self.assertEqual(self.repo.read("Companies")[0]["Scan State"], "Complete")
        fresh_cycle = self.engine.start_cycle(["C-1"])
        recovered = State()
        self.addCleanup(recovered.close)
        engine = Engine(self.repo, recovered, fetcher=self.fetch)
        engine.resume(fresh_cycle)
        self.assertEqual(self.fetch_count, 2)
        self.assertEqual(engine.status(fresh_cycle)["status"], "Complete")

    def test_import_after_interrupted_staging_does_not_skip_remaining_job(self):
        self.engine.batch_size = 1  # This test interrupts between two committed batches.
        self.inventory.jobs.append(posting("456"))
        cycle = self.engine.start_cycle(["C-1"])
        original = self.engine._stage_posting
        def interrupted(current_cycle, current_company, current_posting):
            if current_posting["posting_id"] == "456":
                raise RuntimeError("Injected interruption before staging second job")
            return original(current_cycle, current_company, current_posting)
        with patch.object(self.engine, "_stage_posting", side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                self.engine.resume(cycle)
        self.assertEqual(len(self.pending(cycle)), 1)
        self.import_values(cycle, self.decision(cycle))
        self.assertNotEqual(self.engine.status(cycle)["status"], "Complete")
        self.assertNotEqual(self.repo.read("Companies")[0]["Scan State"], "Complete")
        self.engine.resume(cycle)
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(len(self.pending(cycle)), 1)
        self.assertEqual(self.pending(cycle)[0]["posting"]["posting_id"], "456")
        self.import_values(cycle, self.decision(cycle))
        self.assertEqual(len(self.repo.read("Opportunities")), 2)
        self.assertEqual(self.engine.status(cycle)["status"], "Complete")

    def test_stable_id_changed_url_keeps_one_opportunity_and_alias(self):
        self.accept_initial()
        original_url = self.repo.read("Opportunities")[0]["Job URL"]
        self.user_edit("Opportunities", 0, **{"Application Status": "Applied", "Notes": "USER DECISION"})
        self.inventory.jobs[0]["url"] = "https://careers.acme.example/new-path?id=123"
        self.inventory.jobs[0]["location"] = "Colorado"
        cycle = self.begin()
        self.import_values(cycle, self.decision(cycle))
        self.assertEqual(len(self.repo.read("Opportunities")), 1)
        row = self.repo.read("Opportunities")[0]
        self.assertEqual(row["Job URL"], original_url)
        self.assertEqual(row["Application Status"], "Applied")
        self.assertTrue(row["Notes"].startswith("USER DECISION"))
        self.assertIn(self.inventory.jobs[0]["url"], row["Notes"])
        self.assertEqual(self.history()["Official Job URL"], self.inventory.jobs[0]["url"])
        self.assertEqual(unpack_snapshot(self.history()["Current Snapshot"])["opportunity_url"], original_url)

    def test_reused_url_new_posting_id_requires_manual_disambiguation(self):
        self.accept_initial()
        history_before = self.repo.read("Job History")
        opportunities_before = self.repo.read("Opportunities")
        self.inventory.jobs[0]["posting_id"] = "NEW-POSTING-456"
        cycle = self.engine.start_cycle(["C-1"])
        with self.assertRaisesRegex(ValueError, "[Mm]anual disambiguation"):
            self.engine.resume(cycle)
        self.assertEqual(self.repo.read("Job History"), history_before)
        self.assertEqual(self.repo.read("Opportunities"), opportunities_before)

    def test_inventory_from_different_board_does_not_close_prior_board_jobs(self):
        self.accept_initial()
        original = self.history()
        self.user_edit("Companies", 0, **{"Official Careers URL": "https://boards.greenhouse.io/acme-other"})
        self.inventory = Inventory("complete", [])
        self.begin()
        self.begin()
        self.assertEqual(self.history(), original)

    def test_external_claim_blocks_decision_import(self):
        cycle = self.begin()
        decision = self.decision(cycle)
        self.user_edit("Companies", 0, **{"Claimed By": "other-worker", "Claim Token": "active-other-token"})
        before = self.repo.tables
        with self.assertRaisesRegex(ValueError, "[Cc]laim"):
            self.import_values(cycle, decision)
        self.assertEqual(self.repo.tables, before)
        self.assertEqual(len(self.pending(cycle)), 1)


if __name__ == "__main__":
    unittest.main()
