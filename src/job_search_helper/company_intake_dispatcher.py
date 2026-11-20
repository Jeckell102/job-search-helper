"""One-tick supervised dispatcher for durable Company-event intake."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import subprocess
import tempfile

from .company_events import CompanyEventBridge, _json_digest
from .cli import PROJECT_ROOT


class CompanyIntakeDispatcher:
    """Durable, one-shot admission adapter for a coordinator supervision tick."""

    def __init__(self, repository, state_directory, *, command=None,
                 child_runner=None, queue_status=None, retained_child_runner=None):
        self.repository = repository
        self.root = Path(state_directory).resolve()
        self.command = tuple(command or (str(PROJECT_ROOT / "job-search-scraper"), "start"))
        self.child_runner = child_runner or self._public_start
        self.retained_child_runner = retained_child_runner or self._public_retained_start
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
            db.execute("INSERT INTO settings(key,value) VALUES('intake_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("true" if enabled else "false",))

    def retained_enabled(self):
        with self._journal() as db:
            row = db.execute("SELECT value FROM settings WHERE key='retained_intake_enabled'").fetchone()
            return row is not None and row[0] == "true"

    def set_retained_enabled(self, enabled):
        """A separate, default-disabled consent for exceptional intake."""
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('retained_intake_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("true" if enabled else "false",))

    def status(self):
        if not self.journal_path.exists():
            return {"enabled": False, "retained_enabled": False,
                    "retained_configured": self._retained_config() is not None,
                    "dispatches": {}, "ownership": {}, "last_error": ""}
        with self._journal() as db:
            enabled = db.execute("SELECT value FROM settings WHERE key='intake_enabled'").fetchone()
            error = db.execute("SELECT value FROM settings WHERE key='last_intake_error'").fetchone()
            retained = db.execute("SELECT value FROM settings WHERE key='retained_intake_enabled'").fetchone()
            rows = db.execute("SELECT state,count(*) FROM dispatches GROUP BY state").fetchall()
            routes = db.execute("SELECT route,state,count(*) FROM request_ownership GROUP BY route,state").fetchall()
        return {"enabled": bool(enabled and enabled[0] == "true"),
                "retained_enabled": bool(retained and retained[0] == "true"),
                "retained_configured": self._retained_config() is not None,
                "dispatches": {state: count for state, count in rows},
                "ownership": {route + ":" + state: count for route, state, count in routes},
                "last_error": error[0] if error else ""}

    def record_error(self, error):
        """Persist an intake-only failure without changing sync/local work."""
        value = (type(error).__name__ + ": " + str(error))[:500]
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('last_intake_error',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        return value

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
        retained_recovery = self._reconcile_retained_ownership()
        if retained_recovery is not None:
            return retained_recovery
        try:
            bridge_results = CompanyEventBridge(self.repository, self.root).process_pending()
        except Exception as exc:
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
        digest = _json_digest(request)
        status = self.queue_status()
        retained = self._retained_tick(request, digest, status, bridge_results)
        if retained is not None:
            return retained
        if status.get("state") != "READY_FOR_START":
            return {"state": "HELD_" + str(status.get("state", "UNKNOWN")), "bridge": bridge_results, "queue": status}
        held = self._guard_hold()
        if held is not None:
            return {"state": held, "bridge": bridge_results}
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return {"state": "HELD_REQUEST_ID", "bridge": bridge_results}
        reservation = self._reserve(request_id, digest)
        if reservation != "RESERVED":
            return {"state": reservation, "bridge": bridge_results, "request_id": request_id}
        self._write_handoff(request_id, digest)
        return self._spawn(request_id, self.command, bridge_results, resume=False)

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
            return {"state": "CHILD_FAILED", "bridge": bridge_results, "request_id": request_id, "returncode": child}
        if not hasattr(child, "poll"):
            self._finish(request_id, "CHILD_FAILED", detail="public child returned no PID")
            return {"state": "CHILD_FAILED", "bridge": bridge_results, "request_id": request_id}
        self._finish(request_id, "CHILD_LAUNCHED", detail="public lifecycle spawned")
        return {"state": "CHILD_LAUNCHED", "bridge": bridge_results, "request_id": request_id, "resume": resume}

    def _retained_config(self):
        """Read ambient public verification material without exposing it."""
        key_id = os.environ.get("COMPANY_RETAINED_KEY_ID", "").strip()
        public_key = os.environ.get("COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64", "").strip()
        if not key_id or not public_key:
            return None
        return {"key_id": key_id,
                "public_key": public_key,
                "fingerprint": hashlib.sha256(public_key.encode("utf-8")).hexdigest()}

    def _retained_tick(self, request, request_digest, status, bridge_results):
        """Offer only an exactly-blocked request to the public retained route."""
        if status.get("state") != "WAITING_SAFE_BOUNDARY":
            return None
        blocking = status.get("blocking_cycle_ids")
        if not isinstance(blocking, list) or len(blocking) != 1 or not isinstance(blocking[0], str):
            return None
        request_id = request["request_id"]
        receipt_state = self._retained_receipt_state(request)
        if receipt_state == "VALID":
            self._record_retained_terminal(request_id, request_digest)
            return {"state": "RETAINED_CONSUMED", "bridge": bridge_results,
                    "request_id": request_id}
        if receipt_state == "INVALID":
            return {"state": "HELD_RETAINED_RECEIPT", "bridge": bridge_results}
        if not self.retained_enabled():
            return {"state": "HELD_RETAINED_DISABLED", "bridge": bridge_results}
        config = self._retained_config()
        if config is None:
            return {"state": "HELD_RETAINED_KEY_CONFIG", "bridge": bridge_results}
        try:
            eligibility = self._retained_eligibility(request, status, config)
        except (OSError, ValueError, RuntimeError, sqlite3.Error, ImportError) as exc:
            self._record_retained_hold(request_id, request_digest, str(exc))
            return {"state": "HELD_RETAINED_EXCEPTION", "bridge": bridge_results,
                    "detail": str(exc)}
        claimed = self._claim_retained(request_id, request_digest, eligibility, config)
        if claimed != "RESERVED":
            return {"state": claimed, "bridge": bridge_results, "request_id": request_id}
        owner = self._retained_owner(request_id)
        adopted = self._adopt_retained_child(owner["owner_token"] if owner else None)
        if adopted is not None:
            self._record_retained_active(request_id, adopted)
            return {"state": "RETAINED_CHILD_ACTIVE", "bridge": bridge_results,
                    "request_id": request_id}
        if owner and self._pid_is_exactly_live(owner["pid"], owner["pid_start"]):
            return {"state": "RETAINED_CHILD_ACTIVE", "bridge": bridge_results,
                    "request_id": request_id}
        return self._spawn_retained(request_id, request_digest, eligibility, config, bridge_results)

    def _reconcile_retained_ownership(self):
        """Settle or safely retain a prior retained owner before newer work."""
        with self._journal() as db:
            rows = db.execute("SELECT request_id,request_digest,state,exception_cycle,manifest_digest,key_fingerprint FROM request_ownership WHERE route='RETAINED' AND state!='RETAINED_CONSUMED'").fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            return {"state": "HELD_RETAINED_OWNERSHIP_AMBIGUOUS"}
        request_id, request_digest, state, cycle, manifest, fingerprint = rows[0]
        archived = self._retained_archived_request(request_id, request_digest)
        if archived is not None:
            receipt_state = self._retained_receipt_state(archived)
            if receipt_state == "VALID":
                self._record_retained_terminal(request_id, request_digest)
                return {"state": "RETAINED_CONSUMED", "request_id": request_id}
            if receipt_state == "INVALID":
                return {"state": "HELD_RETAINED_RECEIPT", "request_id": request_id}
        current = self._read_current_request()
        if current is not None and (current.get("request_id") != request_id or _json_digest(current) != request_digest) and archived is None:
            return {"state": "HELD_RETAINED_REQUEST_REPLACED", "request_id": request_id}
        config = self._retained_config()
        if not self.retained_enabled():
            return {"state": "HELD_RETAINED_DISABLED", "request_id": request_id}
        if config is None or config["fingerprint"] != fingerprint:
            return {"state": "HELD_RETAINED_KEY_CONFIG", "request_id": request_id}
        owner = self._retained_owner(request_id)
        adopted = self._adopt_retained_child(owner["owner_token"] if owner else None)
        if adopted is not None:
            self._record_retained_active(request_id, adopted)
            return {"state": "RETAINED_CHILD_ACTIVE", "request_id": request_id}
        if owner and self._pid_is_exactly_live(owner["pid"], owner["pid_start"]):
            return {"state": "RETAINED_CHILD_ACTIVE", "request_id": request_id}
        # An archive proves that this exact request reached post-settlement
        # recovery. The public retained command verifies it before factories.
        # If it has not archived yet, only recover when the exact request is
        # still current; a newer request is never substituted into its slot.
        if archived is None and current is None:
            return {"state": "HELD_RETAINED_REQUEST_MISSING", "request_id": request_id}
        if archived is None:
            try:
                eligibility = self._retained_eligibility(current, self.queue_status(), config)
            except (OSError, ValueError, RuntimeError, sqlite3.Error, ImportError) as exc:
                return {"state": "HELD_RETAINED_EXCEPTION", "request_id": request_id,
                        "detail": str(exc)}
            if (eligibility["exception_cycle"] != cycle
                    or eligibility["manifest_digest"] != manifest):
                return {"state": "HELD_RETAINED_BINDING_CHANGED", "request_id": request_id}
        self._record_retained_recoverable(request_id, "reconciling retained owner after restart")
        return self._spawn_retained(request_id, request_digest,
                                    {"exception_cycle": cycle, "manifest_digest": manifest},
                                    config, [])

    def _retained_archived_request(self, request_id, request_digest):
        directory = self.root / "company-event-bridge" / "consumed-requests"
        if not directory.is_dir():
            return None
        found = []
        for path in directory.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if isinstance(value, dict) and value.get("request_id") == request_id and _json_digest(value) == request_digest:
                found.append(value)
        return found[0] if len(found) == 1 else None

    def _read_current_request(self):
        path = self.root / "next-scan.json"
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _retained_eligibility(self, request, status, config):
        blocking = status.get("blocking_cycle_ids")
        if not isinstance(blocking, list) or len(blocking) != 1 or not isinstance(blocking[0], str):
            raise ValueError("retained_event_requires_exactly_one_blocker")
        from .engine import State
        from .retained_company_event import _verifier
        from .retained_work_exception import _active_record, revalidate_manifest
        verifier = _verifier(config["key_id"], config["public_key"])
        state = State(str(self.root / "state.db"), readonly=True)
        try:
            unfinished = [cycle for cycle in state.cycles()
                          if cycle.get("status") not in {"Complete", "Complete with exceptions"}]
            if len(unfinished) != 1 or unfinished[0].get("id") != blocking[0]:
                raise ValueError("retained_event_blocker_scope_changed")
            record = _active_record(self.root / "retained-work-exceptions.sqlite3", blocking[0], verifier)
            revalidate_manifest(record["manifest"], unfinished[0],
                                self.root / "inventories.sqlite3", self.root / "jobs.sqlite3")
        finally:
            state.close()
        return {"exception_cycle": blocking[0], "manifest_digest": record["manifest_digest"]}

    def _claim_retained(self, request_id, request_digest, eligibility, config):
        with self._journal() as db:
            row = db.execute("SELECT request_digest,route,state,key_fingerprint,manifest_digest FROM request_ownership WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[0] != request_digest:
                    return "HELD_REQUEST_ID_REUSED"
                if row[1] != "RETAINED":
                    return "HELD_NORMAL_OWNERSHIP"
                if row[3] != config["fingerprint"] or row[4] != eligibility["manifest_digest"]:
                    return "HELD_RETAINED_BINDING_CHANGED"
                if row[2] == "RETAINED_CONSUMED":
                    return "RETAINED_CONSUMED"
                db.execute("UPDATE request_ownership SET state='RETAINED_RECOVERABLE',owner_token=COALESCE(owner_token,?),detail='retained child absent; public recovery pending' WHERE request_id=?", (secrets.token_urlsafe(32), request_id))
                return "RESERVED"
            db.execute("INSERT INTO request_ownership(request_id,request_digest,route,state,exception_cycle,manifest_digest,key_id,key_fingerprint,owner_token,detail) VALUES (?,?,?,?,?,?,?,?,?,?)", (request_id, request_digest, "RETAINED", "RETAINED_STARTING", eligibility["exception_cycle"], eligibility["manifest_digest"], config["key_id"], config["fingerprint"], secrets.token_urlsafe(32), "public retained lifecycle not yet spawned"))
            return "RESERVED"

    def _retained_owner(self, request_id):
        with self._journal() as db:
            row = db.execute("SELECT request_digest,state,pid,pid_start,owner_token FROM request_ownership WHERE request_id=? AND route='RETAINED'", (request_id,)).fetchone()
        return None if row is None else {"request_digest": row[0], "state": row[1], "pid": row[2], "pid_start": row[3], "owner_token": row[4]}

    def _spawn_retained(self, request_id, request_digest, eligibility, config, bridge_results):
        command = (str(PROJECT_ROOT / "job-search-scraper"), "run-retained-company-event")
        owner = self._retained_owner(request_id)
        if owner is None or not owner["owner_token"]:
            self._record_retained_hold(request_id, request_digest, "retained owner token missing")
            return {"state": "RETAINED_CHILD_FAILED", "bridge": bridge_results, "request_id": request_id}
        environment = dict(os.environ, JOB_SEARCH_RETAINED_OWNER_TOKEN=owner["owner_token"])
        try:
            try:
                child = self.retained_child_runner(command, environment=environment)
            except TypeError:
                child = self.retained_child_runner(command)
        except BaseException as exc:
            self._record_retained_hold(request_id, request_digest, type(exc).__name__ + ": " + str(exc))
            return {"state": "RETAINED_CHILD_FAILED", "bridge": bridge_results, "request_id": request_id}
        if isinstance(child, int):
            self._record_retained_recoverable(request_id, "test child exit=" + str(child))
            return {"state": "RETAINED_CHILD_LAUNCHED", "bridge": bridge_results, "request_id": request_id}
        if not hasattr(child, "pid"):
            self._record_retained_hold(request_id, request_digest, "public retained child returned no PID")
            return {"state": "RETAINED_CHILD_FAILED", "bridge": bridge_results, "request_id": request_id}
        start = self._process_start_identity(child.pid)
        with self._journal() as db:
            db.execute("UPDATE request_ownership SET state='RETAINED_CHILD_ACTIVE',pid=?,pid_start=?,detail='public retained lifecycle spawned' WHERE request_id=? AND request_digest=? AND route='RETAINED'", (child.pid, start, request_id, request_digest))
        return {"state": "RETAINED_CHILD_LAUNCHED", "bridge": bridge_results, "request_id": request_id}

    def _record_retained_recoverable(self, request_id, detail):
        with self._journal() as db:
            db.execute("UPDATE request_ownership SET state='RETAINED_RECOVERABLE',pid=NULL,pid_start=NULL,detail=? WHERE request_id=? AND route='RETAINED'", (detail, request_id))

    def _record_retained_active(self, request_id, child):
        with self._journal() as db:
            db.execute("UPDATE request_ownership SET state='RETAINED_CHILD_ACTIVE',pid=?,pid_start=?,detail='retained child adopted after supervisor restart' WHERE request_id=? AND route='RETAINED'", (child[0], child[1], request_id))

    def _record_retained_hold(self, request_id, request_digest, detail):
        with self._journal() as db:
            db.execute("UPDATE request_ownership SET state='RETAINED_HELD',detail=? WHERE request_id=? AND request_digest=? AND route='RETAINED'", (detail[:500], request_id, request_digest))

    def _record_retained_terminal(self, request_id, request_digest):
        with self._journal() as db:
            db.execute("UPDATE request_ownership SET state='RETAINED_CONSUMED',detail='exact retained consumption receipt verified' WHERE request_id=? AND request_digest=? AND route='RETAINED'", (request_id, request_digest))

    def _retained_receipt_state(self, request):
        from .retained_work_runner import digest
        path_digest = digest(request)
        archive = self.root / "company-event-bridge" / "consumed-requests" / (path_digest + ".json")
        receipt = self.root / "company-event-bridge" / "consumption-receipts" / (path_digest + ".json")
        if archive.exists() != receipt.exists():
            return "INVALID"
        try:
            archived = json.loads(archive.read_text(encoding="utf-8"))
            value = json.loads(receipt.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "NONE"
        except (OSError, ValueError):
            return "INVALID"
        current = self.root / "next-scan.json"
        try:
            still_current = json.loads(current.read_text(encoding="utf-8")) if current.exists() else None
        except (OSError, ValueError):
            return "INVALID"
        return "VALID" if (archived == request and value == {"request_sha256": path_digest, "state": "FIRST_PASS_RELEASED_CONSUMED"} and still_current != request) else "INVALID"

    def _retained_consumed(self, request, request_digest):
        """Compatibility probe used by narrow recovery tests."""
        return self._retained_receipt_state(request) == "VALID"

    @staticmethod
    def _process_start_identity(pid):
        try:
            identity = CompanyIntakeDispatcher._process_identity(pid)
            return identity[0] if identity and identity[1] not in {"Z", "X", "x"} else None
        except (OSError, ValueError, IndexError):
            return None

    @staticmethod
    def _process_identity(pid):
        """Parse Linux stat without trusting spaces/parentheses in comm."""
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        _, tail = raw.rsplit(") ", 1)
        fields = tail.split()
        # tail starts at field 3 (state); starttime is field 22.
        return fields[19], fields[0]

    @classmethod
    def _pid_is_exactly_live(cls, pid, start):
        return isinstance(pid, int) and start is not None and cls._process_start_identity(pid) == start

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
        from .cli import scraper_lock_name, job_database_path
        for name, held in ((scraper_lock_name(), "HELD_SCRAPER_LOCK"), ("scrape-first-pass/controller.lock", "HELD_CONTROLLER_LOCK")):
            if not _lock_available(self.root / name):
                return held
        try:
            from .retained_work_runner import assert_normal_lifecycle_not_held
            from .integration_release import assert_release_settled
            assert_normal_lifecycle_not_held(self.root, job_database_path())
            assert_release_settled(self.root)
        except (RuntimeError, ValueError, OSError):
            return "HELD_LIFECYCLE_GUARD"
        return None

    def _reserve(self, request_id, request_digest):
        with self._journal() as db:
            owner = db.execute("SELECT request_digest,route FROM request_ownership WHERE request_id=?", (request_id,)).fetchone()
            if owner and owner[0] != request_digest:
                return "HELD_REQUEST_ID_REUSED"
            if owner and owner[1] != "NORMAL":
                return "HELD_RETAINED_OWNERSHIP"
            if not owner:
                db.execute("INSERT INTO request_ownership(request_id,request_digest,route,state) VALUES (?,?,?,?)", (request_id, request_digest, "NORMAL", "NORMAL_STARTING"))
            row = db.execute("SELECT request_digest,state FROM dispatches WHERE request_id=?", (request_id,)).fetchone()
            if row:
                if row[0] != request_digest:
                    return "HELD_REQUEST_ID_REUSED"
                if row[1] == "STARTING":
                    db.execute("UPDATE dispatches SET state='STARTING',detail='reconciled supervisor retry',pid=NULL WHERE request_id=?", (request_id,))
                    return "RESERVED"
                return "ALREADY_" + row[1]
            db.execute("INSERT INTO dispatches(request_id,request_digest,state,detail,pid) VALUES (?,?,?,?,NULL)", (request_id, request_digest, "STARTING", "public lifecycle not yet spawned"))
            return "RESERVED"

    def _finish(self, request_id, state, *, detail=""):
        with self._journal() as db:
            changed = db.execute("UPDATE dispatches SET state=?,detail=? WHERE request_id=? AND state='STARTING'", (state, detail, request_id)).rowcount
            if changed != 1:
                raise RuntimeError("company intake dispatch reservation changed before child completion")
            db.execute("UPDATE request_ownership SET state=? WHERE request_id=? AND route='NORMAL'", ("NORMAL_" + state.removeprefix("CHILD_"), request_id))

    def _workflow_binding(self, workflow):
        handoff = workflow.get("company_intake") if isinstance(workflow, dict) else None
        if (not isinstance(handoff, dict) or set(handoff) != {"request_id", "request_digest"} or not isinstance(handoff["request_id"], str) or not isinstance(handoff["request_digest"], str)):
            return None
        with self._journal() as db:
            rows = db.execute("SELECT request_id FROM dispatches WHERE request_id=? AND request_digest=? AND state IN ('CHILD_LAUNCHED','WORKFLOW_COMPLETE')", (handoff["request_id"], handoff["request_digest"])).fetchall()
        return (handoff["request_id"], handoff["request_digest"]) if len(rows) == 1 else None

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
        descriptor, temporary = tempfile.mkstemp(prefix=".handoff.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"request_id": request_id, "request_digest": request_digest}, handle, sort_keys=True, separators=(",", ":"))
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
            db.execute("CREATE TABLE IF NOT EXISTS request_ownership (request_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, route TEXT NOT NULL CHECK(route IN ('NORMAL','RETAINED')), state TEXT NOT NULL, exception_cycle TEXT, manifest_digest TEXT, key_id TEXT, key_fingerprint TEXT, pid INTEGER, pid_start TEXT, owner_token TEXT, detail TEXT NOT NULL DEFAULT '')")
            columns = {row[1] for row in db.execute("PRAGMA table_info(request_ownership)")}
            if "owner_token" not in columns:
                db.execute("ALTER TABLE request_ownership ADD COLUMN owner_token TEXT")
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
        return subprocess.Popen(command)

    @staticmethod
    def _public_retained_start(command, *, environment):
        return subprocess.Popen(command, env=environment, cwd=PROJECT_ROOT)

    def _adopt_retained_child(self, token):
        """Find only the exact, same-user public retained child by token."""
        if not isinstance(token, str) or not token:
            return None
        marker = b"JOB_SEARCH_RETAINED_OWNER_TOKEN=" + token.encode("ascii")
        for process in Path("/proc").glob("[0-9]*"):
            try:
                if marker not in (process / "environ").read_bytes().split(b"\0"):
                    continue
                uid = next((line.split()[1] for line in (process / "status").read_text(encoding="utf-8").splitlines() if line.startswith("Uid:")), None)
                if uid is None or int(uid) != os.getuid():
                    continue
                expected_python = self._expected_scraper_python()
                values = [part.decode("utf-8", "replace") for part in
                          (process / "cmdline").read_bytes().split(b"\0") if part]
                if (values != [str(expected_python), "-m", "job_search_helper.runner",
                               "run-retained-company-event"]
                        or (process / "exe").resolve() != expected_python.resolve()):
                    continue
                environment = (process / "environ").read_bytes().split(b"\0")
                pythonpath = next((item.split(b"=", 1)[1].decode("utf-8") for item in environment if item.startswith(b"PYTHONPATH=")), "")
                first = pythonpath.split(os.pathsep, 1)[0]
                if (not first or Path(first).resolve() != (PROJECT_ROOT / "src").resolve()
                        or (process / "cwd").resolve() != PROJECT_ROOT.resolve()):
                    continue
                pid = int(process.name)
                identity = self._process_identity(pid)
                if identity and identity[1] not in {"Z", "X", "x"}:
                    start = identity[0]
                    return pid, start
            except (OSError, ValueError):
                continue
        return None

    @staticmethod
    def _expected_scraper_python():
        bundled = PROJECT_ROOT / ".venv" / "bin" / "python"
        if bundled.is_file() and os.access(bundled, os.X_OK):
            # Preserve the wrapper's argv[0] spelling (normally the venv
            # symlink), then separately compare /proc/<pid>/exe by resolution.
            return bundled.absolute()
        selected = os.environ.get("PYTHON", "python3")
        found = shutil.which(selected)
        return Path(found or selected).resolve()

    def _workflow_state(self):
        latest = self.root / "scrape-first-pass" / "latest.json"
        try:
            pointer = json.loads(latest.read_text(encoding="utf-8"))
            workflow = json.loads(Path(pointer["workflow"]).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "NONE", None
        except (OSError, ValueError, KeyError, TypeError):
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
    event = request.get("company_event")
    if request.get("mode") != "company-only" or not isinstance(event, dict):
        return False
    event_id, company_id, revision = event.get("event_id"), event.get("company_id"), event.get("source_revision")
    return (event.get("schema") == "company-event-scan-request-v1" and isinstance(event_id, str) and bool(event_id)
            and request.get("request_id") == "company-event:" + event_id and isinstance(company_id, str) and bool(company_id)
            and request.get("company_ids") == [company_id] and isinstance(revision, str) and bool(revision)
            and request.get("source_revision") == revision)
