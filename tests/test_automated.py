"""Current scraper lifecycle; AI decisions use the separate managed reviewer."""
from pathlib import Path
import tempfile
import unittest
from job_search_helper.engine import State
from job_search_helper.runner import resolve_cycle
from job_search_helper.screening import screen_posting

class DummyRepo:
    def __init__(self, cycles=None): self.cycles = cycles or []
    def read(self, tab): return list(self.cycles) if tab == "Scan Cycles" else []

class DummyEngine:
    def __init__(self): self.recovered = []
    def _recover(self, cycle_id): self.recovered.append(cycle_id)

class AutomatedWorkflowTests(unittest.TestCase):
    def test_exclusion_runs_without_ai_worker_or_description(self):
        self.assertIn("Title exclusion", screen_posting({"title": "Software Engineer"}).reason)
        self.assertIsNone(screen_posting({"title": "Staff Solutions Engineer"}).reason)

    def test_resume_does_not_reopen_an_older_unfinished_cycle(self):
        with tempfile.TemporaryDirectory() as root:
            state = State(Path(root) / "state.db")
            self.addCleanup(state.close)
            state.save_cycle({"id": "old", "started_at": "2026-09-17", "status": "In Progress", "companies": {}})
            state.save_cycle({"id": "new", "started_at": "2026-09-18", "status": "Complete", "companies": {}})
            with self.assertRaisesRegex(ValueError, "already complete"):
                resolve_cycle(DummyEngine(), state, DummyRepo())

    def test_resume_recovers_latest_remote_cycle_but_never_creates_one(self):
        state = State()
        self.addCleanup(state.close)
        engine = DummyEngine()
        repo = DummyRepo([{"Cycle ID": "remote", "Cycle Status": "In Progress", "Started At": "2026-09-18"}])
        cycle_id, action = resolve_cycle(engine, state, repo)
        self.assertEqual(cycle_id, "remote")
        self.assertEqual(engine.recovered, ["remote"])
        with self.assertRaisesRegex(ValueError, "No saved scan"):
            resolve_cycle(engine, state, DummyRepo())
