"""Durable F8 supervision for the existing MuleLab coordinator service.

This module does not create another scheduler.  It owns only maintenance:
durable intake catch-up, disk-pressure holds, shutdown pause semantics and a
read-only retention/support report.  The coordinator's existing scheduler
lock remains the sole task owner.
"""
from __future__ import annotations

import fcntl
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time


SCHEMA = "coordinator-supervision-v1"
POLICY = "preserve-unacknowledged-active-release-and-recovery-evidence"
_PROTECTED_TABLES = (
    "tasks", "receipts", "inference_receipts", "scrape_outcome_intake",
    "repair_intake", "repair_intake_evidence", "repair_retry_lineage",
)


def external_retention_snapshot(database, *, company_consumer,
                                outcome_consumer):
    """Read-only counts for evidence owned by scraper and release storage."""
    database = Path(database)
    counts = {
        "unacknowledged_company_events": 0,
        "unacknowledged_scrape_outcomes": 0,
        "unconfirmed_publication_receipts": 0,
        "nonterminal_release_journals": 0,
        "active_release_records": 0,
    }
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        counts["unacknowledged_company_events"] = int(connection.execute(
            "SELECT count(*) FROM company_event_outbox o LEFT JOIN company_event_deliveries d "
            "ON d.event_id=o.event_id AND d.consumer=? WHERE d.event_id IS NULL",
            (company_consumer,)).fetchone()[0])
        counts["unacknowledged_scrape_outcomes"] = int(connection.execute(
            "SELECT count(*) FROM scrape_outcomes o LEFT JOIN scrape_outcome_deliveries d "
            "ON d.outcome_id=o.outcome_id AND d.consumer=? WHERE d.outcome_id IS NULL",
            (outcome_consumer,)).fetchone()[0])
    finally:
        connection.close()

    inventory = database.parent / "inventories.sqlite3"
    if inventory.exists():
        connection = sqlite3.connect(f"file:{inventory}?mode=ro", uri=True)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_receipts'"
            ).fetchone()
            if table:
                counts["unconfirmed_publication_receipts"] = int(connection.execute(
                    "SELECT count(*) FROM publication_receipts WHERE state!='SYNC_CONFIRMED'"
                ).fetchone()[0])
        finally:
            connection.close()

    journal_path = database.parent / "integration-release-journal.json"
    if journal_path.exists():
        journal = json.loads(journal_path.read_text())
        if journal.get("state") not in ("COMPLETE", "ROLLED_BACK"):
            counts["nonterminal_release_journals"] = 1
            record = journal.get("record")
            counts["active_release_records"] = int(
                isinstance(record, str) and Path(record).is_dir())
    return counts


def support_matrix():
    """Report the configured automatic scope without broadening it."""
    from coordinator_repair_profiles import PROFILE_REGISTRY
    automatic = sorted({str(item.get("profile_id", "")).strip()
                        for item in PROFILE_REGISTRY if isinstance(item, dict)
                        and str(item.get("profile_id", "")).strip()})
    return {
        "automatic_profiles": automatic,
        "engineering_review": "all unmatched or unqualified capabilities",
    }


