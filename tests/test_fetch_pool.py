from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from threading import Barrier, Event, Lock, get_ident
import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository
from test_ats import Transport, response
from test_discovery import html


def company(index, source=""):
    return {"Company": f"Company {index}", "Company ID": f"C-{index}", "Company Status": "Active",
            "ATS / Source": source, "Official Careers URL": f"https://boards.greenhouse.io/company{index}"}


def inventory(cid, name, url, status="complete", ats="Greenhouse"):
    jobs = [] if status != "complete" else [{
        "company_id": cid, "company": name, "ats": "Greenhouse", "posting_id": "1",
        "url": url + "/jobs/1", "title": "Field Applications Engineer", "description": "Integrate products.",
        "location": "Ohio", "work_arrangement": "Hybrid", "compensation": "$140k-$180k annual base",
        "is_listed": True,
    }]
    return Inventory(status, jobs, "HTTP 403" if status == "blocked" else "fixture", url, ats)


class OwnedRepository(MemoryRepository):
    def __init__(self, tables):
        self.owner = get_ident()
        super().__init__(tables)

    def read(self, *args, **kwargs):
        assert get_ident() == self.owner, "Fetcher accessed Sheets"
        return super().read(*args, **kwargs)

    def read_many(self, *args, **kwargs):
        assert get_ident() == self.owner, "Fetcher accessed Sheets"
        return super().read_many(*args, **kwargs)

    def read_columns(self, *args, **kwargs):
        assert get_ident() == self.owner, "Fetcher accessed Sheets"
        return super().read_columns(*args, **kwargs)

    def commit(self, *args, **kwargs):
        assert get_ident() == self.owner, "Fetcher wrote to Sheets"
        return super().commit(*args, **kwargs)


