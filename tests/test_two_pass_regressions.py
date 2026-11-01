import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import MagicMock, patch

from job_search_helper import runner
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repository import MemoryRepository
from job_search_helper.review_queue import build_review_queues, export_review_queues, score_posting, _score_band
from job_search_helper.title_audit import load_title_audits
import test_review_queue as fixtures


def repo_for(rows, descriptions=None):
    history = [{"Job Key": str(i), "Source Hash": "h" + str(i),
                "Job Title": "Coordinator", "Review Status": "Needs Review",
                "Added to Opportunities?": "Pending", **row} for i, row in enumerate(rows)]
    evidence = [{"Job Key": row["Job Key"], "Source Hash": row["Source Hash"],
                 "Job Description": (descriptions or ["Details"] * len(rows))[i]}
                for i, row in enumerate(history)]
    return MemoryRepository({"Job History": history, "Job Evidence": evidence})


def fixed_score(value):
    return {"score": value, "title_score": value, "description_score": 0, "score_reasons": []}

class QueueRegressions(unittest.TestCase):
    def test_band_boundaries_and_routing(self):
        scores = [0, 7, 8, 16, 17, 29, 30]
        with patch("job_search_helper.review_queue.score_posting", side_effect=[fixed_score(x) for x in scores]):
            result = build_review_queues(repo_for([{} for _ in scores]))
        self.assertEqual({x["score"] for x in result["first_pass"]}, {0, 7, 8, 16})
        self.assertEqual({x["score"] for x in result["second_pass"]}, {17, 29, 30})
        self.assertEqual(result["summary"]["band_counts"], {
            "SECOND_PASS_HIGH": 1, "SECOND_PASS_STANDARD": 2, "FIRST_PASS_BORDERLINE": 2,
            "FIRST_PASS_LOW": 2, "FIRST_PASS_TITLE_FILTER_AUDIT": 0})

    def test_high_band_missing_or_truncated_evidence_stays_first(self):
        with patch("job_search_helper.review_queue.score_posting", return_value=fixed_score(45)):
            result = build_review_queues(repo_for([{}, {}], ["", "Details [TRUNCATED — fetch remainder]"]))
        self.assertEqual(len(result["second_pass"]), 0)
        self.assertTrue(all(x["evidence_missing"] for x in result["first_pass"]))
        self.assertTrue(all(x["band"] == "SECOND_PASS_HIGH" for x in result["first_pass"]))

    def test_salary_exclusion_works_without_description(self):
        result = build_review_queues(repo_for([{"Salary / Range": "$90,000-$110,000 annual base"}], [""]))
        self.assertEqual(len(result["first_pass"]), 0)
        self.assertIn("Compensation exclusion", result["deterministic_filtered"][0]["reason"])

    def test_other_hard_exclusion_precedes_title_rescue(self):
        result = build_review_queues(repo_for([{"Job Title": "Software Engineer"}], ["Travel required 75%."]))
        self.assertFalse(result["first_pass"])
        self.assertIn("Travel exclusion", result["deterministic_filtered"][0]["reason"])
        self.assertFalse(result["deterministic_filtered"][0]["first_pass_audit"])

    def test_existing_decisions_claims_closed_and_frozen_are_untouched(self):
        repo = repo_for([{"Added to Opportunities?": "No"}, {"Review Status": "Reviewed"},
                        {"Review Status": "In Progress"}, {"Job Status": "Closed"},
                        {"Reconsideration Status": "Frozen after 2"},
                        {"Added to Opportunities?": "Manual Review"},
                        {"Review Status": "Manual Review"}])
        before = repo.read("Job History")
        result = build_review_queues(repo)
        self.assertFalse(result["first_pass"] or result["second_pass"])
        self.assertEqual(before, repo.read("Job History"))

    def test_word_fragments_do_not_score_but_inflections_do(self):
        self.assertEqual(score_posting("", "performance commission demographic")["score"], 0)
        phrases = {x["phrase"] for x in score_posting("", "RF demonstrations troubleshooting")["score_reasons"]}
        self.assertTrue({"rf", "demonstration", "troubleshoot"}.issubset(phrases))

    def test_threshold_tuning_and_band_labels_agree(self):
        self.assertEqual(_score_band(12, 12), "SECOND_PASS_STANDARD")
        with self.assertRaises(ValueError):
            build_review_queues(repo_for([{}]), threshold=31)

    def test_stale_evidence_is_not_used(self):
        repo = MemoryRepository({"Job History": [{"Job Key": "k", "Source Hash": "new",
            "Job Title": "Technical Program Manager", "Added to Opportunities?": "Pending",
            "Review Status": "Needs Review"}], "Job Evidence": [{"Job Key": "k",
            "Source Hash": "old", "Job Description": "hardware systems integration field deployment"}]})
        result = build_review_queues(repo)
        self.assertFalse(result["second_pass"])
        self.assertTrue(result["first_pass"][0]["evidence_missing"])

    def test_export_cleanup_manifest_and_decision_preservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("full-review.jsonl", "title-audit.jsonl", "first-pass-decisions.jsonl"):
                (root / name).write_text("keep")
            with self.assertRaises(ValueError):
                export_review_queues(repo_for([{}]), root)
            summary = export_review_queues(repo_for([{}]), root, overwrite=True)
            self.assertFalse((root / "full-review.jsonl").exists())
            self.assertFalse((root / "title-audit.jsonl").exists())
            self.assertEqual((root / "first-pass-decisions.jsonl").read_text(), "keep")
            for name, digest in summary["file_sha256"].items():
                self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), digest)

    def test_failed_build_keeps_previous_queue_and_legacy_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            export_review_queues(repo_for([{}]), root)
            (root / "full-review.jsonl").write_text("legacy")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            with patch("job_search_helper.review_queue.build_review_queues", side_effect=RuntimeError("read failed")):
                with self.assertRaisesRegex(RuntimeError, "read failed"):
                    export_review_queues(repo_for([{}]), root, overwrite=True)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


class TitleAuditRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "inventories.sqlite3"
        self.inbox = InventoryInbox(self.path, "test-sheet")
        self.addCleanup(self.inbox.close)
        self.posting = {"ats": "greenhouse", "posting_id": "1", "title": "Software Engineer",
                        "url": "https://example.test/jobs/1", "description": "hardware integration",
                        "compensation": "$150,000 annual base", "company": "Not for AI"}
        self.payload = {"inventory_status": "complete", "fetched_at": "2026-09-26T10:00:00Z",
                        "ats": "greenhouse", "jobs": [self.posting]}

    def test_audit_survives_acknowledgment_and_is_company_free(self):
        self.inbox.save("cycle", "company-id", self.payload)
        self.inbox.acknowledge("cycle", "company-id")
        records, _ = load_title_audits(self.path, "test-sheet")
        self.assertEqual(len(records), 1)
        repo = repo_for([])
        result = build_review_queues(repo, inventory_database=self.path)
        first = result["first_pass"][0]
        self.assertEqual(first["band"], "FIRST_PASS_TITLE_FILTER_AUDIT")
        self.assertEqual(first["evidence_source"], "local_title_audit")
        self.assertIsNone(first["row_number"])
        self.assertNotIn("company", first)
        self.assertNotIn("job_description", first)
        self.assertFalse(repo.read("Job History"))
        self.assertEqual(len(result["deterministic_filtered"]), 1)

    def test_reviewed_legacy_url_is_not_reopened_by_local_audit(self):
        self.inbox.save("cycle", "company-id", self.payload)
        repo = repo_for([{"Job Key": "legacy-key", "Official Job URL": self.posting["url"],
                         "Added to Opportunities?": "No", "Review Status": "Reviewed"}])
        result = build_review_queues(repo, inventory_database=self.path)
        self.assertFalse(result["first_pass"])
        self.assertEqual(result["summary"]["local_title_audit_existing_history_skipped"], 1)

    def test_failed_inventory_keeps_audit_but_complete_empty_retires_it(self):
        self.inbox.save("one", "company-id", self.payload)
        self.inbox.acknowledge("one", "company-id")
        failed = dict(self.payload, inventory_status="failed", jobs=[], fetched_at="2026-09-26T11:00:00Z")
        self.inbox.save("two", "company-id", failed)
        self.assertEqual(len(load_title_audits(self.path)[0]), 1)
        empty = dict(failed, inventory_status="complete", fetched_at="2026-09-26T12:00:00Z")
        self.inbox.save("three", "company-id", empty)
        self.inbox.acknowledge("three", "company-id")
        self.assertEqual(len(load_title_audits(self.path)[0]), 0)

    def test_wrong_workbook_and_nonexistent_db_are_safe(self):
        with self.assertRaisesRegex(ValueError, "different spreadsheet"):
            load_title_audits(self.path, "different-sheet")
        absent = self.path.with_name("absent.sqlite3")
        self.assertEqual(load_title_audits(absent)[0], [])
        self.assertFalse(absent.exists())


class RunnerRefreshRegressions(unittest.TestCase):
    def test_lifecycle_refreshes_before_and_after(self):
        events = []
        with patch.object(runner, "_refresh_review_queue", side_effect=lambda *a: events.append("refresh")):
            with runner._review_queue_lifecycle(object(), Path("unused")):
                events.append("work")
        self.assertEqual(events, ["refresh", "work", "refresh"])

    def test_interruption_still_refreshes(self):
        with patch.object(runner, "_refresh_review_queue") as refresh:
            with self.assertRaises(KeyboardInterrupt):
                with runner._review_queue_lifecycle(object(), Path("unused")):
                    raise KeyboardInterrupt()
        self.assertEqual(refresh.call_count, 2)

    def test_failed_final_refresh_does_not_hide_original_error(self):
        with patch.object(runner, "_refresh_review_queue", side_effect=[None, RuntimeError("refresh failed")]), redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "original scrape error"):
                with runner._review_queue_lifecycle(object(), Path("unused")):
                    raise ValueError("original scrape error")

    def test_empty_sync_runs_both_refreshes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = MagicMock(spreadsheet_id="test-sheet", metrics={})
            engine = MagicMock(performance={})
            engine.sync_manual_opportunities.return_value = {"added": 0, "skipped": 0}
            with patch.object(runner, "_load_environment"), patch.object(runner, "state_path", return_value=Path(directory) / "state.db"), patch.object(runner, "get_repository", return_value=repo), patch.object(runner, "Engine", return_value=engine), patch.object(runner, "_refresh_review_queue") as refresh, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.run_start(sync_only=True, browser_fallback=False), 0)
            self.assertEqual(refresh.call_count, 2)
            engine.resume_local.assert_not_called()