class CoordinatorSupervision:
    def __init__(self, coordinator, catch_up, *, disk_usage=shutil.disk_usage,
                 min_free_bytes=2 * 1024**3, min_free_ratio=0.05, clock=time.time,
                 retention_probe=None):
        if not callable(catch_up):
            raise ValueError("Supervision requires a durable catch-up callback")
        self.coordinator = coordinator
        self.store = coordinator.store
        self.catch_up = catch_up
        self.disk_usage = disk_usage
        self.min_free_bytes = int(min_free_bytes)
        self.min_free_ratio = float(min_free_ratio)
        self.clock = clock
        self.retention_probe = retention_probe
        self.stop = threading.Event()
        # This is distinct from a failed/dead maintenance thread.  The host
        # watchdog must stand down before an intentional shutdown begins.
        self.planned_shutdown = threading.Event()
        self.thread = None
        self.lock_handle = None

    def _retention(self):
        with self.store.connect() as db:
            counts = {}
            for table in _PROTECTED_TABLES:
                counts[table] = int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        result = {"policy": POLICY, "protected_counts": counts,
                  "external_protected_counts": {}, "automatic_cleanup": False}
        if self.retention_probe is not None:
            try:
                external = self.retention_probe()
                if not isinstance(external, dict):
                    raise ValueError("retention probe did not return counts")
                result["external_protected_counts"] = {
                    str(key): int(value) for key, value in external.items()
                    if isinstance(key, str) and type(value) is int and value >= 0
                }
            except Exception as exc:
                # A visibility failure can never authorize deletion.  Keep the
                # hold policy and expose that the external count needs retry.
                result["external_probe_error"] = (
                    f"{type(exc).__name__}: {str(exc)[:160]}")
        return result

    def _record(self, state, *, usage=None, catch_up=None, error="",
                recovery_required=False):
        usage = usage or self.disk_usage(self.store.base)
        record = {
            "schema": SCHEMA,
            "state": state,
            "updated_at": float(self.clock()),
            "disk": {"free_bytes": int(usage.free), "total_bytes": int(usage.total)},
            "retention": self._retention(),
            "support": support_matrix(),
            "catch_up": catch_up if isinstance(catch_up, dict) else {},
            "error": str(error)[:250],
            "recovery_required": bool(recovery_required),
        }
        with self.store.connect() as db:
            db.execute(
                "INSERT INTO settings(key,value) VALUES('supervision_status',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (json.dumps(record, sort_keys=True, separators=(",", ":")),),
            )
        return record

    def status(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key='supervision_status'").fetchone()
        return json.loads(row[0]) if row else None

    def acquire(self):
        if self.lock_handle is not None:
            return
        path = Path(self.store.base) / "supervision.lock"
        handle = path.open("a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            handle.close()
            raise RuntimeError("Another coordinator process owns supervision") from None
        self.lock_handle = handle

    def release(self):
        if self.lock_handle is not None:
            self.lock_handle.close()
            self.lock_handle = None

    def tick(self):
        """Run one bounded catch-up pass or establish a durable safety hold."""
        usage = self.disk_usage(self.store.base)
        ratio = usage.free / usage.total if usage.total else 0.0
        if usage.free < self.min_free_bytes or ratio < self.min_free_ratio:
            self.store.configure_queue(False)
            self.coordinator.wake.set()
            return self._record("DISK_PRESSURE_HOLD", usage=usage,
                                error="Free space below the supervised safety threshold; all evidence retained")
        try:
            result = self.catch_up()
            bounded = result if isinstance(result, dict) else {"result": str(result)[:120]}
            return self._record("ACTIVE", usage=usage, catch_up=bounded)
        except Exception as exc:
            # The durable producer outbox remains authoritative.  Never ACK or
            # invent work after a catch-up transport/storage failure.
            return self._record("CATCHUP_RETRY", usage=usage,
                                error=f"{type(exc).__name__}: {str(exc)[:200]}")

    def start(self, *, interval=30):
        self.acquire()
        if self.thread and self.thread.is_alive():
            return
        self.stop.clear()

        def run():
            try:
                while not self.stop.is_set():
                    self.tick()
                    self.stop.wait(interval)
            finally:
                self.release()

        self.thread = threading.Thread(target=run, name="coordinator-supervision", daemon=True)
        self.thread.start()

    def _pause_completed_boundaries(self):
        """Persist the pause only after the scheduler no longer owns an action."""
        paused = []
        for state in self.store.all():
            if state.get("status") in ("RUNNING", "QUEUED", "PAUSING"):
                result = self.store.stop_at_boundary(
                    state["id"], "Service stopped at a safe action boundary.")
                paused.append({"id": state["id"], "status": result["status"]})
                try:
                    self.coordinator.export(state["id"])
                except (AttributeError, OSError):
                    # SQLite remains authoritative; snapshot retry is handled
                    # by normal startup reconciliation.
                    pass
        return paused

    def shutdown(self, reason="Service shutdown requested", *, boundary_timeout=30):
        """Pause every scheduler mode and wait for its current action boundary."""
        self.planned_shutdown.set()
        self.store.configure_queue(False)
        self.coordinator.stop.set()
        self.coordinator.wake.set()
        self.stop.set()
        usage = self.disk_usage(self.store.base)
        self._record("SHUTDOWN_REQUESTED", usage=usage, error=reason,
                     recovery_required=True)

        scheduler = getattr(self.coordinator, "thread", None)
        if scheduler and scheduler is not threading.current_thread():
            scheduler.join(max(0, float(boundary_timeout)))
        boundary_reached = not scheduler or not scheduler.is_alive()
        paused = self._pause_completed_boundaries() if boundary_reached else []

        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(5)
        else:
            self.release()
        if not boundary_reached:
            return self._record(
                "SHUTDOWN_RECOVERY_REQUIRED", usage=usage, error=reason,
                catch_up={"paused_boundaries": paused}, recovery_required=True)
        return self._record(
            "SHUTDOWN_PAUSED", usage=usage, error=reason,
            catch_up={"paused_boundaries": paused}, recovery_required=False)


def watchdog(coordinator, supervision, *, exit_process, interval=1):
    """Fail dead workers, but never convert a planned stop into a crash."""
    while not supervision.planned_shutdown.is_set():
        scheduler_dead = not coordinator.thread.is_alive()
        maintenance_dead = (supervision.thread is not None
                            and not supervision.thread.is_alive())
        if scheduler_dead or maintenance_dead:
            exit_process(75)
            return
        supervision.planned_shutdown.wait(interval)
