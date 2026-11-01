"""One-command scraper coordinator. AI review is performed separately in ChatGPT Work."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import uuid
from collections import Counter, deque
from contextlib import ExitStack, contextmanager

from . import cli as helper_cli
from .cli import PROJECT_ROOT, get_repository, load_environment, project_path, state_path, writer_lock, scraper_lock_name, storage_backend
from .engine import MAX_BATCH_SIZE, MAX_FETCH_WORKERS, Engine, State
from .inbox import InventoryInbox
from .efficiency import load_title_blacklist, load_title_review_list
from .review_queue import export_review_queues

FINISHED = {"Complete", "Complete with exceptions"}
DEFAULT_FETCH_WORKERS = 5
DEFAULT_ASSIGNMENT_WINDOW = 100
DEFAULT_SCRAPER_BATCH_SIZE = MAX_BATCH_SIZE


def print_help():
    print(
        """Usage: ./job-search-scraper <command>

Commands:
  start        Start a fresh scan of all currently active companies.
               - Rechecks companies completed or partial in an earlier scan.
               - Includes new companies from the startup company list.
               - Use start --resume to continue the latest scan instead.
               - SQLite: pulls Sheets once, publishes saved changes, then scrapes.
               - Publishes saved batches continuously while updates are pending.
               - No Sheets watcher runs after the command exits.
               - SQLite: a busy reviewer defers Sheets sync; scraping continues.
               - Renews both Google credentials automatically when either expires.
               - Opens Google sign-in if an expired/revoked grant needs authorization.

  sync         Sync saved SQLite inventories without fetching companies.
               Blocked saved work is retried by default.
  performance  Show timing/request/byte totals from the last run.

  cleanup-blacklist
      Set Job History "Added to Opportunities?" to No for current
      title-blacklist.txt matches.

  cleanup-titles
      Apply the same exclusions and report potentially good and uncertain
      titles using title-review-list.txt. Exclusions always win; seniority
      alone is not an exclusion. Existing No decisions stay No.
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
  review-queue Build read-only FIRST PASS and SECOND PASS review queues.
  auth         Renew both Google OAuth credentials; no spreadsheet writes.
               --write / --read-only renew just the selected credential.
  test         Run the offline unittest suite.
  demo         Run an isolated offline demonstration.

Options for start (batch size, sync interval and request interval also apply to sync):
  --resume
      Continue the latest scan using saved inventories and browser progress.
      Skip completed companies; retry partial results and unfinished fetches.
      Blocked/failed retries follow --retry-blocked. Never starts a new cycle.

  --retry-blocked / --no-retry-blocked
      Retry blocked saved work by default; start can also retry failed fetches.
      Use --no-retry-blocked to leave blocked work on manual-review hold.

  --browser-fallback / --no-browser-fallback
      Enabled by default. If a direct public-board fetch is blocked/unsupported/failed/partial, open the
      careers page in a local Chromium browser and try to scrape visible job
      postings. Requires optional Playwright setup. Browser failure is treated
      as incomplete/manual review, never as evidence of closure.

  --defer-sync
      Save full inventories in SQLite for a later ./job-search-scraper sync.
      With SQLite, this is local-only: no Google authentication, pull, or publish.
      With direct Sheets storage, company/cycle controls still synchronize.

  --fetch-workers N
      Run N fetch-only workers while this process remains the only Google
      Sheets writer. Allowed: 1-50. Default: 5.
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
      Also controls cycle-progress updates; final status saves immediately.
      With SQLite, saved changes are checked every 2 seconds and pending
      batches publish back to back. This interval bounds each publishing pass
      and retries held/error work; startup pulls once and exit drains changes.

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
  Restart after rule changes. Ctrl+C then start --resume continues the latest cycle;
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
  ./job-search-scraper start --resume
  ./job-search-scraper start --fetch-workers 5 --assignment-window 100 --batch-size 200
  ./job-search-scraper start --defer-sync
  ./job-search-scraper sync
  ./job-search-scraper performance
  ./job-search-scraper cleanup-blacklist
  ./job-search-scraper errors
  ./job-search-scraper cleanup-blacklist --dry-run
  ./job-search-scraper cleanup-titles
  ./job-search-scraper cleanup-titles --dry-run
  ./job-search-scraper review-queue --overwrite
  ./job-search-scraper repair-careers-urls --dry-run
  ./job-search-scraper repair-careers-urls --apply --exclusive-writer
  ./job-search-scraper setup-evidence-tab --apply --exclusive-writer
