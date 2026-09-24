"""Automated reviewer/orchestrator regression tests. No network or API calls."""
from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from job_search_helper.ai_worker import title_rejection
from job_search_helper.core import excluded_title, material_hash, POLICY_VERSION
from job_search_helper.engine import State
from job_search_helper.runner import resolve_cycle


class DummyRepo:
    def __init__(self, cycles=None):
        self._cycles = cycles or []

    def read(self, tab):
        if tab == "Scan Cycles":
            return list(self._cycles)
        return []


class DummyEngine:
    def __init__(self):
        self.started = 0
        self.recovered = []

    def start_cycle(self, company_ids=None):
        self.started += 1
        return "CYC-NEW"

    def _recover(self, cycle_id):
        self.recovered.append(cycle_id)
        return {"id": cycle_id}


class AutomatedWorkflowTests(unittest.TestCase):
    def test_exact_staff_engineer_example_is_zero_model_reject(self):
        title = "Senior Staff Engineer, Survivability Materials"
        self.assertTrue(excluded_title(title))
        posting = {
            "title": title, "location": "", "work_arrangement": "",
            "compensation": "", "description": "",
        }
        review = {
            "job_key": "comp:x:1",
            "description_hash": material_hash(posting),
            "posting": posting,
            "previous_posting": None,
        }
        decision = title_rejection(review)
        self.assertEqual(decision["decision"], "reject")
        self.assertEqual(decision["evaluation_stage"], "title_screen")
        self.assertEqual(decision["policy_version"], POLICY_VERSION)

    def test_target_staff_solutions_engineer_survives_title_screen(self):
        self.assertFalse(excluded_title("Staff Solutions Engineer"))
        self.assertFalse(excluded_title("Senior Field Applications Engineer"))
        self.assertFalse(excluded_title("Manager, Field Engineering"))

    def test_start_prefers_saved_unfinished_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = State(Path(temporary) / "state.db")
            state.save_cycle({
                "id": "CYC-OLD", "started_at": "2026-09-17T01:00:00+00:00",
                "status": "Awaiting Review", "all": True, "companies": {},
            })
            state.save_cycle({
                "id": "CYC-DONE", "started_at": "2026-09-17T02:00:00+00:00",
                "status": "Complete", "all": True, "companies": {},
            })
            engine = DummyEngine()
            cycle_id, action = resolve_cycle(engine, state, DummyRepo())
            self.assertEqual(cycle_id, "CYC-OLD")
            self.assertIn("resuming", action)
            self.assertEqual(engine.started, 0)
            state.close()

    def test_start_recovers_remote_or_creates_new_full_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = State(Path(temporary) / "state.db")
            engine = DummyEngine()
            repo = DummyRepo([{
                "Cycle ID": "CYC-REMOTE",
                "Cycle Status": "In Progress",
                "Started At": "2026-09-17T03:00:00+00:00",
            }])
            cycle_id, action = resolve_cycle(engine, state, repo)
            self.assertEqual(cycle_id, "CYC-REMOTE")
            self.assertEqual(engine.recovered, ["CYC-REMOTE"])

            # Once nothing unfinished remains, the exact same start operation
            # creates a new all-company cycle.
            engine = DummyEngine()
            cycle_id, action = resolve_cycle(engine, state, DummyRepo())
            self.assertEqual(cycle_id, "CYC-NEW")
            self.assertEqual(engine.started, 1)
            state.close()


if __name__ == "__main__":
    unittest.main()
