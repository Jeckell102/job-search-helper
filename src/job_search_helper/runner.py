"""One-command scraper coordinator. AI review is performed separately in ChatGPT Work."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import deque

from . import cli as helper_cli
from .cli import PROJECT_ROOT, get_repository, load_environment, project_path, state_path, writer_lock
from .engine import MAX_BATCH_SIZE, Engine, State
from .inbox import InventoryInbox
from .efficiency import load_title_blacklist, load_title_review_list

FINISHED = {"Complete", "Complete with exceptions"}
DEFAULT_FETCH_WORKERS = 5
DEFAULT_ASSIGNMENT_WINDOW = 100
DEFAULT_SCRAPER_BATCH_SIZE = MAX_BATCH_SIZE


def print_help():
    print(
        """Usage: ./job-search-scraper <command>

Commands:
  start        Start or resume the automated scraper.
               - Resumes the newest unfinished local cycle if one exists.
               - Otherwise recovers an unfinished workbook cycle.
               - Otherwise starts a new full-company scan.
               - Writes to Google Sheets and requires no other sheet writers.

  sync         Sync saved SQLite inventories without fetching companies.
               Blocked saved work is retried by default.
  performance  Show timing/request/byte totals from the last run.

  cleanup-blacklist
      Set Job History "Added to Opportunities?" to No for current
      title-blacklist.txt matches.

  cleanup-titles
      Apply the same exclusions and report potentially good and uncertain
      titles using title-review-list.txt. Exclusions always win, including
      Staff, Principal, and Director. Existing No decisions stay No.
      Stop other sheet writers first. Use --dry-run for a read-only report.

  repair-careers-urls
      For blocked companies, discover a replacement ATS board from the careers
      page or an obvious same-site jobs/apply link, validate it by fetching
      jobs, update Official Careers URL, and set Scan State to Queued.
      Unvalidated candidate URLs go to Candidate Careers URL for manual review.
      Dry-run by default; use --apply --exclusive-writer to write changes.

  setup-evidence-tab
      Create or repair the Job Evidence tab used to store full descriptions
      outside Job History. Dry-run by default.

  preflight    Validate access and workbook headers; never change cells.
  status       Read local cycle status without creating or updating state.
  errors       Show recent per-company scraper errors from the local log.
  reviews      Export the saved pending review queue to a local file.
  auth         Obtain Google OAuth credentials; no spreadsheet writes.
  test         Run the offline unittest suite.
  demo         Run an isolated offline demonstration.

Options for start (batch size, sync interval and request interval also apply to sync):
  --retry-blocked / --no-retry-blocked
      Retry blocked saved work by default; start can also retry failed fetches.
      Use --no-retry-blocked to leave blocked work on manual-review hold.

  --browser-fallback
      If a direct public-board fetch is blocked/unsupported/failed, open the
      careers page in a local Chromium browser and try to scrape visible job
      postings. Requires optional Playwright setup. Browser failure is treated
      as incomplete/manual review, never as evidence of closure.

  --defer-sync
      Save full inventories in SQLite for a later ./job-search-scraper sync.
      Company/cycle control records synchronize at startup/end; jobs wait for sync.

  --fetch-workers N
      Run N fetch-only workers while this process remains the only Google
      Sheets writer. Allowed: 1-5. Default: 5.
      A returning worker takes its next local assignment even during a write.

  --assignment-window N
      Bound queued fetch assignments. Allowed: 1-100. Default: 100;
      effective minimum is the worker count. Completed results accumulate
      durably on disk and do not prevent workers taking new assignments.

  --batch-size N
      Sync up to N planned changes across companies per atomic Sheets write.
      Allowed: 1-200. Default: 200.

  --sync-interval SECONDS
      Upload a partly filled local batch after this interval, checked between
      company planning steps. Allowed: 1-3600. Default: 60. Full batches and
      the last batch upload immediately. Applies to start and sync.

  --sheet-request-interval SECONDS
      Minimum delay between Google Sheets requests made by the writer.
      Allowed: 0.5-5.0. Default: 1.1.

Screening on start (no AI calls):
  Existing title blacklist plus SaaS exclusions always win.
  title-review-list.txt highlights preferred roles; unmatched titles still
  go to AI review. Hardware/mixed products are preferred, not required.
  New jobs with clear base pay below $120,000, travel above 50%, or temporary/
  contract employment are saved as No with a reason. Unknowns stay for review.
  Any location/work arrangement is eligible. Existing review decisions stay.
  Supported public boards: Greenhouse, Lever, Ashby, Workday, iCIMS,
  ADP Workforce Now, Paylocity, and Taleo. Dayforce remains manual unless
  a supported board link is found.
  Detected ATS / Source is saved even for blocked/failed/partial scans.
  Start opens a terminal dashboard. Each worker keeps a persistent color-coded
  row with its current company. "Saved locally" means the worker finished and
  the durable queue accepted the inventory. The writer row is green and shows
  save progress, duration, locally processed count, queued local companies,
  pending sync plans, and confirmed new-job count. The Workers list records
  every handoff to the writer. The Jobs list records confirmed new Job History
  rows, clipping job entries to 20 characters with `...`.
  Changing a blocked company in Sheets back to Queued is recognized on
  startup and refreshes the local blocked retry list for that company.
  Restart after rule changes. Ctrl+C then start resumes the unfinished cycle;
  saved inventories resume from SQLite; unfinished fetches are refetched.
  Keep the whole .state directory until all saved work is synchronized.
  The local database holds inventories and frozen changes until Sheets confirms
  them. Failed companies retain work for the next sync unless
  --no-retry-blocked is used. Workers use the
  company list read at startup; uploads recheck current company controls.

  help         Show this command list.
  --help       Show this command list.
  -h           Show this command list.

