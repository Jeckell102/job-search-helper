"""Public scrape-to-FIRST-PASS workflow and its internal scan worker."""
from __future__ import annotations

import argparse
import hashlib
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
DEFAULT_PARTIAL_RETRIES = 1


def print_help():
    print(
        """Usage: ./job-search-scraper <command>

Commands:
  start        Start a fresh scan of all currently active companies.
               - After completed scraping and verified Sheets sync, automatically
                 read AI Prompt in Google Drive and run FIRST PASS through Codex
                 using GPT-5.6 Luna with medium reasoning.
               - Rechecks companies completed or partial in an earlier scan.
               - Includes new companies from the startup company list.
               - Use start --resume to continue the saved scan or FIRST PASS.
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
  company-queue-status
               Read a pending one-company request, its age, blockers, and safe
               recovery guidance without changing it. Use --local-only when
               Sheets read access is unavailable.
  recover-interrupted-cycle
               Explicitly pause one exact inactive cycle for recovery. Requires
               --cycle-id, --reason, and --apply; preserves its checkpoint.
  recover-interrupted-cycle-status
               Prove whether one exact inactive cycle can be paused safely.
               Read-only: applies no recovery and changes no workbook data.
  errors       Show recent per-company scraper errors from the local log.
  reviews      Export the saved pending review queue to a local file.
  review-queue Build read-only FIRST PASS and SECOND PASS review queues.
  auth         Renew both Google OAuth credentials; no spreadsheet writes.
               --write / --read-only renew just the selected credential.
  test         Run the full offline pytest suite (requires the test extra).
  demo         Run an isolated offline demonstration.

Options for start (batch size, sync interval and request interval also apply to sync):
  --resume
      Continue the latest scan using saved inventories and browser progress.
      Skip completed companies; retry partial results and unfinished fetches.
      Blocked/failed retries follow --retry-blocked. Never starts a new cycle.

  --cycle-id CYCLE_ID
      Recover only the exact saved cycle. Applies to sync only and requires
      one or more repeatable --company-id values.

  --company-id COMPANY_ID
      Select one Company from --cycle-id for exact recovery. Repeatable;
      requires 1-5 unique IDs. Never broadens to another Company or cycle.

  --retry-blocked / --no-retry-blocked
      Retry blocked saved work by default; start can also retry failed fetches.
      Use --no-retry-blocked to leave blocked work on manual-review hold.

  --partial-retries N
      After the first pass, retry incomplete companies before finishing.
      Allowed: 0-2. Default: 1. Completed and blocked companies are skipped.
      Jobs already saved remain available; incomplete coverage stays flagged.

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
      When no company assignments remain, idle workers help download remaining
      job descriptions on supported public job boards. Website request limits
      still apply; browser sessions stay with their original worker.

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
      updates gather up to 100 rows or 15 seconds (capped by this interval).
      Full batches publish back to back. The interval also bounds each publishing
      pass and retries held/error work; startup pulls once and exit drains immediately.

  --sheet-request-interval SECONDS
      Minimum delay between Google Sheets requests made by the writer.
      Allowed: 0.5-5.0. Default: 1.1.

Deterministic screening during scraping (before the automatic AI review):
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


def company_only_queue_status(engine, state, database, *, observed_at=None, include_remote=True):
    """Expose scoped-request queue state without changing the durable request."""
    from .scan_request import company_only_queue_status as read_status
    return read_status(engine, state, database, observed_at=observed_at,
                       include_remote=include_remote)


def show_company_only_queue_status(*, database=None, repo=None, local_only=False, observed_at=None):
    """Print the non-mutating scoped-request status and recovery boundary."""
    database = database or state_path()
    if not (database.parent / 'next-scan.json').exists():
        print('Company-only queue: no pending request.')
        return 0
    state = State(str(database), readonly=True) if database.is_file() else State()
    try:
        if repo is None and not local_only:
            _load_environment()
            repo = get_repository(write=False, interactive=False)
        if repo is None:
            from .repository import MemoryRepository
            repo = MemoryRepository({'Scan Cycles': []})
        status = company_only_queue_status(
            Engine(repo, state), state, database, observed_at=observed_at,
            include_remote=not local_only,
        )
    finally:
        state.close()
    if status is None:
        print('Company-only queue: no pending company-only request.')
        return 0
    print(json.dumps(dict(status, visibility='local-only' if local_only else 'local-and-workbook'),
                     indent=2, sort_keys=True))
    return 0


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


def validate_exact_sync_cycle(database, cycle_id, *, retry_blocked=True):
    """Prove one exact saved cycle is selectable before any sync side effect."""
    if (not isinstance(cycle_id, str) or cycle_id != cycle_id.strip()
            or not cycle_id or len(cycle_id) > 128 or any(char.isspace() for char in cycle_id)):
        raise ValueError('--cycle-id must be one exact saved cycle ID without whitespace.')
    state = State(str(database), readonly=True)
    try:
        cycles = state.cycles()
        cycle = state.cycle(cycle_id)
        if cycle is None:
            raise ValueError('Exact sync cycle checkpoint is missing; no sync was started.')
        from .scan_request import superseded_cycle_ids
        if (cycle.get('status') in FINISHED
                or cycle_id in superseded_cycle_ids(cycles)):
            raise ValueError(
                'Exact sync cycle is finished or superseded, not an active blocker; '
                'historical inventory was not replayed.')
    finally:
        state.close()
    inventory_database = database.parent / 'inventories.sqlite3'
    if not inventory_database.is_file():
        raise ValueError('Saved-inventory database is missing; no sync was started.')
    uri = inventory_database.resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as connection:
        sql = 'SELECT count(*) FROM inventories WHERE cycle=?'
        parameters = [cycle_id]
        if not retry_blocked:
            sql += ' AND blocked=0'
        count = connection.execute(sql, parameters).fetchone()[0]
    if not count:
        qualifier = 'eligible ' if not retry_blocked else ''
        raise ValueError(f'Exact sync cycle has no {qualifier}saved inventories; no sync was started.')
    return cycle_id


def selected_sync_cycles(inbox, *, cycle_id=None, retry_blocked=True):
    """Select either one prevalidated cycle or the legacy all-saved-work set."""
    available = inbox.cycles(include_blocked=retry_blocked)
    if cycle_id is None:
        return available
    if cycle_id not in available:
        raise ValueError('Exact sync cycle changed after preflight; no inventory was processed.')
    return [cycle_id]


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
        f"bands={json.dumps(result['band_counts'], sort_keys=True)} | "
        f"build_seconds={result.get('build_seconds', 0):.2f} | "
        f"calculations={json.dumps(result.get('calculations', {}), sort_keys=True)}",
        flush=True,
    )
    return result


def _print_run_status(final):
    stages = Counter(item['stage'] for item in final['companies'].values())
    print(f"Scraper invocation finished {final['cycle_id']}: cycle_status={final['status']} | "
          f"company_stages={json.dumps(dict(stages), sort_keys=True)}", flush=True)
    print(f"Job History (all cycles): needs_review_or_in_progress={final['pending_reviews']} | "
          f"manual_review={final['manual_review']}", flush=True)
    incomplete = stages['partial'] + stages['blocked'] + stages['failed'] + stages['unsupported']
    if incomplete:
        print(f'Coverage incomplete for {incomplete} companies; existing jobs may still be missing. '
              'See company Scan State and Last Scan Result. '
              'Use ./job-search-scraper start --resume to retry unfinished companies.', flush=True)
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


def _format_elapsed(seconds):
    """Format a wall-clock duration compactly for the completion summary."""
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _print_run_summary(counts, *, elapsed_seconds=None):
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
    if elapsed_seconds is not None:
        print(f"Total run time: {_format_elapsed(elapsed_seconds)}", flush=True)


def _run_scan_with_retries(engine, cycle_id, *, partial_retries=DEFAULT_PARTIAL_RETRIES, **options):
    """Retry only partial inventories, retaining keyed jobs and unique run counts."""
    result = engine.resume_local(cycle_id, **options)
    attempted = set(result['attempted_company_ids'])
    new_jobs = result['run_counts']['new_jobs']
    if not options.get('sync_only') and not options.get('defer_sync'):
        for retry in range(partial_retries):
            cycle = engine.state.cycle(cycle_id)
            incomplete = {cid for cid, item in cycle['companies'].items()
                          if cid in attempted and item['stage'] == 'partial'}
            if not incomplete:
                break
            print(f"Retrying {len(incomplete)} incomplete company inventories "
                  f"(retry {retry + 1}/{partial_retries}); completed companies are skipped.", flush=True)
            retry_options = {**options, 'retry_partial': True, 'retry_blocked': False,
                             'retry_company_ids': incomplete}
            result = engine.resume_local(cycle_id, **retry_options)
            attempted.update(result['attempted_company_ids'])
            new_jobs += result['run_counts']['new_jobs']
    cycle = engine.state.cycle(cycle_id)
    stages = [cycle['companies'][cid]['stage'] for cid in attempted]
    result['run_counts'] = {
        'new_jobs': new_jobs,
        'successful': stages.count('complete'),
        'partial': stages.count('partial'),
        'skipped': len(set(cycle['companies']) - attempted),
        'failed': sum(stage in {'blocked', 'failed', 'unsupported'} for stage in stages),
        'pending': sum(stage in {'queued', 'inventory'} for stage in stages),
    }
    result['attempted_company_ids'] = sorted(attempted)
    return result


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
              browser_fallback=True, resume=False, partial_retries=DEFAULT_PARTIAL_RETRIES,
              sync_cycle_id=None, sync_company_ids=None):
    if sync_cycle_id is not None:
        if not sync_only:
            raise ValueError('--cycle-id applies to sync only.')
        if not isinstance(sync_cycle_id, str) or not sync_cycle_id.strip():
            raise ValueError('Use a non-empty exact --cycle-id for sync.')
        sync_cycle_id = sync_cycle_id.strip()
    exact_sync = sync_only and sync_cycle_id is not None
    if exact_sync and sync_company_ids is not None:
        if not isinstance(sync_company_ids, (list, tuple)):
            raise ValueError('Exact --cycle-id sync requires one or more --company-id values.')
        sync_company_ids = [str(value).strip() for value in sync_company_ids]
        if (not sync_company_ids or len(sync_company_ids) > 5
                or any(not value for value in sync_company_ids)
                or len(sync_company_ids) != len(set(sync_company_ids))):
            raise ValueError('Exact --company-id selection must be unique and bounded to 1-5.')
    elif sync_company_ids:
        raise ValueError('--company-id applies only with sync --cycle-id.')
    if type(partial_retries) is not int or not 0 <= partial_retries <= 2:
        raise ValueError('Partial retries must be between 0 and 2')
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
    if exact_sync and sync_company_ids is not None:
        # The recovery API owns the normal lock. Dependencies are deliberately
        # built by its factory only after that acquisition.
        from .exact_cycle_recovery import recover_exact_cycle_with_factory
        from .cli import get_remote_repository, job_database_path
        from .sheet_profile import profile_schemas
        from .sqlite_repository import SQLiteRepository

        @contextmanager
        def exact_dependencies():
            spreadsheet_id = InventoryInbox.destination_id(
                database.parent / 'inventories.sqlite3')
            # Exact compact recovery owns the normal scraper lock and needs a
            # writable connection for its local apply/readback journal.  It
            # still never starts the global Sheets synchronizer or discovers
            # unrelated dirty work.
            local = SQLiteRepository(job_database_path(), spreadsheet_id, readonly=False)
            state = inbox = None
            try:
                schemas = profile_schemas(local.get_meta('sheets_profile'))
                state = State(str(database))
                inbox = InventoryInbox(
                    database.parent / 'inventories.sqlite3', spreadsheet_id)
                cycle = state.cycle(sync_cycle_id)
                if (not isinstance(cycle, dict) or cycle.get('id') != sync_cycle_id
                        or cycle.get('status') in FINISHED):
                    raise ValueError('Exact sync cycle is missing, finished, or superseded.')
                for company_id in sync_company_ids:
                    item = cycle.get('companies', {}).get(company_id)
                    saved = inbox.get(sync_cycle_id, company_id)
                    planned = inbox.plan(sync_cycle_id, company_id)
                    if not isinstance(item, dict) or saved is None or saved[1]:
                        raise ValueError('Exact selected Company is missing or blocked.')
                    stage = item.get('stage')
                    if not (stage == 'queued'
                            or (stage == 'inventory' and planned is not None)
                            or (stage in {'complete', 'partial'} and planned is not None)):
                        raise ValueError(
                            'Exact selected Company has no recoverable State/plan combination.')
                from .integration_release import assert_release_settled
                assert_release_settled(database.parent)
                remote = get_remote_repository(
                    write=True, interactive=True, renew_both=True,
                    min_request_interval=sheet_request_interval,
                    schemas=schemas, evidence_archives=False)
                yield Engine(
                    local, state, inbox=inbox,
                    error_log_path=database.parent / 'errors.jsonl'), remote
            finally:
                if inbox is not None:
                    inbox.close()
                if state is not None:
                    state.close()
                local.close()

        report = recover_exact_cycle_with_factory(
            database, exact_dependencies, sync_cycle_id, sync_company_ids)
        print('Exact cycle recovery: ' + json.dumps(report, sort_keys=True), flush=True)
        return 0
    with writer_lock(database.parent / scraper_lock_name()), ExitStack() as resources:
        # Activation uses this same lock. A durable nonterminal release journal
        # therefore blocks the real scraper boundary after an interrupted install.
        from .integration_release import assert_release_settled
        assert_release_settled(database.parent)
        if exact_sync:
            # A legacy direct call without an explicit Company selection owns
            # no global sync side effects and remains conservatively held.
            inventory_path = database.parent / 'inventories.sqlite3'
            if not InventoryInbox.has_unblocked_inventory(
                    inventory_path, sync_cycle_id):
                print(f'No saved inventory for exact cycle {sync_cycle_id}.')
                return 0
            report = {
                'cycle_id': sync_cycle_id,
                'status': 'HELD_NO_EXACT_PLANNER',
                'message': ('Selected-plan publishing requires explicit Company IDs; '
                            'global repository and Sheets sync are disabled for this '
                            'legacy named recovery. No inventory, workbook, review, '
                            'or coordinator changes were applied.'),
            }
            print('Exact cycle recovery held: '
                  + json.dumps(report, sort_keys=True), flush=True)
            return 0
        repo = get_repository(write=True, interactive=True, renew_both=True,
                              min_request_interval=sheet_request_interval)
        repo.validate_schema()
        performance = {}
        performance_sources = [performance]
        run_counts = Counter()
        # Registered first to print after final Sheets drain and performance.
        resources.callback(lambda: _print_run_summary(
            run_counts, elapsed_seconds=time.monotonic() - run_started))
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
                if not sync_only and getattr(repo, 'is_local', False) is True:
                    # This writer lock is also the bridge's standalone boundary,
                    # so admission cannot race a Company-only request write.
                    from .company_events import CompanyEventBridge
                    bridge_results = CompanyEventBridge(repo, database.parent).process_pending(
                        writer_lock_held=True,
                    )
                    if bridge_results:
                        print(
                            f"Company changes: safely handled {len(bridge_results)} queued change(s).",
                            flush=True,
                        )
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
                    cycle_ids = selected_sync_cycles(
                        inbox, cycle_id=sync_cycle_id, retry_blocked=retry_blocked)
                    if not cycle_ids:
                        print("No saved inventories to sync.")
                        return 0
                else:
                    cycle_ids = [select_start_cycle(engine, state, repo, database, resume=resume)]
                for cycle_id in cycle_ids:
                    result = _run_scan_with_retries(engine, cycle_id, partial_retries=partial_retries,
                                        fetch_workers=fetch_workers, assignment_window=assignment_window,
                                        sync_interval=sync_interval,
                                        sync_only=sync_only, defer_sync=defer_sync, retry_blocked=retry_blocked,
                                        retry_partial=resume)
                    run_counts.update(result["run_counts"])
                    if getattr(repo, 'is_local', False) is True:
                        # Record bounded facts only; coordinator delivery is a
                        # separate held-only path and cannot start a worker here.
                        from .scrape_outcome_producer import record_cycle_outcomes
                        cycle = state.cycle(cycle_id)
                        receipts = record_cycle_outcomes(
                            repo, cycle, engine._company_rows(),
                            storage_confirmed=not defer_sync and repo.status()['pending_cells'] == 0,
                        )
                        if receipts:
                            print(f"Scrape outcomes: recorded {len(receipts)} bounded result(s) for safe follow-up.", flush=True)
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


def interrupted_cycle_recovery_status(engine, state, database, cycle_id):
    """Return the full no-write recovery gate used by status and apply."""
    assessment = engine.assess_interrupted_cycle_recovery(cycle_id)
    from .scan_request import _unfinished_cycle_ids
    blocking = sorted(_unfinished_cycle_ids(engine, state))
    inventory_database = database.parent / 'inventories.sqlite3'
    if not inventory_database.is_file():
        raise ValueError('Saved-inventory database is missing; recovery safety cannot be proven.')
    placeholders = ','.join('?' for _ in blocking)
    uri = inventory_database.resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as connection:
        if blocking:
            saved_inventories = connection.execute(
                f'SELECT count(*) FROM inventories WHERE cycle IN ({placeholders})', blocking).fetchone()[0]
            saved_plans = connection.execute(
                f'SELECT count(*) FROM sync_plans WHERE cycle IN ({placeholders})', blocking).fetchone()[0]
            partial_plans = connection.execute(
                f'SELECT count(*) FROM sync_plans WHERE cycle IN ({placeholders}) AND cursor > 0', blocking).fetchone()[0]
        else:
            saved_inventories = saved_plans = partial_plans = 0
    assessment = dict(assessment)
    assessment.pop('paused_company_ids', None)
    exact_cycle_passed = assessment.pop('eligible')
    blocker_digest = hashlib.sha256(
        '\n'.join(blocking).encode('utf-8')).hexdigest()
    safe = bool(exact_cycle_passed and blocking == [assessment['cycle_id']]
                and not saved_inventories and not saved_plans)
    if saved_inventories or saved_plans:
        state_name = 'SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED'
    elif len(blocking) != 1 or blocking != [assessment['cycle_id']]:
        state_name = 'MULTI_CYCLE_RECONCILIATION_REQUIRED'
    elif not exact_cycle_passed:
        state_name = 'EXACT_CYCLE_RECONCILIATION_REQUIRED'
    else:
        state_name = 'READY_FOR_OWNER_REVIEW'
    assessment.update({
        'eligible': safe,
        'exact_cycle_assessment_passed': exact_cycle_passed,
        'state': state_name,
        'blocking_cycle_count': len(blocking),
        'blocking_cycle_ids_sha256': blocker_digest,
        'saved_inventory_count': saved_inventories,
        'saved_plan_count': saved_plans,
        'partially_applied_plan_count': partial_plans,
    })
    assessment['read_only'] = True
    assessment['next_action'] = (
        'Publish or explicitly reconcile every saved inventory and plan before any cycle pause.'
        if saved_inventories or saved_plans else
        'Reconcile all unfinished cycles before pausing any one cycle.'
        if len(blocking) != 1 or blocking != [assessment['cycle_id']] else
        'Owner-review this exact cycle, count and scope digest. Apply recovery only with '
        'the guarded command and a written reason; never delete locks.'
    )
    return assessment


def pause_interrupted_cycle(cycle_id, reason, *, database=None):
    """Run an explicit recovery pause through the normal writer boundary."""
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('Use an exact --cycle-id for interrupted-cycle recovery.')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Use a written --reason for interrupted-cycle recovery.')
    _load_environment()
    database = database or state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with writer_lock(database.parent / scraper_lock_name()):
        from .integration_release import assert_release_settled
        assert_release_settled(database.parent)
        repo = get_repository(write=True, interactive=True, renew_both=True)
        repo.validate_schema()
        state = State(str(database))
        try:
            engine = Engine(repo, state, dry_run=False)
            if getattr(repo, 'is_local', False) is True:
                from .run_sync import run_scoped_sync
                # Finish startup intake/publication and stop its worker before
                # the final global gate. No synchronizer may race the pause.
                with run_scoped_sync(repo, database):
                    pass
            assessment = interrupted_cycle_recovery_status(engine, state, database, cycle_id)
            if not assessment['eligible']:
                raise ValueError(
                    'Interrupted-cycle recovery refused: '
                    f"state={assessment['state']}; "
                    f"blocking_cycles={assessment['blocking_cycle_count']}; "
                    f"saved_inventories={assessment['saved_inventory_count']}; "
                    f"saved_plans={assessment['saved_plan_count']}; "
                    f"partially_applied_plans={assessment['partially_applied_plan_count']}.")
            result = engine.pause_interrupted_cycle(cycle_id, reason=reason)
            if getattr(repo, 'is_local', False) is True:
                # Publish the already-guarded local pause only after the
                # mutation is complete; this worker is also stopped on exit.
                with run_scoped_sync(repo, database):
                    pass
            print('Interrupted cycle paused safely: ' + json.dumps(result, sort_keys=True), flush=True)
            return result
        finally:
            state.close()


def show_interrupted_cycle_recovery_status(cycle_id, *, database=None, repo=None):
    """Print the exact no-write preflight used by interrupted-cycle recovery."""
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('Use an exact --cycle-id for interrupted-cycle recovery status.')
    _load_environment()
    database = database or state_path()
    from .integration_release import assert_release_settled
    assert_release_settled(database.parent)
    repo = repo or get_repository(write=False, interactive=False)
    repo.validate_schema()
    state = State(str(database), readonly=True)
    try:
        engine = Engine(repo, state, dry_run=False)
        assessment = interrupted_cycle_recovery_status(engine, state, database, cycle_id)
    finally:
        state.close()
    print(json.dumps(assessment, indent=2, sort_keys=True))
    return assessment


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


def scrape_main(argv=None):
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
    if argv[0] == 'company-queue-status':
        parser = argparse.ArgumentParser(prog='./job-search-scraper company-queue-status')
        parser.add_argument('--local-only', action='store_true')
        try:
            status_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        try:
            return show_company_only_queue_status(local_only=status_args.local_only)
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'recover-interrupted-cycle':
        parser = argparse.ArgumentParser(prog='./job-search-scraper recover-interrupted-cycle')
        parser.add_argument('--cycle-id', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--apply', action='store_true')
        try:
            recovery_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        if not recovery_args.apply:
            print('ERROR: recovery pause changes only the named cycle; rerun with --apply after reviewing the ID and reason.', file=sys.stderr)
            return 2
        try:
            pause_interrupted_cycle(recovery_args.cycle_id, recovery_args.reason)
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'recover-interrupted-cycle-status':
        parser = argparse.ArgumentParser(prog='./job-search-scraper recover-interrupted-cycle-status')
        parser.add_argument('--cycle-id', required=True)
        try:
            recovery_status_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        try:
            show_interrupted_cycle_recovery_status(recovery_status_args.cycle_id)
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    delegated = {"cleanup-blacklist", "cleanup-titles", "repair-careers-urls", "setup-evidence-tab", "preflight", "status", "reviews", "review-queue", "auth", "test", "demo"}
    if argv[0] in delegated:
        if argv[0] in {"cleanup-blacklist", "cleanup-titles"} and "--dry-run" not in argv and "--apply" not in argv:
            argv = [*argv, "--apply", "--exclusive-writer"]
        return helper_cli.main(argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command")
    parser.add_argument("--defer-sync", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--cycle-id")
    parser.add_argument("--company-id", action="append", default=[])
    parser.add_argument("--retry-blocked", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--partial-retries", type=int, default=DEFAULT_PARTIAL_RETRIES)
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
    if args.command != "sync" and args.cycle_id is not None:
        print("ERROR: --cycle-id applies to sync only.", file=sys.stderr)
        return 2
    if args.company_id and (args.command != 'sync' or args.cycle_id is None):
        print('ERROR: --company-id applies only with sync --cycle-id.', file=sys.stderr)
        return 2
    try:
        return run_start(
            fetch_workers=args.fetch_workers,
            assignment_window=args.assignment_window,
            batch_size=args.batch_size,
            sheet_request_interval=args.sheet_request_interval,
            defer_sync=args.defer_sync, sync_only=args.command == "sync", retry_blocked=args.retry_blocked,
            sync_interval=args.sync_interval, browser_fallback=args.browser_fallback, resume=args.resume,
            partial_retries=args.partial_retries,
            sync_cycle_id=args.cycle_id,
            sync_company_ids=args.company_id,
        )
    except KeyboardInterrupt:
        print("Stopped. Run ./job-search-helper start --resume to continue this scan; start without --resume begins a fresh scan.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def main(argv=None):
    """All public starts use the same scrape, publication, and review lifecycle."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == 'start':
        forbidden = next((flag for flag in ('--cycle-id', '--company-id')
                          if any(value == flag or value.startswith(flag + '=')
                                 for value in arguments[1:])), None)
        if forbidden is not None:
            print(f'ERROR: {forbidden} applies to sync only.', file=sys.stderr)
            return 2
    if arguments and arguments[0] == 'start' and not any(
            flag in arguments for flag in ('--help', '-h')):
        from .scrape_first_pass import main as pipeline_main
        return pipeline_main(['run', '--scraper-args', *arguments[1:]])
    return scrape_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
