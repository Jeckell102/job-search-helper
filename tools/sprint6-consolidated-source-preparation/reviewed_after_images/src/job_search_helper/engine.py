"""Single-writer pipeline with atomic batches and local lookup caching.

SQLite is a local work cache. Durable evidence and cycle IDs are also stored in
the workbook; a known cycle can be reconstructed without repeating decisions.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import copy
import hashlib
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Lock, get_ident
from urllib.parse import urlencode, urlsplit

from .ats import (Inventory, fetch_inventory, resolve_board, lever_location_scope,
                  validate_outcome_failure)
from .batching import PlanningRepository, PendingState
from .cooperative_fetch import CooperativeFetchWork
from .core import (FIT_LABELS, POLICY_VERSION, canonicalize_url, changed_fields,
                   job_key, material_hash, pack_snapshot,
                   plain_text, reconsiderations, unpack_snapshot, validate_decision)
from .dashboard import TerminalDashboard
from .efficiency import classify_title, strip_job_boilerplate
from .screening import Screening, screen_posting


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _manual_opportunity_status(row):
    """Never replace a user's final Yes/No when deferring an older review."""
    added = str(row.get("Added to Opportunities?", "")).strip().casefold()
    return {"Added to Opportunities?": "Manual Review"} if added in {"", "pending", "manual review"} else {}

def _review_guards(row):
    return {field: row.get(field, "") for field in
            ("Added to Opportunities?", "Review Status", "Review Started At", "Source Hash")}


def _inventory_source(url):
    try:
        name, board, root = resolve_board("", url)
        location = lever_location_scope(url) if name == "Lever" else ""
        return root + board + ("?" + urlencode({"location": location.casefold()}) if location else "")
    except (ValueError, TypeError):
        return canonicalize_url(url)


def _safe_canonical_url(url):
    try:
        return canonicalize_url(url)
    except ValueError:
        return ""


def _cycle_inventory_source(cycle, company):
    item = cycle.get("companies", {}).get(company["Company ID"], {})
    return _inventory_source(item.get("source_url") or company["Official Careers URL"])


def _compact_evaluation_history(snapshot: dict) -> None:
    """Drop repeated full posting copies from historical evaluation entries."""
    compact = []
    for item in snapshot.get("evaluations", []):
        if not isinstance(item, dict):
            continue
        compact.append({
            "decision": item.get("decision", ""),
            "fit_level": item.get("fit_level"),
            "narrative": item.get("narrative", ""),
            "evaluated_at": item.get("evaluated_at", ""),
            "description_hash": item.get("description_hash", ""),
            "changed_fields": item.get("changed_fields", []),
        })
    snapshot["evaluations"] = compact[-3:]


def inventory_payload(inventory, company):
    # This payload is part of the F6 durable inbox/receipt contract.  M3
    # provenance belongs in the saved cycle item, never in these bytes.
    return {"jobs": inventory.jobs, "inventory_status": inventory.status,
            "reason": inventory.reason, "source_url": inventory.source_url, "ats": inventory.ats,
            "browser_pending_urls": inventory.browser_pending_urls,
            "browser_discovery_incomplete": inventory.browser_discovery_incomplete,
            "fetched_at": now(), "requested_url": company.get("Official Careers URL", company.get("requested_url", ""))}


