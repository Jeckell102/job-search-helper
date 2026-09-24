"""Failure/recovery and request-count acceptance checks; entirely offline."""
import copy
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from job_search_helper import cli
from job_search_helper.ats import Inventory
from job_search_helper.batching import PlanningRepository
from job_search_helper.core import POLICY_VERSION, excluded_title, plain_text
from job_search_helper.engine import Engine, State
from job_search_helper.repository import GoogleRepository, MemoryRepository, RepositoryError, SCHEMAS
from test_engine import company, posting
from test_repository import FakeSheets


class StatefulSheets(FakeSheets):
    """Apply actual updateCells requests to an in-memory Sheets service."""
    def batchUpdate(self, **kwargs):
        self.batches.append(copy.deepcopy(kwargs))
        outer = self
        class Response:
            def execute(self):
                if outer.write_error:
                    raise outer.write_error
                saved = copy.deepcopy(outer.sheets)
                for request in kwargs["body"]["requests"]:
                    if "updateCells" in request:
                        update = request["updateCells"]
                        start = update["start"]
                        sheet = next(s for s in saved if s["properties"]["sheetId"] == start["sheetId"])
                        rows = sheet["data"][0]["rowData"]
                        for i, row in enumerate(update["rows"], start["rowIndex"]):
                            while len(rows) <= i:
                                rows.append({"values": []})
                            values = rows[i]["values"]
                            for j, cell in enumerate(row["values"], start["columnIndex"]):
                                while len(values) <= j:
                                    values.append({})
                                values[j]["userEnteredValue"] = copy.deepcopy(cell["userEnteredValue"])
                                values[j]["effectiveValue"] = copy.deepcopy(cell["userEnteredValue"])
                    elif "appendDimension" in request:
                        update = request["appendDimension"]
                        sheet = next(s for s in saved if s["properties"]["sheetId"] == update["sheetId"])
                        sheet["properties"]["gridProperties"]["rowCount"] += update["length"]
                    elif "updateTable" in request:
                        table = request["updateTable"]["table"]
                        old = next(t for s in saved for t in s["tables"] if t["tableId"] == table["tableId"])
                        old["range"] = table["range"]
                    else:
                        raise AssertionError("Unexpected write operation")
                outer.sheets = saved
                return {}
        return Response()


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.addCleanup(self.state.close)
        self.repo = MemoryRepository({"Companies": [company()]})
        self.jobs = [posting(str(i)) for i in range(61)]
        self.fetch_count = 0
        self.engine = Engine(self.repo, self.state, fetcher=self.fetch)
        self.output = io.StringIO()
        capture = redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def fetch(self, *args):
        self.fetch_count += 1
        return Inventory("complete", copy.deepcopy(self.jobs))

    def start(self):
        return self.engine.start_cycle(["C-1"])

    def pending(self, cycle):
        return self.state.reviews(cycle, "pending")

    def index(self, cycle):
        return self.state.cycle(cycle)["companies"]["C-1"].get("next_job_index", 0)

    def decision_file(self, cycle):
        path = Path(self.temp.name) / "decisions.jsonl"
        decisions = [dict(job_key=r["job_key"], description_hash=r["description_hash"], decision="accept",
                          fit_level="Possible", narrative="Customer integration and training match; verify travel.",
                          reviewer="Offline test", policy_version=POLICY_VERSION, mandatory_clearance=False,
                          code_authoring_required=False, primary_test_automation=False, base_max_usd=180000,
                          material_change=True) for r in self.pending(cycle)]
        path.write_text("".join(json.dumps(d) + "\n" for d in decisions), encoding="utf-8")
        return path

    def test_61_jobs_saved_in_three_batches_with_progress(self):
        cycle = self.start()
        original = self.repo.commit
        batches = []
        def commit(ops):
            if any(op["tab"] == "Job History" for op in ops):
                batches.append(copy.deepcopy(ops))
            return original(ops)
        with patch.object(self.repo, "commit", side_effect=commit):
            result = self.engine.resume(cycle)
        self.assertEqual([len(b) for b in batches], [25, 25, 11])
        self.assertEqual(result["pending_reviews"], 61)
        self.assertEqual(result["status"], "Awaiting Review")
        self.assertEqual(self.index(cycle), 61)
        self.assertIn("saved 25/61", self.output.getvalue())
        self.assertIn("saved 61/61", self.output.getvalue())

    def test_failed_second_batch_resumes_saved_inventory_without_duplicates(self):
        cycle = self.start()
        original = self.repo.commit
        attempts = 0
        def commit(ops):
            nonlocal attempts
            if any(op["tab"] == "Job History" for op in ops):
                attempts += 1
                if attempts == 2:
                    raise TimeoutError("Simulated transport failure")
            return original(ops)
        with patch.object(self.repo, "commit", side_effect=commit), self.assertRaises(TimeoutError):
            self.engine.resume(cycle)
        self.assertEqual(self.index(cycle), 25)
        self.assertEqual(len(self.repo.read("Job History")), 25)
        self.assertEqual(len(self.pending(cycle)), 25)
        self.engine.resume(cycle)
        self.assertEqual(self.fetch_count, 1)
        self.assertEqual(self.index(cycle), 61)
        rows = self.repo.read("Job History")
        self.assertEqual(len(rows), 61)
        self.assertEqual(len({r["Job Key"] for r in rows}), 61)

    def test_remote_success_lost_response_replay_repairs_queue(self):
        cycle = self.start()
        original = self.repo.commit
        def commit(ops):
            result = original(ops)
            if any(op["tab"] == "Job History" for op in ops):
                raise TimeoutError("Server committed; response was lost")
            return result
        with patch.object(self.repo, "commit", side_effect=commit), self.assertRaises(TimeoutError):
            self.engine.resume(cycle)
        self.assertEqual(self.index(cycle), 0)
        self.assertEqual(len(self.pending(cycle)), 0)
        self.assertEqual(len(self.repo.read("Job History")), 25)
        self.engine.resume(cycle)
        self.assertEqual(len(self.pending(cycle)), 61)
        self.assertEqual(len(self.repo.read("Job History")), 61)
        self.assertEqual(self.fetch_count, 1)

    def test_local_checkpoint_failure_replays_acknowledged_batch(self):
        cycle = self.start()
        with patch.object(self.state, "apply_buffer", side_effect=OSError("disk full")), self.assertRaises(OSError):
            self.engine.resume(cycle)
        self.assertEqual(self.index(cycle), 0)
        self.assertEqual(len(self.repo.read("Job History")), 25)
        self.engine.resume(cycle)
        self.assertEqual(len(self.pending(cycle)), 61)
        self.assertEqual(len(self.repo.read("Job History")), 61)

    def test_ctrl_c_mid_plan_saves_neither_partial_rows_nor_checkpoint(self):
        cycle = self.start()
        original = self.engine._stage_posting
        count = 0
        def stage(*args):
            nonlocal count
            count += 1
            if count == 8:
                raise KeyboardInterrupt()
            return original(*args)
        with patch.object(self.engine, "_stage_posting", side_effect=stage), self.assertRaises(KeyboardInterrupt):
            self.engine.resume(cycle)
        self.assertEqual(self.index(cycle), 0)
        self.assertEqual(self.pending(cycle), [])
        self.assertEqual(self.repo.read("Job History"), [])
        self.assertIs(self.engine.repo, self.repo)
        self.assertIs(self.engine.state, self.state)
        self.engine.resume(cycle)
        self.assertEqual(len(self.pending(cycle)), 61)

    def test_new_pause_between_batches_preserves_first_checkpoint(self):
        cycle = self.start()
        original = self.repo.commit
        def commit(ops):
            result = original(ops)
            if any(op["tab"] == "Job History" for op in ops):
                tables = self.repo.tables
                tables["Companies"][0]["Company Status"] = "Paused"
                self.repo._sheets = MemoryRepository(tables)._sheets
            return result
        with patch.object(self.repo, "commit", side_effect=commit), self.assertRaisesRegex(ValueError, "paused"):
            self.engine.resume(cycle)
        self.assertEqual(self.index(cycle), 25)
        self.assertEqual(len(self.pending(cycle)), 25)

    def test_formula_conflict_rejects_whole_batch_before_checkpoint(self):
        self.jobs = self.jobs[:2]
        cycle = self.start()
        self.repo.commit([{"tab": "Job History", "identity": {"Job Key": "c-1:greenhouse:1"},
                           "values": {"Company": "Acme", "Job Title": "old"}, "append_if_missing": True}])
        sheet = self.repo._sheets["Job History"]
        col = sheet.headers.index("Job Title")
        sheet.cells[(1, col)] = {"userEnteredValue": {"formulaValue": '="old"'},
                                 "effectiveValue": {"stringValue": "old"}}
        before = self.repo.read("Job History")
        with self.assertRaises(RepositoryError):
            self.engine.resume(cycle)
        self.assertEqual(self.repo.read("Job History"), before)
        self.assertEqual(self.index(cycle), 0)
        self.assertEqual(self.pending(cycle), [])

    def test_title_screen_candidates_remain_auditable_until_reviewer_decides(self):
        self.jobs = [posting("1", title="Associate Facilities Coordinator (R5456)"),
                     posting("2", title="Senior Staff Talent Sourcer - G&A"), posting("3")]
        cycle = self.start()
        self.engine.resume(cycle)
        self.assertEqual(len(self.pending(cycle)), 3)
        self.assertEqual(len(self.repo.read("Job History")), 3)
        self.assertEqual(self.engine.status(cycle)["status"], "Awaiting Review")
        self.assertEqual(self.fetch_count, 1)

    def test_new_title_exclusions_create_history_rows(self):
        self.jobs = [posting("1", title="Associate Facilities Coordinator (R5456)"), posting("2")]
        cycle = self.start()
        self.engine.resume(cycle)
        self.assertEqual(len(self.repo.read("Job History")), 2)
        self.assertEqual(len(self.pending(cycle)), 2)

    def test_existing_opportunity_survives_title_screen_queueing_with_user_choice(self):
        self.jobs = [posting("1", title="Associate Facilities Coordinator (R5456)")]
        tables = self.repo.tables
        tables["Opportunities"] = [{"Company": "Acme", "Job Title": self.jobs[0]["title"],
            "Job URL": self.jobs[0]["url"], "Application Status": "Applied", "Date Applied": "2026-09-01", "Notes": "My note"}]
        self.repo._sheets = MemoryRepository(tables)._sheets
        cycle = self.start()
        self.engine.resume(cycle)
        self.assertEqual(len(self.pending(cycle)), 1)
        row = self.repo.read("Opportunities")[0]
        self.assertEqual(row["Application Status"], "Applied")
        self.assertEqual(row["Date Applied"], "2026-09-01")
        self.assertEqual(row["Notes"], "My note")

    def test_decision_import_batched_and_idempotent(self):
        cycle = self.start()
        self.engine.resume(cycle)
        path = self.decision_file(cycle)
        original = self.repo.commit
        writes = []
        def commit(ops):
            writes.append(copy.deepcopy(ops))
            return original(ops)
        with patch.object(self.repo, "commit", side_effect=commit):
            result = self.engine.import_decisions(cycle, path)
        self.assertEqual(len(writes), 3)
        self.assertEqual(result["status"], "Complete")
        self.assertEqual(len(self.repo.read("Opportunities")), 61)
        before = self.repo.tables
        self.engine.import_decisions(cycle, path)
        self.assertEqual(self.repo.tables, before)

    def test_failed_decision_batch_emits_no_added_notice_and_preserves_queue(self):
        self.jobs = self.jobs[:5]
        cycle = self.start()
        self.engine.resume(cycle)
        path = self.decision_file(cycle)
        self.output.truncate(0)
        self.output.seek(0)
        with patch.object(self.repo, "commit", side_effect=TimeoutError()), self.assertRaises(TimeoutError):
            self.engine.import_decisions(cycle, path)
        self.assertNotIn("Added:", self.output.getvalue())
        self.assertEqual(self.repo.read("Opportunities"), [])
        self.assertEqual(len(self.pending(cycle)), 5)

    def test_fresh_commit_preserves_manual_edits_after_planning_read(self):
        self.jobs = self.jobs[:1]
        cycle = self.start()
        self.engine.resume(cycle)
        path = self.decision_file(cycle)
        self.engine.import_decisions(cycle, path)
        planner = PlanningRepository(self.repo)
        tables = self.repo.tables
        tables["Opportunities"][0].update({"Application Status": "Not Interested", "Notes": "Just entered"})
        self.repo._sheets = MemoryRepository(tables)._sheets
        def plan():
            self.engine.repo.commit([{"tab": "Opportunities", "identity": {"Company": "Acme", "Job URL": self.jobs[0]["url"]},
                                     "values": {"Location": "Florida"}, "append_notes": {"Notes": "Scanner update"}}])
        self.engine._planned_batch(planner, plan)
        row = self.repo.read("Opportunities")[0]
        self.assertEqual(row["Application Status"], "Not Interested")
        self.assertEqual(row["Notes"], "Just entered\n\nScanner update")
        self.assertEqual(planner.read("Opportunities")[0], row)


