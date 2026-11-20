"""Exercise the live first-pass CLI with an isolated scraper and Sheet fixture."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from job_search_helper.repository import MemoryRepository, SCHEMAS, _encoded
from job_search_helper.review_controls import refresh_sheet_controls
from job_search_helper.review_queue import export_review_queues
from job_search_helper.review_refresh import refresh_lock
from job_search_helper.review_runtime import Runtime, atomic_json, main
from job_search_helper.sqlite_repository import SQLiteRepository
from test_concurrent_review import response
from test_sqlite_migration import job


def first_pass_job(key):
    return job(key, **{"Job Title": "Engineer"})


class SafeResumeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.queue = self.root / "queue"
        self.path = self.root / "jobs.sqlite3"
        self.local = SQLiteRepository(self.path, "fixture", initialize=True)
        self.addCleanup(self.local.close)
        self.remote = MemoryRepository({
            "Job History": [first_pass_job(key) for key in ("a", "b", "c")],
            "Job Evidence": [{
                "Job Key": key, "Source Hash": "source-1", "Job Description": "Complete posting.",
            } for key in ("a", "b", "c")],
        })
        self.remote.spreadsheet_id = "fixture"
        for tab in SCHEMAS:
            self.local.import_rows(tab, enumerate(self.remote.read(tab), 2))
        self.local.set_meta("ready", "yes")
        export_review_queues(self.local, self.queue)
        runtime = Runtime(self.queue)
        try:
            runtime.sync()
            self.run_id = runtime.start(1)["run_id"]
            runtime.pause(1, self.run_id)
        finally:
            runtime.close()
        self.enterContext(patch(
            "job_search_helper.review_controls.refresh_sheet_controls",
            side_effect=lambda runtime: refresh_sheet_controls(runtime, local=self.local, remote=self.remote),
        ))
        self.enterContext(patch(
            "job_search_helper.cli.get_repository",
            side_effect=lambda *, write, interactive: SQLiteRepository(self.path, "fixture", readonly=not write),
        ))
        self.enterContext(patch("job_search_helper.review_publication.retry_run_deliveries", return_value=None))
        self.writeback = self.enterContext(patch(
            "job_search_helper.review_writeback.sync_pending", return_value={"counts": {}},
        ))
        self.enterContext(patch("job_search_helper.review_publication.publish_reviews", return_value=None))

    def cli(self, command, *args, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = main([command, "--pass", "1", "--run-id", self.run_id,
                           "--queue-dir", str(self.queue), *args])
        self.assertEqual(result, code, stderr.getvalue())
        return json.loads((stdout if code == 0 else stderr).getvalue())

    def submit(self, items):
        answers = self.root / "answers.jsonl"
        atomic_json(answers, [response(item, 1, "RESCUE") for item in items], lines=True)
        return self.cli("submit", "--file", str(answers))

    def edit_choice(self, row, choice):
        sheet = self.remote._sheets["Job History"]
        cell = sheet.cells[(row, sheet.headers.index("Added to Opportunities?"))]
        cell["userEnteredValue"] = cell["effectiveValue"] = _encoded(choice)

    def test_resume_claim_and_save_while_refresher_waits_and_scraper_commits(self):
        started = threading.Event()
        stop = threading.Event()
        errors = []

        def scrape():
            writer = SQLiteRepository(self.path, "fixture")
            try:
                writer.commit([{"tab": "Job History", "identity": {"Job Key": "a"},
                                "values": {"Job Title": "Field Support Engineer"}}])
                counter = 0
                while not stop.is_set():
                    # Keep changing a real queue input while the reviewer works.
                    writer.commit([{"tab": "Job History", "identity": {"Job Key": "a"},
                                    "values": {"Salary / Range": f"${150000 + counter} annual base"}}])
                    started.set()
                    counter += 1
                    stop.wait(0.01)
            except Exception as error:
                errors.append(error)
                started.set()
            finally:
                writer.close()

        worker = threading.Thread(target=scrape)
        worker.start()
        try:
            self.assertTrue(started.wait(5))
            with refresh_lock(self.queue), patch(
                "job_search_helper.review_runtime.live_refresh", side_effect=AssertionError("Synchronous rebuild"),
            ):
                self.assertEqual(self.cli("start")["queue_refresh"]["source"], "published_snapshot")
                batch = self.cli("next", "--limit", "1")
                self.assertEqual(batch["stale_inputs"], 1)
                self.assertEqual([item["job_key"] for item in batch["items"]], ["b"])
                self.assertEqual(self.submit(batch["items"])["saved"], 1)
        finally:
            stop.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_changed_evidence_and_manual_choice_leave_other_submission_intact(self):
        self.cli("start")
        batch = self.cli("next")["items"]
        self.assertEqual([item["job_key"] for item in batch], ["a", "b", "c"])
        with self.local.transaction():
            number, evidence = self.local.matches("Job Evidence", {"Job Key": "a"})[0]
            evidence["Job Description"] = "This is a contract position."
            self.local.db.execute(
                "UPDATE records SET data=? WHERE tab='Job Evidence' AND row_id=?",
                (json.dumps(evidence), number),
            )
        self.edit_choice(2, "No")
        result = self.submit(batch)
        self.assertEqual(result["saved"], 1)
        self.assertEqual([item["job_key"] for item in result["skipped_stale"]], ["a"])
        self.assertEqual([item["job_key"] for item in result["skipped_manual"]], ["b"])
        self.assertNotIn(("a", "source-1"), self.writeback.call_args.kwargs["identities"])
        self.assertEqual(self.cli("next")["items"], [])

    def test_incompatible_snapshot_requires_live_refresh(self):
        manifest = self.queue / "summary.json"
        data = json.loads(manifest.read_text())
        data["source_fingerprint"]["policies"] = {}
        atomic_json(manifest, data)
        with patch("job_search_helper.review_runtime.live_refresh",
                   side_effect=RuntimeError("refresh unavailable")) as refresh:
            self.assertIn("refresh unavailable", self.cli("start", code=1)["error"])
        refresh.assert_called_once()

    def test_finish_still_refreshes_and_finds_new_jobs(self):
        self.cli("start")
        self.assertEqual(self.submit(self.cli("next")["items"])["saved"], 3)
        self.local.import_rows("Job History", [(5, first_pass_job("d"))])
        self.remote = MemoryRepository({"Job History": [first_pass_job(key) for key in ("a", "b", "c", "d")]})
        self.remote.spreadsheet_id = "fixture"
        with patch("job_search_helper.review_runtime.live_refresh",
                   side_effect=lambda queue, **kwargs: export_review_queues(self.local, queue, overwrite=True)) as refresh:
            self.assertEqual(self.cli("finish")["state"], "CONTINUE")
        refresh.assert_called_once()
        self.assertEqual([item["job_key"] for item in self.cli("next")["items"]], ["d"])
