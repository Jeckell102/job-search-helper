"""Offline batch carryover, durable replay, and independent progress timing."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from job_search_helper.dashboard import TerminalDashboard
from job_search_helper.engine import Engine, State, inventory_payload
from job_search_helper.inbox import InventoryInbox
from job_search_helper.local_pipeline import LocalPipeline
from job_search_helper.repository import GoogleRepository
from sheets_fixture import RangeSheets
from test_fetch_pool import company, inventory


class SyncBatchingTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stdout(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = State(self.root / "state.db")
        self.addCleanup(self.state.close)
        self.inbox = InventoryInbox(self.root / "inbox.db", "fixture")
        self.addCleanup(self.inbox.close)
        self.service = RangeSheets({"Companies": [company(i) for i in range(2)]})
        self.repo = GoogleRepository(self.service, "fixture", min_request_interval=0)
        self.engine = Engine(self.repo, self.state, batch_size=3, inbox=self.inbox,
                             fetcher=lambda *args: self.fail("Saved plans must not refetch"),
                             error_log_path=self.root / "errors.jsonl")
        self.cycle = self.engine.start_cycle(["C-0", "C-1"])
        self.tick = 100.0
        clock = patch("job_search_helper.local_pipeline.time", SimpleNamespace(monotonic=lambda: self.tick))
        clock.start()
        self.addCleanup(clock.stop)
        self.pipeline = LocalPipeline(self.engine, self.cycle, sync_interval=60)
        self.pipeline.dashboard = TerminalDashboard(1)
        self.engine._dashboard = self.pipeline.dashboard
        self.pipeline.retry_blocked = False

    def save_plan(self, cid, count, description="Evidence"):
        number = int(cid.split("-")[1])
        source = company(number)
        payload = inventory_payload(inventory(cid, source["Company"], source["Official Careers URL"]), source)
        self.inbox.save(self.cycle, cid, payload)
        operations = [{"tab": "Job Evidence",
                       "identity": {"Job Key": f"{cid}-{i}", "Source Hash": "h1"},
                       "values": {"Company": source["Company"], "Job Description": description},
                       "append_if_missing": True} for i in range(count)]
        plan = {"operations": operations, "final": {"stage": "complete"},
                "requested_url": source["Official Careers URL"]}
        self.inbox.save_plan(self.cycle, cid, plan)
        self.pipeline.planner.commit(operations)
        self.pipeline.cycle["companies"][cid].update(stage="inventory", durable_inventory=True)
        self.state.save_cycle(self.pipeline.cycle)
        self.pipeline.pending.append(cid)
        return plan

    def evidence_batches(self, commit):
        return [call.args[0] for call in commit.call_args_list
                if any(op["tab"] == "Job Evidence" for op in call.args[0])]

    def restart(self):
        state = State(self.root / "state.db")
        self.addCleanup(state.close)
        inbox = InventoryInbox(self.root / "inbox.db", "fixture")
        self.addCleanup(inbox.close)
        repo = GoogleRepository(self.service, "fixture", min_request_interval=0)
        return Engine(repo, state, batch_size=self.engine.batch_size, inbox=inbox,
                      fetcher=lambda *args: self.fail("Saved plans must not refetch"),
                      error_log_path=self.root / "restart-errors.jsonl")

    def test_full_only_carries_tail_and_persisted_cursor_into_next_company(self):
        original = self.save_plan("C-0", 5)
        self.tick = 120.0
        with patch.object(self.repo, "commit", wraps=self.repo.commit) as commit:
            self.pipeline.flush(full_only=True)
            saved, cursor = self.inbox.plan(self.cycle, "C-0")
            self.assertEqual(saved, original)
            self.assertEqual(cursor, 3)
            self.assertEqual(list(self.pipeline.pending), ["C-0"])
            self.assertEqual(self.pipeline.cycle["companies"]["C-0"]["stage"], "inventory")
            self.assertEqual(self.pipeline.last_sync, 100.0)
            self.save_plan("C-1", 1)
            self.pipeline.flush(full_only=True)
        batches = self.evidence_batches(commit)
        self.assertEqual([len(batch) for batch in batches], [3, 3])
        self.assertEqual([op["identity"]["Job Key"] for op in batches[1]], ["C-0-3", "C-0-4", "C-1-0"])
        self.assertEqual(list(self.pipeline.pending), [])
        self.assertEqual(self.inbox.pending(self.cycle), [])
        self.assertEqual(len(self.repo.read("Job Evidence")), 6)

    def test_exact_full_batch_sends_and_small_tail_waits_for_final_drain(self):
        self.save_plan("C-0", 3)
        with patch.object(self.repo, "commit", wraps=self.repo.commit) as commit:
            self.pipeline.flush(full_only=True)
            self.assertEqual([len(batch) for batch in self.evidence_batches(commit)], [3])
            self.assertIsNone(self.inbox.plan(self.cycle, "C-0"))
            self.save_plan("C-1", 1)
            self.pipeline.flush(full_only=True)
            self.assertEqual([len(batch) for batch in self.evidence_batches(commit)], [3])
            self.assertEqual(self.inbox.plan(self.cycle, "C-1")[1], 0)
            self.tick = 135.0
            self.pipeline.flush()
        self.assertEqual([len(batch) for batch in self.evidence_batches(commit)], [3, 1])
        self.assertEqual(self.pipeline.last_sync, 135.0)
        self.assertEqual(self.pipeline.last_cycle_sync, 100.0)
        self.assertEqual(self.inbox.pending(self.cycle), [])

    def test_byte_budget_splits_full_batch_and_retains_small_remainder(self):
        self.engine.batch_size = 200
        frozen = self.save_plan("C-0", 13, description="x" * 44_000)
        with patch.object(self.repo, "commit", wraps=self.repo.commit) as commit:
            self.pipeline.flush(full_only=True)
            batches = self.evidence_batches(commit)
            self.assertEqual(len(batches), 1)
            sent = len(batches[0])
            size = lambda ops: sum(len(json.dumps(op, ensure_ascii=True).encode()) for op in ops)
            self.assertGreater(sent, 0)
            self.assertLess(sent, 13)
            self.assertLessEqual(size(batches[0]), 500_000)
            self.assertGreater(size(frozen["operations"][:sent + 1]), 500_000)
            self.assertEqual(self.inbox.plan(self.cycle, "C-0")[1], sent)
            self.pipeline.flush()
        batches = self.evidence_batches(commit)
        self.assertEqual(sum(map(len, batches)), 13)
        self.assertTrue(all(size(batch) <= 500_000 for batch in batches))
        self.assertEqual(len(self.repo.read("Job Evidence")), 13)

    def test_interrupted_tail_resumes_frozen_plans_without_duplicate_writes(self):
        frozen = self.save_plan("C-0", 5)
        self.pipeline.flush(full_only=True)
        self.save_plan("C-1", 1)
        with patch.object(self.pipeline, "upload", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.pipeline.flush(full_only=True)
        self.assertEqual(self.inbox.plan(self.cycle, "C-0"), (frozen, 3))
        self.assertEqual(self.inbox.plan(self.cycle, "C-1")[1], 0)
        restarted = self.restart()
        with patch.object(restarted.repo, "commit", wraps=restarted.repo.commit) as commit:
            restarted.resume_local(self.cycle, sync_only=True, fetch_workers=1)
        batches = self.evidence_batches(commit)
        keys = [op["identity"]["Job Key"] for batch in batches for op in batch]
        self.assertEqual(keys, ["C-0-3", "C-0-4", "C-1-0"])
        self.assertEqual(len(restarted.repo.read("Job Evidence")), 6)
        self.assertEqual(restarted.inbox.pending(self.cycle), [])
        self.assertEqual(restarted.state.cycle(self.cycle)["status"], "Complete")

    def test_run_forces_last_partial_batch_and_final_cycle_status(self):
        self.engine.batch_size = 4
        self.save_plan("C-0", 2)
        self.save_plan("C-1", 1)
        with patch.object(self.engine, "_sync_cycle", wraps=self.engine._sync_cycle) as sync, \
                patch.object(self.repo, "commit", wraps=self.repo.commit) as commit:
            self.engine.resume_local(self.cycle, sync_only=True, fetch_workers=1)
        self.assertEqual([len(batch) for batch in self.evidence_batches(commit)], [3])
        sync.assert_called_once()
        self.assertEqual(self.state.cycle(self.cycle)["status"], "Complete")
        self.assertTrue(all(item["stage"] == "complete"
                            for item in self.state.cycle(self.cycle)["companies"].values()))
        self.assertEqual(self.repo.read("Scan Cycles")[0]["Cycle Status"], "Complete")
        self.assertEqual(self.inbox.pending(self.cycle), [])

    def test_cycle_progress_has_independent_deadline_and_force_override(self):
        self.save_plan("C-0", 3)
        with patch.object(self.engine, "_sync_cycle", wraps=self.engine._sync_cycle) as sync:
            self.tick = 120.0
            self.pipeline.flush(full_only=True)
            self.pipeline.sync_cycle_progress()
            sync.assert_not_called()
            self.assertEqual(self.pipeline.last_cycle_sync, 100.0)
            self.assertEqual(self.pipeline.last_sync, 100.0)
            self.tick = 160.0
            self.pipeline.sync_cycle_progress()
            self.assertEqual(sync.call_count, 1)
            self.tick = 220.0
            self.pipeline.sync_cycle_progress()
            self.assertEqual(sync.call_count, 1, "Unchanged progress should not be rewritten")
            self.pipeline.cycle["companies"]["C-1"]["stage"] = "complete"
            self.pipeline.sync_cycle_progress()
            self.assertEqual(sync.call_count, 2)
            self.tick = 221.0
            self.pipeline.sync_cycle_progress(force=True)
            self.assertEqual(sync.call_count, 2, "Final progress must not rewrite unchanged stages")
            self.pipeline.cycle["companies"]["C-1"]["stage"] = "partial"
            self.pipeline.sync_cycle_progress(force=True)
            self.assertEqual(sync.call_count, 3)
        self.assertEqual(self.state.cycle(self.cycle)["status"], "Complete with exceptions")


if __name__ == "__main__":
    unittest.main()
