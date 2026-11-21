"""One-tick supervised dispatcher for durable Company-event intake."""
from __future__ import annotations

from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile

from .company_events import (
    CompanyEventBridge, MANUAL_RETAINED_HOLD, _json_digest, _read_ordinary_event_file,
    is_manual_retained_event_request, read_verified_queued_event,
)
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

    def set_scrape_enabled(self, enabled):
        """Gate future supervised launches without changing intake or saved requests."""
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('intake_scrape_enabled',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("true" if enabled else "false",))

    @staticmethod
    def _scrape_enabled(db):
        row = db.execute("SELECT value FROM settings WHERE key='intake_scrape_enabled'").fetchone()
        # A journal written before the separate control keeps the behavior of
        # its existing intake setting. An explicit value gates future claims.
        return row is None or row == ("true",)

    def retained_enabled(self):
        with self._journal() as db:
            row = db.execute("SELECT value FROM settings WHERE key='retained_intake_enabled'").fetchone()
            return row is not None and row[0] == "true"

    def temporary_retry_enabled(self):
        with self._journal() as db:
            row = db.execute("SELECT value FROM settings WHERE key='temporary_retry_enabled'").fetchone()
            return row is not None and row[0] == "true"

    def set_temporary_retry_enabled(self, enabled):
        """Separate default-off gate for M3 automatic rescrape admission."""
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('temporary_retry_enabled',?) "
                       "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       ("true" if enabled else "false",))

    def set_retained_enabled(self, enabled):
        """A separate, default-disabled consent for exceptional intake."""
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('retained_intake_enabled',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("true" if enabled else "false",))

    def status(self):
        if not self.journal_path.exists():
            return {"enabled": False, "scrape_enabled": False,
                    "retained_enabled": False, "temporary_retry_enabled": False,
                    "retained_configured": self._retained_config() is not None,
                    "dispatches": {}, "ownership": {}, "ordinary_handoff": None, "last_error": ""}
        with self._journal() as db:
            enabled = db.execute("SELECT value FROM settings WHERE key='intake_enabled'").fetchone()
            scrape_enabled = enabled == ("true",) and self._scrape_enabled(db)
            error = db.execute("SELECT value FROM settings WHERE key='last_intake_error'").fetchone()
            retained = db.execute("SELECT value FROM settings WHERE key='retained_intake_enabled'").fetchone()
            temporary = db.execute("SELECT value FROM settings WHERE key='temporary_retry_enabled'").fetchone()
            rows = db.execute("SELECT state,count(*) FROM dispatches GROUP BY state").fetchall()
            routes = db.execute("SELECT route,state,count(*) FROM request_ownership GROUP BY route,state").fetchall()
            ordinary = self._ordinary_pending(db)
        handoff = self._ordinary_identity(ordinary)
        return {"enabled": bool(enabled and enabled[0] == "true"),
                "scrape_enabled": scrape_enabled,
                "retained_enabled": bool(retained and retained[0] == "true"),
                "temporary_retry_enabled": bool(temporary and temporary[0] == "true"),
                "retained_configured": self._retained_config() is not None,
                "dispatches": {state: count for state, count in rows},
                "ownership": {route + ":" + state: count for route, state, count in routes},
                "ordinary_handoff": handoff,
                "last_error": error[0] if error else ""}

    def record_error(self, error):
        """Persist an intake-only failure without changing sync/local work."""
        value = (type(error).__name__ + ": " + str(error))[:500]
        with self._journal() as db:
            db.execute("INSERT INTO settings(key,value) VALUES('last_intake_error',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        return value

    def reconcile_ordinary(self):
        """Reconcile an existing ordinary claim without bridging or launching work."""
        if not self.ordinary_reconciliation_enabled():
            return {"state": "DISABLED"}
        return self._reconcile_ordinary()

    def ordinary_reconciliation_enabled(self):
        """Check the persisted gate without initializing a dispatcher journal."""
        path = self.journal_path
        if path.is_symlink():
            raise ValueError("Company intake journal may not be a symlink.")
        if not path.is_file():
            return False
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='settings' AND type='table'").fetchone() is None:
                return False
            row = db.execute("SELECT value FROM settings WHERE key='intake_enabled'").fetchone()
        return row == ("true",)

    def run_once(self):
        """Perform one supervised catch-up tick; never wait or start a loop."""
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.enabled():
            return {"state": "DISABLED"}
        request_path = self.root / "next-scan.json"
        if request_path.is_symlink() or (request_path.exists() and not request_path.is_file()):
            return {"state": "HELD_REQUEST_UNREADABLE"}
        bridge = CompanyEventBridge(self.repository, self.root)
        try:
            if bridge.manually_held_request():
                return {"state": MANUAL_RETAINED_HOLD}
        except (OSError, ValueError, RuntimeError):
            return {"state": "HELD_REQUEST_UNREADABLE"}
        ordinary = self._reconcile_ordinary()
        if ordinary is not None:
            return ordinary
        workflow_state, workflow = self._workflow_state()
        if workflow_state == "UNREADABLE":
            return {"state": "HELD_WORKFLOW_UNREADABLE"}
        if workflow_state in {"UNFINISHED", "COMPLETE"}:
            binding = self._workflow_binding(workflow)
            if binding is None:
                return {"state": "HELD_UNMATCHED_WORKFLOW"}
            request_id, digest = binding
            if not request_id.startswith("temporary-retry:"):
                return {"state": "HELD_LEGACY_INTAKE_WORKFLOW", "request_id": request_id}
            if workflow_state == "COMPLETE":
                self._mark_workflow_complete(request_id, digest)
            else:
                held = self._guard_hold()
                if held is not None:
                    return {"state": held}
                if (self.root / "next-scan.json").exists() or (self.root / "next-scan.json").is_symlink():
                    return {"state": "HELD_QUEUED_REQUEST_REVIEW"}
                reservation = self._resume_reservation(request_id, digest)
                if reservation == "HELD_SCRAPE_DISABLED":
                    return {"state": reservation}
                if reservation != "RESERVED":
                    return {"state": "HELD_WORKFLOW_RESERVATION"}
                return self._spawn(request_id, self.command + ("--resume",), [], resume=True)
        retained_recovery = self._reconcile_retained_ownership()
        if retained_recovery is not None:
            return retained_recovery
        # A durable M3 retry owns the single request slot.  Do not invoke the
        # Company-event bridge while that slot is occupied by this unrelated
        # lineage.
        temporary_request = False
        if request_path.exists():
            try:
                probe = json.loads(request_path.read_text(encoding="utf-8"))
                from .temporary_retry import is_temporary_retry_request
                temporary_request = is_temporary_retry_request(probe)
            except (OSError, ValueError):
                return {"state": "HELD_REQUEST_UNREADABLE"}
            if not temporary_request and not is_event_bound_company_request(probe):
                return {"state": "HELD_FOREIGN_REQUEST"}
        if temporary_request:
            bridge_results = []
            if not self.temporary_retry_enabled():
                return {"state": "HELD_TEMPORARY_RETRY_DISABLED", "bridge": bridge_results}
        else:
            try:
                bridge_results = bridge.process_pending()
            except Exception as exc:
                return {"state": "HELD_BRIDGE_BOUNDARY", "detail": str(exc)}
        if not request_path.exists():
            if any(result["state"] == "WAITING_FOR_UNFINISHED_CYCLE" for result in bridge_results):
                return {"state": "HELD_UNFINISHED_CYCLE", "bridge": bridge_results}
            return {"state": "NO_READY_REQUEST", "bridge": bridge_results}
        try:
            request = json.loads(request_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"state": "HELD_REQUEST_UNREADABLE", "bridge": bridge_results, "detail": str(exc)}
        if is_manual_retained_event_request(request):
            return {"state": MANUAL_RETAINED_HOLD}
        from .temporary_retry import is_temporary_retry_request
        temporary_request = is_temporary_retry_request(request)
        if not is_event_bound_company_request(request) and not temporary_request:
            return {"state": "HELD_FOREIGN_REQUEST", "bridge": bridge_results}
        digest = _json_digest(request)
        try:
            status = self.queue_status()
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            return {"state": "HELD_REQUEST_UNREADABLE", "bridge": bridge_results}
        retained = None if temporary_request else self._retained_tick(request, digest, status, bridge_results)
        if retained is not None:
            return retained
        if status.get("state") != "READY_FOR_START":
            return {"state": "HELD_" + str(status.get("state", "UNKNOWN")), "bridge": bridge_results, "queue": status}
        held = self._guard_hold()
        if held is not None:
            return {"state": held, "bridge": bridge_results}
        if temporary_request and not self._temporary_request_current(request):
            return {"state": "HELD_TEMPORARY_RETRY_SOURCE_CHANGED", "bridge": bridge_results}
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return {"state": "HELD_REQUEST_ID", "bridge": bridge_results}
        if not temporary_request:
            return self._launch_ordinary(request_id, digest, bridge_results)
        reservation = self._reserve(request_id, digest)
        if reservation != "RESERVED":
            return {"state": reservation, "bridge": bridge_results, "request_id": request_id}
        self._write_handoff(request_id, digest)
        return self._spawn(request_id, self.command, bridge_results, resume=False)

    def _ordinary_command(self, action, digest, cycle_id=None):
        command = (str(PROJECT_ROOT / "job-search-scraper"), "ordinary-company-event", action,
                   "--request-sha256", digest)
        return command if cycle_id is None else command + ("--cycle-id", cycle_id)

    @staticmethod
    def _ordinary_pending(db):
        return db.execute(
            "WITH pending AS (SELECT request_id FROM dispatches WHERE state IN ('ORDINARY_CLAIMED','ORDINARY_ADMITTED') "
            "UNION SELECT request_id FROM request_ownership WHERE state IN ('ORDINARY_CLAIMED','ORDINARY_ADMITTED')) "
            "SELECT p.request_id,d.request_digest,d.cycle_id,d.state,o.request_digest,o.route,o.state "
            "FROM pending p LEFT JOIN dispatches d USING(request_id) "
            "LEFT JOIN request_ownership o USING(request_id)",
        ).fetchall()

    @staticmethod
    def _ordinary_identity(pending):
        if len(pending) != 1:
            return None
        request_id, digest, cycle, state, owner_digest, route, owner_state = pending[0]
        if (digest != owner_digest or route != "NORMAL" or state not in {"ORDINARY_CLAIMED", "ORDINARY_ADMITTED"}
                or owner_state != state or not isinstance(request_id, str)
                or not request_id.startswith("company-event:") or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or (cycle is not None and (not isinstance(cycle, str) or not re.fullmatch(r"CYC-[0-9A-F]{12}", cycle)))):
            return None
        result = {"request_id": request_id, "request_sha256": digest}
        if cycle is not None:
            result["cycle_id"] = cycle
        return result

    def _launch_ordinary(self, request_id, digest, bridge_results):
        try:
            _, request = read_verified_queued_event(self.repository, self.root)
            if request["request_id"] != request_id or _json_digest(request) != digest:
                raise ValueError("ordinary dispatch request changed before claim")
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            return {"state": "HELD_ORDINARY_QUEUE_EVIDENCE", "request_id": request_id}
        with self._journal() as db:
            gate = db.execute("SELECT value FROM settings WHERE key='intake_enabled'").fetchone()
            if gate != ("true",):
                return {"state": "DISABLED"}
            if not self._scrape_enabled(db):
                return {"state": "HELD_SCRAPE_DISABLED", "bridge": bridge_results, "request_id": request_id}
            if (self._ordinary_pending(db) or db.execute(
                    "SELECT 1 FROM request_ownership WHERE route='RETAINED' AND state!='RETAINED_CONSUMED'",
            ).fetchone()):
                return {"state": "HELD_INTAKE_OWNERSHIP", "request_id": request_id}
            if (db.execute("SELECT 1 FROM request_ownership WHERE request_id=?", (request_id,)).fetchone()
                    or db.execute("SELECT 1 FROM dispatches WHERE request_id=?", (request_id,)).fetchone()):
                return {"state": "HELD_ORDINARY_PRIOR_OWNERSHIP", "request_id": request_id}
            db.execute("INSERT INTO request_ownership(request_id,request_digest,route,state) "
                       "VALUES (?,?,'NORMAL','ORDINARY_CLAIMED')", (request_id, digest))
            db.execute("INSERT INTO dispatches(request_id,request_digest,state,detail) "
                       "VALUES (?,?,'ORDINARY_CLAIMED','exact launch reserved before process creation')",
                       (request_id, digest))
        result = {"bridge": bridge_results, "request_id": request_id, "request_sha256": digest}
        try:
            child = self.child_runner(self._ordinary_command("admit-fetch", digest))
        except Exception:
            return {"state": "HELD_ORDINARY_LAUNCH_UNCONFIRMED", **result}
        if isinstance(child, int):
            return {"state": "ORDINARY_CHILD_RETURNED", "returncode": child, **result}
        if not hasattr(child, "poll"):
            return {"state": "HELD_ORDINARY_LAUNCH_UNCONFIRMED", **result}
        return {"state": "ORDINARY_CHILD_LAUNCHED", **result}

    def _reconcile_ordinary(self):
        """Advance the handoff only on exact archive, observation and settlement evidence."""
        from .cli import scraper_lock_name
        from .engine import State
        from .integration_release import assert_release_settled
        from .ordinary_company_event_command import _publish_preflight, _queue_admission
        from .ordinary_company_event_fetch import _admission, _require_frozen_provider, DIRECTORY
        from .ordinary_event_settlement import _outcome_rows, _read_settlement, ordinary_event_outcome_settled
        from .retained_work_runner import assert_normal_lifecycle_not_held
        from .scan_request import _cycle_views, _unfinished_from_views
        from .scoped_provider_observation import read_observation
        from .sqlite_repository import SQLiteRepository

        with self._journal() as db:
            pending = self._ordinary_pending(db)
        if not pending:
            return None
        result = self._ordinary_identity(pending)
        if result is None:
            return {"state": "HELD_ORDINARY_OWNERSHIP"}
        request_id, digest, saved_cycle = result['request_id'], result['request_sha256'], result.get('cycle_id')
        _, _, _, dispatch_state, *_ = pending[0]
        if not _lock_available(self.root / scraper_lock_name()):
            return {"state": "HELD_SCRAPER_LOCK", **result}
        try:
            archive = self.root / "company-event-bridge" / "ordinary-admissions" / (digest + ".json")
            state_path, jobs = self.root / "state.db", self.root / "jobs.sqlite3"
            if not archive.exists() and not archive.is_symlink():
                if dispatch_state == "ORDINARY_ADMITTED":
                    raise ValueError("ordinary dispatch lost its admitted request archive")
                if not (self.root / "next-scan.json").is_file():
                    raise ValueError("ordinary dispatch has no exact queued or admitted request")
                _, queued = read_verified_queued_event(self.repository, self.root)
                if _json_digest(queued) != digest or queued["request_id"] != request_id:
                    raise ValueError("ordinary dispatch queue changed without a consumed admission")
                if state_path.is_symlink() or (state_path.exists() and not state_path.is_file()):
                    raise ValueError("ordinary dispatch State is unsafe")
                if state_path.is_file():
                    with closing(State(str(state_path), readonly=True)) as state:
                        cycles, mirrors = _cycle_views(self.repository, state)
                        matches = [cycle for cycle in cycles if cycle.get("start_request_id") == request_id]
                        if matches or saved_cycle is not None:
                            [cycle] = matches
                            _, _, cycle_id = _queue_admission(
                                self.repository, cycle["runtime_binding"], self.root, digest, saved_cycle, cycles, mirrors,
                            )
                            result["cycle_id"] = cycle_id
                if saved_cycle is not None and not state_path.is_file():
                    raise ValueError("ordinary dispatch lost its exact cycle")
                cycle_id = result.get("cycle_id")
                held = self._guard_hold()
                if held is not None:
                    return {"state": held, **result}
                if cycle_id is not None and not self._record_ordinary_cycle(pending, request_id, cycle_id, admitted=False):
                    return {"state": "HELD_ORDINARY_OWNERSHIP", **result}
                return {"state": "HELD_ORDINARY_ADMIT_FETCH", **result,
                        "continuation": self._ordinary_command("admit-fetch", digest, cycle_id)}
            request = _read_ordinary_event_file(archive)
            if request["request_id"] != request_id or _json_digest(request) != digest:
                raise ValueError("ordinary dispatch archive has a different request")
            if any(path.is_symlink() or not path.is_file() for path in (state_path, jobs)):
                raise ValueError("ordinary dispatch dependencies changed")
            with (closing(State(str(state_path), readonly=True)) as state,
                  closing(SQLiteRepository(jobs, self.repository.spreadsheet_id, readonly=True)) as local):
                [cycle] = [row for row in state.cycles() if row.get("start_request_id") == request_id]
                cycle_id = cycle["id"]
                if saved_cycle is not None and cycle_id != saved_cycle:
                    raise ValueError("ordinary dispatch cycle changed")
                root, _, admission, binding = _admission(local, state, cycle["runtime_binding"], cycle_id, digest)
                observation = read_observation(root / DIRECTORY / (cycle_id + ".json"), binding)
                result["cycle_id"] = cycle_id
                settlement = _read_settlement(local, cycle_id, request_id)
                terminal = cycle.get("status") in {"Complete", "Complete with exceptions"}
                if terminal:
                    if not settlement or observation is None or observation["state"] != "FROZEN":
                        raise ValueError("ordinary dispatch terminal cycle lacks exact settlement evidence")
                    _require_frozen_provider(observation["inventory"], binding)
                    outcome = settlement["outcome"]
                    rows = _outcome_rows(local, settlement["binding"])
                    identity = outcome["identity"]
                    if (settlement["binding"]["request_sha256"] != digest or len(rows) != 1
                            or rows[0][:6] != (outcome["outcome_id"], request_id, identity["company_id"],
                                               identity["source_revision"], outcome["outcome"], outcome["action"])
                            or rows[0][-1] != settlement["recorded_at"] or json.loads(rows[0][-2]) != outcome
                            or not ordinary_event_outcome_settled(local, outcome)):
                        raise ValueError("ordinary dispatch terminal outcome proof changed")
                else:
                    if _unfinished_from_views(*_cycle_views(local, state)) - {cycle_id}:
                        return {"state": "HELD_ORDINARY_COMPETING_CYCLE", **result}
                    assert_release_settled(self.root)
                    assert_normal_lifecycle_not_held(self.root, jobs, ordinary_event_cycle_id=cycle_id)
                    if observation is not None and observation["state"] == "FROZEN":
                        _require_frozen_provider(observation["inventory"], binding)
                        scope = _publish_preflight(
                            local, state, cycle["runtime_binding"], cycle, admission, root / "inventories.sqlite3",
                        )
                        if scope == "held":
                            return {"state": "HELD_ORDINARY_NO_PUBLICATION_SCOPE", **result}
        except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError, AttributeError):
            return {"state": "HELD_ORDINARY_EVIDENCE", **result}

        if not self._record_ordinary_cycle(pending, request_id, cycle_id, terminal=terminal):
            return {"state": "HELD_ORDINARY_OWNERSHIP", **result}
        if terminal:
            return {"state": "ORDINARY_SETTLED", **result}
        if observation is None:
            return {"state": "HELD_ORDINARY_ADMIT_FETCH", **result,
                    "continuation": self._ordinary_command("admit-fetch", digest, cycle_id)}
        if observation["state"] != "FROZEN":
            return {"state": "HELD_ORDINARY_FETCH_UNCERTAIN", **result}
        return {"state": "HELD_ORDINARY_PUBLICATION", **result,
                "continuation": self._ordinary_command("publish", digest, cycle_id)}

    def _record_ordinary_cycle(self, pending, request_id, cycle_id, *, terminal=False, admitted=True):
        with self._journal() as db:
            gate = db.execute("SELECT value FROM settings WHERE key='intake_enabled'").fetchone()
            if gate != ("true",) or self._ordinary_pending(db) != pending:
                return False
            state = "ORDINARY_SETTLED" if terminal else "ORDINARY_ADMITTED" if admitted else "ORDINARY_CLAIMED"
            db.execute("UPDATE dispatches SET cycle_id=?,state=? WHERE request_id=?", (cycle_id, state, request_id))
            db.execute("UPDATE request_ownership SET state=? WHERE request_id=?", (state, request_id))
        return True

    def _temporary_request_current(self, request):
        from .company_events import current_company_source_revision
        retry = request.get('temporary_retry')
        if not isinstance(retry, dict):
            return False
        company_id = retry.get('company_id')
        if current_company_source_revision(self.repository, company_id) != retry.get('source_revision'):
            return False
        matches = self.repository.matches('Companies', {'Company ID': company_id})
        return len(matches) == 1 and not matches[0][1].get('Claimed By') and not matches[0][1].get('Claim Token')

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
        if not self._record_retained_recoverable(
                request_id, "reconciling retained owner after restart", for_launch=True):
            return {"state": "HELD_SCRAPE_DISABLED", "request_id": request_id}
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
            if not self._scrape_enabled(db):
                return "HELD_SCRAPE_DISABLED"
            if self._ordinary_pending(db):
                return "HELD_ORDINARY_OWNERSHIP"
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

    def _record_retained_recoverable(self, request_id, detail, *, for_launch=False):
        with self._journal() as db:
            if for_launch and not self._scrape_enabled(db):
                return False
            db.execute("UPDATE request_ownership SET state='RETAINED_RECOVERABLE',pid=NULL,pid_start=NULL,detail=? WHERE request_id=? AND route='RETAINED'", (detail, request_id))
            return True

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
        database = CompanyEventBridge(self.repository, self.root).state_database
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
            if not self._scrape_enabled(db):
                return "HELD_SCRAPE_DISABLED"
            if self._ordinary_pending(db):
                return "HELD_ORDINARY_OWNERSHIP"
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
            if not self._scrape_enabled(db):
                return "HELD_SCRAPE_DISABLED"
            if self._ordinary_pending(db):
                return "HELD"
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
            if "cycle_id" not in {row[1] for row in db.execute("PRAGMA table_info(dispatches)")}:
                db.execute("ALTER TABLE dispatches ADD COLUMN cycle_id TEXT")
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