class RequestAndFilterTests(unittest.TestCase):
    def test_448_job_google_staging_uses_under_150_requests(self):
        service = StatefulSheets({"Companies": [company()]})
        repo = GoogleRepository(service, "fixture-id", min_request_interval=0)
        state = State()
        self.addCleanup(state.close)
        engine = Engine(repo, state, fetcher=lambda *args: Inventory("complete", [posting(str(i)) for i in range(448)]))
        with redirect_stdout(io.StringIO()):
            cycle = engine.start_cycle(["C-1"])
            result = engine.resume(cycle)
        request_count = len(service.get_calls) + len(service.batches)
        self.assertLess(request_count, 150)
        self.assertEqual(result["pending_reviews"], 448)
        history_id = service.sheet("Job History")["properties"]["sheetId"]
        history_batches = [batch for batch in service.batches if any(
            r.get("updateCells", {}).get("start", {}).get("sheetId") == history_id for r in batch["body"]["requests"])]
        self.assertEqual(len(history_batches), 18)
        self.assertEqual(len(repo.read("Job History")), 448)

    def test_large_payload_refused_before_write(self):
        service = FakeSheets()
        repo = GoogleRepository(service, "fixture-id", min_request_interval=0)
        operations = [{"tab": "Job History", "identity": {"Job Key": str(i)}, "append_if_missing": True,
                       "values": {"Review Notes": "x" * 44_000, "Current Snapshot": "y" * 44_000}}
                      for i in range(25)]
        with self.assertRaisesRegex(RepositoryError, "--batch-size"):
            repo.commit(operations)
        self.assertEqual(service.batches, [])

    def test_all_tab_lookup_uses_two_reads_and_excludes_prompt(self):
        service = FakeSheets()
        repo = GoogleRepository(service, "fixture-id", min_request_interval=0)
        self.assertEqual(set(repo.read_many(SCHEMAS)), set(SCHEMAS))
        self.assertEqual(len(service.get_calls), 2)
        self.assertNotIn("Prompt Library", json.dumps(service.get_calls))

    def test_explicit_title_exclusions(self):
        for title in ("Associate Facilities Coordinator (R5456)", "Facilities Coordinator", "Office Assistant",
                      "Senior Staff Talent Sourcer - G&A", "Technical Sourcer", "Executive Assistant",
                      "Warehouse Associate", "Material Handler", "Machinist", "Engineering Intern"):
            with self.subTest(title=title):
                self.assertTrue(excluded_title(title))

    def test_contextual_titles_still_need_review(self):
        for title in ("Field Operations Manager", "Product Marketing Manager", "Technical Program Manager",
                      "Associate Solutions Engineer", "Customer Implementation Coordinator", "Integration Lead",
                      "Senior Field Engineer", "Facilities Engineering Manager", "Medical Device Field Applications Engineer",
                      "Mobile Field Support", "Engineering Operations Manager"):
            with self.subTest(title=title):
                self.assertFalse(excluded_title(title))

    def test_trailing_ampersand_fix_preserved(self):
        self.assertEqual(plain_text("Senior Staff Talent Sourcer - G&A"), "Senior Staff Talent Sourcer - G&A")

    def test_batch_size_bounds_validated_by_cli(self):
        for size in ("0", "201", "-1", "word"):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                cli.parser().parse_args(["resume", "--cycle", "test", "--batch-size", size])
        self.assertEqual(cli.parser().parse_args(["resume", "--cycle", "test"]).batch_size, 100)
        self.assertEqual(cli.parser().parse_args(["resume", "--cycle", "test", "--batch-size", "200"]).batch_size, 200)


if __name__ == "__main__":
    unittest.main()