class FetchPoolTests(unittest.TestCase):
    def setUp(self):
        self.output = StringIO()
        capture = redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def make(self, count, fetcher, source=""):
        repo = OwnedRepository({"Companies": [company(index, source) for index in range(count)]})
        state = State()
        self.addCleanup(state.close)
        engine = Engine(repo, state, fetcher=fetcher, batch_size=1)
        cycle = engine.start_cycle([f"C-{index}" for index in range(count)])
        return repo, state, engine, cycle

    def test_four_fetchers_take_new_companies_while_writer_is_busy(self):
        first_four = Barrier(4, timeout=5)
        writer_busy, all_started = Event(), Event()
        lock = Lock()
        calls, active, peak = Counter(), set(), [0]

        def fetch(source, url, cid, name):
            with lock:
                calls[cid] += 1
                active.add(cid)
                peak[0] = max(peak[0], len(active))
                if len(calls) == 12:
                    all_started.set()
            try:
                if int(cid[2:]) < 4:
                    first_four.wait()
                elif not writer_busy.wait(5):
                    raise RuntimeError("Writer did not start")
                return inventory(cid, name, url)
            finally:
                with lock:
                    active.remove(cid)

        repo, state, engine, cycle = self.make(12, fetch)
        stage = engine._stage_inventory
        checked = []

        def slow_write(*args, **kwargs):
            if not checked:
                writer_busy.set()
                checked.append(True)
                # No writer callback is serviced during this wait. Workers must
                # finish and get their next assignment independently.
                self.assertTrue(all_started.wait(5), "Sheet writing stalled company assignment")
            return stage(*args, **kwargs)

        with patch.object(engine, "_stage_inventory", side_effect=slow_write):
            engine.resume_parallel(cycle, fetch_workers=4, assignment_window=25)
        self.assertEqual(peak[0], 4)
        self.assertEqual(calls, Counter({f"C-{index}": 1 for index in range(12)}))
        self.assertEqual(len(repo.read("Job History")), 12)
        self.assertTrue(all(row["Location"] == "Ohio" for row in repo.read("Job History")))
        self.assertTrue(all(item["stage"] == "complete" for item in state.cycle(cycle)["companies"].values()))
        text = self.output.getvalue()
        self.assertIn("Dashboard | Worker 1 -", text)
        self.assertIn("Workers | Worker", text)
        self.assertIn("Writer - Saving - Company", text)
        self.assertIn("Inventory processed: 12", text)
        self.assertIn("New jobs written: 12", text)
        self.assertIn("Jobs | Field Applications Engineer at Company", text)

    def test_prefetch_buffer_is_bounded_and_each_company_runs_once(self):
        calls = Counter()
        lock = Lock()

        def fetch(source, url, cid, name):
            with lock:
                calls[cid] += 1
            return inventory(cid, name, url)

        repo, _, engine, cycle = self.make(30, fetch)
        stage = engine._stage_inventory
        observations = []

        def check_buffer(current, *args, **kwargs):
            completed = sum(item.get("stage") == "complete" for item in current["companies"].values())
            with lock:
                self.assertLessEqual(sum(calls.values()) - completed, 6)
            self.assertTrue(all("jobs" not in item for item in current["companies"].values() if item.get("stage") == "complete"))
            observations.append(True)
            return stage(current, *args, **kwargs)

        with patch.object(engine, "_stage_inventory", side_effect=check_buffer):
            engine.resume_parallel(cycle, fetch_workers=4, assignment_window=5)
        self.assertEqual(len(observations), 30)
        self.assertEqual(len(repo.read("Job History")), 30)
        self.assertTrue(all(count == 1 for count in calls.values()))

    def test_interrupt_cancels_unstarted_assignments_and_resumes_without_duplicates(self):
        release = Event()
        pools = []

        class Pool(ThreadPoolExecutor):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.futures = []
                pools.append(self)

            def submit(self, *args, **kwargs):
                future = super().submit(*args, **kwargs)
                self.futures.append(future)
                return future

            def shutdown(self, wait=True, *, cancel_futures=False):
                super().shutdown(wait=False, cancel_futures=cancel_futures)
                release.set()
                super().shutdown(wait=wait, cancel_futures=cancel_futures)

        def fetch(source, url, cid, name):
            if cid != "C-0" and not release.wait(5):
                raise RuntimeError("Writer did not release running fetches")
            return inventory(cid, name, url)

        repo, _, engine, cycle = self.make(20, fetch)

        def interrupt():
            raise KeyboardInterrupt()

        engine.checkpoint_hook = interrupt
        with patch("job_search_helper.engine.ThreadPoolExecutor", Pool), self.assertRaises(KeyboardInterrupt):
            engine.resume_parallel(cycle, fetch_workers=4, assignment_window=25)
        self.assertTrue(any(future.cancelled() for future in pools[0].futures))
        self.assertEqual(len(repo.read("Job History")), 1)
        engine.checkpoint_hook = None
        engine.resume_parallel(cycle, fetch_workers=4, assignment_window=25)
        self.assertEqual(len(repo.read("Job History")), 20)
        self.assertEqual(len({row["Job Key"] for row in repo.read("Job History")}), 20)

    def test_small_assignment_window_does_not_disable_configured_workers(self):
        barrier = Barrier(4, timeout=5)

        def fetch(source, url, cid, name):
            barrier.wait()
            return inventory(cid, name, url)

        repo, _, engine, cycle = self.make(4, fetch)
        engine.resume_parallel(cycle, fetch_workers=4, assignment_window=1)
        self.assertEqual(len(repo.read("Job History")), 4)

    def test_blocked_ats_saved_serial_and_parallel_without_success_dates(self):
        for workers in (1, 4):
            with self.subTest(workers=workers):
                repo, state, engine, cycle = self.make(1, lambda source, url, cid, name: inventory(cid, name, url, "blocked", "Workday"))
                engine.resume_parallel(cycle, fetch_workers=workers)
                row = repo.read("Companies")[0]
                self.assertEqual(row["ATS / Source"], "Workday")
                self.assertEqual(row["Scan State"], "Blocked / Manual Review")
                self.assertEqual(row["Blocked Reason"], "HTTP 403")
                self.assertFalse(row.get("Last Successful Scan"))
                self.assertFalse(row.get("Last Checked"))
                self.assertEqual(state.cycle(cycle)["companies"]["C-0"]["ats"], "Workday")

    def test_partial_and_success_also_record_adapter(self):
        for status in ("complete", "partial"):
            with self.subTest(status=status):
                repo, _, engine, cycle = self.make(1, lambda source, url, cid, name: inventory(cid, name, url, status))
                engine.resume_parallel(cycle, fetch_workers=4)
                self.assertEqual(repo.read("Companies")[0]["ATS / Source"], "Greenhouse")

    def test_unknown_adapter_preserves_existing_source_and_known_annotations(self):
        for detected, configured in (("", "Custom source"), ("Workday", "Workday (filtered parent board)")):
            with self.subTest(detected=detected):
                repo, _, engine, cycle = self.make(1, lambda source, url, cid, name: inventory(cid, name, url, "blocked", detected), source=configured)
                engine.resume_parallel(cycle, fetch_workers=4)
                self.assertEqual(repo.read("Companies")[0]["ATS / Source"], configured)

    def test_worker_exception_and_invalid_result_record_failure_and_continue(self):
        def fetch(source, url, cid, name):
            if cid == "C-0":
                raise OSError("not exposed")
            if cid == "C-1":
                return None
            return inventory(cid, name, url)

        repo, state, engine, cycle = self.make(3, fetch)
        engine.resume_parallel(cycle, fetch_workers=4)
        self.assertEqual(len(repo.read("Job History")), 1)
        rows = repo.read("Companies")
        self.assertEqual(rows[0]["Last Scan Result"], "failed")
        self.assertIn("OSError", rows[0]["Blocked Reason"])
        self.assertEqual(rows[1]["Last Scan Result"], "failed")
        self.assertEqual(state.cycle(cycle)["companies"]["C-2"]["stage"], "complete")


