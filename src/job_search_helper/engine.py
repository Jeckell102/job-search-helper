"""Single-writer pipeline with atomic batches and local lookup caching.

SQLite is a local work cache. Durable evidence and cycle IDs are also stored in
the workbook; a known cycle can be reconstructed without repeating decisions.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
import copy
import json
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Lock, get_ident

from .ats import Inventory, fetch_inventory, resolve_board
from .batching import PlanningRepository, PendingState
from .core import (FIT_LABELS, POLICY_VERSION, canonicalize_url, changed_fields,
                   job_key, material_hash, pack_snapshot,
                   plain_text, reconsiderations, unpack_snapshot, validate_decision)
from .dashboard import TerminalDashboard
from .efficiency import classify_title, strip_job_boilerplate
from .screening import screen_posting


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _inventory_source(url):
    try:
        _, board, root = resolve_board("", url)
        return root + board
    except (ValueError, TypeError):
        return canonicalize_url(url)


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
    return {"jobs": inventory.jobs, "inventory_status": inventory.status,
            "reason": inventory.reason, "source_url": inventory.source_url, "ats": inventory.ats,
            "fetched_at": now(), "requested_url": company.get("Official Careers URL", company.get("requested_url", ""))}


class State:
    def __init__(self, db_path=":memory:", readonly=False):
        self.readonly = readonly
        self.path = str(db_path)
        self.checkpoint_seconds = 0.0
        self.checkpoint_bytes = 0
        if readonly:
            uri = Path(db_path).resolve().as_uri() + "?mode=ro"
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
                 checkpoint_hook=None, error_log_path=DEFAULT_ERROR_LOG, inbox=None):
        self.repo, self.state, self.dry_run, self.fetcher = repo, state, dry_run, fetcher
        self.inbox = inbox
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

    def _history_op(self, key, values, insert=False, append_notes=None):
        return {"tab": "Job History", "identity": {"Job Key": key}, "values": values,
                "append_if_missing": insert, "append_notes": {"Review Notes": append_notes} if append_notes else {}}

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

    def start_cycle(self, company_ids=None):
        self.repo.validate_schema()
        if any(c["status"] not in {"Complete", "Complete with exceptions"} for c in self.state.cycles()):
            raise ValueError("An unfinished local cycle exists. Resume it before starting another.")
        # Also reject a remote unfinished cycle after a local cache loss.
        if hasattr(self.repo, "read_columns"):
            remote_cycles = [row for _, row in self.repo.read_columns(
                "Scan Cycles", ["Cycle ID", "Cycle Status"]
            )]
        else:
            remote_cycles = self.repo.read("Scan Cycles")
        if any(r.get("Cycle Status") not in {"Complete", "Complete with exceptions", "", None}
               for r in remote_cycles):
            raise ValueError("An unfinished workbook cycle exists. Resume its Cycle ID.")
        rows = self._company_rows()
        selected = set(company_ids or [])
        if selected and selected - {r.get("Company ID") for r in rows}:
            raise ValueError("Unknown Company ID in requested scope")
        scope = {}
        for company in rows:
            if selected and company.get("Company ID") not in selected:
                continue
            if str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
                continue
            if not company.get("Company ID"):
                # New intake: date is first detection, not a fabricated entry date.
                self._assign_company_id(company)
            scope[company["Company ID"]] = {"company": company["Company"], "stage": "queued"}
        if not scope:
            raise ValueError("No active companies selected")
        cycle = {"id": "CYC-" + uuid.uuid4().hex[:12].upper(), "started_at": now(), "status": "In Progress",
                 "all": not bool(selected), "companies": scope}
        self.state.save_cycle(cycle)
        self._sync_cycle(cycle)
        # Persist membership before fetching; reconstructible if local cache is lost.
        for company in rows:
            if company.get("Company ID") in scope:
                values = {"Active Cycle ID": cycle["id"], "Record Updated": now()}
                # Preserve a user-requested blocked hold, but never carry an old
                # Complete marker into the new cycle's membership.
                if company.get("Scan State") != "Blocked / Manual Review":
                    values["Scan State"] = "Queued"
                self._commit(self._company_op(company, values))
        return cycle["id"]

    def _recover(self, cycle_id):
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
        if not scope and cycle["status"] not in {"Complete", "Complete with exceptions"}:
            raise ValueError("Cannot reconstruct cycle scope; restore the local state backup")
        self.state.save_cycle(cycle)
        return cycle

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
                    "helper_version": 1, "mode": "single writer; no model calls"}, separators=(",", ":"))}
        if status in {"Complete", "Complete with exceptions"}:
            values["Completed At"] = cycle.setdefault("completed_at", now())
        else:
            values["Completed At"] = ""
        self._commit({"tab": "Scan Cycles", "identity": {"Cycle ID": cycle["id"]}, "values": values,
                      "on_insert": {"Started At": cycle["started_at"], "Started By": "Local helper (single writer)"},
                      "append_if_missing": True})
        self.state.save_cycle(cycle)

    def _history(self, posting, company):
        key = job_key(company["Company ID"], posting["ats"], posting.get("posting_id", ""), posting["url"])
        url = canonicalize_url(posting["url"])
        matches = []
        row_numbers = {}
        if hasattr(self.repo, "history_candidates"):
            history_rows = self.repo.history_candidates(company["Company"], key, url)
        elif hasattr(self.repo, "read_columns"):
            numbered = self.repo.read_columns("Job History",
                ["Company", "Job Key", "Official Job URL", "Current Snapshot"])
            history_rows = [row for _, row in numbered]
            row_numbers = {id(row): number for number, row in numbered}
        else:
            history_rows = self.repo.read("Job History")
        for row in history_rows:
            if str(row.get("Company", "")).casefold() != str(company["Company"]).casefold():
                continue
            same_key = row.get("Job Key") == key
            old_url = row.get("Official Job URL", "")
            same_url = bool(old_url) and canonicalize_url(old_url) == url
            if same_url and not same_key:
                prior = unpack_snapshot(row.get("Current Snapshot", ""))
                prior_posting = prior.get("pending") or prior.get("evaluated")
                if prior_posting and str(prior_posting.get("posting_id", "")) != str(posting.get("posting_id", "")):
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
        return (old.get("Job Key") if old else key), old

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
            raise ValueError("Ambiguous opportunity URL; refusing to choose a duplicate row")
        return matches[0] if matches else None

    def _opportunity_op(self, posting, company, values, create=False, note=None, existing_url=None):
        return {"tab": "Opportunities", "identity": {"Company": company["Company"], "Job URL": existing_url or posting["url"]},
                "values": values, "append_if_missing": create,
                "on_insert": {"Job Title": posting["title"], "Location": posting.get("location", ""),
                              "Salary / Range": posting.get("compensation", ""), "Work Arrangement": posting.get("work_arrangement", ""),
                              "Application Status": "Not Reviewed", "Date Applied": "", "Date Found": now()[:10]},
                "append_notes": {"Notes": note} if note else {}}

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
            "Official Job URL": posting["url"], "Requisition ID": posting.get("posting_id", ""),
            "Location": posting.get("location", ""), "Last Checked": stamp[:10],
            "Last Seen In Inventory": stamp, "Consecutive Missing Scans": 0,
            "Job Status": "Open and verified", "Record Updated": stamp,
            "Source Last Modified": posting.get("updated_at", ""), "Recheck Limit": 2,
            "Source Hash": current_hash,
            "Salary / Range": posting.get("compensation", ""),
            "Work Arrangement": posting.get("work_arrangement", ""),
            "Job Description": description,
        }

        # Once Work has reviewed the current source hash, normalize the internal
        # snapshot on the next sighting. Work never has to decode or rewrite it.
        if unchanged:
            snapshot["evaluated"] = copy.deepcopy(posting)
            snapshot["pending"] = None
        else:
            snapshot["pending"] = copy.deepcopy(posting)

        # New postings get free deterministic screening before they ever enter
        # the Work queue. Changed previously reviewed postings always return to
        # Needs Review so an earlier decision is not silently replaced.
        if not old:
            screening = screen_posting(posting)
            auto_reason = screening.reason
            values["Review Notes"] = screening.review_note

            if auto_reason:
                snapshot["evaluated"] = copy.deepcopy(posting)
                snapshot["pending"] = None
                snapshot["evaluations"] = [{
                    "decision": "reject",
                    "fit_level": None,
                    "narrative": auto_reason,
                    "evaluated_at": stamp,
                    "description_hash": current_hash,
                    "changed_fields": ["Initial evidence baseline"],
                }]
                values.update({
                    "First Seen": stamp[:10], "Added to Opportunities?": "No",
                    "Reconsideration Count": 0, "Reconsideration Status": "Eligible",
                    "Review Status": "Reviewed", "Review Started At": "",
                    "Decision": "Reject", "Fit Level": "",
                    "Rejection Reason": auto_reason, "Last Evaluated": stamp,
                    "Description Hash": current_hash,
                })
                self._notice(f"Filtered - {posting['title']} at {company['Company']}: {auto_reason}")
            else:
                values.update({
                    "First Seen": stamp[:10], "Added to Opportunities?": "Pending",
                    "Reconsideration Count": 0, "Reconsideration Status": "Eligible",
                    "Review Status": "Needs Review", "Review Started At": "",
                    "Decision": "", "Fit Level": "",
                })
        elif not unchanged:
            values.update({
                "Review Status": "Needs Review", "Review Started At": "",
                "Decision": "", "Fit Level": "", "Rejection Reason": "",
                "Material Change Summary": "Official source content changed; reassessment required.",
            })

        existing = self._opportunity(posting, company, [snapshot.get("opportunity_url"), (old or {}).get("Official Job URL")])
        if existing:
            snapshot["opportunity_url"] = existing["Job URL"]
        values["Current Snapshot"] = pack_snapshot(snapshot)

        url_note = None
        if existing and canonicalize_url(existing["Job URL"]) != canonicalize_url(posting["url"]):
            url_note = f"[source URL updated] Current official posting URL: {posting['url']}. Existing Opportunity link retained to preserve record identity."

        history_op = self._history_op(key, values, insert=True, append_notes=url_note)
        history_op["expected"] = {h: (old or {}).get(h, "") for h in (
            "Added to Opportunities?", "Review Status", "Decision", "Reconsideration Count",
            "Description Hash", "Rejection Reason", "Review Notes")}
        operations = [history_op]
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
                 "Reconsideration Count", "Job Status", "Consecutive Missing Scans"],
            )]
        else:
            history_rows = self.repo.read("Job History")
        for row in history_rows:
            if str(row.get("Company", "")).casefold() != company["Company"].casefold() or not row.get("Job Key"):
                continue
            if reconsiderations(row) >= 2 or row.get("Job Status") == "Closed":
                continue
            if row["Job Key"] in seen_keys or (row.get("Official Job URL") and canonicalize_url(row["Official Job URL"]) in seen_urls):
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
            operations.append(self._history_op(row["Job Key"], {
                "Consecutive Missing Scans": missing, "Job Status": "Closed" if missing >= 2 else "Unable to verify",
                "Current Snapshot": pack_snapshot(snapshot), "Record Updated": now(), "Material Change Summary": note},
                append_notes=f"[{cycle['id']} inventory absence] {note}"))
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
        values = {"Scan State": scan, "Active Cycle ID": cycle["id"], "Next Action": action,
                  "Coverage Status": "Complete official inventory" if source_status == "complete" else "Incomplete inventory",
                  "Last Inventory Count": len(item.get("jobs", [])), "Last Scan Result": item.get("reason", ""), "Record Updated": now()}
        values.update(self._ats_update(company, item.get("ats", "")))
        if item["stage"] == "complete":
            values["Last Successful Scan"] = item.get("fetched_at", now())
            values["Last Checked"] = item.get("fetched_at", now())[:10]
            values["Blocked Reason"] = ""
        self._commit(self._company_op(company, values))
        self.state.save_cycle(cycle)

    def resume(self, cycle_id, retry_blocked=False):
        self.repo.validate_schema()
        cycle = self.state.cycle(cycle_id) or self._recover(cycle_id)
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
        while True:
            rows = self._company_rows()
            if cycle["all"]:
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
                self._commit(self._company_op(company, {"Active Cycle ID": cycle_id, "Scan State": "In Progress", "Record Updated": now()}))
                inventory = self.fetcher(str(company.get("ATS / Source", "")), str(company.get("Official Careers URL", "")), cid, company["Company"])
                item.update(jobs=inventory.jobs, inventory_status=inventory.status, reason=inventory.reason,
                            source_url=inventory.source_url, ats=inventory.ats, fetched_at=now(), stage="inventory",
                            staging_complete=False, next_job_index=0)
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
        if not 1 <= fetch_workers <= 5:
            raise ValueError("Fetch workers must be between 1 and 5")
        if not 1 <= assignment_window <= 100:
            raise ValueError("Assignment window must be between 1 and 100")

        self.repo.validate_schema()
        cycle = self.state.cycle(cycle_id) or self._recover(cycle_id)
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

        def worker_slot():
            thread = get_ident()
            with dashboard_lock:
                if thread not in worker_slots:
                    used = set(worker_slots.values())
                    worker_slots[thread] = next(number for number in range(1, fetch_workers + 1)
                                                if number not in used)
                return worker_slots[thread]

        def fetch_company(snapshot):
            cid = snapshot["Company ID"]
            slot = worker_slot()
            dashboard.worker_fetching(slot, snapshot["Company"])
            started.put(cid)
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
            # Outside the fetch exception handler: durability failures must not
            # replace a successfully fetched inventory with an error payload.
            if self.inbox is not None:
                self.inbox.save(cycle_id, cid, inventory_payload(inventory, snapshot))
            dashboard.worker_handoff(slot, snapshot["Company"], len(inventory.jobs))
            return cid, inventory

        def set_writer_status(company, done, total, elapsed, processed=0):
            dashboard.writer_progress(company, done, total, elapsed, processed)

        processed = set()
        in_flight = {}
        saving_cid = None
        planner = None
        window_size = max(assignment_window, fetch_workers)
        with _fetch_pool(fetch_workers) as executor:
            def collect_finished():
                for future in list(in_flight):
                    if not future.done():
                        continue
                    cid = in_flight.pop(future)
                    item = cycle["companies"][cid]
                    try:
                        result_cid, inventory = future.result()
                        if result_cid != cid or not isinstance(inventory, Inventory):
                            inventory = Inventory("failed", reason="Fetch worker returned an invalid inventory result")
                    except (sqlite3.Error, OSError):
                        raise  # Local durability failed; keep the previous checkpoint.
                    except Exception as exc:
                        inventory = Inventory("failed", reason=f"Fetch worker failed: {type(exc).__name__}")
                    saved = self.inbox.get(cycle_id, cid) if self.inbox is not None else None
                    payload = saved[0] if saved else inventory_payload(inventory, item)
                    item.update(payload, stage="inventory", staging_complete=False, next_job_index=0)
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
                        assignments.append((cid, copy.deepcopy(company)))
                        capacity -= 1
                        continue
                    self.state.save_cycle(cycle)
                    processed.add(cid)
                if assignments:
                    self._commit(*operations)
                    self.state.save_cycle(cycle)
                    for cid, snapshot in assignments:
                        in_flight[executor.submit(fetch_company, snapshot)] = cid

            def service_fetchers(rows=None):
                collect_finished()
                record_started()
                refill(rows)

            while True:
                rows = self._company_rows()
                if cycle["all"]:
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
                        wait(in_flight, return_when=FIRST_COMPLETED)
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
        planner = PlanningRepository(self.repo)
        reviews = {r["job_key"]: r for r in self.state.reviews(cycle_id)}
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
                self._commit(self._history_op(
                    key,
                    {"Record Updated": now(), "Material Change Summary": "Manual review required"},
                    append_notes=f"[needs-info {review['description_hash'][:12]}] {decision['narrative']}",
                ))
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

        Queue scans fetch only Job Key/Review Status/Review Started At. The full
        row is fetched only after one candidate is selected.
        """
        if hasattr(self.repo, "read_columns"):
            queue = self.repo.read_columns(
                "Job History", ["Job Key", "Review Status", "Review Started At"]
            )
        else:
            queue = [(index + 2, row) for index, row in enumerate(self.repo.read("Job History"))]

        now_dt = datetime.now(timezone.utc)
        candidate = None
        self.last_review_queue_pending = False
        for row_number, row in queue:
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
        if old.get("Review Status") not in {"Needs Review", "In Progress"}:
            return None

        snapshot = unpack_snapshot(old.get("Current Snapshot", ""))
        pending = snapshot.get("pending")
        if not pending:
            self.repo.commit([self._history_op(key, {
                "Review Status": "Manual Review", "Review Started At": "",
                "Decision": "Needs Info", "Record Updated": now(),
                "Material Change Summary": "Missing pending source snapshot for AI review",
            }, append_notes="[review] Missing pending source snapshot; manual review required.")])
            return None

        stamp = now()
        self.repo.commit([self._history_op(
            key,
            {"Review Status": "In Progress", "Review Started At": stamp, "Record Updated": stamp},
        )])
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
            self.repo.commit([self._history_op(key, {
                "Review Status": "Manual Review", "Review Started At": "",
                "Decision": "Needs Info", "Fit Level": "", "Last Evaluated": stamp,
                "Record Updated": stamp, "Material Change Summary": "Manual review required",
                "Rejection Reason": decision["narrative"],
            }, append_notes=f"[needs-info {claim['description_hash'][:12]}] {decision['narrative']}")])
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
    engine = Engine(repo, state, fetcher=lambda *args: Inventory(status="complete", jobs=[posting, excluded], reason="Offline fixture", source_url=company["Official Careers URL"]))
    cycle = engine.start_cycle(["DEMO-001"])
    before = engine.resume(cycle)
    engine.export_reviews(cycle, destination / "reviews.jsonl")
    queued = state.reviews(cycle, "pending")[0]
    decision = {"job_key": queued["job_key"], "description_hash": queued["description_hash"], "decision": "accept", "fit_level": "Strong",
                "narrative": "DEMO ONLY: customer discovery and field deployment align with the fictional test profile; no mandatory clearance or code ownership. Confirm travel. Resume selection would be performed by the reviewer.",
                "reviewer": "Offline demonstration fixture", "policy_version": POLICY_VERSION, "mandatory_clearance": False,
                "code_authoring_required": False, "primary_test_automation": False, "base_max_usd": 190000, "material_change": False}
    decision_path = destination / "decisions.example.jsonl"
    decision_path.write_text(json.dumps(decision) + "\n", encoding="utf-8")
    after = engine.import_decisions(cycle, decision_path)
    output = {"before_review": before, "after_review": after, "tables": {tab: repo.read(tab) for tab in ("Companies", "Job History", "Opportunities", "Scan Cycles")}}
    (destination / "demo-results.json").write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    state.close()
    return {"output_dir": str(destination.resolve()), "before_review": before, "after_review": after, "notice": "Offline fixtures only. No Google writes or AI/API charges."}