class State:
    def __init__(self, db_path=":memory:", readonly=False, *, immutable=False):
        self.readonly = readonly
        self.path = str(db_path)
        self.checkpoint_seconds = 0.0
        self.checkpoint_bytes = 0
        if immutable and not readonly:
            raise ValueError('An immutable State database must be opened read-only.')
        if readonly:
            uri = Path(db_path).resolve().as_uri() + "?mode=ro"
            if immutable:
                uri += '&immutable=1'
            self.connection = sqlite3.connect(uri, uri=True, timeout=5)
            self.connection.execute("PRAGMA busy_timeout=5000")
        else:
            if self.path != ":memory:":
                Path(db_path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.connection = sqlite3.connect(self.path, timeout=5)
            self.connection.execute("PRAGMA busy_timeout=5000")
            if self.path != ":memory:":
                self.connection.execute("PRAGMA journal_mode=WAL")
            with self.connection:
                self.connection.execute("CREATE TABLE IF NOT EXISTS cycles (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
                self.connection.execute("CREATE TABLE IF NOT EXISTS reviews (cycle TEXT, key TEXT, data TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(cycle,key))")
            if self.path != ":memory:":
                Path(db_path).chmod(0o600)

    def close(self):
        self.connection.close()

    def clone(self):
        result = State()
        self.connection.backup(result.connection)
        return result

    def cycle(self, cycle_id):
        row = self.connection.execute("SELECT data FROM cycles WHERE id=?", (cycle_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def cycles(self):
        return [json.loads(row[0]) for row in self.connection.execute("SELECT data FROM cycles ORDER BY rowid")]

    def save_cycle(self, cycle):
        # Large inventories live in the durable inbox, separately from compact
        # control checkpoints so saving progress does not rewrite descriptions.
        started = time.monotonic()
        stored = copy.deepcopy(cycle)
        for item in stored.get("companies", {}).values():
            item.pop("jobs", None)
        encoded = json.dumps(stored, ensure_ascii=False)
        with self.connection:
            self.connection.execute("INSERT INTO cycles VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                                    (stored["id"], encoded))
        self.checkpoint_seconds += time.monotonic() - started
        self.checkpoint_bytes += len(encoded.encode("utf-8"))

    def source_configuration_evidence(self, cycle_id, company_id):
        """Bound read-only descriptor used only by a repository at construction."""
        cycle = self.cycle(cycle_id)
        item = cycle.get('companies', {}).get(company_id) if isinstance(cycle, dict) else None
        if not isinstance(cycle, dict) or not isinstance(item, dict):
            return None
        return copy.deepcopy(cycle), copy.deepcopy(item)

    def purge_reviews(self):
        if self.readonly:
            return
        with self.connection:
            self.connection.execute("DELETE FROM reviews")

    def put_review(self, cycle_id, key, data, status="pending"):
        with self.connection:
            self.connection.execute("INSERT INTO reviews VALUES (?,?,?,?) ON CONFLICT(cycle,key) DO UPDATE SET data=excluded.data,status=excluded.status",
                                    (cycle_id, key, json.dumps(data, ensure_ascii=False), status))

    def reviews(self, cycle_id, status=None):
        query, args = "SELECT data,status FROM reviews WHERE cycle=?", [cycle_id]
        if status:
            query += " AND status=?"
            args.append(status)
        return [dict(json.loads(row[0]), queue_status=row[1]) for row in self.connection.execute(query, args)]

    def apply_buffer(self, updates, cycles):
        """One local transaction AFTER an acknowledged spreadsheet batch."""
        started = time.monotonic()
        with self.connection:
            for (cycle_id, key), (data, status) in updates.items():
                self.connection.execute("INSERT INTO reviews VALUES (?,?,?,?) ON CONFLICT(cycle,key) DO UPDATE SET data=excluded.data,status=excluded.status",
                                        (cycle_id, key, json.dumps(data, ensure_ascii=False), status))
            for cycle_id, cycle in cycles.items():
                stored = copy.deepcopy(cycle)
                for item in stored.get("companies", {}).values():
                    item.pop("jobs", None)
                self.connection.execute("INSERT INTO cycles VALUES (?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                                        (cycle_id, json.dumps(stored, ensure_ascii=False)))
                self.checkpoint_bytes += len(json.dumps(stored, ensure_ascii=False).encode("utf-8"))
        self.checkpoint_seconds += time.monotonic() - started


DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 200
MAX_FETCH_WORKERS = 50
DEFAULT_ERROR_LOG = Path(".state/scraper-errors.jsonl")


@contextmanager
def _fetch_pool(workers):
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        yield executor
    finally:
        # Ctrl+C cancels assignments that have not started; only running HTTP
        # requests need to finish before the single-writer lock is released.
        executor.shutdown(wait=True, cancel_futures=True)


class Engine:
    def __init__(self, repo, state, dry_run=False, fetcher=fetch_inventory, batch_size=DEFAULT_BATCH_SIZE,
                 checkpoint_hook=None, error_log_path=DEFAULT_ERROR_LOG, inbox=None,
                 runtime_binding=None):
        self.repo, self.state, self.dry_run, self.fetcher = repo, state, dry_run, fetcher
        self.inbox = inbox
        self.runtime_binding = copy.deepcopy(runtime_binding)
        self.performance = {"staging_seconds": 0.0, "checkpoint_seconds": 0.0}
        self.checkpoint_hook = checkpoint_hook
        self.error_log_path = Path(error_log_path) if error_log_path else None
        if not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError(f"Batch size must be between 1 and {MAX_BATCH_SIZE}")
        self.batch_size = batch_size
        self._notices = None
        self._dashboard = None
        if dry_run and repo.__class__.__name__ != "MemoryRepository":
            raise ValueError("Dry runs require an isolated MemoryRepository")

    def _commit(self, *operations):
        result = self.repo.commit(list(operations))
        self._report_new_jobs(result)
        return result

    def _report_new_jobs(self, result):
        if not self.dry_run:
            for title, company in result.get("new_jobs", []):
                if self._dashboard is not None:
                    self._dashboard.job_written(title, company)
                else:
                    print(f"New job found - {title} at {company}", flush=True)

    def _notice(self, message):
        if self._notices is None:
            print(message, flush=True)
        else:
            self._notices.append(message)

    def _checkpoint(self):
        if self.checkpoint_hook is not None:
            self.checkpoint_hook()

    def _log_company_error(self, cycle, company, item, exc, context):
        message = str(exc)
        item.update(stage="failed", reason=message[:900])
        item.pop("jobs", None)
        self.state.save_cycle(cycle)
        entry = {
            "at": now(),
            "cycle_id": cycle.get("id", ""),
            "company_id": company.get("Company ID", ""),
            "company": company.get("Company", ""),
            "context": context,
            "error_type": type(exc).__name__,
            "error": message,
        }
        if self.error_log_path is not None and not self.dry_run:
            self.error_log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self.error_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self.error_log_path.chmod(0o600)
        print(f"ERROR: {company.get('Company', 'Company')}: {message}", flush=True)

    @staticmethod
    def _format_batch_timings(timings):
        if not timings:
            return ""
        labels = (
            ("refresh_company_seconds", "refresh"),
            ("plan_seconds", "plan"),
            ("commit_total_seconds", "commit"),
            ("sheets_load_seconds", "sheets_load"),
            ("prepare_seconds", "prepare"),
            ("build_requests_seconds", "build_requests"),
            ("payload_seconds", "payload"),
            ("sheets_write_seconds", "sheets_write"),
            ("committed_rows_seconds", "cache_rows"),
            ("local_state_seconds", "local_state"),
            ("read_seconds", "read_api"),
            ("write_seconds", "write_api"),
            ("throttle_seconds", "throttle"),
        )
        parts = []
        for key, label in labels:
            value = timings.get(key)
            if isinstance(value, (int, float)):
                parts.append(f"{label}={value:.1f}s")
        payload = timings.get("payload_bytes")
        if isinstance(payload, int):
            parts.append(f"payload={payload / 1_000_000:.2f}MB")
        requests = timings.get("requests")
        if isinstance(requests, int):
            parts.append(f"requests={requests}")
        for key in ("read_requests", "write_requests", "read_response_bytes", "write_payload_bytes"):
            if key in timings:
                parts.append(f"{key}={timings[key]}")
        return ", ".join(parts)

    def _planned_batch(self, planner, action):
        timings = {}
        base_repo, base_state = self.repo, self.state
        pending = PendingState(base_state)
        planner.begin()
        notices = []
        self.repo, self.state, self._notices = planner, pending, notices
        plan_started = time.monotonic()
        try:
            result = action()
        finally:
            self.repo, self.state, self._notices = base_repo, base_state, None
            timings["plan_seconds"] = time.monotonic() - plan_started
            self.performance["staging_seconds"] += timings["plan_seconds"]
        # Fresh row identities, formulas and user fields are revalidated here.
        # A failure or Ctrl+C before acknowledgement leaves the local checkpoint
        # at the preceding batch. Replaying that batch is idempotent.
        result = base_repo.commit(planner.operations)
        timings.update(result.get("timings", {}))
        self._report_new_jobs(result)
        flush_started = time.monotonic()
        pending.flush()
        timings["local_state_seconds"] = time.monotonic() - flush_started
        self.performance["checkpoint_seconds"] += timings["local_state_seconds"]
        planner.accept_commit()
        for message in notices:
            print(message, flush=True)
        result["timings"] = timings
        return result

    @staticmethod
    def _verify_same_board(before, after):
        if canonicalize_url(before.get("Official Careers URL", "")) != canonicalize_url(after.get("Official Careers URL", "")):
            raise ValueError("Company careers board changed during the run; saved inventory needs explicit reconciliation")

    @staticmethod
    def _source_guard(company, frozen_revision):
        """Return an ephemeral commit guard for source-derived work.

        The guard deliberately never enters an inbox plan or publication
        receipt: it is reconstructed from a fresh Company row for this one
        commit attempt and makes a changed source fail preflight.
        """
        from .company_events import canonical_company_fact, source_revision
        if not isinstance(frozen_revision, str) or not frozen_revision:
            raise ValueError("Missing frozen Company source revision; saved work is held for reconciliation")
        fact = canonical_company_fact(company)
        if not fact["eligible"]:
            raise ValueError("Company source is no longer eligible; saved work is held for reconciliation")
        if company.get("Claimed By") or company.get("Claim Token"):
            raise ValueError("Company has an external claim; saved work is held for reconciliation")
        if source_revision(company) != frozen_revision:
            raise ValueError("Company source revision changed; saved work is held for reconciliation")
        return {"tab": "Companies", "identity": {"Company ID": fact["company_id"]},
                "values": {}, "expected": {
                    "Company Status": company.get("Company Status", ""),
                    "Official Careers URL": company.get("Official Careers URL", ""),
                    "ATS / Source": company.get("ATS / Source", ""),
                }}

    def _admit_source_fact(self, item, company):
        """Durably bind the whole canonical Company source at admission.

        ``outcome_source_revision`` fences normal commits.  The fact is kept
        alongside it (never in the F6 payload or frozen plan) so a lost
        response may prove that only the scanner's own planned source update
        occurred before its receipt is reconciled.
        """
        from .company_events import canonical_company_fact, source_revision
        fact = canonical_company_fact(company)
        if not fact['eligible']:
            raise ValueError('Company source is not eligible for automatic scanning')
        if company.get('Claimed By') or company.get('Claim Token'):
            raise ValueError('Company has an external claim')
        revision = source_revision(company)
        # Admission is freeze-once.  A checkpoint that already records the
        # source fact never re-resolves a missing configuration snapshot.
        if 'outcome_source_revision' in item or 'outcome_source_fact' in item:
            if 'installed_source_configuration' in item:
                from .source_configuration_snapshot import validate_installed_source_configuration
                if (item.get('outcome_source_revision') != revision
                        or item.get('outcome_source_fact') != fact):
                    raise ValueError('Company source revision changed; saved work is held for reconciliation')
                if validate_installed_source_configuration(item['installed_source_configuration']) is None:
                    raise ValueError('Frozen installed source configuration is malformed')
            else:
                # Preserve the established retry behavior for cycles without
                # installed-capability evidence.  The scanner may have filled
                # ATS / Source from its own confirmed inventory.  Refresh the
                # ordinary source fence, but never reconstruct the missing
                # configuration snapshot after a crash or legacy admission.
                item['outcome_source_revision'] = revision
                item['outcome_source_fact'] = fact
            return
        item['outcome_source_revision'] = revision
        item['outcome_source_fact'] = fact
        # This is cycle-only admission evidence.  It is never carried through
        # Inventory/F6 worker or publication payloads, and a lost checkpoint
        # deliberately degrades to no installed-capability evidence.
        item.pop('installed_source_configuration', None)
        from .source_configuration_snapshot import (resolve_installed_source_configuration,
                                                    _resolve_authoritative_installed_source_configuration,
                                                    validate_installed_source_configuration)
        try:
            candidate = validate_installed_source_configuration(
                resolve_installed_source_configuration(self.repo, fact['company_id']))
            authoritative = validate_installed_source_configuration(
                _resolve_authoritative_installed_source_configuration(self.repo, fact['company_id']))
        except (AttributeError, OSError, TypeError, ValueError):
            candidate = authoritative = None
        snapshot = authoritative if candidate is not None and candidate == authoritative else None
        if (snapshot is not None
                and snapshot['schema'] == 'installed-source-configuration-v1'
                and snapshot['company_id'] == fact['company_id']
                and snapshot['source_revision'] == revision
                and snapshot['company'] == str(company.get('Company', '')).strip()
                and snapshot['official_careers_url'] == fact['official_careers_url']
                and snapshot['ats_source'] == fact['ats_source']):
                item['installed_source_configuration'] = copy.deepcopy(snapshot)

    def _accept_source_configuration_defect_evidence(self, cycle_id, company_id, fact_id):
        """Atomically checkpoint one already-produced, closed F5 evidence group.

        There intentionally is no production caller in Slice B.  This narrow
        seam is for the later authorized immutable F5 verifier; it never
        fetches, parses a reason, or accepts a worker/coordinator sidecar.
        """
        if (not isinstance(cycle_id, str) or not cycle_id
                or not isinstance(company_id, str) or not company_id
                or not isinstance(fact_id, str) or not fact_id):
            raise ValueError('Source-configuration evidence identifiers are required')
        cycle = self.state.cycle(cycle_id)
        if not isinstance(cycle, dict) or not isinstance(cycle.get('companies'), dict):
            raise ValueError('Source-configuration evidence cycle is unavailable')
        item = cycle['companies'].get(company_id)
        from .source_configuration_snapshot import mapping_fact_by_id
        machine_fact = mapping_fact_by_id(cycle_id, company_id, fact_id)
        if not isinstance(item, dict) or machine_fact is None:
            raise ValueError('Source-configuration evidence is not durably owned')
        return self._accept_source_configuration_defect_evidence_loaded(cycle, item, machine_fact)

    def _accept_source_configuration_defect_evidence_loaded(self, cycle, item, machine_fact):
        """Internal implementation over a cycle/fact loaded by the stable-ID seam."""
        from .company_events import canonical_company_fact
        from .source_configuration_snapshot import (
            _resolve_authoritative_installed_source_configuration,
            qualification_for_snapshot, validate_installed_source_configuration,
            validate_mapping_divergence_fact, validate_source_configuration_defect,
            validate_source_configuration_qualification_evidence)
        if (not isinstance(cycle, dict) or not isinstance(item, dict)
                or not isinstance(cycle.get('id'), str) or not cycle['id']
                or cycle.get('company_event') is not None
                or not isinstance(cycle.get('companies'), dict)):
            raise ValueError('Source-configuration evidence requires an ordinary saved cycle')
        company_id = item.get('outcome_source_fact', {}).get('company_id') if isinstance(item.get('outcome_source_fact'), dict) else None
        if not isinstance(company_id, str) or cycle['companies'].get(company_id) is not item:
            raise ValueError('Source-configuration evidence owner is not exact')
        frozen_fact = item.get('outcome_source_fact')
        frozen_revision = item.get('outcome_source_revision')
        frozen_snapshot = validate_installed_source_configuration(item.get('installed_source_configuration'))
        if (not isinstance(frozen_fact, dict) or frozen_fact.get('company_id') != company_id
                or not isinstance(frozen_revision, str) or not frozen_revision
                or frozen_snapshot is None or frozen_snapshot.get('company_id') != company_id
                or frozen_snapshot.get('source_revision') != frozen_revision):
            raise ValueError('Source-configuration evidence has no frozen admission')
        rows = [row for row in self._company_rows()
                if isinstance(row, dict) and str(row.get('Company ID', '')).strip() == company_id]
        if len(rows) != 1 or canonical_company_fact(rows[0]) != frozen_fact:
            raise ValueError('Company source changed before configuration qualification')
        current = validate_installed_source_configuration(
            _resolve_authoritative_installed_source_configuration(self.repo, company_id))
        if current != frozen_snapshot:
            raise ValueError('Installed source configuration changed before qualification')
        fact = validate_mapping_divergence_fact(machine_fact, cycle_id=cycle['id'], snapshot=frozen_snapshot)
        qualified = qualification_for_snapshot(frozen_snapshot)
        if fact is None or qualified is None:
            raise ValueError('No exact held source-configuration qualification exists')
        sidecar = validate_source_configuration_defect({
            'schema': 'source-configuration-defect-v1',
            'capability_id': frozen_snapshot['capability_id'],
            'capability_digest': frozen_snapshot['capability_digest'],
            'mapping_digest': frozen_snapshot['mapping_digest'],
            'configuration_digest': frozen_snapshot['configuration_digest'],
            'category': 'same_provider_source_mapping',
            'evidence_code': 'rippling_verified_mapping_divergence',
        }, snapshot=frozen_snapshot)
        evidence = validate_source_configuration_qualification_evidence({
            'schema': 'source-configuration-qualification-evidence-v1',
            'matrix_digest': qualified['matrix_digest'],
            'qualification': qualified['qualification'],
        }, snapshot=frozen_snapshot)
        if sidecar is None or evidence is None:
            raise ValueError('Source-configuration evidence failed sealed validation')
        # Build on a detached checkpoint.  A save failure must not leave a
        # partial group in the caller's in-memory cycle to leak through a
        # later unrelated checkpoint.
        checkpoint = copy.deepcopy(cycle)
        saved_item = checkpoint['companies'][company_id]
        saved_item['source_configuration_mapping_fact'] = fact
        saved_item['source_configuration_defect'] = sidecar
        saved_item['source_configuration_qualification_evidence'] = evidence
        self.state.save_cycle(checkpoint)
        item['source_configuration_mapping_fact'] = fact
        item['source_configuration_defect'] = sidecar
        item['source_configuration_qualification_evidence'] = evidence

    def _fresh_source_guard(self, company_id, frozen_revision):
        matches = [row for row in self._company_rows() if row.get("Company ID") == company_id]
        if len(matches) != 1:
            raise ValueError("Company was removed or its identity is ambiguous; saved work is held for reconciliation")
        return self._source_guard(matches[0], frozen_revision), matches[0]

    @staticmethod
    def _validate_company_event_start_admission(request, company_ids, rows):
        """Fail closed before an event-bound request can create a cycle.

        This is deliberately a direct-call boundary as well as a companion to
        scan_request._read_request: no caller may turn an event into scope
        membership without proving its immutable request/event/current-Company
        binding first.
        """
        if not isinstance(request, dict):
            return
        if request.get('company_event') is None:
            if isinstance(request.get('request_id'), str) and request['request_id'].startswith('company-event:'):
                raise ValueError('Company-event request admission is invalid; request is held unchanged.')
            return
        event = request.get('company_event')
        if (request.get('mode') != 'company-only'
                or not isinstance(company_ids, (list, tuple)) or len(company_ids) != 1
                or not isinstance(company_ids[0], str) or not company_ids[0].strip()
                or request.get('company_ids') != [company_ids[0]]
                or request.get('repair_retry') is not None
                or request.get('operator_request') is not None
                or not isinstance(event, dict)
                or set(event) != {'schema', 'event_id', 'company_id', 'revision', 'source_revision'}
                or event.get('schema') != 'company-event-scan-request-v1'
                or not isinstance(event.get('event_id'), str) or not event['event_id'].strip()
                or not isinstance(event.get('company_id'), str) or not event['company_id'].strip()
                or type(event.get('revision')) is not int or event['revision'] < 1
                or not isinstance(event.get('source_revision'), str) or not event['source_revision'].strip()
                or request.get('request_id') != 'company-event:' + event['event_id']
                or request.get('source_revision') != event['source_revision']
                or company_ids[0] != event['company_id']):
            raise ValueError('Company-event request admission is invalid; request is held unchanged.')
        matches = [row for row in rows if row.get('Company ID') == event['company_id']]
        if len(matches) != 1:
            raise ValueError('Company-event request admission is held: current Company identity is missing or ambiguous.')
        from .company_events import canonical_company_fact, source_revision
        company = matches[0]
        try:
            fact = canonical_company_fact(company)
        except (TypeError, ValueError) as exc:
            raise ValueError('Company-event request admission is held: current Company is invalid.') from exc
        if not fact['eligible'] or company.get('Claimed By') or company.get('Claim Token'):
            raise ValueError('Company-event request admission is held: current Company is ineligible or claimed.')
        if source_revision(company) != event['source_revision']:
            raise ValueError('Company-event request admission is held: current Company source revision changed.')

    def _stage_inventory(self, cycle, company, item, planner, progress_hook=None, status_hook=None):
        jobs = item.get("jobs", [])
        start = item.get("next_job_index", 0)
        started = time.monotonic()
        print(f"{company['Company']}: {len(jobs)} inventory items; resuming at {start}. Saving up to {self.batch_size} at a time.", flush=True)
        if status_hook is not None:
            status_hook(company["Company"], start, len(jobs), 0, 0)
        while start < len(jobs):
            stop = min(start + self.batch_size, len(jobs))
            refresh_started = time.monotonic()
            current = planner.refresh_company(company["Company ID"])
            refresh_seconds = time.monotonic() - refresh_started
            self._verify_same_board(company, current)
            def stage():
                for posting in jobs[start:stop]:
                    self._stage_posting(cycle, current, posting)
                item["next_job_index"] = stop
                self.state.save_cycle(cycle)
            result = self._planned_batch(planner, stage)
            timings = result.get("timings", {})
            timings["refresh_company_seconds"] = refresh_seconds
            timings["requests"] = result.get("requests", 0)
            self._checkpoint()
            print(f"{company['Company']}: {'simulated' if self.dry_run else 'saved'} {stop}/{len(jobs)} inventory items processed; {time.monotonic()-started:.0f}s elapsed.", flush=True)
            if status_hook is not None:
                status_hook(company["Company"], stop, len(jobs), time.monotonic() - started, stop - start)
            detail = self._format_batch_timings(timings)
            if detail:
                print(f"{company['Company']}: batch timing: {detail}.", flush=True)
            start = stop
            if progress_hook is not None:
                progress_hook()

    def _company_op(self, company, values):
        return {"tab": "Companies", "identity": {"Company ID": company["Company ID"]}, "values": values}

    @staticmethod
    def _ats_update(company, ats):
        # Keep source annotations such as parent-board scope when they already
        # name the adapter used. Unknown discovery must never erase a source.
        if not ats or ats.casefold() in str(company.get("ATS / Source", "")).casefold():
            return {}
        return {"ATS / Source": ats}

    def _history_op(self, key, values, insert=False, append_notes=None, identity=None):
        return {"tab": "Job History", "identity": identity or {"Job Key": key}, "values": values,
                "append_if_missing": insert, "append_notes": {"Review Notes": append_notes} if append_notes else {}}

    def _evidence_op(self, key, source_hash, company, posting, description, stamp):
        return {
            "tab": "Job Evidence",
            "identity": {"Job Key": key, "Source Hash": source_hash},
            "values": {
                "Company": company["Company"],
                "Job Title": posting["title"],
                "Official Job URL": posting["url"],
                "Captured At": stamp,
                "Job Description": description,
            },
            "append_if_missing": True,
        }

    def _company_rows(self):
        rows = self.repo.read("Companies")
        names, ids = set(), set()
        for row in rows:
            name = str(row.get("Company", "")).strip()
            if not name:
                continue
            if name.casefold() in names:
                raise ValueError("Duplicate company name requires manual disambiguation: " + name)
            names.add(name.casefold())
            cid = str(row.get("Company ID", "")).strip()
            if cid and cid.casefold() in ids:
                raise ValueError("Duplicate Company ID: " + cid)
            ids.add(cid.casefold())
        return [row for row in rows if str(row.get("Company", "")).strip()]

    def _assign_company_id(self, company):
        if company.get("Company ID"):
            return
        values = {"Company ID": "COMP-" + uuid.uuid4().hex[:12].upper(), "Record Updated": now()}
        if not company.get("Date Added"):
            values["Date Added"] = now()[:10]
        self._commit({"tab": "Companies", "identity": {"Company": company["Company"]}, "values": values,
                      "append_notes": {"Notes": "Date Added populated on first helper detection; original entry date was not recorded."} if not company.get("Date Added") else {}})
        company.update(values)

    def start_cycle(self, company_ids=None, *, new_scan_request=None, selected_retry_reservation=None):
        from .scan_request import superseded_cycle_ids
        self.repo.validate_schema()
        local_cycles = self.state.cycles()
        superseded = superseded_cycle_ids(local_cycles)
        unfinished_local = [c['id'] for c in local_cycles if c['id'] not in superseded
                            and c['status'] not in {'Complete', 'Complete with exceptions'}]
        # A company-only request must wait for the existing cycle; it may never
        # supersede work merely because it arrived through the request file.
        may_supersede = bool(new_scan_request and new_scan_request.get('mode') == 'fresh-full-scan')
        if unfinished_local and not may_supersede:
            raise ValueError("An unfinished local cycle exists. Resume it before starting another.")
        # Also reject a remote unfinished cycle after a local cache loss.
        if hasattr(self.repo, "read_columns"):
            remote_cycles = [row for _, row in self.repo.read_columns(
                "Scan Cycles", ["Cycle ID", "Cycle Status", "Notes"]
            )]
        else:
            remote_cycles = self.repo.read("Scan Cycles")
        superseded |= superseded_cycle_ids(remote_cycles)
        unfinished_remote = [r['Cycle ID'] for r in remote_cycles if r.get('Cycle ID') not in superseded
                             and r.get('Cycle Status') not in {'Complete', 'Complete with exceptions', '', None}]
        if unfinished_remote and not may_supersede:
            raise ValueError("An unfinished workbook cycle exists. Resume its Cycle ID.")
        rows = self._company_rows()
        # None alone means all companies. An empty scoped request must fail,
        # never silently become an all-company run.
        selected = None if company_ids is None else set(company_ids)
        if selected is not None and not selected:
            raise ValueError("Company-only cycle requires at least one Company ID")
        if selected is not None and selected - {r.get("Company ID") for r in rows}:
            raise ValueError("Unknown Company ID in requested scope")
        scope = {}
        for company in rows:
            if selected is not None and company.get("Company ID") not in selected:
                continue
            if str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                continue
            if not company.get("Company ID"):
                # New intake: date is first detection, not a fabricated entry date.
                self._assign_company_id(company)
            # Preserve the established queue/status behavior for legacy rows
            # that do not yet have a careers URL.  They receive no source
            # fence and therefore cannot publish source-derived work.  Rows
            # that do provide a source must pass the full admission guard.
            if company.get('Claimed By') or company.get('Claim Token'):
                continue
            admitted = {}
            if str(company.get('Official Careers URL') or '').strip():
                try:
                    self._admit_source_fact(admitted, company)
                except ValueError:
                    continue
            scope[company["Company ID"]] = {
                "company": company["Company"], "stage": "queued",
                **{key: admitted[key] for key in (
                    'outcome_source_revision', 'outcome_source_fact',
                    'installed_source_configuration') if key in admitted},
            }
        if not scope:
            raise ValueError("No active companies selected")
        cycle = {"id": "CYC-" + uuid.uuid4().hex[:12].upper(), "started_at": now(), "status": "In Progress",
                 "all": selected is None, "companies": scope}
        if self.runtime_binding is not None:
            cycle["runtime_binding"] = copy.deepcopy(self.runtime_binding)
        if new_scan_request is not None:
            last = set(new_scan_request.get('start_last', []))
            cycle['companies'] = dict(sorted(scope.items(), key=lambda pair: pair[0] in last))
            cycle.update(start_request_id=new_scan_request['request_id'],
                         supersedes=sorted(set(unfinished_local + unfinished_remote)),
                         start_last=list(new_scan_request.get('start_last', [])),
                         comparison_baseline_id=new_scan_request.get('comparison_baseline_id'),
                         request_fingerprint=new_scan_request.get('request_fingerprint'))
            if new_scan_request.get('company_event') is not None:
                cycle['company_event'] = dict(new_scan_request['company_event'])
            if new_scan_request.get('repair_retry') is not None:
                from .company_events import source_revision
                from .repair_retry import validate_retry_request
                retry = validate_retry_request(new_scan_request, list(company_ids or ()))
                company = next(row for row in rows if row.get('Company ID') == retry['company_id'])
                if source_revision(company) != retry['source_revision']:
                    raise ValueError('Repair retry source revision is stale; refusing to start a cycle.')
                cycle['repair_retry'] = retry
            if new_scan_request.get('operator_request') is not None:
                from .company_events import source_revision
                operator = new_scan_request['operator_request']
                if (not isinstance(operator, dict)
                        or operator.get('schema') != 'operator-company-scan-request-v1'
                        or operator.get('request_id') != new_scan_request.get('request_id')
                        or operator.get('company_id') not in set(company_ids or ())
                        or operator.get('source_revision') != new_scan_request.get('source_revision')):
                    raise ValueError('Operator company request is not bound to this cycle scope.')
                company = next(row for row in rows if row.get('Company ID') == operator['company_id'])
                if source_revision(company) != operator['source_revision']:
                    raise ValueError('Operator company request source revision is stale; refusing to start a cycle.')
                cycle['operator_request'] = dict(operator)
            if new_scan_request.get('temporary_retry') is not None:
                from .company_events import current_company_source_revision
                from .temporary_retry import is_temporary_retry_request
                retry = new_scan_request['temporary_retry']
                if (not is_temporary_retry_request(new_scan_request)
                        or current_company_source_revision(self.repo, retry['company_id']) != retry['source_revision']):
                    raise ValueError('Temporary retry source revision is stale; refusing to start a cycle.')
                company = next(row for row in rows if row.get('Company ID') == retry['company_id'])
                if company.get('Claimed By') or company.get('Claim Token'):
                    raise ValueError('Temporary retry Company is claimed; refusing to start a cycle.')
                cycle['temporary_retry'] = dict(retry)
        if selected_retry_reservation is not None:
            if (not isinstance(selected_retry_reservation, str)
                    or re.fullmatch(r'[0-9a-f]{64}', selected_retry_reservation) is None
                    or 'temporary_retry' not in cycle or len(cycle['companies']) != 1
                    or not isinstance(cycle.get('runtime_binding'), dict)):
                raise ValueError('Selected retry start requires one pinned reservation.')
            cycle['selected_retry_reservation_sha256'] = selected_retry_reservation
        self.state.save_cycle(cycle)
        self._sync_cycle(cycle)
        # Persist membership before fetching; reconstructible if local cache is lost.
        membership = []
        for company in rows:
            if company.get("Company ID") in scope:
                values = {"Active Cycle ID": cycle["id"], "Record Updated": now()}
                # Preserve a user-requested blocked hold, but never carry an old
                # Complete marker into the new cycle's membership.
                if company.get("Scan State") != "Blocked / Manual Review":
                    values["Scan State"] = "Queued"
                membership.append(self._company_op(company, values))
                if len(membership) >= self.batch_size:
                    self._commit(*membership)
                    membership = []
        if membership:
            self._commit(*membership)
        return cycle["id"]

    def _recover(self, cycle_id, *, persist=True, sync_only=False):
        matches = [r for r in self.repo.read("Scan Cycles") if r.get("Cycle ID") == cycle_id]
        if len(matches) != 1:
            raise ValueError("Unknown/ambiguous cycle ID. Start a cycle explicitly.")
        row = matches[0]
        scope = {}
        for company in self._company_rows():
            if company.get("Active Cycle ID") == cycle_id:
                scan = company.get("Scan State")
                stage = "complete" if scan == "Complete" else "blocked" if scan == "Blocked / Manual Review" else "queued"
                scope[company["Company ID"]] = {"company": company["Company"], "stage": stage}
        # Scope is also embedded in the cycle Notes to survive interrupted membership writes.
        try:
            control = json.loads(row.get("Notes", "{}"))
        except (json.JSONDecodeError, TypeError):
            control = {}
        by_id = {r["Company ID"]: r for r in self._company_rows() if r.get("Company ID")}
        for cid in control.get("company_ids", []):
            if cid in by_id and cid not in scope:
                scope[cid] = {"company": by_id[cid]["Company"], "stage": "queued"}
        cycle = {"id": cycle_id, "started_at": row.get("Started At") or now(), "status": row.get("Cycle Status"),
                 "all": bool(control.get("all", False)), "companies": scope}
        cycle.update({key: control[key] for key in ('start_request_id', 'supersedes', 'start_last', 'comparison_baseline_id', 'request_fingerprint', 'company_event', 'operator_request', 'repair_retry', 'temporary_retry', 'recovery_pause', 'runtime_binding', 'selected_retry_reservation_sha256')
                      if key in control})
        if cycle.get('repair_retry') is not None:
            from .repair_retry import validate_retry_request
            request = {'repair_retry': cycle['repair_retry'],
                       'request_id': cycle.get('start_request_id'),
                       'source_revision': cycle['repair_retry'].get('source_revision')}
            cycle['repair_retry'] = validate_retry_request(request, list(scope))
        self._assert_repair_retry_release(cycle)
        last = set(cycle.get('start_last', []))
        if last:
            cycle['companies'] = dict(sorted(scope.items(), key=lambda pair: pair[0] in last))
        if not scope and cycle["status"] not in {"Complete", "Complete with exceptions"}:
            raise ValueError("Cannot reconstruct cycle scope; restore the local state backup")
        self.check_admitted_cycle(cycle, sync_only=sync_only)
        if persist:
            self.state.save_cycle(cycle)
        return cycle

    def assert_runtime_binding(self, cycle_id, *, sync_only=False):
        """Hold an attempt rather than continue it on a different runtime."""
        cycle = self.state.cycle(cycle_id)
        if not cycle:
            raise ValueError("Runtime binding requires an exact saved cycle")
        return self._check_runtime_binding(cycle, sync_only=sync_only)

    def _check_runtime_binding(self, cycle, *, sync_only=False):
        return self.validate_cycle_runtime_binding(cycle, self.runtime_binding, sync_only=sync_only)

    def check_admitted_cycle(self, cycle, *, sync_only=False):
        if 'selected_retry_reservation_sha256' in cycle:
            raise ValueError('Selected retry requires its dedicated execution and publication path.')
        if self.runtime_binding is not None or 'runtime_binding' in cycle:
            self._check_runtime_binding(cycle, sync_only=sync_only)

    @staticmethod
    def validate_cycle_runtime_binding(cycle, runtime_binding, *, sync_only=False):
        """One policy for preflight and execution in every admitted scan route."""
        if runtime_binding is None:
            raise ValueError("Scraper runtime admission identity is unavailable")
        if (sync_only and "runtime_binding" not in cycle
                and runtime_binding["state"] == "NO_RELEASE"
                and "repair_retry" not in cycle):
            # A pre-upgrade inventory may still be processed without a fetch
            # before any integration release is installed. Preserve its
            # original provenance and never assign a retroactive runtime pin.
            return None
        if cycle.get("runtime_binding") != runtime_binding:
            raise ValueError(
                "Saved cycle runtime differs from this admitted worker; keeping "
                "the cycle and saved work on hold."
            )
        return copy.deepcopy(runtime_binding)

    def _assert_repair_retry_release(self, cycle):
        """Fail closed before a retry cycle can fetch or change saved work.

        A retry cycle retains its full release pin both in the local
        checkpoint and in the remote Scan Cycles Notes.  Every resume path
        must re-check that pin because a later activation or rollback may have
        happened after the cycle was first admitted.  This check deliberately
        precedes all retry-state rewrites, inbox acknowledgements, fetches,
        and workbook writes.
        """
        retry = cycle.get("repair_retry")
        if retry is None:
            return
        from .integration_release import assert_active_release_binding
        binding = retry.get("release") if isinstance(retry, dict) else None
        assert_active_release_binding(Path(self.state.path).parent, binding)

    def _sync_cycle(self, cycle):
        stages = [value["stage"] for value in cycle["companies"].values()]
        complete = stages.count("complete")
        blocked = sum(s in {"blocked", "unsupported", "failed", "paused"} for s in stages)
        partial = sum(s in {"partial", "awaiting_review"} for s in stages)
        remaining = sum(s in {"queued", "inventory"} for s in stages)
        if remaining:
            status = "In Progress"
        elif "awaiting_review" in stages:
            status = "Awaiting Review"
        else:
            status = "Complete with exceptions" if blocked or partial else "Complete"
        cycle["status"] = status
        values = {"Cycle Status": status, "Companies in Scope": len(stages), "Companies Complete": complete,
                  "Companies Partial": partial, "Companies Blocked": blocked, "Companies Remaining": remaining,
                  "Last Checkpoint At": now(), "Notes": json.dumps({"all": cycle["all"], "company_ids": list(cycle["companies"]),
                    "helper_version": 1, "mode": "single writer; no model calls",
                    **{key: cycle[key] for key in ('start_request_id', 'supersedes', 'start_last', 'comparison_baseline_id', 'request_fingerprint', 'company_event', 'operator_request', 'repair_retry', 'temporary_retry', 'recovery_pause', 'runtime_binding', 'selected_retry_reservation_sha256')
                       if key in cycle}}, separators=(",", ":"))}
        if status in {"Complete", "Complete with exceptions"}:
            values["Completed At"] = cycle.setdefault("completed_at", now())
        else:
            values["Completed At"] = ""
        self._commit({"tab": "Scan Cycles", "identity": {"Cycle ID": cycle["id"]}, "values": values,
                      "on_insert": {"Started At": cycle["started_at"], "Started By": "Local helper (single writer)"},
                      "append_if_missing": True})
        self.state.save_cycle(cycle)

    def assess_interrupted_cycle_recovery(self, cycle_id):
        """Prove an exact recovery pause is currently safe without changing data."""
        if not isinstance(cycle_id, str) or not cycle_id.strip():
            raise ValueError('Interrupted-cycle recovery requires an exact cycle ID.')
        cycle_id = cycle_id.strip()
        cycle = self.state.cycle(cycle_id)
        if not cycle or cycle.get('status') in {'Complete', 'Complete with exceptions'}:
            raise ValueError('Only an unfinished saved cycle can be paused for recovery.')
        remote = [row for row in self.repo.read('Scan Cycles') if row.get('Cycle ID') == cycle_id]
        if len(remote) != 1 or remote[0].get('Cycle Status') != cycle.get('status'):
            raise ValueError('Cycle checkpoint no longer matches the workbook; refresh and reconcile before recovery.')
        try:
            remote_control = json.loads(remote[0].get('Notes') or '{}')
        except (TypeError, ValueError) as exc:
            raise ValueError('Cycle workbook control is unreadable; refresh and reconcile before recovery.') from exc
        local_ids = set(cycle.get('companies', {}))
        if not isinstance(remote_control, dict) or set(remote_control.get('company_ids', [])) != local_ids:
            raise ValueError('Cycle workbook scope no longer matches the saved checkpoint; refresh and reconcile before recovery.')
        paused = sorted(company_id for company_id, item in cycle.get('companies', {}).items()
                        if item.get('stage') in {'queued', 'inventory'})
        if not paused:
            raise ValueError('Interrupted cycle has no queued or in-progress work to pause.')
        rows = {row.get('Company ID'): row for row in self._company_rows()}
        if any(company_id not in rows for company_id in paused):
            raise ValueError('A paused Company is missing from the workbook; reconcile before recovery.')
        if any(rows[company_id].get('Active Cycle ID') != cycle_id for company_id in paused):
            raise ValueError('A paused Company is no longer bound to this cycle; refresh and reconcile before recovery.')
        stages = {}
        for item in cycle.get('companies', {}).values():
            stage = str(item.get('stage') or 'unknown')
            stages[stage] = stages.get(stage, 0) + 1
        fingerprint = hashlib.sha256(
            '\n'.join(sorted(local_ids)).encode('utf-8')).hexdigest()
        return {
            'schema': 'interrupted-cycle-recovery-assessment-v1',
            'cycle_id': cycle_id,
            'eligible': True,
            'current_status': cycle.get('status'),
            'scope_count': len(local_ids),
            'scope_company_ids_sha256': fingerprint,
            'stage_counts': dict(sorted(stages.items())),
            'paused_company_ids': paused,
            'pause_count': len(paused),
            'local_workbook_status_match': True,
            'local_workbook_scope_match': True,
            'active_membership_match': True,
            'changes_applied': False,
        }

    def pause_interrupted_cycle(self, cycle_id, *, reason):
        """Freeze an exact inactive cycle without discarding its checkpoint."""
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 256:
            raise ValueError('Interrupted-cycle recovery requires a bounded reason.')
        assessment = self.assess_interrupted_cycle_recovery(cycle_id)
        cycle_id = assessment['cycle_id']
        paused = assessment['paused_company_ids']
        cycle = self.state.cycle(cycle_id)
        rows = {row.get('Company ID'): row for row in self._company_rows()}
        for company_id in paused:
            item = cycle['companies'][company_id]
            item['recovery_previous_stage'] = item['stage']
            item['stage'] = 'paused'
        hold = 'Interrupted cycle paused for recovery: ' + reason.strip()
        self._commit(*[self._company_op(rows[company_id], {
            'Scan State': 'Blocked / Manual Review', 'Automatic Retry?': 'No',
            'Blocked Reason': hold, 'Next Action': 'Cycle preserved for explicit recovery; do not retry automatically.',
            'Record Updated': now(),
        }) for company_id in paused])
        cycle['recovery_pause'] = {'reason': reason.strip(), 'paused_company_ids': sorted(paused),
                                   'previous_stages': {company_id: cycle['companies'][company_id]['recovery_previous_stage']
                                                       for company_id in sorted(paused)},
                                   'paused_at': now()}
        self.state.save_cycle(cycle)
        self._sync_cycle(cycle)
        return {'cycle_id': cycle_id, 'paused_company_ids': sorted(paused),
                'status': cycle['status'], 'recovery_pause': dict(cycle['recovery_pause'])}

    def _history(self, posting, company):
        key = job_key(company["Company ID"], posting["ats"], posting.get("posting_id", ""), posting["url"])
        url = canonicalize_url(posting["url"])
        matches = []
        row_numbers = {}
        if hasattr(self.repo, "history_candidates"):
            history_rows = self.repo.history_candidates(company["Company"], key, url)
        elif hasattr(self.repo, "read_columns"):
            numbered = self.repo.read_columns("Job History",
                ["Company", "Job Key", "Official Job URL", "Current Snapshot", "Requisition ID", "Job Title"])
            history_rows = [row for _, row in numbered]
            row_numbers = {id(row): number for number, row in numbered}
        else:
            history_rows = self.repo.read("Job History")
        for row in history_rows:
            if str(row.get("Company", "")).casefold() != str(company["Company"]).casefold():
                continue
            same_key = row.get("Job Key") == key
            old_url = row.get("Official Job URL", "")
            same_url = bool(old_url) and _safe_canonical_url(old_url) == url
            if same_url and not same_key:
                prior = unpack_snapshot(row.get("Current Snapshot", ""))
                prior_posting = prior.get("pending") or prior.get("evaluated")
                prior_id = (prior_posting or {}).get("posting_id") or row.get("Requisition ID", "")
                # Browser IDs encode only this URL, not an employer-issued
                # identity. Upgrading that exact synthetic ID to a real board
                # ID uses the existing legacy-key migration below. Never relax
                # the check for two different provider IDs or unrelated hashes.
                browser_id = "browser-" + hashlib.sha256(url.encode()).hexdigest()[:24]
                upgrading_browser_id = bool(
                    prior_posting and prior_id == browser_id
                    and _safe_canonical_url(prior_posting.get("url", "")) == url
                    and str(posting.get("posting_id", ""))
                    and not str(posting["posting_id"]).startswith("browser-")
                    and all(str((prior.get(stage) or {}).get("posting_id") or "")
                            in {"", browser_id, str(posting["posting_id"])}
                            for stage in ("pending", "evaluated"))
                )
                legacy_req = str(row.get('Requisition ID', '')).strip()
                provider_id = str(posting.get('posting_id', '')).strip()
                title = str(posting.get('title', '')).strip()
                # Older manually seeded rows used a requisition namespace,
                # distinct from the public Jobs2Web posting ID. Promote only
                # that exact legacy shape with corroborating official source
                # metadata; real provider-ID collisions still fail closed.
                upgrading_requisition_key = bool(
                    not prior.get('pending') and not prior.get('evaluated')
                    and re.fullmatch(r'\d{1,24}', legacy_req)
                    and row.get('Job Key') == str(company['Company']).strip().casefold() + '|req:' + legacy_req
                    and str(posting.get('ats', '')).casefold() == 'successfactors'
                    and str(posting.get('req_id', '')).strip() == legacy_req
                    and re.fullmatch(r'\d{4,24}', provider_id)
                    and re.fullmatch(r'/job/[^/]+/' + re.escape(provider_id) + r'/?', urlsplit(url).path)
                    and title and str(row.get('Job Title', '')).strip() in {title, title + ' — ' + legacy_req}
                )
                if prior_id and str(prior_id) != str(posting.get("posting_id", "")) and not (upgrading_browser_id or upgrading_requisition_key):
                    raise ValueError("An official URL was reused by a different posting ID. Manual disambiguation is required; the old posting will not be merged.")
            if same_key or same_url:
                matches.append(row)
        if len(matches) > 1:
            raise ValueError("Ambiguous history identity; reconcile duplicate rows before continuing")
        old = matches[0] if matches else None
        if old is not None and id(old) in row_numbers:
            old = self.repo.read_row("Job History", row_numbers[id(old)])
        if old and not old.get("Job Key"):
            raise ValueError("Matched legacy row lacks Job Key; backfill explicitly before scanning")
        # Always return the current stable provider identity. A legacy row may
        # have been found by its unique official URL even when several rows
        # share the same obsolete key; _stage_posting migrates that row by URL.
        return key, old

    def _opportunity(self, posting, company, aliases=()):
        urls = {canonicalize_url(value) for value in [posting["url"], *aliases] if value}
        if hasattr(self.repo, "opportunity_candidates"):
            candidates = self.repo.opportunity_candidates(company["Company"], urls)
        elif hasattr(self.repo, "read_columns"):
            candidates = [values for _, values in self.repo.read_columns(
                "Opportunities", ["Company", "Job URL"]
            )]
        else:
            candidates = self.repo.read("Opportunities")
        matches = [r for r in candidates
                   if str(r.get("Company", "")).casefold() == company["Company"].casefold()
                   and r.get("Job URL") and canonicalize_url(r["Job URL"]) in urls]
        if len(matches) > 1:
            if (getattr(self.repo, 'is_local', False)
                    and 'Opportunity ID' in self.repo.schemas['Opportunities']
                    and len({canonicalize_url(r['Job URL']) for r in matches}) == 1):
                # This represents the shared posting URL, not a chosen
                # application. The local repository scopes source updates to
                # each permanent application ID and preserves user fields.
                return {'Job URL': matches[0]['Job URL']}
            raise ValueError("Ambiguous opportunity URL; refusing to choose a duplicate row")
        return matches[0] if matches else None

    def _opportunity_op(self, posting, company, values, create=False, note=None, existing_url=None):
        return {"tab": "Opportunities", "identity": {"Company": company["Company"], "Job URL": existing_url or posting["url"]},
                "values": values, "append_if_missing": create,
                "on_insert": {"Job Title": posting["title"], "Location": posting.get("location", ""),
                              "Salary / Range": posting.get("compensation", ""), "Work Arrangement": posting.get("work_arrangement", ""),
                              "Application Status": "Not Reviewed", "Date Applied": "", "Date Found": now()[:10]},
                "append_notes": {"Notes": note} if note else {}}

    def sync_manual_opportunities(self):
        """Create missing Opportunities for Job History rows manually set to Yes."""
        headers = [
            "Company", "Job Title", "Added to Opportunities?", "Official Job URL",
            "Location", "Last Checked", "Fit Level", "Salary / Range", "Work Arrangement",
        ]
        if hasattr(self.repo, "read_columns"):
            history = [row for _, row in self.repo.read_columns("Job History", headers)]
            opportunities = [row for _, row in self.repo.read_columns(
                "Opportunities", ["Company", "Job URL"]
            )]
        else:
            history = self.repo.read("Job History")
            opportunities = self.repo.read("Opportunities")

        existing = set()
        duplicates = set()
        for row in opportunities:
            identity = (
                str(row.get("Company", "")).strip().casefold(),
                _safe_canonical_url(row.get("Job URL", "")),
            )
            if not all(identity):
                continue
            if identity in existing:
                duplicates.add(identity)
            existing.add(identity)

        operations = []
        planned = set()
        skipped = 0
        for row in history:
            if str(row.get("Added to Opportunities?", "")).strip().casefold() != "yes":
                continue
            company_name = str(row.get("Company", "")).strip()
            title = str(row.get("Job Title", "")).strip()
            url = str(row.get("Official Job URL", "")).strip()
            canonical_url = _safe_canonical_url(url)
            if not company_name or not title or not canonical_url:
                skipped += 1
                continue
            identity = (company_name.casefold(), canonical_url)
            if identity in planned:
                continue
            if identity in duplicates:
                if getattr(self.repo, 'is_local', False):
                    # Both application records already exist. A Yes selection
                    # does not authorize choosing, merging, or creating a third.
                    skipped += 1
                    continue
                raise ValueError("Ambiguous opportunity URL; reconcile duplicate rows before continuing")
            posting = {
                "title": title, "url": url, "location": row.get("Location", ""),
                "compensation": row.get("Salary / Range", ""),
                "work_arrangement": row.get("Work Arrangement", ""),
            }
            company = {"Company": company_name}
            if identity in existing:
                continue
            values = {
                "Job Title": title, "Last Checked": row.get("Last Checked", ""),
                "Location": row.get("Location", ""),
                "Salary / Range": row.get("Salary / Range", ""),
                "Work Arrangement": row.get("Work Arrangement", ""),
            }
            fit = str(row.get("Fit Level", "")).strip().casefold()
            fit_label = next((label for key, label in FIT_LABELS.items() if key.casefold() == fit), "")
            if fit_label:
                values["Fit Review"] = fit_label
            operations.append(self._opportunity_op(
                posting, company, values, create=True,
                note="[manual selection] Added from Job History after Added to Opportunities? was set to Yes.",
            ))
            planned.add(identity)
            existing.add(identity)

        if operations:
            self.repo.commit(operations)
        return {"added": len(operations), "skipped": skipped}

    def _stage_posting(self, cycle, company, posting):
        # Skip before history lookup, description processing, or any write.
        # Keep the full inventory unchanged for checkpoints and absence checks.
        if classify_title(posting.get("title", "")) == "reject":
            self._notice(f"Filtered - {posting.get('title', '')} at {company['Company']}: title blacklist match.")
            return
        key, old = self._history(posting, company)
        if old and reconsiderations(old) >= 2:
            return
        if posting.get("is_listed") is False and not old:
            return

        # Job-level review lock: while ChatGPT Work owns this row, the scraper
        # does not touch source evidence or Last Checked/Last Seen. It will
        # revisit the posting on the next scan after the review lock clears.
        if old and old.get("Review Status") == "In Progress":
            return

        snapshot = unpack_snapshot((old or {}).get("Current Snapshot", ""))
        snapshot["inventory_source"] = _cycle_inventory_source(cycle, company)
        current_hash = material_hash(posting)
        manual_review = bool(old and (
            str(old.get("Added to Opportunities?", "")).strip().casefold() == "manual review"
            or old.get("Review Status") == "Manual Review"
        ))
        changed_manual_source = bool(manual_review and old.get("Source Hash") and old["Source Hash"] != current_hash)
        reviewed_hash = str((old or {}).get("Description Hash", "") or "")
        unchanged = bool(
            old
            and old.get("Review Status") == "Reviewed"
            and reviewed_hash
            and reviewed_hash == current_hash
        )
        stamp = now()

        description = strip_job_boilerplate(posting.get("description", ""))
        if len(description) > 44_000:
            description = description[:43_900] + "\n[TRUNCATED — open Official Job URL for the remainder]"

        values = {
            "Company": company["Company"], "Job Title": posting["title"],
            "Job Key": key,
            "Official Job URL": posting["url"], "Requisition ID": posting.get("posting_id", ""),
            "Location": posting.get("location", ""), "Last Checked": stamp[:10],
            "Last Seen In Inventory": stamp, "Consecutive Missing Scans": 0,
            "Job Status": "Open and verified", "Record Updated": stamp,
            "Source Last Modified": posting.get("updated_at", ""), "Recheck Limit": 2,
            "Source Hash": current_hash,
            "Salary / Range": posting.get("compensation", ""),
            "Work Arrangement": posting.get("work_arrangement", ""),
            "Job Description": f"See Job Evidence tab: {key} / {current_hash[:12]}",
        }

        # Once Work has reviewed the current source hash, normalize the internal
        # snapshot on the next sighting. Work never has to decode or rewrite it.
        if unchanged:
            snapshot["evaluated"] = copy.deepcopy(posting)
            snapshot["pending"] = None
        else:
            snapshot["pending"] = copy.deepcopy(posting)

        # New postings and still-unreviewed Pending jobs get full screening,
        # including pay/employment rule improvements, preserving choices and any
        # existing Opportunity. Other prior decisions retain reassessment rules.
        from .locations import check_posting_location
        location_reason = check_posting_location(posting).rejection_reason
        auto_location_rejection = bool(old and old.get("Added to Opportunities?") == "No"
            and old.get("Decision") == "Reject"
            and str(old.get("Rejection Reason", "")).startswith("Location exclusion:")
            and "[US location cleanup]" in str(old.get("Review Notes", "")))
        location_rescreen = bool(old and location_reason
            and (old.get("Added to Opportunities?") == "Pending" and old.get("Review Status") == "Needs Review"
                 or auto_location_rejection and old.get("Review Status") == "Reviewed")
            and not old.get("Review Started At")
            and not self._opportunity(posting, company, [snapshot.get("opportunity_url"), old.get("Official Job URL")]))
        pending_rescreen = bool(old and old.get("Added to Opportunities?") == "Pending"
            and old.get("Review Status") == "Needs Review" and not old.get("Review Started At")
            and not self._opportunity(posting, company, [snapshot.get("opportunity_url"), old.get("Official Job URL")]))
        candidate_screen = screen_posting(posting) if not old or pending_rescreen else None
        # Managed claims can exist without an In Progress value in the Sheet.
        if pending_rescreen and candidate_screen.reason:
            from .location_cleanup import active_review_keys
            state_path = getattr(self.state, "path", None)
            if state_path and state_path != ":memory:":
                if key in active_review_keys(Path(state_path).parent / "review-queue/concurrent/review-runtime.sqlite3"):
                    return
        pending_rejection = pending_rescreen and candidate_screen.reason
        if not old or location_rescreen or pending_rejection:
            screening = (candidate_screen if not old else
                Screening(candidate_screen.reason if pending_rejection else location_reason, old.get("Review Notes", "")))
            auto_reason = screening.reason
            values["Review Notes"] = screening.review_note

            if auto_reason:
                snapshot["evaluated"] = copy.deepcopy(posting)
                snapshot["pending"] = None
                snapshot["evaluations"] = [*snapshot.get("evaluations", []), {
                    "decision": "reject",
                    "fit_level": None,
                    "narrative": auto_reason,
                    "evaluated_at": stamp,
                    "description_hash": current_hash,
                    "changed_fields": ["Initial evidence baseline"],
                }]
                values.update({
                    "Added to Opportunities?": "No",
                    "Reconsideration Count": reconsiderations(old) if old else 0,
                    "Reconsideration Status": old.get("Reconsideration Status", "Eligible") if old else "Eligible",
                    "Review Status": "Reviewed", "Review Started At": "",
                    "Decision": "Reject", "Fit Level": "",
                    "Rejection Reason": auto_reason, "Last Evaluated": stamp,
                    "Description Hash": current_hash,
                })
                if not old:
                    values["First Seen"] = stamp[:10]
                self._notice(f"Filtered - {posting['title']} at {company['Company']}: {auto_reason}")
            else:
                values.update({
                    "First Seen": stamp[:10], "Added to Opportunities?": "Pending",
                    "Reconsideration Count": 0, "Reconsideration Status": "Eligible",
                    "Review Status": "Needs Review", "Review Started At": "",
                    "Decision": "", "Fit Level": "",
                })
        elif manual_review and not changed_manual_source:
            # Repeated sightings do not turn a completed manual review back
            # into unreviewed work. A changed source still gets reassessed.
            values["Review Status"] = "Manual Review"
        elif not unchanged:
            values.update({
                "Review Status": "Needs Review", "Review Started At": "",
                "Decision": "", "Fit Level": "", "Rejection Reason": "",
                "Material Change Summary": "Official source content changed; reassessment required.",
            })
            if changed_manual_source and str(old.get("Added to Opportunities?", "")).strip().casefold() == "manual review":
                values["Added to Opportunities?"] = "Pending"

        existing = self._opportunity(posting, company, [snapshot.get("opportunity_url"), (old or {}).get("Official Job URL")])
        if existing:
            snapshot["opportunity_url"] = existing["Job URL"]
        values["Current Snapshot"] = pack_snapshot(snapshot)

        url_note = None
        if existing and canonicalize_url(existing["Job URL"]) != canonicalize_url(posting["url"]):
            url_note = f"[source URL updated] Current official posting URL: {posting['url']}. Existing Opportunity link retained to preserve record identity."

        history_identity = None
        migrating_legacy_key = bool(old and old.get("Job Key") != key)
        if migrating_legacy_key:
            # A legacy scraper could assign the careers-page URL as the key for
            # every posting on a board. Locate the one row by its distinct job
            # URL so duplicate legacy keys cannot make planning ambiguous.
            history_identity = {
                "Company": old["Company"],
                "Official Job URL": old["Official Job URL"],
            }
            if not old.get("Prior Job Key"):
                values["Prior Job Key"] = old["Job Key"]
        history_op = self._history_op(
            key, values, insert=not migrating_legacy_key,
            append_notes=url_note, identity=history_identity,
        )
        history_op["expected"] = {h: (old or {}).get(h, "") for h in (
            "Added to Opportunities?", "Review Status", "Review Started At", "Decision", "Reconsideration Count",
            "Description Hash", "Source Hash", "Rejection Reason", "Review Notes")}
        if migrating_legacy_key:
            history_op["expected"]["Job Key"] = old["Job Key"]
        operations = [history_op, self._evidence_op(key, current_hash, company, posting, description, stamp)]
        if existing:
            operations.append(self._opportunity_op(posting, company, {"Last Checked": stamp[:10]}, note=url_note, existing_url=existing["Job URL"]))
        self._commit(*operations)

    def _reconcile_absences(self, cycle, company, jobs):
        seen_urls = {canonicalize_url(p["url"]) for p in jobs}
        seen_keys = {job_key(company["Company ID"], p["ats"], p.get("posting_id", ""), p["url"]) for p in jobs}
        operations = []
        if hasattr(self.repo, "read_columns"):
            history_rows = [row for _, row in self.repo.read_columns(
                "Job History",
                ["Company", "Job Key", "Official Job URL", "Current Snapshot",
                 "Reconsideration Count", "Job Status", "Consecutive Missing Scans",
                 "Job Title", "Source Hash", "Added to Opportunities?", "Review Status",
                 "Review Started At", "Review Notes"],
            )]
        else:
            history_rows = self.repo.read("Job History")
        from .closed_jobs import close_pending_operation, opportunity_identities
        opportunities = opportunity_identities(self.repo)
        for row in history_rows:
            if str(row.get("Company", "")).casefold() != company["Company"].casefold() or not row.get("Job Key"):
                continue
            if str(row.get("Job Status", "")).strip().casefold() == "closed":
                cleanup = close_pending_operation(row, opportunities)
                if cleanup:
                    operations.append(cleanup)
                    if len(operations) >= self.batch_size:
                        self._commit(*operations)
                        operations = []
                continue
            if reconsiderations(row) >= 2:
                continue
            if row["Job Key"] in seen_keys or (row.get("Official Job URL") and _safe_canonical_url(row["Official Job URL"]) in seen_urls):
                continue
            snapshot = unpack_snapshot(row.get("Current Snapshot", ""))
            if _inventory_source(snapshot.get("inventory_source", "")) != _cycle_inventory_source(cycle, company):
                # Legacy targeted checks or another board's scope are not a
                # comparable complete-inventory baseline for closure inference.
                continue
            if snapshot.get("last_missing_cycle") == cycle["id"]:
                continue
            raw = row.get("Consecutive Missing Scans", "")
            try:
                missing = int(raw or 0) + 1
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid missing-scan count; refusing to reset evidence") from exc
            snapshot["last_missing_cycle"] = cycle["id"]
            note = ("Inferred removed after two consecutive complete official inventories; not directly verified closed."
                    if missing >= 2 else "Not Found – Verify: absent from one complete official inventory.")
            closure = close_pending_operation(row, opportunities, closing=True) if missing >= 2 else None
            operation = self._history_op(row["Job Key"], {
                "Consecutive Missing Scans": missing, "Job Status": "Closed" if missing >= 2 else "Unable to verify",
                "Current Snapshot": pack_snapshot(snapshot), "Record Updated": now(), "Material Change Summary": note},
                append_notes=f"[{cycle['id']} inventory absence] {note}")
            if closure:
                operation["expected"] = closure["expected"]
                operation["values"].update(closure["values"])
                operation["append_notes"]["Review Notes"] += "\n\n" + closure["append_notes"]["Review Notes"]
            operations.append(operation)
            if len(operations) >= self.batch_size:
                self._commit(*operations)
                operations = []
            # Do not overwrite Application Status, Last Checked, or user notes to claim a direct check.
        if operations:
            self._commit(*operations)

    def _finish_company(self, cycle, company):
        item = cycle["companies"][company["Company ID"]]
        if not item.get("staging_complete"):
            item["stage"] = "inventory"
            self.state.save_cycle(cycle)
            return
        source_status = item.get("inventory_status", "partial")
        if source_status == "complete":
            item["stage"] = "complete"
            scan, action = "Complete", "Official inventory saved; AI review runs independently from Job History"
        else:
            item["stage"] = "partial"
            scan, action = "Partial", "Inventory incomplete; manual review needed; no closure inference"
        if item.get("browser_pending_urls") or item.get("browser_discovery_incomplete"):
            item["stage"] = "partial"
            scan = "Partial"
            action = "Browser fetch incomplete; start a fresh scan or use start --resume for saved discovery and unresolved job URLs"
        values = {"Scan State": scan, "Active Cycle ID": cycle["id"], "Next Action": action,
                  "Coverage Status": "Complete official inventory" if source_status == "complete" else "Incomplete inventory",
                  "Last Inventory Count": len(item.get("jobs", [])), "Last Scan Result": item.get("reason", ""),
                  "Blocked Reason": "", "Record Updated": now()}
        values.update(self._ats_update(company, item.get("ats", "")))
        if item["stage"] == "complete":
            values["Last Successful Scan"] = item.get("fetched_at", now())
            values["Last Checked"] = item.get("fetched_at", now())[:10]
        self._commit(self._company_op(company, values))
        self.state.save_cycle(cycle)

    def resume(self, cycle_id, retry_blocked=False):
        self.repo.validate_schema()
        cycle = self.state.cycle(cycle_id) or self._recover(cycle_id)
        self.check_admitted_cycle(cycle)
        self._assert_repair_retry_release(cycle)
        if cycle["status"] in {"Complete", "Complete with exceptions"} and not retry_blocked:
            return self.status(cycle_id)
        if retry_blocked:
            for item in cycle["companies"].values():
                if item["stage"] in {"blocked", "failed", "unsupported", "partial"}:
                    item["stage"] = "queued"
                    item.pop("jobs", None)
            cycle.pop("completed_at", None)
        # Local state intentionally contains no scraped jobs. If a prior run
        # stopped mid-company, refetch that company and replay idempotently.
        for item in cycle["companies"].values():
            if item.get("stage") == "inventory" and not item.get("jobs"):
                item["stage"] = "queued"
                item.pop("next_job_index", None)
                item.pop("staging_complete", None)
        self.state.save_cycle(cycle)

        # Re-read company rows between each company; add genuinely new intake to --all.
        processed = set()
        fetch_work = CooperativeFetchWork(scope_id=cycle_id)
        while True:
            rows = self._company_rows()
            if cycle["all"]:
                for company in rows:
                    if not company.get("Company ID"):
                        self._assign_company_id(company)
                    cid = company.get("Company ID")
                    if not cid or cid in cycle["companies"] or company.get("Last Successful Scan"):
                        continue
                    admitted = {}
                    try:
                        self._admit_source_fact(admitted, company)
                    except ValueError:
                        continue
                    cycle["companies"][cid] = {
                        "company": company["Company"], "stage": "queued",
                        **{key: admitted[key] for key in (
                            'outcome_source_revision', 'outcome_source_fact',
                            'installed_source_configuration') if key in admitted},
                    }
                    self.state.save_cycle(cycle)
                    self._sync_cycle(cycle)
                    values = {"Active Cycle ID": cycle_id, "Record Updated": now()}
                    if company.get("Scan State") != "Blocked / Manual Review":
                        values["Scan State"] = "Queued"
                    self._commit(self._company_op(company, values))
            available = [(cid, data) for cid, data in cycle["companies"].items() if cid not in processed]
            if not available:
                break
            cid, item = available[0]
            processed.add(cid)
            company = next((r for r in rows if r.get("Company ID") == cid), None)
            if not company:
                item.update(stage="failed", reason="Company removed from workbook; scope retained for audit")
                self.state.save_cycle(cycle)
                continue
            if item["stage"] in {"complete", "blocked", "unsupported", "failed", "paused", "partial"}:
                continue
            if str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                item.update(stage="paused", reason="User paused or removed this company")
                self.state.save_cycle(cycle)
                continue
            if company.get("Claimed By") or company.get("Claim Token"):
                raise ValueError(f"{cid} has an external claim. Release it through its coordinator before running this single-writer helper.")
            if item["stage"] == "queued":
                if str(company.get("Automatic Retry?", "")).strip().casefold() == "no" and company.get("Scan State") == "Blocked / Manual Review" and not retry_blocked:
                    item.update(stage="blocked", reason="Manual-review hold; explicit --retry-blocked required")
                    self.state.save_cycle(cycle)
                    continue
                item.pop('outcome_failure', None)
                self.state.save_cycle(cycle)
                self._commit(self._company_op(company, {"Active Cycle ID": cycle_id, "Scan State": "In Progress", "Record Updated": now()}))
                with fetch_work.bind_worker(company["Company"]):
                    inventory = self.fetcher(str(company.get("ATS / Source", "")), str(company.get("Official Careers URL", "")), cid, company["Company"])
                from .company_events import source_revision as company_source_revision
                item.update(jobs=inventory.jobs, inventory_status=inventory.status, reason=inventory.reason,
                            source_url=inventory.source_url, ats=inventory.ats, fetched_at=now(), stage="inventory",
                            browser_pending_urls=inventory.browser_pending_urls,
                            browser_discovery_incomplete=inventory.browser_discovery_incomplete,
                            staging_complete=False, next_job_index=0,
                            outcome_source_revision=company_source_revision(company))
                failure = validate_outcome_failure(inventory.outcome_failure)
                if failure is not None:
                    item['outcome_failure'] = failure
                else:
                    item.pop('outcome_failure', None)
                self.state.save_cycle(cycle)
                if inventory.status in {"blocked", "failed", "unsupported"}:
                    item["stage"] = inventory.status
                    self._commit(self._company_op(company, {"Scan State": "Blocked / Manual Review", "Blocked Reason": inventory.reason,
                        "Automatic Retry?": "No", "Coverage Status": "Incomplete inventory", "Next Action": "Verify official careers URL / inspect manually; retry only on request",
                        **self._ats_update(company, inventory.ats),
                        "Last Scan Result": inventory.status, "Record Updated": now()}))
                    self.state.save_cycle(cycle)
                    self._sync_cycle(cycle)
                    continue
            planner = PlanningRepository(self.repo)
            if item["stage"] == "inventory":
                self._stage_inventory(cycle, company, item, planner)
                if item["inventory_status"] == "complete":
                    self._reconcile_absences(cycle, company, item.get("jobs", []))
                item["staging_complete"] = True
                self.state.save_cycle(cycle)
            self._finish_company(cycle, company)
            self._sync_cycle(cycle)
            self._checkpoint()
        self._sync_cycle(cycle)
        self._checkpoint()
        return self.status(cycle_id)

    def resume_local(self, cycle_id, sync_interval=60, **options):
        from .local_pipeline import LocalPipeline
        return LocalPipeline(self, cycle_id, sync_interval=sync_interval,
                             sync_only=options.get('sync_only', False)).run(**options)

    def resume_parallel(self, cycle_id, retry_blocked=False, fetch_workers=1, assignment_window=25,
                        sync_only=False, defer_sync=False):
        """Resume with multiple fetch-only workers and a single sheet writer.

        Worker threads receive an immutable company snapshot and return an
        Inventory durably saved in the SQLite inbox. Only this thread accesses
        Sheets and cycle checkpoints; producer threads only append inbox data.
        """
        if defer_sync and self.inbox is None:
            raise ValueError("Deferred sync requires a durable inventory inbox")
        if defer_sync and sync_only:
            raise ValueError("Deferred fetching and sync-only cannot be combined")
        if not 1 <= fetch_workers <= MAX_FETCH_WORKERS:
            raise ValueError(f"Fetch workers must be between 1 and {MAX_FETCH_WORKERS}")
        if not 1 <= assignment_window <= 100:
            raise ValueError("Assignment window must be between 1 and 100")

        self.repo.validate_schema()
        cycle = self.state.cycle(cycle_id) or self._recover(cycle_id, sync_only=sync_only)
        self.check_admitted_cycle(cycle, sync_only=sync_only)
        self._assert_repair_retry_release(cycle)
        if self.inbox is not None:
            for cid, item in cycle["companies"].items():
                saved = self.inbox.get(cycle_id, cid)
                if saved and item.get("stage") in {"complete", "partial"}:
                    self.inbox.acknowledge(cycle_id, cid)
                elif saved:
                    payload, blocked = saved
                    if (retry_blocked and not sync_only and not payload.get("jobs")
                            and payload.get("inventory_status") in {"failed", "blocked", "unsupported"}):
                        self.inbox.acknowledge(cycle_id, cid)
                        item["stage"] = "queued"
                        cycle["status"] = "In Progress"
                        continue
                    if not blocked or retry_blocked:
                        progress = item.get("next_job_index", 0) if item.get("stage") == "inventory" else 0
                        payload.pop("jobs", None)
                        item.update(payload, stage="inventory", next_job_index=progress, durable_inventory=True)
                        cycle["status"] = "In Progress"
        if cycle["status"] in {"Complete", "Complete with exceptions"} and not retry_blocked:
            return self.status(cycle_id)
        if retry_blocked:
            for item in cycle["companies"].values():
                if item["stage"] in {"blocked", "failed", "unsupported", "partial"}:
                    item["stage"] = "queued"
                    item.pop("jobs", None)
            cycle.pop("completed_at", None)
        for item in cycle["companies"].values():
            if item.get("stage") == "inventory" and not item.get("jobs") and not item.get("durable_inventory"):
                item["stage"] = "queued"
                item.pop("next_job_index", None)
                item.pop("staging_complete", None)
        self.state.save_cycle(cycle)

        started = SimpleQueue()
        dashboard_lock = Lock()
        worker_slots = {}
        dashboard = TerminalDashboard(fetch_workers)
        self._dashboard = dashboard
        dashboard.start()
        shared_work = CooperativeFetchWork(max_pending=2 * fetch_workers, scope_id=cycle_id)

        def worker_slot():
            thread = get_ident()
            with dashboard_lock:
                if thread not in worker_slots:
                    used = set(worker_slots.values())
                    worker_slots[thread] = next(number for number in range(1, fetch_workers + 1)
                                                if number not in used)
                return worker_slots[thread]

        def fetch_company(snapshot):
            try:
                cid = snapshot["Company ID"]
                slot = worker_slot()
                dashboard.worker_fetching(slot, snapshot["Company"])
                started.put(cid)
                with shared_work.bind_worker(snapshot["Company"]):
                    try:
                        inventory = self.fetcher(
                            str(snapshot.get("ATS / Source", "")),
                            str(snapshot.get("Official Careers URL", "")),
                            cid, snapshot["Company"],
                        )
                        if not isinstance(inventory, Inventory):
                            inventory = Inventory("failed", reason="Fetch worker returned an invalid inventory result")
                    except Exception as exc:
                        dashboard.worker_failed(slot, snapshot["Company"])
                        inventory = Inventory("failed", reason=f"Fetch worker failed: {type(exc).__name__}")
                    # Durability failures must surface, never replace a fetched
                    # inventory with an error payload or a success checkpoint.
                    payload = inventory_payload(inventory, snapshot)
                    if self.inbox is not None:
                        self.inbox.save(cycle_id, cid, payload)
                    dashboard.worker_handoff(slot, snapshot["Company"], len(inventory.jobs))
                    return cid, inventory, payload
            finally:
                shared_work.company_done()

        def set_writer_status(company, done, total, elapsed, processed=0):
            dashboard.writer_progress(company, done, total, elapsed, processed)

        processed = set()
        in_flight = {}
        helpers = {}
        saving_cid = None
        planner = None
        window_size = max(assignment_window, fetch_workers)

        def stop_helpers():
            for future, stop in helpers.items():
                stop.set()
                future.cancel()

        @contextmanager
        def helper_lifetime():
            try:
                yield
            finally:
                # End helper loops before executor shutdown waits for threads.
                # Owners still finish or cancel their own outstanding details.
                stop_helpers()

        def help_company(stop):
            slot = worker_slot()
            try:
                shared_work.help_until_finished(
                    stop, on_help=lambda name: dashboard.worker_assisting(slot, name))
            finally:
                dashboard.worker_assisting(slot, "")

        with _fetch_pool(fetch_workers) as executor, helper_lifetime():
            def collect_finished():
                for future in list(helpers):
                    if future.done():
                        helpers.pop(future)
                        if not future.cancelled():
                            future.result()
                for future in list(in_flight):
                    if not future.done():
                        continue
                    cid = in_flight.pop(future)
                    item = cycle["companies"][cid]
                    fetched_payload = None
                    try:
                        result_cid, inventory, fetched_payload = future.result()
                        if result_cid != cid or not isinstance(inventory, Inventory):
                            inventory = Inventory("failed", reason="Fetch worker returned an invalid inventory result")
                            fetched_payload = None
                    except (sqlite3.Error, OSError):
                        raise  # Local durability failed; keep the previous checkpoint.
                    except Exception as exc:
                        inventory = Inventory("failed", reason=f"Fetch worker failed: {type(exc).__name__}")
                    saved = self.inbox.get(cycle_id, cid) if self.inbox is not None else None
                    payload = saved[0] if saved else (fetched_payload or inventory_payload(inventory, item))
                    item.update(payload, stage="inventory", staging_complete=False, next_job_index=0)
                    failure = validate_outcome_failure(inventory.outcome_failure)
                    if failure is not None:
                        item['outcome_failure'] = failure
                    else:
                        item.pop('outcome_failure', None)
                    self.state.save_cycle(cycle)
                    if self.inbox is not None:
                        item.pop("jobs", None)
                        item["durable_inventory"] = True

            def record_started():
                operations = []
                while True:
                    try:
                        cid = started.get_nowait()
                    except Empty:
                        break
                    if cycle["companies"][cid].get("stage") == "queued":
                        operations.append(self._company_op({"Company ID": cid}, {"Scan State": "In Progress", "Record Updated": now()}))
                if operations:
                    self._commit(*operations)

            def refill(rows=None):
                if sync_only:
                    return
                # Futures are keyed by Future, not company ID. Exclude their
                # values so one company can never occupy two worker slots.
                assigned_ids = set(in_flight.values())
                queued = [(cid, item) for cid, item in cycle["companies"].items()
                          if cid not in processed and cid not in assigned_ids and item.get("stage") == "queued"]
                ready_count = 0 if defer_sync else sum(item.get("stage") == "inventory" and cid != saving_cid
                                  for cid, item in cycle["companies"].items())
                # Preload local assignments. The executor hands a returning
                # worker its next company without waiting for any Sheets call.
                capacity = window_size - ready_count - len(in_flight)
                if capacity <= 0 or not queued:
                    return
                by_id = {row.get("Company ID"): row for row in (rows if rows is not None else self._company_rows())}
                assignments, operations = [], []
                for cid, item in queued[:window_size]:
                    if capacity <= 0:
                        break
                    company = by_id.get(cid)
                    if not company:
                        item.update(stage="failed", reason="Company removed from workbook; scope retained for audit")
                    elif str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                        item.update(stage="paused", reason="User paused or removed this company")
                    elif company.get("Claimed By") or company.get("Claim Token"):
                        raise ValueError(f"{cid} has an external claim. Release it through its coordinator before running this single-writer helper.")
                    elif str(company.get("Automatic Retry?", "")).strip().casefold() == "no" and company.get("Scan State") == "Blocked / Manual Review" and not retry_blocked:
                        item.update(stage="blocked", reason="Manual-review hold; explicit --retry-blocked required")
                    else:
                        operations.append(self._company_op(company, {"Active Cycle ID": cycle_id, "Scan State": "Queued", "Record Updated": now()}))
                        item["requested_url"] = company["Official Careers URL"]
                        item.pop('outcome_failure', None)
                        # Keep M3's source fence in durable cycle state.  The
                        # inbox payload is F6-bound and must remain byte-for-
                        # byte compatible with existing receipt semantics.
                        from .company_events import source_revision as company_source_revision
                        item["outcome_source_revision"] = company_source_revision(company)
                        assignments.append((cid, copy.deepcopy(company)))
                        capacity -= 1
                        continue
                    self.state.save_cycle(cycle)
                    processed.add(cid)
                if assignments:
                    # New companies take priority. Stop an earlier helper batch
                    # before queueing them; already running details can finish.
                    stop_helpers()
                    self._commit(*operations)
                    self.state.save_cycle(cycle)
                    for cid, snapshot in assignments:
                        shared_work.company_added()
                        try:
                            future = executor.submit(fetch_company, snapshot)
                        except BaseException:
                            shared_work.company_done()
                            raise
                        # Canceled assignments never enter fetch_company's
                        # finally block, but must release their accounting.
                        future.add_done_callback(
                            lambda done: shared_work.company_done() if done.cancelled() else None)
                        in_flight[future] = cid

            def supply_helpers():
                if sync_only or not in_flight:
                    return
                assigned_ids = set(in_flight.values())
                if any(cid not in processed and cid not in assigned_ids and item.get("stage") == "queued"
                       for cid, item in cycle["companies"].items()):
                    return
                # These futures sit behind company assignments in the same
                # bounded executor. They can only use otherwise idle workers.
                for _ in range(max(0, fetch_workers - 1 - len(helpers))):
                    stop = Event()
                    helpers[executor.submit(help_company, stop)] = stop

            def service_fetchers(rows=None):
                collect_finished()
                record_started()
                refill(rows)
                supply_helpers()

            while True:
                rows = self._company_rows()
                if cycle["all"] and not sync_only:
                    for company in rows:
                        if str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                            continue
                        self._assign_company_id(company)
                        cid = company.get("Company ID")
                        if cid and cid not in cycle["companies"] and not company.get("Last Successful Scan") and str(company.get("Company Status", "Active")).strip().casefold() not in {"pause", "paused", "remove"}:
                            cycle["companies"][cid] = {"company": company["Company"], "stage": "queued"}
                            self.state.save_cycle(cycle)
                            self._sync_cycle(cycle)
                            values = {"Active Cycle ID": cycle_id, "Record Updated": now()}
                            if company.get("Scan State") != "Blocked / Manual Review":
                                values["Scan State"] = "Queued"
                            self._commit(self._company_op(company, values))

                service_fetchers(rows)
                inventory_ready = [] if defer_sync else [cid for cid, item in cycle["companies"].items()
                                   if cid not in processed and item.get("stage") == "inventory"]
                if not inventory_ready:
                    if in_flight:
                        wait([*in_flight, *helpers], return_when=FIRST_COMPLETED)
                        continue
                    if not sync_only and any(cid not in processed and item.get("stage") == "queued"
                           for cid, item in cycle["companies"].items()):
                        continue
                    break

                # Save one company, then service the pool again. Refilling at
                # each saved batch keeps fetchers supplied during long saves.
                for cid in inventory_ready[:1]:
                    item = cycle["companies"].get(cid)
                    if not item or item.get("stage") != "inventory":
                        processed.add(cid)
                        continue
                    company = next((r for r in self._company_rows() if r.get("Company ID") == cid), None)
                    if not company:
                        item.update(stage="failed", reason="Company removed from workbook; scope retained for audit")
                        item.pop("jobs", None)
                        self.state.save_cycle(cycle)
                        processed.add(cid)
                        continue
                    if str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                        item.update(stage="paused", reason="User paused or removed this company")
                        if self.inbox is not None:
                            self.inbox.block(cycle_id, cid)
                        item.pop("jobs", None)
                        self.state.save_cycle(cycle)
                        processed.add(cid)
                        continue
                    if company.get("Claimed By") or company.get("Claim Token"):
                        raise ValueError(f"{cid} has an external claim. Release it through its coordinator before running this single-writer helper.")
                    if item.get("inventory_status") in {"blocked", "failed", "unsupported"}:
                        dashboard.writer_message("Recording", company["Company"], item.get("inventory_status", ""))
                        if item.get("inventory_status") == "failed":
                            self._log_company_error(cycle, company, item,
                                RuntimeError(item.get("reason") or "Fetch failed"), "fetching inventory")
                        item["stage"] = item["inventory_status"]
                        if self.inbox is not None:
                            self.inbox.block(cycle_id, cid)
                        self._commit(self._company_op(company, {"Scan State": "Blocked / Manual Review", "Blocked Reason": item.get("reason", ""),
                            "Automatic Retry?": "No", "Coverage Status": "Incomplete inventory", "Next Action": "Verify official careers URL / inspect manually; retry only on request",
                            **self._ats_update(company, item.get("ats", "")),
                            "Last Scan Result": item["inventory_status"], "Record Updated": now()}))
                        item.pop("jobs", None)
                        self.state.save_cycle(cycle)
                        self._sync_cycle(cycle)
                        processed.add(cid)
                        continue
                    saving_cid = cid
                    try:
                        if self.inbox is not None:
                            saved = self.inbox.get(cycle_id, cid)
                            if saved is None:
                                raise ValueError("Saved inventory is missing; refusing to advance its checkpoint")
                            item["jobs"] = saved[0].get("jobs", [])
                        if planner is None:
                            planner = PlanningRepository(self.repo)
                        self._verify_same_board({"Official Careers URL": item.get("requested_url", company["Official Careers URL"])}, company)
                        service_fetchers()
                        self._stage_inventory(cycle, company, item, planner,
                                              progress_hook=service_fetchers,
                                              status_hook=set_writer_status)
                        if item["inventory_status"] == "complete":
                            self._reconcile_absences(cycle, company, item.get("jobs", []))
                        item["staging_complete"] = True
                        self.state.save_cycle(cycle)
                        self._finish_company(cycle, company)
                        if self.inbox is not None:
                            self.inbox.acknowledge(cycle_id, cid)
                    except Exception as exc:
                        planner = None
                        if self.inbox is not None:
                            self.inbox.block(cycle_id, cid)
                        self._log_company_error(cycle, company, item, exc, "saving inventory")
                        dashboard.writer_message("Error", company["Company"], type(exc).__name__)
                        try:
                            self._commit(self._company_op(company, {"Scan State": "Blocked / Manual Review",
                                "Blocked Reason": str(exc)[:900], "Automatic Retry?": "No",
                                "Coverage Status": "Incomplete inventory",
                                "Next Action": "Review .state/scraper-errors.jsonl, fix the sheet/source issue, then retry blocked companies",
                                **self._ats_update(company, item.get("ats", "")),
                                "Last Scan Result": "failed", "Record Updated": now()}))
                        except Exception as status_error:
                            self._log_company_error(cycle, company, item, status_error, "recording company error")
                    finally:
                        saving_cid = None
                    item.pop("jobs", None)
                    self._sync_cycle(cycle)
                    self._checkpoint()
                    processed.add(cid)
            dashboard.writer_message("Saved locally" if defer_sync else "Complete")
            if in_flight:
                for future in in_flight:
                    future.cancel()
        for future in helpers:
            if not future.cancelled():
                future.result()
        self._sync_cycle(cycle)
        self._checkpoint()
        return self.status(cycle_id)

    def export_reviews(self, cycle_id, path):
        if not self.state.cycle(cycle_id):
            raise ValueError("Unknown local cycle; resume it first to recover remote checkpoints")
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Explicit output must not overwrite an existing review file.
        with destination.open("x", encoding="utf-8") as stream:
            rows = self.state.reviews(cycle_id, "pending")
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        destination.chmod(0o600)
        return len(rows)

    def import_decisions(self, cycle_id, path):
        with Path(path).open(encoding="utf-8") as stream:
            decisions = [json.loads(line) for line in stream if line.strip()]
        if any(not isinstance(d, dict) for d in decisions):
            raise ValueError("Every decision JSONL line must be an object")
        keys = [d.get("job_key") for d in decisions]
        if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
            raise ValueError("Missing or duplicate decision keys in import file")
        if not decisions:
            return self.status(cycle_id)
        reviews = {r["job_key"]: r for r in self.state.reviews(cycle_id)}
        if any(key not in reviews for key in keys):
            raise ValueError(
                "Decision file has no matching saved legacy review queue. "
                "Current scans use job-search-reviewer submit; no decisions were saved."
            )
        planner = PlanningRepository(self.repo)
        for start in range(0, len(decisions), self.batch_size):
            chunk = decisions[start:start + self.batch_size]
            company_ids = {reviews[d["job_key"]]["company_id"] for d in chunk if d["job_key"] in reviews}
            for company_id in company_ids:
                planner.refresh_company(company_id)
            self._planned_batch(planner, lambda: self._import_decision_records(cycle_id, chunk))
            print(f"Decisions {'simulated' if self.dry_run else 'saved'}: {min(start+self.batch_size, len(decisions))}/{len(decisions)}", flush=True)
        return self.status(cycle_id)

    def _import_decision_records(self, cycle_id, decisions):
        cycle = self.state.cycle(cycle_id) or self._recover(cycle_id)
        if cycle["status"] in {"Complete", "Complete with exceptions"}:
            # Replaying a file after completion is a harmless no-op, never starts a cycle.
            return self.status(cycle_id)
        if any(not isinstance(d, dict) for d in decisions):
            raise ValueError("Every decision JSONL line must be an object")
        keys = [d.get("job_key") for d in decisions]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate decisions in import file")
        reviews = {r["job_key"]: r for r in self.state.reviews(cycle_id)}
        companies = {r.get("Company ID"): r for r in self._company_rows()}
        for decision in decisions:
            key = decision.get("job_key")
            if key not in reviews:
                raise ValueError("Decision is not in this cycle's review queue")
            review = reviews[key]
            if review["queue_status"] == "completed":
                if decision.get("description_hash") != review["description_hash"]:
                    raise ValueError("Replayed decision hash differs from completed review")
                continue
            company = companies.get(review["company_id"])
            if not company or str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                raise ValueError("Company is no longer active; decision import paused")
            if company.get("Claimed By") or company.get("Claim Token"):
                raise ValueError("Company has an external worker claim; decision import paused")
            posting = review["posting"]
            actual_key, old = self._history(posting, company)
            if actual_key != key or not old:
                raise ValueError("History identity changed; resume and inspect before importing")
            if str(old.get("Added to Opportunities?", "")).strip().casefold() == "manual review" and decision.get("decision") != "needs_info":
                raise ValueError("Manual review choice prevents automatic decision import")
            snapshot = unpack_snapshot(old.get("Current Snapshot", ""))
            if not snapshot.get("pending"):
                # Network response may have been lost after an atomic remote commit.
                if old.get("Description Hash") == decision.get("description_hash") and snapshot.get("evaluations"):
                    self.state.put_review(cycle_id, key, review, "completed")
                    continue
                raise ValueError("No matching pending evidence in the workbook")
            pending = snapshot["pending"]
            if material_hash(pending) != review["description_hash"]:
                raise ValueError("Workbook pending evidence changed; export a fresh review")
            validate_decision(decision, pending, snapshot)
            if reconsiderations(old) >= 2:
                raise ValueError("Posting is frozen after two reconsiderations; automatic import refused")
            if decision["decision"] == "needs_info":
                operation = self._history_op(
                    key,
                    {"Record Updated": now(), "Material Change Summary": "Manual review required",
                     **_manual_opportunity_status(old), "Review Status": "Manual Review",
                     "Review Started At": "", "Decision": "Needs Info", "Fit Level": ""},
                    append_notes=f"[needs-info {review['description_hash'][:12]}] {decision['narrative']}",
                )
                operation["expected"] = _review_guards(old)
                self._commit(operation)
                self.state.put_review(cycle_id, key, review, "deferred")
                continue
            previous = snapshot.get("evaluated")
            changed = bool(previous and material_hash(previous) != material_hash(pending))
            substantive = changed and decision.get("material_change") is True
            baseline_only = changed and not substantive
            prior_evaluations = snapshot["evaluations"]
            if baseline_only and prior_evaluations:
                last = prior_evaluations[-1]
                if decision["decision"] != last["decision"] or (decision["decision"] == "accept" and decision.get("fit_level") != last.get("fit_level")):
                    raise ValueError("A changed decision/fit is substantive; material_change must be true")
            count = reconsiderations(old) + int(substantive)
            stamp = now()
            change_summary = ", ".join(changed_fields(previous, pending))
            note = f"[review {review['description_hash'][:12]}] {decision.get('fit_level') or decision['decision']} — {decision['narrative']}"
            if decision["decision"] == "accept" and decision.get("base_max_usd") is None:
                note += " Compensation unverified: confirm annual base meets $120,000 floor; target near $180,000."
            if substantive:
                note += f" Reconsideration {count}/2; changed fields: {change_summary}."
            if baseline_only:
                note += " Nonmaterial source refresh; previous decision retained; reconsideration count unchanged."
            if count >= 2:
                note += " Automatic job-specific checking stopped after second reconsideration."
            _compact_evaluation_history(snapshot)
            snapshot.update(evaluated=pending, pending=None)
            if not baseline_only:
                snapshot["evaluations"].append({
                    "decision": decision["decision"],
                    "fit_level": decision.get("fit_level"),
                    "narrative": decision["narrative"],
                    "evaluated_at": stamp,
                    "description_hash": review["description_hash"],
                    "changed_fields": changed_fields(previous, pending),
                })
            else:
                snapshot["last_nonmaterial_refresh"] = {"at": stamp, "note": decision["narrative"], "hash": review["description_hash"]}
            snapshot["evaluations"] = snapshot["evaluations"][-3:]
            existing = self._opportunity(pending, company, [snapshot.get("opportunity_url")])
            accepted = decision["decision"] == "accept"
            if accepted or existing:
                snapshot["opportunity_url"] = existing["Job URL"] if existing else pending["url"]
            if existing and canonicalize_url(existing["Job URL"]) != canonicalize_url(pending["url"]):
                note += f" Official posting URL changed to {pending['url']}; prior Opportunity link retained to preserve its identity."
            values = {"Description Hash": review["description_hash"], "Current Snapshot": pack_snapshot(snapshot),
                      "Reconsideration Count": count, "Reconsideration Status": "Frozen after 2" if count >= 2 else "Eligible",
                      "Material Change Summary": change_summary, "Record Updated": stamp,
                      "Added to Opportunities?": "Yes" if existing or accepted else "No",
                      "Rejection Reason": "" if accepted else decision["narrative"]}
            if not baseline_only:
                values["Last Evaluated"] = stamp
            operations = [self._history_op(key, values, append_notes=note)]
            if accepted or existing:
                opportunity_values = {"Job Title": pending["title"], "Last Checked": old.get("Last Checked", ""), "Location": pending.get("location", ""),
                                      "Salary / Range": pending.get("compensation", ""), "Work Arrangement": pending.get("work_arrangement", "")}
                if accepted:
                    opportunity_values["Fit Review"] = FIT_LABELS[decision["fit_level"]]
                else:
                    opportunity_values["Fit Review"] = "Not Relevant"
                operations.append(self._opportunity_op(pending, company, opportunity_values, create=accepted, note=note,
                                                      existing_url=existing["Job URL"] if existing else None))
            result = self._commit(*operations)
            # This message is AFTER the successful atomic commit, never before it.
            if accepted and not existing:
                self._notice(f"{'[DRY RUN] Would add' if self.dry_run else 'Added'}: {company['Company']} — {pending['title']} | {decision['fit_level']} | Not Reviewed")
            self.state.put_review(cycle_id, key, review, "completed")
        for cid, item in cycle["companies"].items():
            if item["stage"] in {"awaiting_review", "inventory"} and cid in companies:
                self._finish_company(cycle, companies[cid])
        self._sync_cycle(cycle)
        return self.status(cycle_id)

    def status(self, cycle_id=None):
        if cycle_id:
            cycle = self.state.cycle(cycle_id)
            if not cycle:
                raise ValueError("Unknown local cycle")
            if hasattr(self.repo, "read_columns"):
                history = [values for _, values in self.repo.read_columns(
                    "Job History", ["Review Status"]
                )]
            else:
                history = self.repo.read("Job History")
            pending = sum(r.get("Review Status") in {"Needs Review", "In Progress"} for r in history)
            manual = sum(r.get("Review Status") == "Manual Review" for r in history)
            return {"cycle_id": cycle_id, "status": cycle["status"], "dry_run": self.dry_run,
                    "companies": {key: {"company": value["company"], "stage": value["stage"], "reason": value.get("reason", "")}
                                  for key, value in cycle["companies"].items()},
                    "pending_reviews": pending, "manual_review": manual}
        return {"cycles": [self.status(c["id"]) for c in self.state.cycles()]}


    def claim_next_review(self, stale_minutes=30):
        """Claim exactly one Job History row for AI review.

        Queue scans fetch identity and review controls. The full
        row is fetched only after one candidate is selected.
        """
        if hasattr(self.repo, "read_columns"):
            queue = self.repo.read_columns(
                "Job History", ["Job Key", "Review Status", "Review Started At", "Added to Opportunities?"]
            )
        else:
            queue = [(index + 2, row) for index, row in enumerate(self.repo.read("Job History"))]

        now_dt = datetime.now(timezone.utc)
        candidate = None
        self.last_review_queue_pending = False
        for row_number, row in queue:
            if str(row.get("Added to Opportunities?", "")).strip().casefold() == "manual review":
                continue
            status = row.get("Review Status", "")
            if status in {"Needs Review", "In Progress"}:
                self.last_review_queue_pending = True
            if status == "Needs Review":
                candidate = (row_number, row)
                break
            if status == "In Progress":
                raw = str(row.get("Review Started At", "") or "")
                try:
                    started = datetime.fromisoformat(raw)
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                except ValueError:
                    started = None
                if started is None or (now_dt - started).total_seconds() >= stale_minutes * 60:
                    candidate = (row_number, row)
                    break
        if not candidate:
            return None

        row_number, queue_row = candidate
        old = self.repo.read_row("Job History", row_number) if hasattr(self.repo, "read_row") else queue_row
        key = old.get("Job Key")
        if not key or key != queue_row.get("Job Key"):
            return None
        if old.get("Review Status") not in {"Needs Review", "In Progress"} or str(old.get("Added to Opportunities?", "")).strip().casefold() == "manual review":
            return None

        snapshot = unpack_snapshot(old.get("Current Snapshot", ""))
        pending = snapshot.get("pending")
        if not pending:
            operation = self._history_op(key, {
                "Review Status": "Manual Review", "Review Started At": "",
                **_manual_opportunity_status(old),
                "Decision": "Needs Info", "Record Updated": now(),
                "Material Change Summary": "Missing pending source snapshot for AI review",
            }, append_notes="[review] Missing pending source snapshot; manual review required.")
            operation["expected"] = _review_guards(old)
            self.repo.commit([operation])
            return None

        stamp = now()
        operation = self._history_op(
            key,
            {"Review Status": "In Progress", "Review Started At": stamp, "Record Updated": stamp},
        )
        operation["expected"] = _review_guards(old)
        self.repo.commit([operation])
        claimed = dict(old)
        claimed.update({"Review Status": "In Progress", "Review Started At": stamp, "Record Updated": stamp})
        return {
            "job_key": key,
            "row_number": row_number,
            "company": claimed.get("Company", ""),
            "title": claimed.get("Job Title", ""),
            "review_started_at": stamp,
            "posting": pending,
            "description_hash": material_hash(pending),
            "old_row": claimed,
            "snapshot": snapshot,
        }


    def apply_ai_decision(self, claim, decision):
        """Validate the live sheet claim and commit one AI decision directly."""
        key = claim["job_key"]
        if hasattr(self.repo, "read_row") and claim.get("row_number"):
            old = self.repo.read_row("Job History", claim["row_number"])
            if old.get("Job Key") != key:
                matches = [(rownum, row) for rownum, row in self.repo.read_columns(
                    "Job History", ["Job Key"]
                ) if row.get("Job Key") == key]
                if len(matches) != 1:
                    raise ValueError("Claimed Job History row no longer exists or is ambiguous")
                claim["row_number"] = matches[0][0]
                old = self.repo.read_row("Job History", claim["row_number"])
        else:
            rows = self.repo.read("Job History")
            old = next((r for r in rows if r.get("Job Key") == key), None)
        if not old:
            raise ValueError("Claimed Job History row no longer exists")
        if old.get("Review Status") != "In Progress" or old.get("Review Started At") != claim["review_started_at"]:
            raise ValueError("Review claim changed before decision commit")
        if old.get("Added to Opportunities?", "") != claim["old_row"].get("Added to Opportunities?", ""):
            raise ValueError("Manual opportunity choice changed before decision commit")
        if str(old.get("Added to Opportunities?", "")).strip().casefold() == "manual review":
            raise ValueError("Manual review choice changed before decision commit")
        snapshot = unpack_snapshot(old.get("Current Snapshot", ""))
        pending = snapshot.get("pending")
        if not pending or material_hash(pending) != claim["description_hash"]:
            raise ValueError("Source evidence changed before decision commit")
        decision = dict(decision)
        decision.update({
            "job_key": key, "description_hash": claim["description_hash"],
            "reviewer": decision.get("reviewer", "OpenAI"), "policy_version": POLICY_VERSION,
        })
        validate_decision(decision, pending, snapshot)

        stamp = now()
        if decision["decision"] == "needs_info":
            operation = self._history_op(key, {
                "Review Status": "Manual Review", "Review Started At": "",
                **_manual_opportunity_status(old),
                "Decision": "Needs Info", "Fit Level": "", "Last Evaluated": stamp,
                "Record Updated": stamp, "Material Change Summary": "Manual review required",
                "Rejection Reason": decision["narrative"],
            }, append_notes=f"[needs-info {claim['description_hash'][:12]}] {decision['narrative']}")
            operation["expected"] = _review_guards(old)
            self.repo.commit([operation])
            return "manual_review"

        previous = snapshot.get("evaluated")
        changed = bool(previous and material_hash(previous) != material_hash(pending))
        substantive = changed and decision.get("material_change") is True
        baseline_only = changed and not substantive
        if baseline_only and snapshot.get("evaluations"):
            last = snapshot["evaluations"][-1]
            if decision["decision"] != last.get("decision") or (decision["decision"] == "accept" and decision.get("fit_level") != last.get("fit_level")):
                raise ValueError("Changed decision/fit requires material_change=true")
        count = reconsiderations(old) + int(substantive)
        change_summary = ", ".join(changed_fields(previous, pending))
        note = f"[review {claim['description_hash'][:12]}] {decision.get('fit_level') or decision['decision']} — {decision['narrative']}"
        if decision["decision"] == "accept" and decision.get("base_max_usd") is None:
            note += " Compensation unverified: confirm annual base meets $120,000 floor; target near $180,000."
        if substantive:
            note += f" Reconsideration {count}/2; changed fields: {change_summary}."
        if baseline_only:
            note += " Nonmaterial source refresh; previous decision retained; reconsideration count unchanged."
        if count >= 2:
            note += " Automatic job-specific checking stopped after second reconsideration."

        _compact_evaluation_history(snapshot)
        snapshot.update(evaluated=pending, pending=None)
        if not baseline_only:
            snapshot["evaluations"].append({
                "decision": decision["decision"],
                "fit_level": decision.get("fit_level"),
                "narrative": decision["narrative"],
                "evaluated_at": stamp,
                "description_hash": claim["description_hash"] if "description_hash" in claim else decision.get("description_hash", ""),
                "changed_fields": changed_fields(previous, pending),
            })
        else:
            snapshot["last_nonmaterial_refresh"] = {"at": stamp, "note": decision["narrative"], "hash": claim["description_hash"]}
        snapshot["evaluations"] = snapshot["evaluations"][-3:]

        if hasattr(self.repo, "read_columns"):
            company_candidates = [(rownum, row) for rownum, row in self.repo.read_columns(
                "Companies", ["Company"]
            ) if str(row.get("Company", "")).casefold() == str(old.get("Company", "")).casefold()]
            if len(company_candidates) != 1:
                raise ValueError("Company row not found or is ambiguous for reviewed job")
            company = self.repo.read_row("Companies", company_candidates[0][0])
        else:
            company = next((r for r in self.repo.read("Companies")
                            if str(r.get("Company", "")).casefold() == str(old.get("Company", "")).casefold()), None)
            if not company:
                raise ValueError("Company row not found for reviewed job")
        existing = self._opportunity(pending, company, [snapshot.get("opportunity_url")])
        accepted = decision["decision"] == "accept"
        if accepted or existing:
            snapshot["opportunity_url"] = existing["Job URL"] if existing else pending["url"]

        values = {
            "Description Hash": claim["description_hash"], "Current Snapshot": pack_snapshot(snapshot),
            "Reconsideration Count": count, "Reconsideration Status": "Frozen after 2" if count >= 2 else "Eligible",
            "Material Change Summary": change_summary, "Record Updated": stamp, "Last Evaluated": stamp,
            "Added to Opportunities?": "Yes" if existing or accepted else "No",
            "Rejection Reason": "" if accepted else decision["narrative"],
            "Review Status": "Reviewed", "Review Started At": "",
            "Decision": "Accept" if accepted else "Reject",
            "Fit Level": decision.get("fit_level") or "",
        }
        operations = [self._history_op(key, values, append_notes=note)]
        operations[0]["expected"] = _review_guards(old)
        if accepted or existing:
            opportunity_values = {
                "Job Title": pending["title"], "Last Checked": old.get("Last Checked", ""),
                "Location": pending.get("location", ""), "Salary / Range": pending.get("compensation", ""),
                "Work Arrangement": pending.get("work_arrangement", ""),
                "Fit Review": FIT_LABELS[decision["fit_level"]] if accepted else "Not Relevant",
            }
            operations.append(self._opportunity_op(pending, company, opportunity_values, create=accepted, note=note,
                                                  existing_url=existing["Job URL"] if existing else None))
        self.repo.commit(operations)
        if accepted and not existing:
            self._notice(f"Added: {company['Company']} — {pending['title']} | {decision['fit_level']} | Not Reviewed")
        return "accepted" if accepted else "rejected"


def run_demo(output_dir):
    """Deterministic offline demo: title exclusions, review gate, atomic addition."""
    from .repository import MemoryRepository
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(destination.iterdir()):
        raise ValueError("Demo output directory must be empty; existing files are never replaced")
    print("OFFLINE DEMO: all following additions are to an isolated in-memory fixture, not your workbook.")
    company = {"Company": "Demo Robotics", "Company ID": "DEMO-001", "Company Status": "Active", "ATS / Source": "Greenhouse",
               "Official Careers URL": "https://boards.greenhouse.io/demo"}
    posting = {"company_id": "DEMO-001", "company": "Demo Robotics", "ats": "Greenhouse", "posting_id": "123", "req_id": "123",
               "url": "https://boards.greenhouse.io/demo/jobs/123", "title": "Field Solutions Engineering Lead", "location": "Remote, US",
               "work_arrangement": "Remote", "compensation": "USD 150000–190000 annual base", "description": "Lead customer deployments and technical discovery. No programming or security clearance required. Annual base salary $150,000–$190,000.",
               "department": "Solutions", "created_at": "", "updated_at": "", "is_listed": True}
    excluded = dict(posting, posting_id="124", title="Software Engineer", url="https://boards.greenhouse.io/demo/jobs/124")
    repo = MemoryRepository({"Companies": [company], "Job History": [], "Opportunities": [], "Scan Cycles": []})
    state = State(destination / "demo-state.db")
    try:
        engine = Engine(repo, state, fetcher=lambda *args: Inventory(status="complete", jobs=[posting, excluded], reason="Offline fixture", source_url=company["Official Careers URL"]))
        cycle = engine.start_cycle(["DEMO-001"])
        before = engine.resume(cycle)
        from .review_queue import export_review_queues
        from .review_runtime import Runtime
        from .review_writeback import sync_pending
        queue = destination / "review-queue"
        export_review_queues(repo, queue)
        runtime = Runtime(queue)
        try:
            # These are declared fictional fixture assessments, never model output.
            owner = runtime.start(1)["run_id"]
            titles = runtime.next(1, owner)["items"]
            claim_fields = ("job_key", "source_hash", "claim_token", "input_version")
            if titles:
                runtime.submit(1, owner, [{**{k:item[k] for k in claim_fields},
                    "decision":"RESCUE", "reason":"DEMO ONLY: fictional deployment title merits description review."}
                    for item in titles])
            owner = runtime.start(2)["run_id"]
            descriptions = runtime.next(2, owner)["items"]
            runtime.submit(2, owner, [{**{k:item[k] for k in claim_fields},
                "triage_decision":"ESCALATE", "description_complete":True,
                "reason":"DEMO ONLY: fixture describes customer deployment responsibilities.",
                "evidence_source":"offline_demo_fixture", "evidence_locator":"Job Evidence exact fixture identity",
                "evidence_packet":{"core_responsibilities":["Lead customer deployments and technical discovery."]}}
                for item in descriptions])
            owner = runtime.start(3)["run_id"]
            item = runtime.next(3, owner)["items"][0]
            decision = {**{k:item[k] for k in claim_fields}, "decision":"Accept", "fit_level":"Strong",
                "reason":"DEMO ONLY: customer discovery and field deployment match the fictional test profile.",
                "location_check":{"status":"verified_us", "source_value":posting["location"],
                                  "evidence":"Explicit Remote, US location in the fictional posting."},
                "policy_conflicts":[]}
            (destination / "decisions.example.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
            runtime.submit(3, owner, [decision])
            delivery = sync_pending(runtime, 3, owner, repo=repo, lock_path=destination / "demo-review.lock")
            if delivery.get("counts") != {"Written":1}:
                raise RuntimeError("Offline demonstration review did not verify its fixture delivery")
            after = engine.status(cycle)
        finally:
            runtime.close()
        output = {"before_review": before, "after_review": after, "tables": {tab: repo.read(tab) for tab in ("Companies", "Job History", "Opportunities", "Scan Cycles")}}
        (destination / "demo-results.json").write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"output_dir": str(destination.resolve()), "before_review": before, "after_review": after, "notice": "Offline fixtures only. No Google writes or AI/API charges."}
    finally:
        state.close()