class ATSIdentityTests(unittest.TestCase):
    def test_direct_adapter_keeps_identity_on_access_failure(self):
        for name, url in (("Greenhouse", "https://boards.greenhouse.io/acme"),
                          ("Lever", "https://jobs.lever.co/acme"), ("Ashby", "https://jobs.ashbyhq.com/acme")):
            with self.subTest(name=name):
                result = fetch_inventory("", url, "C", "Acme", Transport([response({}, 403)]))
                self.assertEqual(result.status, "blocked")
                self.assertEqual(result.ats, name)

    def test_specialized_adapters_keep_identity_on_block(self):
        for name, module in (("Workday", "workday"), ("iCIMS", "icims"), ("ADP", "adp"), ("Paylocity", "paylocity")):
            with self.subTest(name=name), patch("job_search_helper.ats.resolve_board", return_value=(name, "acme", "https://example.com/")), \
                    patch(f"job_search_helper.{module}.fetch_{module}", return_value=Inventory("blocked", reason="Access denied")):
                result = fetch_inventory("", "https://example.com/acme", "C", "Acme", Transport([]))
                self.assertEqual(result.ats, name)

    def test_discovered_adapter_retained_when_its_api_blocks(self):
        result = fetch_inventory("", "https://acme.example/careers", "C", "Acme", Transport([response({}, 403)]),
                                 discovery_transport=Transport([html('<a href="https://jobs.lever.co/acme">Jobs</a>')]))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.ats, "Lever")

    def test_unknown_discovery_does_not_invent_an_ats(self):
        result = fetch_inventory("", "https://acme.example/careers", "C", "Acme", Transport([]),
                                 discovery_transport=Transport([html("Access denied", 403)]))
        self.assertEqual(result.ats, "")


if __name__ == "__main__":
    unittest.main()