"""
    )


def _started_at(cycle):
    return str(cycle.get("started_at") or cycle.get("Started At") or "")


def resolve_cycle(engine, state, repo):
    """Resolve an explicit resume, never an older cycle or an implicit new scan."""
    from .scan_request import superseded_cycle_ids
    local = state.cycles()
    if hasattr(repo, "read_columns"):
        remote = [row for _, row in repo.read_columns(
            "Scan Cycles", ["Cycle ID", "Cycle Status", "Started At", "Notes"])]
    else:
        remote = repo.read("Scan Cycles")
    superseded = superseded_cycle_ids(local + remote)
    candidates = {row["Cycle ID"]: row for row in remote if row.get("Cycle ID")}
    # Local checkpoints include the last acknowledged company results.
    candidates.update({cycle["id"]: cycle for cycle in local})
    candidates = {cid: cycle for cid, cycle in candidates.items() if cid not in superseded}
    if not candidates:
        raise ValueError("No saved scan to resume. Run start without --resume for a fresh scan.")
    cycle_id, chosen = max(reversed(list(candidates.items())), key=lambda pair: _started_at(pair[1]))
    if (chosen.get("status") or chosen.get("Cycle Status")) == "Complete":
        raise ValueError("The latest scan is already complete. Run start without --resume for a fresh scan.")
    if "id" not in chosen:
        engine._recover(cycle_id)
    return cycle_id, "resuming latest scan; completed companies are skipped"


def select_start_cycle(engine, state, repo, database, *, resume=False):
    if resume:
        if (database.parent / "next-scan.json").exists():
            raise ValueError("A fresh next-scan.json request is pending. Run start without --resume to use it.")
        cycle_id, action = resolve_cycle(engine, state, repo)
        print(f"{action}: {cycle_id}.", flush=True)
        return cycle_id
    from .scan_request import requested_scan
    cycle_id = requested_scan(engine, state, database)
    if cycle_id is None:
        cycle_id = engine.start_cycle(new_scan_request={
            "mode": "fresh-full-scan", "request_id": "start-" + uuid.uuid4().hex,
        })
        print(f"Fresh full scan: {cycle_id}. All currently active companies are queued; "
              "previous checkpoints are retained.", flush=True)
    return cycle_id


def active_inbox_cycles(inbox, state, include_blocked=True):
    """Return saved work only for cycles that have not already finished.

    Completed cycles deliberately keep blocked inventories for an explicit
    sync retry.  They must not turn a normal ``start`` into a replay of old
    cycle IDs, otherwise fresh scan cycles are never created.
    """
    from .scan_request import superseded_cycle_ids
    local = state.cycles()
    statuses = {cycle.get("id"): cycle.get("status") for cycle in local}
    superseded = superseded_cycle_ids(local)
    return [
        cycle_id for cycle_id in inbox.cycles(include_blocked=include_blocked)
        if statuses.get(cycle_id) not in FINISHED and cycle_id not in superseded
    ]


def _load_environment():
    load_environment(PROJECT_ROOT / ".env")
    for variable, default in (
        ("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        ("GOOGLE_TOKEN_READ_FILE", ".secrets/token-readonly.json"),
        ("GOOGLE_TOKEN_WRITE_FILE", ".secrets/token-write.json"),
    ):
        os.environ[variable] = str(project_path(os.environ.get(variable, default)))


def _refresh_review_queue(repo, database):
    result = export_review_queues(
        repo, database.parent / "review-queue", overwrite=True,
        inventory_database=database.parent / "inventories.sqlite3"
    )
    print(
        "Review queue: "
        f"first_pass={result['first_pass']} | second_pass={result['second_pass']} | "
        f"filtered={result['deterministic_filtered']} | "
        f"title_audit_overlap={result['title_filter_audit_overlap']} | "
        f"filtered_only={result['deterministic_filtered'] - result['title_filter_audit_overlap']} | "
        f"bands={json.dumps(result['band_counts'], sort_keys=True)}",
        flush=True,
    )
    return result


def _print_run_status(final):
    stages = Counter(item['stage'] for item in final['companies'].values())
    print(f"Scraper invocation finished {final['cycle_id']}: cycle_status={final['status']} | "
          f"company_stages={json.dumps(dict(stages), sort_keys=True)}", flush=True)
    print(f"Job History (all cycles): needs_review_or_in_progress={final['pending_reviews']} | "
          f"manual_review={final['manual_review']}", flush=True)
    if stages['queued'] or stages['inventory']:
        print('Cycle still has unfinished scraping or saved work to process. '
              'Use start --resume to continue it, or start for a fresh full scan. '
              'Job reviews run independently of scrape completion.', flush=True)
    elif final['status'] == 'Complete with exceptions':
        print('Scan pass finished with incomplete or blocked companies. '
              'Their Last Checked dates advance only after a complete inventory. '
              'The next start will scan all currently active companies again.', flush=True)
    else:
        print('The next start will scan all currently active companies again.', flush=True)


def _print_run_summary(counts):
    if not counts:
        return
    print("\nRun summary:", flush=True)
    print(f"New jobs downloaded (new Job History rows): {counts['new_jobs']}", flush=True)
    print(f"Companies successfully scanned: {counts['successful']}", flush=True)
    print(f"Companies partially scanned: {counts['partial']}", flush=True)
    skipped = counts['skipped'] or ''
    print(f"Companies skipped: {skipped}", flush=True)
    if counts['failed']:
        print(f"Companies blocked or failed: {counts['failed']}", flush=True)
    if counts['pending']:
        print(f"Companies with saved work awaiting processing: {counts['pending']}", flush=True)


def _save_performance(database, sources, run_started):
    performance = {key: value for source in sources for key, value in source.items()}
    performance['elapsed_seconds'] = time.monotonic() - run_started
    metrics_path = database.parent / 'scraper-performance.json'
    with metrics_path.open('w', encoding='utf-8') as stream:
        json.dump(performance, stream, indent=2)
    metrics_path.chmod(0o600)
    print('Performance: ' + json.dumps(performance, sort_keys=True), flush=True)


@contextmanager
def _review_queue_lifecycle(repo, database):
    """Refresh after every exit, without delaying the scraper's first fetch."""
    try:
        yield
    except BaseException:
        try:
            _refresh_review_queue(repo, database)
        except Exception as exc:
            print(f"WARNING: final review queue refresh failed ({type(exc).__name__}); previous files retained where possible.", file=sys.stderr)
        raise
    else:
        _refresh_review_queue(repo, database)


