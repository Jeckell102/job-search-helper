"""Durable adapter handoff and atomic catalog reconciliation by one coordinator."""
from __future__ import annotations

from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
import json

from .ats import Inventory
from .posting import canonicalize_url
from .database import Database
from .models import (FETCH_STATUSES, INVENTORY_PAYLOAD_VERSION, InventorySnapshot, SourceScope,
                     canonical_json, fingerprint, new_id, utc_now)
from .repositories import CatalogRepository


class BatchValidationError(ValueError):
    """Retain an inventory for inspection instead of making uncertain changes."""


class ScanService:
    """Call from a single coordinator holding scan_lock during scan/resume."""

    def __init__(self, database: Database):
        self.database = database
        self.connection = database.connection
        self.catalog = CatalogRepository(database)

    def start_cycle(self, company_ids=None, *, all_companies=False, missing_threshold=2,
                    adapter_version="official-v1", run_settings=None) -> str:
        if bool(company_ids) == bool(all_companies):
            raise ValueError("Select company IDs or explicitly select all companies")
        if type(missing_threshold) is not int or not 1 <= missing_threshold <= 100:
            raise ValueError("Missing threshold must be an integer from 1 to 100")
        with self.database.transaction():
            unfinished = self.connection.execute(
                "SELECT cycle_id FROM scan_cycles WHERE status IN ('running', 'interrupted') LIMIT 1"
            ).fetchone()
            if unfinished:
                raise ValueError(f"Resume unfinished local cycle {unfinished[0]} before starting another")
            companies = self.connection.execute(
                "SELECT c.company_id, c.company_name, s.* FROM companies c JOIN job_sources s USING(company_id) "
                "WHERE c.status='active' AND s.is_current=1 ORDER BY c.company_id"
            ).fetchall()
            if company_ids:
                selected = set(company_ids)
                companies = [row for row in companies if row["company_id"] in selected]
                missing = selected - {row["company_id"] for row in companies}
                if missing:
                    raise ValueError("Company has no active local source: " + ", ".join(sorted(missing)))
            if not companies:
                raise ValueError("No eligible companies in the local catalog")
            cycle, stamp = new_id(), utc_now()
            sequence = self.connection.execute("SELECT coalesce(max(cycle_sequence), 0)+1 FROM scan_cycles").fetchone()[0]
            settings = dict(run_settings or {}, missing_threshold=missing_threshold)
            try:
                application_version = version("job-search-helper")
            except PackageNotFoundError:
                application_version = "source"
            self.connection.execute(
                "INSERT INTO scan_cycles(cycle_id, cycle_sequence, started_at, status, initiated_by, "
                "run_settings_json, application_version) VALUES (?, ?, ?, 'running', 'user', ?, ?)",
                (cycle, sequence, stamp, canonical_json(settings), application_version),
            )
            for company in companies:
                scope = SourceScope(company["source_id"], company["careers_url"], adapter_version)
                scope_id = self.catalog.add_scope(scope)
                self.connection.execute(
                    "INSERT INTO cycle_companies(cycle_id, company_id, source_id, scope_id, company_name_at_start, "
                    "careers_url_at_start, provider_at_start, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')",
                    (cycle, company["company_id"], company["source_id"], scope_id, company["company_name"],
                     company["careers_url"], company["provider"]),
                )
            return cycle

    def members(self, cycle: str) -> list[dict]:
        self._cycle(cycle)
        return [dict(row) for row in self.connection.execute(
            "SELECT * FROM cycle_companies WHERE cycle_id=? ORDER BY company_id", (cycle,))]

    def begin_attempt(self, cycle: str, company: str, *, retry=False) -> str:
        with self.database.transaction():
            member = self._member(cycle, company)
            if member["status"] != "queued" and not (
                retry and member["status"] in {"complete", "partial", "blocked", "failed", "unsupported"}
            ):
                raise ValueError("Apply saved work or explicitly retry a finished company")
            newer = self.connection.execute(
                "SELECT 1 FROM cycle_companies m JOIN scan_cycles c USING(cycle_id) "
                "WHERE m.company_id=? AND c.cycle_sequence > (SELECT cycle_sequence FROM scan_cycles WHERE cycle_id=?)",
                (company, cycle),
            ).fetchone()
            if newer:
                raise ValueError("A newer cycle already includes this company; old cycles cannot be refetched")
            number = self.connection.execute(
                "SELECT coalesce(max(attempt_number), 0)+1 FROM scan_attempts WHERE cycle_id=? AND company_id=?",
                (cycle, company),
            ).fetchone()[0]
            sequence = self.connection.execute(
                "SELECT coalesce(max(observation_sequence), 0)+1 FROM scan_attempts"
            ).fetchone()[0]
            attempt, stamp = new_id(), utc_now()
            self.connection.execute(
                "INSERT INTO scan_attempts(attempt_id, cycle_id, company_id, scope_id, source_id, attempt_number, "
                "observation_sequence, started_at, apply_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_fetch')",
                (attempt, cycle, company, member["scope_id"], member["source_id"], number, sequence, stamp),
            )
            self.connection.execute(
                "UPDATE cycle_companies SET status='fetching', selected_attempt_id=?, last_checkpoint_at=? "
                "WHERE cycle_id=? AND company_id=?", (attempt, stamp, cycle, company),
            )
            self.connection.execute("UPDATE scan_cycles SET status='running', completed_at=NULL WHERE cycle_id=?", (cycle,))
            return attempt

    def stage_inventory(self, attempt_id: str, inventory: Inventory) -> None:
        """Commit the full adapter result before normalizing or projecting it."""
        payload = {"inventory": asdict(inventory)}
        encoded, digest = canonical_json(payload), fingerprint(payload)
        with self.database.transaction():
            attempt = self._attempt(attempt_id)
            existing = self.connection.execute("SELECT payload_hash FROM inventory_batches WHERE attempt_id=?", (attempt_id,)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError("A fetched result is already saved for this attempt; it cannot be replaced")
                return
            if attempt["apply_status"] != "awaiting_fetch" or attempt["fetch_status"] is not None:
                raise ValueError("This fetch attempt is no longer active")
            stamp = utc_now()
            self.connection.execute(
                "INSERT INTO inventory_batches VALUES (?, ?, ?, ?, ?, 'pending')",
                (attempt_id, INVENTORY_PAYLOAD_VERSION, encoded, digest, stamp),
            )
            self.connection.execute(
                "UPDATE scan_attempts SET finished_at=?, fetch_status=?, apply_status='pending', error_message=? WHERE attempt_id=?",
                (stamp, inventory.status if inventory.status in FETCH_STATUSES else "failed", inventory.reason, attempt_id),
            )
            self.connection.execute(
                "UPDATE cycle_companies SET status='pending_apply', last_checkpoint_at=? WHERE cycle_id=? AND company_id=?",
                (stamp, attempt["cycle_id"], attempt["company_id"]),
            )

    def apply_inventory(self, attempt_id: str) -> bool:
        try:
            with self.database.transaction():
                attempt = self._attempt(attempt_id)
                batch = self.connection.execute("SELECT * FROM inventory_batches WHERE attempt_id=?", (attempt_id,)).fetchone()
                if batch is None:
                    raise ValueError("No saved inventory for this attempt")
                if batch["apply_state"] == "applied":
                    return True
                if batch["apply_state"] == "quarantined":
                    return False
                snapshot = self._decode(batch, attempt)
                member = self._member(attempt["cycle_id"], attempt["company_id"])
                self._validate_current_source(member, snapshot.scope)
                state = self.connection.execute("SELECT * FROM source_scan_state WHERE source_id=?", (attempt["source_id"],)).fetchone()
                historical = bool(state and state["latest_observation_sequence"] >= attempt["observation_sequence"])
                if not historical:
                    if state and state["scope_id"] != attempt["scope_id"]:
                        self.connection.execute("DELETE FROM job_scope_state WHERE source_id=?", (attempt["source_id"],))
                    self.connection.execute(
                        "INSERT INTO source_scan_state VALUES (?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
                        "scope_id=excluded.scope_id, latest_observation_sequence=excluded.latest_observation_sequence",
                        (attempt["source_id"], attempt["scope_id"], attempt["observation_sequence"]),
                    )
                seen, seen_evidence = {}, set()
                for posting in snapshot.jobs:
                    if posting.evidence_hash in seen_evidence:
                        continue
                    seen_evidence.add(posting.evidence_hash)
                    job_id, change, version_id = self._observe_posting(attempt, posting, historical)
                    if job_id in seen:
                        if seen[job_id] != posting.evidence_hash:
                            raise BatchValidationError("Conflicting duplicate posting evidence; inspect saved inventory")
                        continue
                    seen[job_id] = posting.evidence_hash
                    self._observation(attempt, job_id, version_id, "present", change)
                if snapshot.status == "complete" and not historical:
                    threshold = json.loads(self._cycle(attempt["cycle_id"])["run_settings_json"])["missing_threshold"]
                    self._reconcile_absences(attempt, set(seen), threshold)
                stamp = utc_now()
                self.connection.execute("UPDATE inventory_batches SET apply_state='applied' WHERE attempt_id=?", (attempt_id,))
                self.connection.execute("UPDATE scan_attempts SET apply_status='applied', applied_at=? WHERE attempt_id=?", (stamp, attempt_id))
                self._finish_member(attempt, snapshot.status, stamp)
                return True
        except BatchValidationError as exc:
            with self.database.transaction():
                attempt = self._attempt(attempt_id)
                self.connection.execute("UPDATE inventory_batches SET apply_state='quarantined' WHERE attempt_id=?", (attempt_id,))
                self.connection.execute(
                    "UPDATE scan_attempts SET apply_status='quarantined', error_message=? WHERE attempt_id=?", (str(exc), attempt_id))
                self._finish_member(attempt, "failed", utc_now())
            return False

    def recover(self, cycle: str) -> None:
        """Replay saved work first. Only an attempt with no saved result is refetchable."""
        self._cycle(cycle)
        with self.database.transaction():
            self.connection.execute(
                "UPDATE scan_attempts SET fetch_status='interrupted', finished_at=?, error_message='Interrupted before result was saved' "
                "WHERE cycle_id=? AND apply_status='awaiting_fetch' AND fetch_status IS NULL", (utc_now(), cycle),
            )
            self.connection.execute("UPDATE cycle_companies SET status='queued' WHERE cycle_id=? AND status='fetching'", (cycle,))
        pending = self.connection.execute(
            "SELECT a.attempt_id FROM scan_attempts a JOIN inventory_batches b USING(attempt_id) "
            "WHERE a.cycle_id=? AND b.apply_state='pending' ORDER BY a.observation_sequence", (cycle,),
        ).fetchall()
        for row in pending:
            self.apply_inventory(row[0])

    def interrupt(self, cycle: str) -> None:
        with self.database.transaction():
            self.connection.execute("UPDATE scan_cycles SET status='interrupted' WHERE cycle_id=? AND status='running'", (cycle,))

    def status(self, cycle: str | None = None) -> dict:
        if cycle is None:
            row = self.connection.execute("SELECT cycle_id FROM scan_cycles ORDER BY cycle_sequence DESC LIMIT 1").fetchone()
            if row is None:
                return {"ok": True, "cycle": None, "companies": []}
            cycle = row[0]
        result = dict(self._cycle(cycle))
        members = self.members(cycle)
        result["companies_total"] = len(members)
        result["companies_remaining"] = sum(row["status"] in {"queued", "fetching", "pending_apply"} for row in members)
        for member in members:
            if member["selected_attempt_id"]:
                attempt = self._attempt(member["selected_attempt_id"])
                member.update(fetch_status=attempt["fetch_status"], apply_status=attempt["apply_status"], reason=attempt["error_message"])
        return {"ok": True, "cycle": result, "companies": members}

    def _decode(self, batch, attempt) -> InventorySnapshot:
        try:
            if batch["payload_schema_version"] != INVENTORY_PAYLOAD_VERSION:
                raise ValueError("Unsupported saved inventory version")
            payload = json.loads(batch["payload_json"])
            if fingerprint(payload) != batch["payload_hash"]:
                raise ValueError("Saved inventory checksum mismatch")
            snapshot = InventorySnapshot.from_adapter(Inventory(**payload["inventory"]), self._scope(attempt["scope_id"]))
            provider = self._member(attempt["cycle_id"], attempt["company_id"])["provider_at_start"]
            if snapshot.provider and snapshot.provider.lower() != provider.lower():
                raise ValueError("Fetched provider differs from the selected source")
            return snapshot
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise BatchValidationError(f"Invalid saved inventory: {exc}") from exc

    def _validate_current_source(self, member, scope):
        current = self.connection.execute("SELECT * FROM job_sources WHERE source_id=?", (member["source_id"],)).fetchone()
        if (not current["is_current"] or canonicalize_url(current["careers_url"]) != scope.canonical_inventory_url
                or current["provider"] != member["provider_at_start"]):
            raise BatchValidationError("Source changed since this cycle started; saved evidence retained for inspection")

    def validate_source(self, cycle: str, company: str) -> None:
        member = self._member(cycle, company)
        self._validate_current_source(member, self._scope(member["scope_id"]))

    def _observe_posting(self, attempt, posting, historical):
        source, scope, sequence = attempt["source_id"], attempt["scope_id"], attempt["observation_sequence"]
        public_id = posting.posting_id.strip()
        row = self.connection.execute("SELECT job_id FROM jobs WHERE source_id=? AND source_job_id=?", (source, public_id)).fetchone() if public_id else None
        # Public provider IDs take precedence. A shared URL must never merge
        # two different provider IDs (including a reused job-page URL).
        if row is None and posting.url:
            candidates = self.connection.execute(
                "SELECT DISTINCT j.job_id, j.source_job_id FROM job_identity_aliases a JOIN jobs j USING(job_id) "
                "WHERE a.source_id=? AND a.kind='canonical_url' AND a.value=?",
                (source, canonicalize_url(posting.url)),
            ).fetchall()
            candidates = [item for item in candidates if not public_id or item["source_job_id"] in (None, public_id)]
            if len(candidates) > 1:
                raise BatchValidationError("Ambiguous posting URL; identity needs review")
            row = candidates[0] if candidates else None
        stamp = attempt["finished_at"]
        if row is None:
            job_id = self.catalog.create_job(attempt["company_id"], posting, source_id=source, observed_at=stamp)
            previous = None
        else:
            job_id = row["job_id"]
            previous = self.catalog.get_job(job_id)
        version_id = self.catalog.store_version(job_id, posting, observed_at=stamp)
        historical = historical or bool(previous and previous["latest_observation_sequence"] > sequence)
        if historical:
            if previous is None:
                self.connection.execute("UPDATE jobs SET lifecycle_status='unknown' WHERE job_id=?", (job_id,))
            return job_id, "historical", version_id
        changed = previous is None or previous["material_hash"] != posting.material_hash
        change = ("new" if previous is None else "reopened" if previous["lifecycle_status"] in {"missing", "closed"}
                  else "changed" if changed else "unchanged")
        self.connection.execute(
            "UPDATE jobs SET current_version_id=?, source_job_id=coalesce(source_job_id, ?), requisition_id=?, "
            "last_seen_at=?, last_material_change_at=CASE WHEN ? THEN ? ELSE last_material_change_at END, "
            "lifecycle_status='active', closure_basis=NULL, closed_at=NULL, latest_observation_sequence=?, "
            "updated_at=?, row_version=row_version+1 WHERE job_id=?",
            (version_id, public_id or None, posting.requisition_id, stamp, changed, stamp, sequence, stamp, job_id),
        )
        if posting.url:
            url = canonicalize_url(posting.url)
            alias = self.connection.execute(
                "SELECT alias_id FROM job_identity_aliases WHERE job_id=? AND kind='canonical_url' AND value=?", (job_id, url),
            ).fetchone()
            if alias is None:
                self.catalog.add_alias(job_id, source, "canonical_url", url, "adapter")
        self.connection.execute(
            "INSERT INTO job_scope_state(job_id, scope_id, source_id, last_seen_cycle_id, consecutive_missing, last_reconciled_sequence) "
            "VALUES (?, ?, ?, ?, 0, ?) ON CONFLICT(job_id, scope_id) DO UPDATE SET "
            "last_seen_cycle_id=excluded.last_seen_cycle_id, consecutive_missing=0, last_reconciled_sequence=excluded.last_reconciled_sequence",
            (job_id, scope, source, attempt["cycle_id"], sequence),
        )
        return job_id, change, version_id

    def _reconcile_absences(self, attempt, seen, threshold):
        states = self.connection.execute("SELECT * FROM job_scope_state WHERE scope_id=?", (attempt["scope_id"],)).fetchall()
        for state in states:
            if state["job_id"] in seen or state["last_reconciled_sequence"] >= attempt["observation_sequence"]:
                continue
            if attempt["cycle_id"] in (state["last_seen_cycle_id"], state["last_missing_cycle_id"]):
                self._observation(attempt, state["job_id"], None, "absent", "unchanged")
                continue
            missing = state["consecutive_missing"] + 1
            job = self.catalog.get_job(state["job_id"])
            status = "closed" if missing >= threshold else "missing"
            change = status if job["lifecycle_status"] != status else "unchanged"
            self.connection.execute(
                "UPDATE job_scope_state SET consecutive_missing=?, last_missing_cycle_id=?, last_reconciled_sequence=? "
                "WHERE job_id=? AND scope_id=?",
                (missing, attempt["cycle_id"], attempt["observation_sequence"], state["job_id"], attempt["scope_id"]),
            )
            self.connection.execute(
                "UPDATE jobs SET lifecycle_status=?, closure_basis=?, closed_at=CASE WHEN ?='closed' "
                "THEN coalesce(closed_at, ?) ELSE NULL END, latest_observation_sequence=?, updated_at=?, "
                "row_version=row_version+1 WHERE job_id=?",
                (status, "comparable_complete_absence" if status == "closed" else None, status,
                 attempt["finished_at"], attempt["observation_sequence"], attempt["finished_at"], state["job_id"]),
            )
            self._observation(attempt, state["job_id"], None, "absent", change)

    def _observation(self, attempt, job_id, version_id, presence, change):
        self.connection.execute(
            "INSERT INTO job_observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (attempt["attempt_id"], job_id, attempt["scope_id"], attempt["source_id"], version_id,
             presence, attempt["finished_at"], change, attempt["observation_sequence"]),
        )

    def _finish_member(self, attempt, status, stamp):
        self.connection.execute(
            "UPDATE cycle_companies SET status=?, last_checkpoint_at=? WHERE cycle_id=? AND company_id=? AND selected_attempt_id=?",
            (status, stamp, attempt["cycle_id"], attempt["company_id"], attempt["attempt_id"]),
        )
        members = self.members(attempt["cycle_id"])
        remaining = any(row["status"] in {"queued", "fetching", "pending_apply"} for row in members)
        status = "running" if remaining else "completed" if all(row["status"] == "complete" for row in members) else "completed_with_exceptions"
        self.connection.execute(
            "UPDATE scan_cycles SET status=?, completed_at=?, last_checkpoint_at=? WHERE cycle_id=?",
            (status, None if remaining else stamp, stamp, attempt["cycle_id"]),
        )

    def _scope(self, scope_id):
        row = self.connection.execute("SELECT * FROM source_scopes WHERE scope_id=?", (scope_id,)).fetchone()
        return SourceScope(row["source_id"], row["canonical_inventory_url"], row["adapter_version"], row["scope_parameters_json"])

    def _cycle(self, cycle):
        return self._one("SELECT * FROM scan_cycles WHERE cycle_id=?", (cycle,), "Local cycle not found")

    def _member(self, cycle, company):
        return self._one("SELECT * FROM cycle_companies WHERE cycle_id=? AND company_id=?", (cycle, company), "Company is outside this cycle")

    def _attempt(self, attempt):
        return self._one("SELECT * FROM scan_attempts WHERE attempt_id=?", (attempt,), "Scan attempt not found")

    def _one(self, sql, values, message):
        row = self.connection.execute(sql, values).fetchone()
        if row is None:
            raise ValueError(message)
        return row
