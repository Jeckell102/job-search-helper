"""The CLI and both offline fetch paths share the 50-worker limit."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from threading import Lock
import unittest
from unittest.mock import patch

from job_search_helper import runner
from job_search_helper.engine import MAX_FETCH_WORKERS, Engine, State
from job_search_helper.inbox import InventoryInbox
from test_fetch_pool import OwnedRepository, company, inventory


class StartupBoundary(Exception):
    """Stop immediately before any environment, auth, or state access."""


class FetchWorkerLimitTests(unittest.TestCase):
    def setUp(self):
        self.output, self.errors = StringIO(), StringIO()
        for capture in (redirect_stdout(self.output), redirect_stderr(self.errors)):
            capture.__enter__()
            self.addCleanup(capture.__exit__, None, None, None)

    def make(self, count=4, local=False):
        repo = OwnedRepository({"Companies": [company(i) for i in range(count)]})
        state = State()
        self.addCleanup(state.close)
        inbox = InventoryInbox(":memory:", "fixture") if local else None
        if inbox is not None:
            self.addCleanup(inbox.close)
        calls, lock = Counter(), Lock()

        def fetch(source, url, cid, name):
            with lock:
                calls[cid] += 1
            return inventory(cid, name, url)
        engine = Engine(repo, state, fetcher=fetch, batch_size=200, inbox=inbox,
                        error_log_path=None)
        cycle = engine.start_cycle([f"C-{i}" for i in range(count)])
        return repo, state, engine, cycle, calls

    def test_cli_rejects_51_before_environment_or_auth(self):
        with patch.object(runner, "_load_environment") as environment, \
                patch.object(runner, "get_repository") as repository:
            self.assertEqual(runner.main(["start", "--fetch-workers", "51"]), 1)
        environment.assert_not_called()
        repository.assert_not_called()
        self.assertIn("Fetch workers must be 1-50", self.errors.getvalue())

    def test_cli_accepts_50_to_mocked_startup_boundary(self):
        with patch.object(runner, "_load_environment", side_effect=StartupBoundary) as environment, \
                patch.object(runner, "get_repository") as repository:
            with self.assertRaises(StartupBoundary):
                runner.main(["start", "--fetch-workers", "50"])
        environment.assert_called_once_with()
        repository.assert_not_called()
        self.assertIn("Configured: 50 fetch worker(s)", self.output.getvalue())

    def test_help_and_default_match_shared_limit(self):
        self.assertEqual(MAX_FETCH_WORKERS, 50)
        self.assertEqual(runner.DEFAULT_FETCH_WORKERS, 5)
        runner.print_help()
        self.assertIn("Allowed: 1-50. Default: 5.", self.output.getvalue())

    def test_both_fetch_paths_run_with_50_workers_offline(self):
        for local in (False, True):
            with self.subTest(local=local):
                repo, state, engine, cycle, calls = self.make(local=local)
                module = "local_pipeline" if local else "engine"
                run = engine.resume_local if local else engine.resume_parallel
                with patch(f"job_search_helper.{module}.ThreadPoolExecutor",
                           wraps=ThreadPoolExecutor) as pool:
                    run(cycle, fetch_workers=50, assignment_window=1)
                pool.assert_called_once_with(max_workers=51 if local else 50)
                self.assertEqual(calls, Counter({f"C-{i}": 1 for i in range(4)}))
                self.assertEqual(len(repo.read("Job History")), 4)
                self.assertTrue(all(item["stage"] == "complete"
                                    for item in state.cycle(cycle)["companies"].values()))

    def test_both_fetch_paths_reject_out_of_range_counts(self):
        for local in (False, True):
            repo, state, engine, cycle, calls = self.make(local=local)
            run = engine.resume_local if local else engine.resume_parallel
            for workers in (0, 51):
                with self.subTest(local=local, workers=workers), self.assertRaises(ValueError):
                    run(cycle, fetch_workers=workers)
            self.assertEqual(calls, Counter())


if __name__ == "__main__":
    unittest.main()