Examples:
  ./job-search-scraper start
  ./job-search-scraper start --browser-fallback
  ./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200
  ./job-search-scraper start --defer-sync
  ./job-search-scraper sync
  ./job-search-scraper performance
  ./job-search-scraper cleanup-blacklist
  ./job-search-scraper errors
  ./job-search-scraper cleanup-blacklist --dry-run
  ./job-search-scraper cleanup-titles
  ./job-search-scraper cleanup-titles --dry-run
  ./job-search-scraper repair-careers-urls --dry-run
  ./job-search-scraper repair-careers-urls --apply --exclusive-writer
  ./job-search-scraper setup-evidence-tab --apply --exclusive-writer
"""
    )


def _started_at(cycle):
    return str(cycle.get("started_at") or cycle.get("Started At") or "")


def resolve_cycle(engine, state, repo):
    unfinished_local = [c for c in state.cycles() if c.get("status") not in FINISHED]
    if unfinished_local:
        chosen = max(unfinished_local, key=_started_at)
        return chosen["id"], "resuming saved unfinished cycle"
    unfinished_remote = [
        row for _, row in repo.read_columns("Scan Cycles", ["Cycle ID", "Cycle Status", "Started At"])
        if row.get("Cycle ID") and row.get("Cycle Status") not in FINISHED
    ]
    if unfinished_remote:
        chosen = max(unfinished_remote, key=_started_at)
        cycle = engine._recover(chosen["Cycle ID"])
        return cycle["id"], "recovering unfinished workbook cycle"
    return engine.start_cycle(company_ids=None), "starting new full scan"


def _load_environment():
    load_environment(PROJECT_ROOT / ".env")
    for variable, default in (
        ("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        ("GOOGLE_TOKEN_READ_FILE", ".secrets/token-readonly.json"),
        ("GOOGLE_TOKEN_WRITE_FILE", ".secrets/token-write.json"),
    ):
        os.environ[variable] = str(project_path(os.environ.get(variable, default)))


def run_start(fetch_workers=DEFAULT_FETCH_WORKERS, assignment_window=DEFAULT_ASSIGNMENT_WINDOW,
              batch_size=DEFAULT_SCRAPER_BATCH_SIZE, sheet_request_interval=1.1,
              defer_sync=False, sync_only=False, retry_blocked=True, sync_interval=60,
              browser_fallback=False):
    if not 1 <= sync_interval <= 3600:
        raise ValueError("Sync interval must be between 1 and 3600 seconds")
    if not 1 <= fetch_workers <= 5 or not 1 <= assignment_window <= 100:
        raise ValueError("Fetch workers must be 1-5 and assignment window 1-100")
    run_started = time.monotonic()
    print("Syncing saved inventories" if sync_only else "Starting job scraping", flush=True)
    if not 0.5 <= sheet_request_interval <= 5.0:
        raise ValueError("Sheet request interval must be between 0.5 and 5.0 seconds")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"Batch size must be between 1 and {MAX_BATCH_SIZE}")
    print(f"Configured: {fetch_workers} fetch worker(s), 1 Sheets writer, assignment window {max(assignment_window, fetch_workers)}.", flush=True)
    _load_environment()
    load_title_blacklist()
    load_title_review_list()
    database = state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with writer_lock(database.parent / "writer.lock"):
        repo = get_repository(write=True, interactive=False, min_request_interval=sheet_request_interval)
        repo.validate_schema()
        state = State(str(database))
        os.chmod(database, 0o600)
        state.purge_reviews()
        try:
            inbox = InventoryInbox(database.parent / "inventories.sqlite3", repo.spreadsheet_id)
        except BaseException:
            state.close()
            raise
        fetcher = None
        if browser_fallback:
            from .browser_scraper import with_browser_fallback
            from .ats import fetch_inventory
            fetcher = with_browser_fallback(fetch_inventory)
        engine = Engine(repo, state, dry_run=False, batch_size=batch_size, inbox=inbox,
                        **({"fetcher": fetcher} if fetcher else {}))
        try:
            if sync_only:
                cycle_ids = inbox.cycles(include_blocked=retry_blocked)
                if not cycle_ids:
                    print("No saved inventories to sync.")
                    return 0
            else:
                pending_cycles = inbox.cycles(include_blocked=retry_blocked)
                if pending_cycles:
                    cycle_ids = pending_cycles
                else:
                    cycle_id, _ = resolve_cycle(engine, state, repo)
                    cycle_ids = [cycle_id]
            for cycle_id in cycle_ids:
                engine.resume_local(cycle_id, fetch_workers=fetch_workers, assignment_window=assignment_window,
                                    sync_interval=sync_interval,
                                    sync_only=sync_only, defer_sync=defer_sync, retry_blocked=retry_blocked)
            final = engine.status(cycle_id)
            if defer_sync:
                print("Inventories saved locally. Run ./job-search-scraper sync to write the jobs to Sheets.", flush=True)
            print(
                f"Finished scrape {cycle_id}: {final['status']} | "
                f"needs_review_or_in_progress={final['pending_reviews']} | "
                f"manual_review={final['manual_review']}",
                flush=True,
            )
            return 0
        finally:
            performance = {**getattr(repo, "metrics", {}), **engine.performance,
                           "checkpoint_seconds": state.checkpoint_seconds + inbox.checkpoint_seconds,
                           "checkpoint_payload_bytes": state.checkpoint_bytes + inbox.payload_bytes,
                           "inventories_saved": inbox.saved,
                           "elapsed_seconds": time.monotonic() - run_started}
            metrics_path = database.parent / "scraper-performance.json"
            try:
                # Counts/timings only; no URLs, descriptions, request bodies or tokens.
                with metrics_path.open("w", encoding="utf-8") as stream:
                    json.dump(performance, stream, indent=2)
                metrics_path.chmod(0o600)
                print("Performance: " + json.dumps(performance, sort_keys=True), flush=True)
            finally:
                inbox.close()
                state.close()


def show_performance():
    path = state_path().parent / "scraper-performance.json"
    print(path.read_text() if path.exists() else "No performance measurements saved yet.")
    return 0


def show_errors(limit=25):
    path = project_path(".state/scraper-errors.jsonl")
    if not path.exists():
        print("No scraper error log found.")
        return 0
    rows = deque(maxlen=limit)
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"at": "", "company": "", "context": "", "error": line})
    if not rows:
        print("No scraper errors recorded.")
        return 0
    print(f"Recent scraper errors ({len(rows)} shown):")
    for row in rows:
        at = row.get("at", "")
        company = row.get("company", "") or row.get("company_id", "") or "Unknown company"
        context = row.get("context", "")
        error_type = row.get("error_type", "Error")
        error = str(row.get("error", "")).replace("\n", " ")
        if len(error) > 240:
            error = error[:237] + "..."
        print(f"- {at} | {company} | {context} | {error_type}: {error}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    aliases = {
        "--cleanup-blacklist": "cleanup-blacklist",
        "--cleanup-titles": "cleanup-titles",
        "--repair-careers-urls": "repair-careers-urls",
        "--preflight": "preflight",
        "--status": "status",
        "--errors": "errors",
        "--reviews": "reviews",
        "--auth": "auth",
        "--test": "test",
        "--demo": "demo",
    }
    if argv and argv[0] in aliases:
        argv[0] = aliases[argv[0]]
    if argv in ([], ["help"], ["--help"], ["-h"]):
        print_help()
        return 0
    if argv[0] == "performance":
        return show_performance()
    if argv[0] == "errors":
        return show_errors()
    delegated = {"cleanup-blacklist", "cleanup-titles", "repair-careers-urls", "setup-evidence-tab", "preflight", "status", "reviews", "auth", "test", "demo"}
    if argv[0] in delegated:
        if argv[0] in {"cleanup-blacklist", "cleanup-titles"} and "--dry-run" not in argv and "--apply" not in argv:
            argv = [*argv, "--apply", "--exclusive-writer"]
        return helper_cli.main(argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command")
    parser.add_argument("--defer-sync", action="store_true")
    parser.add_argument("--retry-blocked", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--browser-fallback", action="store_true")
    parser.add_argument("--fetch-workers", type=int, default=DEFAULT_FETCH_WORKERS)
    parser.add_argument("--assignment-window", type=int, default=DEFAULT_ASSIGNMENT_WINDOW)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_SCRAPER_BATCH_SIZE)
    parser.add_argument("--sheet-request-interval", type=float, default=1.1)
    parser.add_argument("--sync-interval", type=float, default=60)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print("Run ./job-search-scraper help for available commands.", file=sys.stderr)
        return 2
    if args.command not in {"start", "sync"}:
        print("ERROR: unknown command.", file=sys.stderr)
        print("Run ./job-search-scraper help for available commands.", file=sys.stderr)
        return 2
    if args.command == "sync" and args.defer_sync:
        print("ERROR: --defer-sync applies to start only.", file=sys.stderr)
        return 2
    try:
        return run_start(
            fetch_workers=args.fetch_workers,
            assignment_window=args.assignment_window,
            batch_size=args.batch_size,
            sheet_request_interval=args.sheet_request_interval,
            defer_sync=args.defer_sync, sync_only=args.command == "sync", retry_blocked=args.retry_blocked,
            sync_interval=args.sync_interval, browser_fallback=args.browser_fallback,
        )
    except KeyboardInterrupt:
        print("Stopped. Run ./job-search-scraper start to continue.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
