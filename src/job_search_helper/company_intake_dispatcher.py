"""One-tick supervised dispatcher for durable Company-event intake.

This is intentionally not a scheduler or a second scraper.  The coordinator
host calls :meth:`CompanyIntakeDispatcher.run_once` after reconciliation (and
on its normal bounded catch-up tick).  The method first lets the durable event
bridge write the normal ``next-scan.json`` request, then invokes only the
public ``job-search-scraper start`` command when the existing lifecycle says
that request is ready.  Its tiny SQLite journal prevents a restart from
starting the same request twice.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

from .company_events import CompanyEventBridge, _json_digest
from .cli import PROJECT_ROOT


class CompanyIntakeDispatcher:
    """Durable, one-shot admission adapter for a coordinator supervision tick."""

    def __init__(self, repository, state_directory, *, command=None,
                 child_runner=None, queue_status=None):
        self.repository = repository
        self.root = Path(state_directory).resolve()
        self.command = tuple(command or (str(PROJECT_ROOT / "job-search-scraper"), "start"))
        self.child_runner = child_runner or self._public_start
        self.queue_status = queue_status or self._queue_status
        if child_runner is None and self.command != (str(PROJECT_ROOT / "job-search-scraper"), "start"):
            raise ValueError("dispatcher must invoke the public job-search-scraper start lifecycle")

    @property
    def journal_path(self):
        return self.root / "company-intake-dispatch.sqlite3"

    def enabled(self):
        with self._journal() as db:
            row = db.execute("SELECT value FROM settings WHERE key='intake_enabled'").fetchone()
            return row is not None and row[0] == "true"

    def set_enabled(self, enabled):
        """Durably gate supervised intake; a new store is disabled by default."""
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('intake_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("true" if enabled else "false",))

    def run_once(self):
        """Perform one supervised catch-up tick; never wait or start a loop."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.enabled():
            return {"state": "DISABLED"}
        workflow_state, workflow = self._workflow_state()
        if workflow_state == "UNREADABLE":
            return {"state": "HELD_WORKFLOW_UNREADABLE"}
        if workflow_state in {"UNFINISHED", "COMPLETE"}:
            binding = self._workflow_binding(workflow)
            if binding is None:
                return {"state": "HELD_UNMATCHED_WORKFLOW"}
            request_id, digest = binding
            if workflow_state == "COMPLETE":
                self._mark_workflow_complete(request_id, digest)
            else:
                held = self._guard_hold()
                if held is not None:
                    return {"state": held}
                if self._resume_reservation(request_id, digest) != "RESERVED":
                    return {"state": "HELD_WORKFLOW_RESERVATION"}
                return self._spawn(request_id, self.command + ("--resume",), [], resume=True)
        try:
            bridge_results = CompanyEventBridge(self.repository, self.root).process_pending()
        except Exception as exc:
            # A live scraper owns the same lock.  A supervision tick must stay
            # responsive; the outbox remains unacknowledged for its next tick.
            return {"state": "HELD_BRIDGE_BOUNDARY", "detail": str(exc)}
        request_path = self.root / "next-scan.json"
        if not request_path.exists():
            return {"state": "NO_READY_REQUEST", "bridge": bridge_results}
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"state": "HELD_REQUEST_UNREADABLE", "bridge": bridge_results, "detail": str(exc)}
        if not is_event_bound_company_request(request):
            return {"state": "HELD_FOREIGN_REQUEST", "bridge": bridge_results}
        status = self.queue_status()
        if status.get("state") != "READY_FOR_START":
            return {"state": "HELD_" + str(status.get("state", "UNKNOWN")),
                    "bridge": bridge_results, "queue": status}
        held = self._guard_hold()
        if held is not None:
            return {"state": held, "bridge": bridge_results}
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return {"state": "HELD_REQUEST_ID", "bridge": bridge_results}
        digest = _json_digest(request)
        command = self.command
        reservation = self._reserve(request_id, digest)
        if reservation != "RESERVED":
            return {"state": reservation, "bridge": bridge_results, "request_id": request_id}
        self._write_handoff(request_id, digest)
        return self._spawn(request_id, command, bridge_results, resume=False)

    def _spawn(self, request_id, command, bridge_results, *, resume):
        try:
            child = self.child_runner(command)
        except BaseException as exc:
            self._finish(request_id, "CHILD_FAILED", detail=type(exc).__name__ + ": " + str(exc))
            return {"state": "CHILD_FAILED", "bridge": bridge_results, "request_id": request_id}
        if isinstance(child, int):
            if child == 0:
                self._finish(request_id, "CHILD_LAUNCHED", detail="test child completed")
                return {"state": "CHILD_LAUNCHED", "bridge": bridge_results, "request_id": request_id}
            self._finish(request_id, "CHILD_FAILED", detail="exit=" + str(child))
            return {"state": "CHILD_FAILED", "bridge": bridge_results, "request_id": request_id,
                    "returncode": child}
        if not hasattr(child, "poll"):
            self._finish(request_id, "CHILD_FAILED", detail="public child returned no PID")
            return {"state": "CHILD_FAILED", "bridge": bridge_results, "request_id": request_id}
        # Do not wait or infer completion from a PID.  The public controller's
        # workflow journal is the only cross-restart lifecycle authority.
        self._finish(request_id, "CHILD_LAUNCHED", detail="public lifecycle spawned")
        return {"state": "CHILD_LAUNCHED", "bridge": bridge_results, "request_id": request_id,
                "resume": resume}

    def _queue_status(self):
        from .engine import State
        from .scan_request import company_only_queue_status
        database = self.root / "state.db"
        if not database.is_file():
            return {"state": "WAITING_SAFE_BOUNDARY", "reason": "state database is absent"}
        state = State(str(database), readonly=True)
        try:
            probe = type("CompanyIntakeProbe", (), {"repo": self.repository})()
            return company_only_queue_status(probe, state, database)
        finally:
            state.close()

    def _guard_hold(self):
        # The public child acquires these locks for real.  This preflight is a
        # fail-closed supervision decision, not a replacement for that guard.
        from .cli import scraper_lock_name
        for name, held in ((scraper_lock_name(), "HELD_SCRAPER_LOCK"),
                           ("scrape-first-pass/controller.lock", "HELD_CONTROLLER_LOCK")):
            if not _lock_available(self.root / name):
                return held
        try:
            from .retained_work_runner import assert_normal_lifecycle_not_held
            from .integration_release import assert_release_settled
            from .cli import job_database_path
            assert_normal_lifecycle_not_held(self.root, job_database_path())
            assert_release_settled(self.root)
        except (RuntimeError, ValueError, OSError):
            return "HELD_LIFECYCLE_GUARD"
        return None

    def _reserve(self, request_id, request_digest, *, resume_existing=False):
        with self._journal() as db:
            row = db.execute("SELECT request_digest,state FROM dispatches WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[0] != request_digest:
                    return "HELD_REQUEST_ID_REUSED"
                if row[1] == "STARTING" or (row[1] == "CHILD_LAUNCHED" and resume_existing):
                    # STARTING means a host died before spawn.  A durable,
                    # unfinished workflow means its controller stopped and
                    # the public resume route is the authority.  In every
                    # other launched/failed case retain the request and hold.
                    db.execute("UPDATE dispatches SET state='STARTING',detail='reconciled supervisor retry',pid=NULL WHERE request_id=?",
                               (request_id,))
                    return "RESERVED"
                return "ALREADY_" + row[1]
            db.execute("INSERT INTO dispatches(request_id,request_digest,state,detail,pid) VALUES (?,?,?,?,NULL)",
                       (request_id, request_digest, "STARTING", "public lifecycle not yet spawned"))
            return "RESERVED"

    def _finish(self, request_id, state, *, detail=""):
        with self._journal() as db:
            changed = db.execute("UPDATE dispatches SET state=?,detail=? WHERE request_id=? AND state='STARTING'",
                                 (state, detail, request_id)).rowcount
            if changed != 1:
                raise RuntimeError("company intake dispatch reservation changed before child completion")

    def _workflow_binding(self, workflow):
        handoff = workflow.get("company_intake") if isinstance(workflow, dict) else None
        if (not isinstance(handoff, dict) or set(handoff) != {"request_id", "request_digest"}
                or not isinstance(handoff["request_id"], str) or not isinstance(handoff["request_digest"], str)):
            return None
        with self._journal() as db:
            rows = db.execute("SELECT request_id FROM dispatches WHERE request_id=? AND request_digest=? AND state IN ('CHILD_LAUNCHED','WORKFLOW_COMPLETE')",
                              (handoff["request_id"], handoff["request_digest"])).fetchall()
        return (handoff["request_id"], handoff["request_digest"]) if len(rows) == 1 else None

    def _launched_request_id(self):
        with self._journal() as db:
            rows = db.execute("SELECT request_id FROM dispatches WHERE state='CHILD_LAUNCHED'").fetchall()
            return rows[0][0] if len(rows) == 1 else None

    def _resume_reservation(self, request_id, request_digest):
        with self._journal() as db:
            changed = db.execute("UPDATE dispatches SET state='STARTING',detail='reconciling durable paused workflow' WHERE request_id=? AND request_digest=? AND state='CHILD_LAUNCHED'", (request_id, request_digest)).rowcount
            return "RESERVED" if changed == 1 else "HELD"

    def _mark_workflow_complete(self, request_id, request_digest):
        with self._journal() as db:
            db.execute("UPDATE dispatches SET state='WORKFLOW_COMPLETE',detail='controller workflow journal completed' WHERE request_id=? AND request_digest=? AND state='CHILD_LAUNCHED'", (request_id, request_digest))

    def _write_handoff(self, request_id, request_digest):
        path = self.root / "scrape-first-pass" / "company-intake-handoff.json"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = {"request_id": request_id, "request_digest": request_digest}
        descriptor, temporary = tempfile.mkstemp(prefix=".handoff.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    @contextmanager
    def _journal(self):
        db = sqlite3.connect(self.journal_path)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS dispatches (request_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL, pid INTEGER)")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(dispatches)")}
            if "pid" not in columns:
                db.execute("ALTER TABLE dispatches ADD COLUMN pid INTEGER")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _public_start(command):
        # Popen is deliberate: coordinator supervision remains responsive and
        # later ticks monitor the durable child ownership rather than waiting
        # through a scrape and FIRST PASS.
        return subprocess.Popen(command)

    def _workflow_state(self):
        latest = self.root / "scrape-first-pass" / "latest.json"
        try:
            pointer = json.loads(latest.read_text(encoding="utf-8"))
            workflow = json.loads(Path(pointer["workflow"]).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "NONE", None
        except (OSError, ValueError, KeyError, TypeError):
            # A malformed authority is held by the controller itself; do not
            # substitute a fresh start around it.
            return "UNREADABLE", None
        return ("COMPLETE", workflow) if workflow.get("stage") == "COMPLETE" else ("UNFINISHED", workflow)

    _is_bridge_request = staticmethod(lambda request: is_event_bound_company_request(request))


def _lock_available(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        try:
            return True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def is_event_bound_company_request(request):
    """One canonical identity check shared by dispatcher and controller."""
    if not isinstance(request, dict):
        return False
    event = request.get("company_event") if isinstance(request, dict) else None
    if request.get("mode") != "company-only" or not isinstance(event, dict):
        return False
    event_id = event.get("event_id")
    company_id = event.get("company_id")
    revision = event.get("source_revision")
    return (event.get("schema") == "company-event-scan-request-v1"
            and isinstance(event_id, str) and bool(event_id)
            and request.get("request_id") == "company-event:" + event_id
            and isinstance(company_id, str) and bool(company_id)
            and request.get("company_ids") == [company_id]
            and isinstance(revision, str) and bool(revision)
            and request.get("source_revision") == revision)