def run_start(fetch_workers=DEFAULT_FETCH_WORKERS, assignment_window=DEFAULT_ASSIGNMENT_WINDOW,
              batch_size=DEFAULT_SCRAPER_BATCH_SIZE, sheet_request_interval=1.1,
              defer_sync=False, sync_only=False, retry_blocked=True, sync_interval=60,
              browser_fallback=True, resume=False):
    if not 1 <= sync_interval <= 3600:
        raise ValueError("Sync interval must be between 1 and 3600 seconds")
    if not 1 <= fetch_workers <= MAX_FETCH_WORKERS or not 1 <= assignment_window <= 100:
        raise ValueError(f"Fetch workers must be 1-{MAX_FETCH_WORKERS} and assignment window 1-100")
    if sync_only and resume:
        raise ValueError("--resume applies to start only.")
    run_started = time.monotonic()
    print("Syncing saved inventories" if sync_only else "Starting job scraping", flush=True)
    if not 0.5 <= sheet_request_interval <= 5.0:
        raise ValueError("Sheet request interval must be between 0.5 and 5.0 seconds")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"Batch size must be between 1 and {MAX_BATCH_SIZE}")
    print(f"Configured: {fetch_workers} fetch worker(s), assignment window {max(assignment_window, fetch_workers)}.", flush=True)
    _load_environment()
    destination = ("local SQLite writer; Sheets sync is local-only/deferred" if defer_sync else
                   "local SQLite writer; Sheets sync belongs to this run") if storage_backend() == "sqlite" else "Sheets writer"
    print(f"Storage: 1 {destination}.", flush=True)
    load_title_blacklist()
    load_title_review_list()
    database = state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with writer_lock(database.parent / scraper_lock_name()), ExitStack() as resources:
        repo = get_repository(write=True, interactive=True, renew_both=True,
                              min_request_interval=sheet_request_interval)
        repo.validate_schema()
        performance = {}
        performance_sources = [performance]
        run_counts = Counter()
        # Registered first to print after final Sheets drain and performance.
        resources.callback(_print_run_summary, run_counts)
        # Registered before sync so queue export and Sheets drain are included.
        resources.callback(_save_performance, database, performance_sources, run_started)
        if getattr(repo, 'is_local', False) is True and not defer_sync:
            from .run_sync import run_scoped_sync
            sync = resources.enter_context(run_scoped_sync(repo, database, interval=sync_interval,
                                                           request_interval=sheet_request_interval))
            if isinstance(sync.totals, dict):
                performance_sources.append(sync.totals)
        with _review_queue_lifecycle(repo, database):
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
                from .closed_jobs import stage_closed_pending
                while True:
                    closed = stage_closed_pending(repo)
                    if closed["changed"]:
                        destination = "saved locally for verified Sheet sync" if getattr(repo, "is_local", False) else "saved to Sheets"
                        print(f"Closed-job cleanup: {closed['changed']} Pending choices changed to No; {destination}.", flush=True)
                    if not closed["remaining"] or not closed["changed"]:
                        break
                manual = engine.sync_manual_opportunities()
                if manual["added"]:
                    print(f"Added {manual['added']} manually selected job(s) to Opportunities.", flush=True)
                if manual["skipped"]:
                    print(f"Skipped {manual['skipped']} manually selected job(s) missing a company, title, or valid URL.", flush=True)
                if sync_only:
                    cycle_ids = inbox.cycles(include_blocked=retry_blocked)
                    if not cycle_ids:
                        print("No saved inventories to sync.")
                        return 0
                else:
                    cycle_ids = [select_start_cycle(engine, state, repo, database, resume=resume)]
                for cycle_id in cycle_ids:
                    result = engine.resume_local(cycle_id, fetch_workers=fetch_workers, assignment_window=assignment_window,
                                        sync_interval=sync_interval,
                                        sync_only=sync_only, defer_sync=defer_sync, retry_blocked=retry_blocked,
                                        retry_partial=resume)
                    run_counts.update(result["run_counts"])
                final = engine.status(cycle_id)
                if defer_sync:
                    print("Inventories saved locally. Run ./job-search-scraper sync to write the jobs to Sheets.", flush=True)
                _print_run_status(final)
                return 0
            finally:
                performance.update({**getattr(repo, "metrics", {}), **engine.performance,
                               "checkpoint_seconds": state.checkpoint_seconds + inbox.checkpoint_seconds,
                               "checkpoint_payload_bytes": state.checkpoint_bytes + inbox.payload_bytes,
                               "inventories_saved": inbox.saved})
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
    if argv and argv[0] == 'storage':
        from .sync_cli import main as storage_main
        return storage_main(argv[1:])
    aliases = {
        "--cleanup-blacklist": "cleanup-blacklist",
        "--cleanup-titles": "cleanup-titles",
        "--repair-careers-urls": "repair-careers-urls",
        "--preflight": "preflight",
        "--status": "status",
        "--errors": "errors",
        "--reviews": "reviews",
        "--review-queue": "review-queue",
        "--auth": "auth",
        "--test": "test",
        "--demo": "demo",
    }
    if argv and argv[0] in aliases:
        argv[0] = aliases[argv[0]]
    if argv in ([], ["help"], ["--help"], ["-h"]) or (
        argv and argv[0] in {"start", "sync"} and any(flag in argv[1:] for flag in ("--help", "-h"))
    ):
        print_help()
        return 0
    if argv[0] == "performance":
        return show_performance()
    if argv[0] == "errors":
        return show_errors()
    delegated = {"cleanup-blacklist", "cleanup-titles", "repair-careers-urls", "setup-evidence-tab", "preflight", "status", "reviews", "review-queue", "auth", "test", "demo"}
    if argv[0] in delegated:
        if argv[0] in {"cleanup-blacklist", "cleanup-titles"} and "--dry-run" not in argv and "--apply" not in argv:
            argv = [*argv, "--apply", "--exclusive-writer"]
        return helper_cli.main(argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command")
    parser.add_argument("--defer-sync", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retry-blocked", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--browser-fallback", action=argparse.BooleanOptionalAction, default=True)
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
    if args.command == "sync" and (args.defer_sync or args.resume):
        print("ERROR: --defer-sync and --resume apply to start only.", file=sys.stderr)
        return 2
    try:
        return run_start(
            fetch_workers=args.fetch_workers,
            assignment_window=args.assignment_window,
            batch_size=args.batch_size,
            sheet_request_interval=args.sheet_request_interval,
            defer_sync=args.defer_sync, sync_only=args.command == "sync", retry_blocked=args.retry_blocked,
            sync_interval=args.sync_interval, browser_fallback=args.browser_fallback, resume=args.resume,
        )
    except KeyboardInterrupt:
        print("Stopped. Run ./job-search-helper start --resume to continue this scan; start without --resume begins a fresh scan.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
