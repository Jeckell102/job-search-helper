import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.company_events import _json_digest


class Repo:
    def pending_latest_company_events(self, consumer, *, limit): return []


def request():
    return {"mode": "company-only", "request_id": "company-event:CEV-1", "company_ids": ["COMP-1"], "source_revision": "revision-1", "enqueued_at": "2026-11-19T00:00:00Z", "start_last": [], "company_event": {"schema": "company-event-scan-request-v1", "event_id": "CEV-1", "company_id": "COMP-1", "revision": 1, "source_revision": "revision-1"}}


class CompanyIntakeDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); (self.root / "next-scan.json").write_text(json.dumps(request())); self.calls = []

    def child(self, command): self.calls.append(tuple(command)); return 0

    def dispatcher(self, status=None, child=None):
        result = CompanyIntakeDispatcher(Repo(), self.root, child_runner=child or self.child, queue_status=lambda: status or {"state": "READY_FOR_START"})
        result._guard_hold = lambda: None
        result.set_enabled(True)
        return result

    def test_idle_ready_request_launches_only_public_start(self):
        self.assertEqual(self.dispatcher().run_once()["state"], "CHILD_LAUNCHED")
        self.assertEqual(self.calls[0][-1], "start")
        self.assertTrue(self.calls[0][0].endswith("job-search-scraper"))

    def test_new_control_store_is_disabled_until_explicitly_enabled(self):
        dispatcher = CompanyIntakeDispatcher(Repo(), self.root, child_runner=self.child, queue_status=lambda: {"state": "READY_FOR_START"})
        self.assertEqual(dispatcher.run_once()["state"], "DISABLED")
        self.assertEqual(self.calls, [])

    def test_busy_or_paused_status_holds_without_launching(self):
        for status in ({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-1"]}, {"state": "WAITING_SAFE_BOUNDARY", "reason": "paused"}):
            self.assertEqual(self.dispatcher(status).run_once()["state"], "HELD_WAITING_SAFE_BOUNDARY")
        self.assertEqual(self.calls, [])

    def test_restart_does_not_launch_a_reserved_request_twice(self):
        self.assertEqual(self.dispatcher().run_once()["state"], "CHILD_LAUNCHED")
        self.assertEqual(self.dispatcher().run_once()["state"], "ALREADY_CHILD_LAUNCHED")
        self.assertEqual(len(self.calls), 1)

    def test_child_failure_is_durable_and_not_relaunched(self):
        def failed(command): self.calls.append(tuple(command)); return 17
        self.assertEqual(self.dispatcher(child=failed).run_once()["state"], "CHILD_FAILED")
        self.assertEqual(self.dispatcher().run_once()["state"], "ALREADY_CHILD_FAILED")
        self.assertEqual(len(self.calls), 1)

    def test_restart_resumes_exact_paused_workflow_without_request(self):
        self.dispatcher().run_once()
        workflow = self.root / "scrape-first-pass" / "run-1" / "workflow.json"; workflow.parent.mkdir(parents=True)
        workflow.write_text(json.dumps({"stage": "SCRAPING", "company_intake": {"request_id": "company-event:CEV-1", "request_digest": _json_digest(request())}}))
        (workflow.parent.parent / "latest.json").write_text(json.dumps({"workflow": str(workflow)})); (self.root / "next-scan.json").unlink()
        self.assertEqual(self.dispatcher().run_once()["state"], "CHILD_LAUNCHED")
        self.assertEqual(self.calls[-1][-1], "--resume")

    def test_crash_before_spawn_reserves_then_recovers_once(self):
        dispatcher = self.dispatcher(); self.assertEqual(dispatcher._reserve("company-event:CEV-1", _json_digest(request())), "RESERVED")
        self.assertEqual(self.dispatcher().run_once()["state"], "CHILD_LAUNCHED"); self.assertEqual(len(self.calls), 1)

    def test_controller_lock_is_checked_at_real_path(self):
        from job_search_helper.company_intake_dispatcher import _lock_available
        lock = self.root / "scrape-first-pass" / "controller.lock"; lock.parent.mkdir()
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX); self.assertFalse(_lock_available(lock))

    def test_bridge_identity_rejects_mutable_mismatches(self):
        good = request(); self.assertTrue(CompanyIntakeDispatcher._is_bridge_request(good))
        for key, value in (("request_id", "wrong"), ("company_ids", ["OTHER"]), ("source_revision", "wrong")):
            bad = json.loads(json.dumps(good)); bad[key] = value; self.assertFalse(CompanyIntakeDispatcher._is_bridge_request(bad))
        for key, value in (("event_id", "CEV-OTHER"), ("company_id", "OTHER"), ("source_revision", "wrong")):
            bad = json.loads(json.dumps(good)); bad["company_event"][key] = value; self.assertFalse(CompanyIntakeDispatcher._is_bridge_request(bad))

    def test_unrelated_paused_workflow_holds_before_event_bridge(self):
        workflow = self.root / "scrape-first-pass" / "other" / "workflow.json"; workflow.parent.mkdir(parents=True)
        workflow.write_text(json.dumps({"stage": "SCRAPING", "company_intake": {"request_id": "company-event:OTHER", "request_digest": "other"}}))
        (workflow.parent.parent / "latest.json").write_text(json.dumps({"workflow": str(workflow)}))
        self.assertEqual(self.dispatcher().run_once()["state"], "HELD_UNMATCHED_WORKFLOW"); self.assertEqual(self.calls, [])
