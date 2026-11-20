import fcntl
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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
        def verified(*args):
            raw = (self.root / 'next-scan.json').read_bytes()
            return raw, json.loads(raw)
        verifier = patch('job_search_helper.company_intake_dispatcher.read_verified_queued_event', verified)
        verifier.start()
        self.addCleanup(verifier.stop)
        result.set_enabled(True)
        return result

    def test_idle_ready_request_launches_only_exact_public_admission(self):
        self.assertEqual(self.dispatcher().run_once()["state"], "ORDINARY_CHILD_RETURNED")
        self.assertEqual(self.calls[0][1:], ('ordinary-company-event', 'admit-fetch', '--request-sha256', _json_digest(request())))
        self.assertTrue(self.calls[0][0].endswith("job-search-scraper"))

    def test_new_control_store_is_disabled_until_explicitly_enabled(self):
        dispatcher = CompanyIntakeDispatcher(Repo(), self.root, child_runner=self.child, queue_status=lambda: {"state": "READY_FOR_START"})
        self.assertEqual(dispatcher.run_once()["state"], "DISABLED")
        self.assertEqual(self.calls, [])

    def test_busy_or_paused_status_holds_without_launching(self):
        self.assertEqual(self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-1"]}).run_once()["state"], "HELD_RETAINED_DISABLED")
        self.assertEqual(self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "reason": "paused"}).run_once()["state"], "HELD_WAITING_SAFE_BOUNDARY")
        self.assertEqual(self.calls, [])

    def test_restart_does_not_launch_a_reserved_request_twice(self):
        self.assertEqual(self.dispatcher().run_once()["state"], "ORDINARY_CHILD_RETURNED")
        self.assertEqual(self.dispatcher().run_once()["state"], "HELD_ORDINARY_ADMIT_FETCH")
        self.assertEqual(len(self.calls), 1)

    def test_child_failure_is_durable_and_not_relaunched(self):
        def failed(command): self.calls.append(tuple(command)); return 17
        self.assertEqual(self.dispatcher(child=failed).run_once()["returncode"], 17)
        self.assertEqual(self.dispatcher().run_once()["state"], "HELD_ORDINARY_ADMIT_FETCH")
        self.assertEqual(len(self.calls), 1)

    def test_restart_holds_legacy_ordinary_workflow_without_generic_resume(self):
        dispatcher = self.dispatcher()
        digest = _json_digest(request())
        self.assertEqual(dispatcher._reserve('company-event:CEV-1', digest), 'RESERVED')
        dispatcher._finish('company-event:CEV-1', 'CHILD_LAUNCHED')
        workflow = self.root / "scrape-first-pass" / "run-1" / "workflow.json"; workflow.parent.mkdir(parents=True)
        workflow.write_text(json.dumps({"stage": "SCRAPING", "company_intake": {"request_id": "company-event:CEV-1", "request_digest": _json_digest(request())}}))
        (workflow.parent.parent / "latest.json").write_text(json.dumps({"workflow": str(workflow)})); (self.root / "next-scan.json").unlink()
        self.assertEqual(dispatcher.run_once()["state"], "HELD_LEGACY_INTAKE_WORKFLOW")
        self.assertEqual(self.calls, [])

    def test_matching_paused_workflow_holds_an_already_queued_request_for_review(self):
        dispatcher = self.dispatcher()
        self.assertEqual(dispatcher.run_once()["state"], "ORDINARY_CHILD_RETURNED")
        path = self.root / "next-scan.json"
        raw = path.read_bytes()
        workflow = self.root / "scrape-first-pass" / "run-1" / "workflow.json"
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(json.dumps({
            "stage": "SCRAPING",
            "company_intake": {"request_id": "company-event:CEV-1", "request_digest": _json_digest(request())},
        }))
        (workflow.parent.parent / "latest.json").write_text(json.dumps({"workflow": str(workflow)}))
        self.assertEqual(dispatcher.run_once()["state"], "HELD_ORDINARY_ADMIT_FETCH")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(path.read_bytes(), raw)

    def test_crash_after_claim_never_automatically_relaunches(self):
        dispatcher = self.dispatcher(child=lambda command: (_ for _ in ()).throw(KeyboardInterrupt()))
        with self.assertRaises(KeyboardInterrupt):
            dispatcher.run_once()
        self.assertEqual(self.dispatcher().run_once()["state"], "HELD_ORDINARY_ADMIT_FETCH")
        self.assertEqual(self.calls, [])

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

    def test_retained_gate_is_separate_and_public_command_has_no_key_arguments(self):
        retained_calls = []
        dispatcher = self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-OLD"]})
        dispatcher.set_retained_enabled(True)
        dispatcher.retained_child_runner = lambda command: retained_calls.append(tuple(command)) or 0
        with patch.dict("os.environ", {"COMPANY_RETAINED_KEY_ID": "fixture-key", "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64": "ZmFrZQ=="}), \
             patch.object(dispatcher, "_retained_eligibility", return_value={"exception_cycle": "CYC-OLD", "manifest_digest": "manifest"}):
            self.assertEqual(dispatcher.run_once()["state"], "RETAINED_CHILD_LAUNCHED")
        self.assertEqual(retained_calls, [(retained_calls[0][0], "run-retained-company-event")])

    def test_retained_missing_key_holds_without_normal_launch(self):
        dispatcher = self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-OLD"]})
        dispatcher.set_retained_enabled(True)
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(dispatcher.run_once()["state"], "HELD_RETAINED_KEY_CONFIG")
        self.assertEqual(self.calls, [])

    def test_retained_crash_after_reserve_before_pid_journal_recovers_public_child(self):
        calls = []
        dispatcher = self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-OLD"]})
        dispatcher.set_retained_enabled(True)
        dispatcher.retained_child_runner = lambda command: calls.append(tuple(command)) or 0
        with patch.dict("os.environ", {"COMPANY_RETAINED_KEY_ID": "fixture-key", "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64": "ZmFrZQ=="}), \
             patch.object(dispatcher, "_retained_eligibility", return_value={"exception_cycle": "CYC-OLD", "manifest_digest": "manifest"}):
            self.assertEqual(dispatcher._claim_retained("company-event:CEV-1", _json_digest(request()), {"exception_cycle": "CYC-OLD", "manifest_digest": "manifest"}, dispatcher._retained_config()), "RESERVED")
            self.assertEqual(dispatcher.run_once()["state"], "RETAINED_CHILD_LAUNCHED")
        self.assertEqual(len(calls), 1)

    def test_retained_receipt_is_terminal_and_preserves_newer_request(self):
        from job_search_helper.retained_work_runner import digest
        old = request(); newer = request(); newer["request_id"] = "company-event:CEV-2"; newer["company_event"]["event_id"] = "CEV-2"
        key = digest(old)
        archive = self.root / "company-event-bridge" / "consumed-requests" / (key + ".json")
        receipt = self.root / "company-event-bridge" / "consumption-receipts" / (key + ".json")
        archive.parent.mkdir(parents=True); receipt.parent.mkdir(parents=True)
        archive.write_text(json.dumps(old)); receipt.write_text(json.dumps({"request_sha256": key, "state": "FIRST_PASS_RELEASED_CONSUMED"}))
        (self.root / "next-scan.json").write_text(json.dumps(newer))
        self.assertTrue(self.dispatcher()._retained_consumed(old, _json_digest(old)))
        self.assertEqual(newer, json.loads((self.root / "next-scan.json").read_text()))

    def test_malformed_retained_receipt_holds_closed(self):
        dispatcher = self.dispatcher({"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-OLD"]})
        dispatcher.set_retained_enabled(True)
        root = self.root / "company-event-bridge" / "consumption-receipts"; root.mkdir(parents=True)
        from job_search_helper.retained_work_runner import digest
        (root / (digest(request()) + ".json")).write_text("not-json")
        self.assertEqual(dispatcher.run_once()["state"], "HELD_RETAINED_RECEIPT")

    def test_fake_token_runner_with_untrusted_pythonpath_is_rejected(self):
        dispatcher = self.dispatcher()
        token = "fixture-owner-token"
        with dispatcher._journal() as db:
            db.execute("INSERT INTO request_ownership(request_id,request_digest,route,state,owner_token) VALUES (?,?,?,?,?)", ("company-event:CEV-CRASH", "digest", "RETAINED", "RETAINED_STARTING", token))
        fake = Path(self.temp.name) / "fake" / "job_search_helper"; fake.mkdir(parents=True)
        (fake / "__init__.py").write_text("")
        (fake / "runner.py").write_text("import time; time.sleep(20)\n")
        environment = dict(os.environ, JOB_SEARCH_RETAINED_OWNER_TOKEN=token,
                           PYTHONPATH=str(fake.parent) + os.pathsep + str(Path.cwd() / "src"))
        child = subprocess.Popen([sys.executable, "-m", "job_search_helper.runner", "run-retained-company-event"], cwd=Path.cwd(), env=environment)
        def stop_child():
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        self.addCleanup(stop_child)
        adopted = None
        for _ in range(40):
            adopted = dispatcher._adopt_retained_child(token)
            __import__("time").sleep(.025)
        self.assertIsNone(adopted)

    def test_faithful_isolated_wrapper_process_is_adopted_without_second_launch(self):
        project = self.root / "isolated-project"
        package = project / "src" / "job_search_helper"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "runner.py").write_text("import time; time.sleep(20)\n")
        venv = project / ".venv" / "bin"; venv.mkdir(parents=True)
        (venv / "python").symlink_to(sys.executable)
        token = "faithful-owner-token"
        environment = dict(os.environ, JOB_SEARCH_RETAINED_OWNER_TOKEN=token,
                           PYTHONPATH=str(project / "src"))
        child = subprocess.Popen([
            str(venv / "python"), "-m", "job_search_helper.runner",
            "run-retained-company-event"], cwd=project, env=environment)
        def stop_child():
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        self.addCleanup(stop_child)
        dispatcher = self.dispatcher()
        with patch("job_search_helper.company_intake_dispatcher.PROJECT_ROOT", project):
            adopted = None
            for _ in range(80):
                adopted = dispatcher._adopt_retained_child(token)
                if adopted is not None:
                    break
                __import__("time").sleep(.025)
        self.assertEqual((child.pid, dispatcher._process_start_identity(child.pid)), adopted)

    def test_real_zombie_is_not_live(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        for _ in range(80):
            identity = CompanyIntakeDispatcher._process_identity(child.pid)
            if identity[1] == "Z":
                break
            __import__("time").sleep(.01)
        self.assertEqual(identity[1], "Z")
        self.assertIsNone(CompanyIntakeDispatcher._process_start_identity(child.pid))
        child.wait(timeout=5)

    def test_retained_preflight_verifies_real_ed25519_active_record_and_manifest(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from job_search_helper.engine import State
        from job_search_helper.retained_work_exception import activate_exception, required_claims
        from job_search_helper.selected_recovery_authorization import Ed25519AuthorizationVerifier, canonical
        from tests.test_retained_work_exception import RetainedWorkExceptionTests
        fixture = RetainedWorkExceptionTests("runTest"); fixture.setUp(); self.addCleanup(fixture.tearDown)
        state = State(str(fixture.root / "state.db")); state.save_cycle(fixture.cycle); state.close()
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        encoded = base64.b64encode(public).decode("ascii")
        claims = required_claims(fixture.manifest, expires_at="2027-01-01T00:00:00+00:00")
        envelope = {"key_id": "fixture-key", "payload": claims,
                    "signature": base64.b64encode(private.sign(canonical(claims))).decode("ascii")}
        activate_exception(fixture.manifest, envelope,
                           Ed25519AuthorizationVerifier({"fixture-key": public}),
                           fixture.store_path)
        dispatcher = CompanyIntakeDispatcher(Repo(), fixture.root, queue_status=lambda: {"state": "WAITING_SAFE_BOUNDARY", "blocking_cycle_ids": ["CYC-OLD"]})
        with patch.dict("os.environ", {"COMPANY_RETAINED_KEY_ID": "fixture-key", "COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64": encoded}):
            eligibility = dispatcher._retained_eligibility(request(), dispatcher.queue_status(), dispatcher._retained_config())
        self.assertEqual(eligibility["exception_cycle"], "CYC-OLD")
        self.assertEqual(eligibility["manifest_digest"], fixture.manifest["manifest_digest"])
