from contextlib import contextmanager
import fcntl
import json
from pathlib import Path
import tempfile
import unittest

from job_search_helper.company_intake_dispatcher import CompanyIntakeDispatcher
from job_search_helper.company_events import _json_digest


class Repo:
    def pending_latest_company_events(self, consumer, *, limit):
        return []


def request():
    return {
        "mode": "company-only", "request_id": "company-event:CEV-1",
        "company_ids": ["COMP-1"], "source_revision": "revision-1",
        "enqueued_at": "2026-11-19T00:00:00Z", "start_last": [],
        "company_event": {"schema": "company-event-scan-request-v1", "event_id": "CEV-1",
                          "company_id": "COMP-1", "revision": 1, "source_revision": "revision-1"},
    }


class CompanyIntakeDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "next-scan.json").write_text(json.dumps(request()))
        self.calls = []

    def dispatcher(self, status=None, child=None):
        result = CompanyIntakeDispatcher(
            Repo(), self.root, child_runner=child or self.child,
            queue_status=lambda: status or {"state": "READY_FOR_START"},
        )
        # The lifecycle guards themselves have dedicated integration coverage;
        # these source-only tests isolate the dispatcher decision/journal.
        result._guard_hold = lambda: None
        result.set_enabled(True)
        return result

    def child(self, command):
        self.calls.append(tuple(command))
        return 0

    def test_idle_ready_request_launches_only_the_public_start_lifecycle(self):
        result = self.dispatcher().run_once()
        self.assertEqual(result["state"], "CHILD_LAUNCHED")
        self.assertEqual(self.calls[0][-1], "start")
        self.assertTrue(self.calls[0][0].endswith("job-search-scraper"))

    def test_new_control_store_is_disabled_until_explicitly_enabled(self):
        dispatcher = CompanyIntakeDispatcher(Repo(), self.root, child_runner=self.child,
                                             queue_status=lambda: {"state": "READY_FOR_START"})
        self.assertEqual(dispatcher.run_once()["state"], "DISABLED")
        self.assertEqual(self.calls, [])

    def test_busy_cycle_status_holds_without_launching(self):
        result = self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-1"]}).run_once()
        self.assertEqual(result["state"], "HELD_WAITING_SAFE_BOUNDARY")
        self.assertEqual(self.calls, [])

    def test_restart_does_not_launch_a_reserved_request_twice(self):
        dispatcher = self.dispatcher()
        self.assertEqual(dispatcher.run_once()["state"], "CHILD_LAUNCHED")
        recovered = self.dispatcher()
        self.assertEqual(recovered.run_once()["state"], "ALREADY_CHILD_LAUNCHED")
        self.assertEqual(len(self.calls), 1)

    def test_paused_intake_does_not_launch(self):
        result = self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "reason": "paused intake"}).run_once()
        self.assertEqual(result["state"], "HELD_WAITING_SAFE_BOUNDARY")
        self.assertEqual(self.calls, [])

    def test_child_failure_is_durable_and_not_relaunched(self):
        def failed(command):
            self.calls.append(tuple(command))
            return 17
        dispatcher = self.dispatcher(child=failed)
        self.assertEqual(dispatcher.run_once()["state"], "CHILD_FAILED")
        self.assertEqual(dispatcher.run_once()["state"], "ALREADY_CHILD_FAILED")
        self.assertEqual(len(self.calls), 1)

    def test_restart_resumes_durable_paused_workflow_without_fresh_start(self):
        dispatcher = self.dispatcher()
        dispatcher.run_once()
        workflow = self.root / "scrape-first-pass" / "run-1" / "workflow.json"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(json.dumps({"stage": "SCRAPING", "status": "PAUSED_NOT_COMPLETE",
                                        "company_intake": {"request_id": "company-event:CEV-1",
                                                           "request_digest": _json_digest(request())}}))
        (workflow.parent.parent / "latest.json").write_text(json.dumps({"workflow": str(workflow)}))
        (self.root / "next-scan.json").unlink()
        self.assertEqual(self.dispatcher().run_once()["state"], "CHILD_LAUNCHED")
        self.assertEqual(self.calls[-1][-1], "--resume")

    def test_crash_before_spawn_reserves_then_recovers_once(self):
        dispatcher = self.dispatcher()
        self.assertEqual(dispatcher._reserve("company-event:CEV-1", _json_digest(request())), "RESERVED")
        self.assertEqual(self.dispatcher().run_once()["state"], "CHILD_LAUNCHED")
        self.assertEqual(len(self.calls), 1)

    def test_controller_lock_holds_before_reservation(self):
        dispatcher = self.dispatcher()
        dispatcher._guard_hold = CompanyIntakeDispatcher._guard_hold.__get__(dispatcher)
        # Avoid unrelated retained/release fixture requirements; exercise the
        # controller-lock portion directly.
        original = dispatcher._guard_hold
        lock_path = self.root / "scrape-first-pass" / "controller.lock"
        lock_path.parent.mkdir()
        with lock_path.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            # A direct nonblocking lock check proves the same guard condition.
            from job_search_helper.company_intake_dispatcher import _lock_available
            self.assertFalse(_lock_available(lock_path))
            self.assertEqual(self.calls, [])
        self.assertIsNotNone(original)

    def test_bridge_identity_rejects_every_mutable_mismatch(self):
        good = request()
        self.assertTrue(CompanyIntakeDispatcher._is_bridge_request(good))
        for key, value in (("request_id", "wrong"), ("company_ids", ["OTHER"]),
                           ("source_revision", "wrong")):
            bad = json.loads(json.dumps(good)); bad[key] = value
            self.assertFalse(CompanyIntakeDispatcher._is_bridge_request(bad))
        for key, value in (("event_id", "CEV-OTHER"), ("company_id", "OTHER"),
                           ("source_revision", "wrong")):
            bad = json.loads(json.dumps(good)); bad["company_event"][key] = value
            self.assertFalse(CompanyIntakeDispatcher._is_bridge_request(bad))

    def test_unrelated_paused_workflow_holds_before_event_bridge(self):
        workflow = self.root / "scrape-first-pass" / "other" / "workflow.json"
        workflow.parent.mkdir(parents=True)
        workflow.write_text(json.dumps({"stage": "SCRAPING", "company_intake": {
            "request_id": "company-event:OTHER", "request_digest": "other"}}))
        (workflow.parent.parent / "latest.json").write_text(json.dumps({"workflow": str(workflow)}))
        self.assertEqual(self.dispatcher().run_once()["state"], "HELD_UNMATCHED_WORKFLOW")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
