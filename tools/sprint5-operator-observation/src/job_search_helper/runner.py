"""Public scrape-to-FIRST-PASS workflow and its internal scan worker."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
import uuid
from collections import Counter, deque
from contextlib import ExitStack, closing, contextmanager, nullcontext

from . import cli as helper_cli
from .cli import PROJECT_ROOT, get_repository, load_environment, project_path, state_path, writer_lock, scraper_lock_name, storage_backend
from .engine import MAX_BATCH_SIZE, MAX_FETCH_WORKERS, Engine, State, now
from .inbox import InventoryInbox
from .efficiency import load_title_blacklist, load_title_review_list
from .review_queue import export_review_queues

FINISHED = {"Complete", "Complete with exceptions"}
DEFAULT_FETCH_WORKERS = 5
DEFAULT_ASSIGNMENT_WINDOW = 100
DEFAULT_SCRAPER_BATCH_SIZE = MAX_BATCH_SIZE
DEFAULT_PARTIAL_RETRIES = 1


_RUNTIME_DIGEST_FIELDS = (
    "source_manifest_sha256",
    "config_sha256",
    "dependency_manifest_sha256",
)


def _canonical_runtime_binding(value):
    """Validate the small immutable identity inherited from stable admission."""
    if not isinstance(value, dict) or value.get("state") not in {
            "NO_RELEASE", "COMPLETE", "ROLLED_BACK"}:
        raise RuntimeError("Inherited runtime binding is incomplete")
    required = {"state", *_RUNTIME_DIGEST_FIELDS}
    if value["state"] != "NO_RELEASE":
        required.add("release_id")
    if set(value) != required:
        raise RuntimeError("Inherited runtime binding has unsupported fields")
    result = {"state": value["state"]}
    if "release_id" in required:
        release_id = value.get("release_id")
        if not isinstance(release_id, str) or not release_id.startswith("REL-"):
            raise RuntimeError("Inherited runtime release identity is invalid")
        result["release_id"] = release_id
    for field in _RUNTIME_DIGEST_FIELDS:
        digest = value.get(field)
        if (not isinstance(digest, str) or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)):
            raise RuntimeError("Inherited runtime digest is invalid: " + field)
        result[field] = digest
    return result


@contextmanager
def _scraper_admission(database, *, require_inherited=False):
    """Use the pre-import launcher lock, or reject unsafe released runtimes."""
    lock_path = (database.parent / scraper_lock_name()).resolve()
    descriptor_text = os.environ.pop("JSH_SCRAPER_ADMISSION_FD", "")
    inherited_path = os.environ.pop("JSH_SCRAPER_ADMISSION_PATH", "")
    runtime_binding = os.environ.pop("JSH_SCRAPER_RUNTIME_BINDING", "")
    if any((descriptor_text, inherited_path, runtime_binding)) and not all(
            (descriptor_text, inherited_path, runtime_binding)):
        raise RuntimeError("Inherited scraper admission is incomplete")
    if descriptor_text:
        try:
            descriptor = int(descriptor_text)
            descriptor_stat = os.fstat(descriptor)
            path_stat = lock_path.stat()
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeError("Inherited scraper admission descriptor is invalid") from exc
        if (inherited_path != str(lock_path)
                or (descriptor_stat.st_dev, descriptor_stat.st_ino)
                != (path_stat.st_dev, path_stat.st_ino)):
            raise RuntimeError("Inherited scraper admission does not own the expected lock")
        # Prove this exact inherited open-file description owns the flock.
        # A second open must be blocked, while reasserting on the inherited
        # description must succeed.  Together those checks reject both an
        # unlocked lookalike FD and a lock owned by another process.
        probe = os.open(lock_path, os.O_RDWR)
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                fcntl.flock(probe, fcntl.LOCK_UN)
                raise RuntimeError("Inherited scraper admission descriptor is not locked")
        finally:
            os.close(probe)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Inherited scraper admission lock belongs to another process") from exc
        try:
            try:
                binding = _canonical_runtime_binding(json.loads(runtime_binding))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Inherited runtime binding is invalid") from exc
            from release_admission_bootstrap import _validate_runtime
            measured = _canonical_runtime_binding(
                _validate_runtime(PROJECT_ROOT, database.parent))
            if binding != measured:
                raise RuntimeError("Inherited runtime binding no longer matches installed state")
            if require_inherited:
                os.set_inheritable(descriptor, False)
            yield binding
        finally:
            os.close(descriptor)
        return
    if require_inherited:
        raise RuntimeError("Retained operator command requires the pre-import scraper lease")
    with writer_lock(lock_path):
        # Check only after taking the same lock as activation.  Checking before
        # it would allow a first release to complete between the check and lock
        # acquisition, after this process had already imported the old source.
        if (database.parent / "integration-release-journal.json").exists():
            raise RuntimeError(
                "Released scraper start/sync requires ./job-search-scraper pre-import admission")
        from release_admission_bootstrap import _validate_runtime
        yield _canonical_runtime_binding(_validate_runtime(PROJECT_ROOT, database.parent))


@contextmanager
def _retained_operator_admission():
    """Yield (state SQLite path, jobs SQLite path, F3 runtime binding) while locked.

    Use this at the reserved operator command boundary before any handler or
    repository construction. A newly opened descriptor must be blocked and
    the inherited descriptor must be able to reassert the scraper flock.
    The installed F3 digests must agree with the bootstrap.
    Compare the effective SQLite paths and device/inode pairs to that same
    launch's pre-import checks. The lease ends on context exit. An integrated
    handler uses locked internals and separately validates operator authority.
    """
    from release_admission_bootstrap import (
        RETAINED_OPERATOR_LAYOUT_ENV, _retained_operator_sqlite_layout,
    )

    _load_environment()
    database = state_path()
    inherited_layout = os.environ.pop(RETAINED_OPERATOR_LAYOUT_ENV, "")
    with _scraper_admission(database, require_inherited=True) as binding:
        if not inherited_layout:
            raise RuntimeError("Missing pre-import retained operator SQLite layout")
        layout = _retained_operator_sqlite_layout(PROJECT_ROOT, database, storage_backend())
        if json.loads(inherited_layout) != layout:
            raise RuntimeError("Retained operator SQLite identity no longer matches admission")
        yield Path(layout["state"]["path"]), Path(layout["jobs"]["path"]), binding


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
               Sheets read access is unavailable. Use --attempt-id for local
               progress on one exact released repair retry.
  queue-company
               Persist one explicit Company ID for the next normal start.
               Requires --company-id and a stable --request-id; does not fetch,
               create a cycle, change Sheets, or replace another pending request.
  ordinary-company-event
               Explicitly admit/fetch one verified request digest or publish its
               exact saved cycle. See ordinary-company-event --help.
  retained-exception-preview
               Read and print the exact claims that an external signer must
               authorize for one retained historical cycle. `--output DIR`
               writes the full manifest plus claims to a private mode-0700
               content-addressed signer-input directory.
               The signer returns `{manifest,envelope}` for activation. Read-only.
  activate-retained-exception
               Verify a separately signed approval envelope and activate one
               exact retained exception; private keys are never accepted.
  run-retained-company-event
               Run one signer-authorized, bridge-owned Company event through
               the isolated retained storage, publication, and FIRST PASS path.
  recover-interrupted-cycle
               Explicitly pause one exact inactive cycle for recovery. Requires
               --cycle-id, --reason, and --apply; preserves its checkpoint.
  recover-interrupted-cycle-status
               Prove whether one exact inactive cycle can be paused safely.
               Read-only: applies no recovery and changes no workbook data.
  legacy-migration-preview
               Read one retained legacy Company plan and print sanitized,
               approval-ready migration pins. Opens no Google connection.
  legacy-migration-adopt
               With --apply and an exact reviewed approval JSON file, journal
               and adopt one completed legacy local plan without replay or a
               Google write. The later sync remains a separate command/gate.
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
  ./job-search-scraper start --resume --resume-cycle-id CYC-ID
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


def resolve_cycle(engine, state, repo, *, persist_recovery=True):
    """Resolve an explicit resume, never an older cycle or an implicit new scan."""
    from .scan_request import superseded_cycle_ids
    from .retained_cycle_retirement_control import verified_retired_cycle_ids
    local = state.cycles()
    retired = verified_retired_cycle_ids(state)
    if hasattr(repo, "read_columns"):
        remote = [row for _, row in repo.read_columns(
            "Scan Cycles", ["Cycle ID", "Cycle Status", "Started At", "Notes"])]
    else:
        remote = repo.read("Scan Cycles")
    superseded = superseded_cycle_ids(local + remote)
    candidates = {row["Cycle ID"]: row for row in remote if row.get("Cycle ID")}
    # Local checkpoints include the last acknowledged company results.
    candidates.update({cycle["id"]: cycle for cycle in local})
    candidates = {cid: cycle for cid, cycle in candidates.items()
                  if cid not in superseded and cid not in retired}
    if not candidates:
        raise ValueError("No saved scan to resume. Run start without --resume for a fresh scan.")
    cycle_id, chosen = max(reversed(list(candidates.items())), key=lambda pair: _started_at(pair[1]))
    if (chosen.get("status") or chosen.get("Cycle Status")) == "Complete":
        raise ValueError("The latest scan is already complete. Run start without --resume for a fresh scan.")
    if "id" not in chosen:
        engine._recover(cycle_id, persist=persist_recovery)
    elif engine.runtime_binding is not None:
        engine.assert_runtime_binding(cycle_id)
    return cycle_id, "resuming latest scan; completed companies are skipped"


def select_start_cycle(engine, state, repo, database, *, resume=False):
    if resume:
        if (database.parent / "next-scan.json").exists():
            raise ValueError("A fresh next-scan.json request is pending. Run start without --resume to use it.")
        cycle_id, action = resolve_cycle(engine, state, repo)
        print(f"{action}: {cycle_id}.", flush=True)
        return cycle_id
    from .ordinary_company_event_command import guard_generic_ordinary_event
    from .scan_request import requested_scan
    guard_generic_ordinary_event(database)
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


def _write_retained_signer_input(path, value):
    """Publish one private, content-addressed signer artifact without overwrite."""
    root = Path(path).expanduser()
    if root.is_symlink():
        raise ValueError('retained_exception_signer_directory_symlink')
    created = not root.exists()
    if created:
        root.mkdir(parents=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('retained_exception_signer_directory_invalid')
    root = root.resolve()
    directory_stat = root.stat()
    if directory_stat.st_uid != os.geteuid() or stat.S_IMODE(directory_stat.st_mode) != 0o700:
        raise ValueError('retained_exception_signer_directory_private_required')
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    identifier = hashlib.sha256(encoded).hexdigest()
    destination = root / (identifier + '.json')

    def existing():
        if destination.is_symlink():
            raise ValueError('retained_exception_signer_artifact_symlink')
        details = destination.stat()
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.geteuid()
                or stat.S_IMODE(details.st_mode) != 0o600):
            raise ValueError('retained_exception_signer_artifact_private_required')
        try:
            actual = json.loads(destination.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('retained_exception_signer_input_unreadable') from exc
        if actual != value:
            raise ValueError('retained_exception_signer_artifact_collision')
        return destination

    if os.path.lexists(destination):
        return existing()
    temporary = root / ('.' + identifier + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            return existing()
        directory = os.open(root, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return existing()
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def retained_exception_preview(cycle_id, expires_at, *, database=None, jobs_path=None,
                               output=None):
    """Build one read-only authorization preview for an exceptional pilot."""
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('Retained exception preview requires an exact cycle ID.')
    database = database or state_path()
    local_jobs = jobs_path or helper_cli.job_database_path()
    if not database.is_file():
        raise ValueError('Retained exception preview state database is missing.')
    # ``State(..., readonly=True)`` is correct for ordinary recovery but may
    # create SQLite's shared-memory sidecar beside a WAL database.  A signer
    # preview is expressly read-only, including its directory footprint.
    uri = database.resolve().as_uri() + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True)
    try:
        row = connection.execute(
            'SELECT data FROM cycles WHERE id=?', (cycle_id.strip(),)).fetchone()
    finally:
        connection.close()
    try:
        cycle = json.loads(row[0]) if row else None
    except (TypeError, ValueError) as exc:
        raise ValueError('Retained exception preview cycle is unreadable.') from exc
    if not isinstance(cycle, dict):
        raise ValueError('Retained exception preview cycle is missing.')
    from .retained_work_exception import build_manifest, required_claims
    manifest = build_manifest(
        cycle, database.parent / 'inventories.sqlite3', local_jobs,
        reason='operator-provenanced company-only containment',
        created_at=now())
    result = {'manifest': manifest,
              'required_claims': required_claims(manifest, expires_at=expires_at)}
    if output is not None:
        result['output'] = str(_write_retained_signer_input(output, result))
    return result


def active_inbox_cycles(inbox, state, include_blocked=True):
    """Return saved work only for cycles that have not already finished.

    Completed cycles deliberately keep blocked inventories for an explicit
    sync retry.  They must not turn a normal ``start`` into a replay of old
    cycle IDs, otherwise fresh scan cycles are never created.
    """
    from .scan_request import superseded_cycle_ids
    from .retained_cycle_retirement_control import verified_retired_cycle_ids
    local = state.cycles()
    retired = verified_retired_cycle_ids(state)
    statuses = {cycle.get("id"): cycle.get("status") for cycle in local}
    superseded = superseded_cycle_ids(local)
    return [
        cycle_id for cycle_id in inbox.cycles(include_blocked=include_blocked)
        if statuses.get(cycle_id) not in FINISHED and cycle_id not in superseded
        and cycle_id not in retired
    ]


def validate_exact_sync_cycle(database, cycle_id, *, retry_blocked=True):
    """Prove one exact saved cycle is selectable before any sync side effect."""
    if (not isinstance(cycle_id, str) or cycle_id != cycle_id.strip()
            or not cycle_id or len(cycle_id) > 128 or any(char.isspace() for char in cycle_id)):
        raise ValueError('--cycle-id must be one exact saved cycle ID without whitespace.')
    state = State(str(database), readonly=True)
    try:
        from .retained_cycle_retirement_control import assert_cycle_not_retired
        assert_cycle_not_retired(state, cycle_id)
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


def _readonly_named_exact_preflight(database, inventory_path, cycle_id, company_ids,
                                    *, runtime_binding=None):
    """Validate only the selected durable records without opening a writer.

    This runs while exact recovery owns the normal scraper lock.  It must stay
    free of schema installers and Google construction: a missing, superseded,
    blocked, or unplanned selection is rejected before an OAuth client can be
    created.
    """
    from .scan_request import superseded_cycle_ids

    state = State(str(database), readonly=True)
    try:
        from .retained_cycle_retirement_control import assert_cycle_not_retired
        assert_cycle_not_retired(state, cycle_id)
        cycle = state.cycle(cycle_id)
        if (not isinstance(cycle, dict) or cycle.get('id') != cycle_id
                or cycle.get('status') in FINISHED):
            raise ValueError('Exact sync cycle is missing, finished, or superseded.')
        if cycle_id in superseded_cycle_ids(state.cycles()):
            raise ValueError('Exact sync cycle is missing, finished, or superseded.')
        if 'selected_retry_reservation_sha256' in cycle:
            raise ValueError('Selected retry requires its dedicated execution and publication path.')
        Engine.validate_cycle_runtime_binding(cycle, runtime_binding, sync_only=True)
    finally:
        state.close()
    location = Path(inventory_path)
    if not location.is_file():
        raise ValueError('Exact selected durable inventory database is missing.')
    uri = location.resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as connection:
        for company_id in company_ids:
            item = cycle.get('companies', {}).get(company_id)
            if not isinstance(item, dict):
                raise ValueError('Exact selected Company is missing or blocked.')
            inventory = connection.execute(
                'SELECT blocked FROM inventories WHERE cycle=? AND company=?',
                (cycle_id, company_id)).fetchone()
            plan_row = connection.execute(
                'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?',
                (cycle_id, company_id)).fetchone()
            if inventory is None or bool(inventory[0]):
                raise ValueError('Exact selected Company is missing or blocked.')
            if plan_row is None:
                raise ValueError('Exact selected Company requires a frozen durable plan.')
            try:
                plan = json.loads(plan_row[0])
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError('Exact selected Company frozen plan is invalid.') from exc
            if not isinstance(plan, dict) or type(plan_row[1]) is not int:
                raise ValueError('Exact selected Company frozen plan is invalid.')
            stage = item.get('stage')
            if stage not in {'queued', 'inventory', 'complete', 'partial'}:
                raise ValueError('Exact selected Company has no recoverable State/plan combination.')


def _run_qualified_repair(argv):
    parser = argparse.ArgumentParser(prog='./job-search-scraper continue-qualified-repair', allow_abbrev=False)
    parser.add_argument('--attempt-id', required=True)
    parser.add_argument('--qualification-owner-path', type=Path, required=True)
    parser.add_argument('--qualification-owner-fd', type=int, required=True)
    parser.add_argument('--qualification-owner-device', type=int, required=True)
    parser.add_argument('--qualification-owner-inode', type=int, required=True)
    parser.add_argument('--qualification-receipt-sha256', required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'RTRY-[0-9a-f]{24}', args.attempt_id) or args.qualification_owner_fd < 3:
        raise ValueError('The exact repair retry ID and inherited qualification descriptor are required')

    _load_environment()
    database = state_path()
    with ExitStack() as resources:
        with _scraper_admission(database, require_inherited=True) as runtime:
            from .release_controller import (
                _continue_qualified_release_retry_admitted, _finish_qualified_release_retry,
                _read_qualified_retry_intent, _require_qualified_retry,
            )
            from .release_qualification import open_release_qualification_owner
            from .sheet_profile import profile_schemas
            from .sqlite_repository import SQLiteRepository

            jobs = helper_cli.job_database_path()
            inbox_path = database.parent / 'inventories.sqlite3'
            if (storage_backend() != 'sqlite' or runtime['state'] != 'COMPLETE'
                    or any(path.is_symlink() or not path.is_file() for path in (database, jobs, inbox_path))):
                raise ValueError('Qualified repair requires the installed release and existing SQLite stores')
            owner = resources.enter_context(open_release_qualification_owner(
                args.qualification_owner_path, args.qualification_owner_fd,
                expected_owner_identity=(args.qualification_owner_device, args.qualification_owner_inode),
                approved_receipt_sha256=args.qualification_receipt_sha256,
            ))
            os.set_inheritable(args.qualification_owner_fd, False)
            binding = _read_qualified_retry_intent(database, args.attempt_id)
            _require_qualified_retry(database, binding, owner)
            with writer_lock(database.parent / 'writer.lock'):
                destination = InventoryInbox.destination_id(inbox_path)
                local = resources.enter_context(closing(SQLiteRepository(jobs, destination)))
                state = resources.enter_context(closing(State(database)))
                inbox = resources.enter_context(closing(InventoryInbox(inbox_path, destination)))
            engine = Engine(local, state, inbox=inbox, runtime_binding=runtime,
                            error_log_path=database.parent / 'errors.jsonl')

            def remote_factory():
                if os.environ.get('SPREADSHEET_ID', '').strip() != destination:
                    raise ValueError('Qualified repair workbook differs from the saved inventory destination')
                return nullcontext(helper_cli.get_remote_repository(
                    write=True, schemas=profile_schemas(local.get_meta('sheets_profile')), evidence_archives=False))

            result = _continue_qualified_release_retry_admitted(
                engine, database, binding, qualification_owner=owner, remote_factory=remote_factory)
        return _finish_qualified_release_retry(engine, binding, result, qualification_owner=owner)


def _run_named_exact_cycle_sync(*, sync_cycle_id, sync_company_ids,
                                sheet_request_interval, database=None,
                                runtime_binding=None):
    """Run the dedicated exact-cycle recovery boundary.

    This command intentionally lives outside ``run_start``'s ordinary
    lifecycle.  It does not start the global synchronizer, pull a workbook,
    drain a local outbox, perform cleanup, refresh reviews, export outcomes,
    or discover a fallback cycle.  The dependency factory first validates the
    named durable records, and only then constructs the remote exact-scope
    repository used by ``recover_exact_cycle_with_factory``.
    """
    _load_environment()
    database = database or state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    from .exact_cycle_recovery import _recover_exact_cycle_with_factory_admitted
    from .cli import get_remote_repository, job_database_path
    from .sheet_profile import profile_schemas
    from .sqlite_repository import SQLiteRepository

    @contextmanager
    def exact_dependencies():
        spreadsheet_id = InventoryInbox.destination_id(
            database.parent / 'inventories.sqlite3')
        # All state/inbox reads above are readonly.  This is the final gate
        # before opening the writable local store or constructing Google.
        _readonly_named_exact_preflight(
            database, database.parent / 'inventories.sqlite3',
            sync_cycle_id, sync_company_ids, runtime_binding=runtime_binding)
        local = SQLiteRepository(job_database_path(), spreadsheet_id, readonly=False)
        state = inbox = None
        try:
            schemas = profile_schemas(local.get_meta('sheets_profile'))
            state = State(str(database))
            inbox = InventoryInbox(database.parent / 'inventories.sqlite3', spreadsheet_id)
            from .integration_release import assert_release_settled
            assert_release_settled(database.parent)
            # The writable local handles above are required only for the
            # exact plan's local journal.  Recheck the named snapshot at the
            # final possible point before Google construction: a normal
            # writer cannot pass this recovery lock between this read and the
            # factory call.
            _readonly_named_exact_preflight(
                database, database.parent / 'inventories.sqlite3',
                sync_cycle_id, sync_company_ids, runtime_binding=runtime_binding)
            remote = get_remote_repository(
                write=True, interactive=True, renew_both=True,
                min_request_interval=sheet_request_interval,
                schemas=schemas, evidence_archives=False)
            yield Engine(local, state, inbox=inbox,
                         runtime_binding=runtime_binding,
                         error_log_path=database.parent / 'errors.jsonl'), remote
        finally:
            if inbox is not None:
                inbox.close()
            if state is not None:
                state.close()
            local.close()

    report = _recover_exact_cycle_with_factory_admitted(
        database, exact_dependencies, sync_cycle_id, sync_company_ids,
        require_frozen_plans=True)
    print('Exact cycle recovery: ' + json.dumps(report, sort_keys=True), flush=True)
    return 0


def run_start(fetch_workers=DEFAULT_FETCH_WORKERS, assignment_window=DEFAULT_ASSIGNMENT_WINDOW,
              batch_size=DEFAULT_SCRAPER_BATCH_SIZE, sheet_request_interval=1.1,
              defer_sync=False, sync_only=False, retry_blocked=True, sync_interval=60,
              browser_fallback=True, resume=False, partial_retries=DEFAULT_PARTIAL_RETRIES,
              sync_cycle_id=None, sync_company_ids=None, resume_cycle_id=None):
    if resume_cycle_id is not None and (not resume or sync_only
            or not isinstance(resume_cycle_id, str) or not resume_cycle_id
            or any(char.isspace() for char in resume_cycle_id)):
        raise ValueError('--resume-cycle-id requires start --resume and one exact cycle ID.')
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
    # This controls the exact remote repository as well as the ordinary
    # synchronizer, so validate it before either branch can construct one.
    if not 0.5 <= sheet_request_interval <= 5.0:
        raise ValueError("Sheet request interval must be between 0.5 and 5.0 seconds")
    if exact_sync and sync_company_ids is not None:
        # Keep every exact selected invocation before the normal startup
        # lifecycle.  In particular it must not enter run_scoped_sync or any
        # cleanup/review/outcome path below.
        _load_environment()
        database = state_path()
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _scraper_admission(database) as runtime_binding:
            from .ordinary_company_event_command import guard_generic_ordinary_event
            from .retained_work_runner import assert_no_manually_staged_event
            assert_no_manually_staged_event(database.parent)
            guard_generic_ordinary_event(database, selected_cycle_id=sync_cycle_id, allow_queued=True)
            return _run_named_exact_cycle_sync(
                sync_cycle_id=sync_cycle_id, sync_company_ids=sync_company_ids,
                sheet_request_interval=sheet_request_interval,
                database=database, runtime_binding=runtime_binding)
    run_started = time.monotonic()
    print("Syncing saved inventories" if sync_only else "Starting job scraping", flush=True)
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
    with _scraper_admission(database) as runtime_binding, ExitStack() as resources:
        # Activation uses this same lock. A durable nonterminal release journal
        # therefore blocks the real scraper boundary after an interrupted install.
        # A retained company-only preflight is not represented in ordinary
        # State/inbox data.  Check its journal before constructing the remote
        # repository or starting any global lifecycle side effect.
        from .retained_work_runner import assert_normal_lifecycle_not_held
        from .cli import job_database_path
        assert_normal_lifecycle_not_held(database.parent, job_database_path())
        from .ordinary_company_event_command import guard_generic_ordinary_event
        guard_generic_ordinary_event(
            database, allow_queued=resume and resume_cycle_id is not None,
            fresh=not sync_only and not resume,
        )
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
        preselected_resume_cycle = None
        queued_request_bytes = None
        next_request = database.parent / 'next-scan.json'
        preselected_sync_cycles = []
        if sync_only:
            preselected_sync_cycles = InventoryInbox.saved_cycle_ids(
                database.parent / 'inventories.sqlite3', include_blocked=retry_blocked)
        if resume or preselected_sync_cycles:
            # A resumed attempt must be pinned before the synchronizer,
            # review cleanup, event bridge, closed-job cleanup, manual sync,
            # provider fetch, or publication can change anything.
            if resume and next_request.exists() and resume_cycle_id is None:
                raise ValueError(
                    "A fresh next-scan.json request is pending. Run start without --resume to use it.")
            with ExitStack() as preflight_resources:
                preflight_state = State(str(database), readonly=True) if database.is_file() else State()
                preflight_resources.callback(preflight_state.close)
                preflight_repo = get_repository(write=False, interactive=False,
                                                min_request_interval=sheet_request_interval)
                close = getattr(preflight_repo, 'close', None)
                if callable(close):
                    preflight_resources.callback(close)
                preflight_engine = Engine(
                    preflight_repo, preflight_state, runtime_binding=runtime_binding)
                if resume:
                    preselected_resume_cycle, action = resolve_cycle(
                        preflight_engine, preflight_state, preflight_repo, persist_recovery=False)
                    if resume_cycle_id is not None and preselected_resume_cycle != resume_cycle_id:
                        raise ValueError('The exact resume ID does not match the current normal cycle.')
                    if next_request.exists():
                        from .scan_request import verify_queued_event_for_normal_resume
                        queued_request_bytes = verify_queued_event_for_normal_resume(
                            preflight_repo, preflight_state, database, cycle_id=preselected_resume_cycle)
                    print(f"{action}: {preselected_resume_cycle}.", flush=True)
                else:
                    for selected_cycle in preselected_sync_cycles:
                        if preflight_state.cycle(selected_cycle) is None:
                            preflight_engine._recover(selected_cycle, persist=False, sync_only=True)
                        else:
                            preflight_engine.assert_runtime_binding(selected_cycle, sync_only=True)
        repo = get_repository(write=True, interactive=True, renew_both=True,
                              min_request_interval=sheet_request_interval)
        repo.validate_schema()
        performance = {}
        performance_sources = [performance]
        run_counts = Counter()
        sync = None
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
                            runtime_binding=runtime_binding,
                            **({"fetcher": fetcher} if fetcher else {}))
            run_completed = False
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
                    cycle_ids = preselected_sync_cycles
                    if not cycle_ids:
                        print("No saved inventories to sync.")
                        return 0
                else:
                    cycle_ids = ([preselected_resume_cycle] if resume else
                                 [select_start_cycle(engine, state, repo, database, resume=False)])
                if queued_request_bytes is not None and next_request.read_bytes() != queued_request_bytes:
                    raise ValueError('The queued Company event changed before exact resume.')
                for cycle_id in cycle_ids:
                    if (resume or sync_only) and state.cycle(cycle_id) is None:
                        engine._recover(cycle_id, sync_only=sync_only)
                    engine.assert_runtime_binding(cycle_id, sync_only=sync_only)
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
                            state=state, inbox=inbox,
                        )
                        if receipts:
                            print(f"Scrape outcomes: recorded {len(receipts)} bounded result(s) for safe follow-up.", flush=True)
                final = engine.status(cycle_id)
                if defer_sync:
                    print("Inventories saved locally. Run ./job-search-scraper sync to write the jobs to Sheets.", flush=True)
                _print_run_status(final)
                run_completed = True
                return 0
            finally:
                if run_completed and sync is not None:
                    # The final run-owned pull must settle before reading the
                    # Company-event outbox. The bridge keeps events deferred
                    # behind unfinished cycles under this same lease.
                    sync.__exit__(None, None, None)
                    if queued_request_bytes is None:
                        from .company_events import CompanyEventBridge
                        terminal_bridge_results = CompanyEventBridge(
                            repo, database.parent, state_database=database).process_pending(writer_lock_held=True)
                        if terminal_bridge_results:
                            print(
                                f"Company changes: recorded {len(terminal_bridge_results)} "
                                "post-run change(s) for the next safe scan.",
                                flush=True,
                            )
                performance.update({**getattr(repo, "metrics", {}), **engine.performance,
                               "checkpoint_seconds": state.checkpoint_seconds + inbox.checkpoint_seconds,
                               "checkpoint_payload_bytes": state.checkpoint_bytes + inbox.payload_bytes,
                               "inventories_saved": inbox.saved})
                inbox.close()
                state.close()
                if queued_request_bytes is not None and next_request.read_bytes() != queued_request_bytes:
                    raise ValueError('The queued Company event changed during exact resume.')


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
        from .retained_work_runner import assert_normal_lifecycle_not_held
        from .cli import job_database_path
        assert_normal_lifecycle_not_held(database.parent, job_database_path())
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


def retire_interrupted_cycle(cycle_id, archive_root, archive_scope_sha256, reason, *, apply=False):
    """Archive-retire one saved cycle; no scrape, plan, or publisher is resumed."""
    if apply is not True:
        raise ValueError('Retirement is an apply-only owner action; pass --apply.')
    if not isinstance(cycle_id, str) or not cycle_id.strip():
        raise ValueError('Use an exact --cycle-id for retirement.')
    if not isinstance(archive_scope_sha256, str) or re.fullmatch(r'[0-9a-f]{64}', archive_scope_sha256) is None:
        raise ValueError('Use the exact lowercase 64-character --archive-scope-sha256 from archive verification.')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('Use a written --reason for retirement.')
    _load_environment()
    database = state_path()
    jobs = helper_cli.job_database_path().resolve()
    if jobs != (database.parent / 'jobs.sqlite3').resolve():
        raise ValueError('Retirement requires the default sibling jobs.sqlite3 store.')
    from .retained_cycle_retirement_control import retire_saved_cycle
    record = retire_saved_cycle(database.parent, Path(archive_root), cycle_id.strip(),
                                archive_scope_sha256=archive_scope_sha256,
                                reason=reason.strip())
    # Never print the archived state/inventory/plan payloads or private path.
    summary = {key: record[key] for key in ('cycle_id', 'state', 'published', 'retired',
                                             'archive_scope_sha256', 'recorded_at')}
    print('Interrupted cycle retired: ' + json.dumps(summary, sort_keys=True), flush=True)
    return summary


def scrape_main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'continue-qualified-repair':
        try:
            result = _run_qualified_repair(argv[1:])
            print('Qualified repair retry: ' + json.dumps(result, sort_keys=True))
            return 0 if result.get('state') in {
                'COMPLETE', 'WAITING_FOR_EXACT_RETRY', 'RETRY_INVENTORY_HELD', 'RETRY_PUBLICATION_HELD',
            } else 1
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
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
    if argv[0] == 'retire-interrupted-cycle':
        parser = argparse.ArgumentParser(prog='./job-search-scraper retire-interrupted-cycle')
        parser.add_argument('--cycle-id', required=True)
        parser.add_argument('--archive-root', required=True)
        parser.add_argument('--archive-scope-sha256', required=True)
        parser.add_argument('--reason', required=True)
        parser.add_argument('--apply', action='store_true')
        try:
            args = parser.parse_args(argv[1:])
            retire_interrupted_cycle(args.cycle_id, args.archive_root,
                                     args.archive_scope_sha256, args.reason,
                                     apply=args.apply)
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == "errors":
        return show_errors()
    if argv[0] == 'company-queue-status':
        parser = argparse.ArgumentParser(prog='./job-search-scraper company-queue-status')
        parser.add_argument('--local-only', action='store_true')
        parser.add_argument('--attempt-id', help='Read one released repair retry from local records only.')
        try:
            status_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        try:
            if status_args.attempt_id is not None:
                _load_environment()
                from .repair_retry_status import read_repair_retry_status
                result = read_repair_retry_status(
                    state_path(), helper_cli.job_database_path(), status_args.attempt_id,
                )
                print(json.dumps(result, sort_keys=True))
                return 0
            return show_company_only_queue_status(local_only=status_args.local_only)
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'queue-company':
        parser = argparse.ArgumentParser(prog='./job-search-scraper queue-company')
        parser.add_argument('--company-id', required=True)
        parser.add_argument('--request-id', required=True)
        try:
            queue_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        repo = None
        try:
            _load_environment()
            repo = get_repository(write=False, interactive=False)
            from .operator_company_request import queue_operator_company_request
            result = queue_operator_company_request(
                repo, state_path().parent, queue_args.company_id, queue_args.request_id)
            print('Company-only request: ' + json.dumps(result, sort_keys=True))
            return 0 if result['state'] != 'WAITING_FOR_SAFE_REQUEST_BOUNDARY' else 1
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
        finally:
            if repo is not None:
                repo.close()
    if argv[0] == 'retained-exception-preview':
        parser = argparse.ArgumentParser(
            prog='./job-search-scraper retained-exception-preview')
        parser.add_argument('--cycle-id', required=True)
        parser.add_argument('--expires-at', required=True)
        parser.add_argument('--output', metavar='DIR')
        try:
            preview_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        try:
            report = retained_exception_preview(
                preview_args.cycle_id, preview_args.expires_at,
                output=preview_args.output)
            # The manifest includes retained historical membership and evidence
            # summaries.  The operator only needs the exact signed claims and
            # its digest; do not spill the entire local manifest to a console.
            print(json.dumps({
                'manifest_digest': report['manifest']['manifest_digest'],
                'required_claims': report['required_claims'],
                **({'signer_input': report['output']} if 'output' in report else {}),
            }, sort_keys=True))
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'activate-retained-exception':
        parser = argparse.ArgumentParser(prog='./job-search-scraper activate-retained-exception')
        parser.add_argument('--cycle-id', required=True)
        parser.add_argument('--approval-file', required=True)
        parser.add_argument('--key-id', required=True)
        parser.add_argument('--ed25519-public-key-base64', required=True)
        try:
            activation = parser.parse_args(argv[1:])
            approval = json.loads(Path(activation.approval_file).read_text(encoding='utf-8'))
            from .retained_company_event import _verifier, activate_signed_exception
            result = activate_signed_exception(state_directory=state_path().parent,
                cycle_id=activation.cycle_id, approval=approval,
                verifier=_verifier(activation.key_id, activation.ed25519_public_key_base64))
            # The frozen store retains the complete evidence.  Console output is
            # deliberately a receipt only: do not echo the manifest or signed
            # envelope into terminal scrollback or a service journal.
            print('Retained exception activated: ' + json.dumps({
                'state': result['state'],
                'cycle_id': activation.cycle_id,
                'manifest_digest': result['manifest_digest'],
                'authorization_digest': result['authorization_digest'],
                'key_id': result['key_id'],
                'authorization_expires_at': result['authorization_expires_at'],
            }, sort_keys=True))
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError, json.JSONDecodeError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'ordinary-company-event':
        from .ordinary_company_event_command import execute_ordinary_event, parse_ordinary_event_command

        args = parse_ordinary_event_command(argv[1:])
        try:
            with _retained_operator_admission() as admission:
                result = execute_ordinary_event(
                    args.action, admission, request_sha256=args.request_sha256, cycle_id=args.cycle_id,
                )
            print('Ordinary Company event: ' + json.dumps(result, sort_keys=True))
            return 0 if result['state'] in {
                'INVENTORY_FROZEN', 'SYNC_CONFIRMED', 'VERIFIED_ZERO', 'FETCH_TEMPORARY', 'FETCH_BLOCKED',
                'FETCH_REPAIR_QUALIFIED',
            } else 1
        except KeyboardInterrupt:
            return 130
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'operator-amphenol-partial':
        parser = argparse.ArgumentParser(prog='./job-search-scraper operator-amphenol-partial', allow_abbrev=False)
        parser.add_argument('--request-sha256', action='append', required=True)
        args = parser.parse_args(argv[1:])
        try:
            from .ats import fetch_inventory
            from .ordinary_company_event_command import _digest_text
            from .operator_amphenol_settlement import execute_operator_amphenol
            from .sheet_profile import COMPACT_SCHEMAS

            if len(args.request_sha256) != 1 or not _digest_text(args.request_sha256[0]):
                raise ValueError('Supply one exact lowercase request SHA-256.')
            with _retained_operator_admission() as admission:
                result = execute_operator_amphenol(
                    admission, request_sha256=args.request_sha256[0], fetcher=fetch_inventory,
                    remote_reader=lambda: helper_cli.get_remote_repository(
                        write=False, interactive=False, schemas=COMPACT_SCHEMAS, evidence_archives=False),
                )
            print('Operator Amphenol partial: ' + json.dumps(result, sort_keys=True))
            return 0 if result['state'] == 'FETCH_REPAIR_QUALIFIED' else 1
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'run-retained-operator-company':
        try:
            with _retained_operator_admission() as admission:
                if argv[1:]:
                    from .retained_operator_command import operator_command
                    return operator_command(argv[1:], admission)
                raise ValueError("Specify the retained operator command and exact request identity")
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'run-retained-company-event':
        try:
            _load_environment()
            parser = argparse.ArgumentParser(prog='./job-search-scraper run-retained-company-event')
            parser.add_argument('--key-id',
                                default=os.environ.get('COMPANY_RETAINED_KEY_ID'))
            parser.add_argument('--ed25519-public-key-base64',
                                default=os.environ.get('COMPANY_RETAINED_ED25519_PUBLIC_KEY_BASE64'))
            parser.add_argument('--sheet-request-interval', type=float)
            parser.add_argument('--max-operations', type=int, default=100)
            retained_args = parser.parse_args(argv[1:])
            if not retained_args.key_id or not retained_args.ed25519_public_key_base64:
                raise ValueError('Retained Company event public-key configuration is missing')
            request_interval = retained_args.sheet_request_interval
            if request_interval is None:
                request_interval = float(os.environ.get(
                    'COMPANY_RETAINED_SHEET_REQUEST_INTERVAL', '1.1'))
            if not 0.5 <= request_interval <= 5.0:
                raise ValueError('Sheet request interval must be between 0.5 and 5.0 seconds')
            from .retained_company_event import production_command
            result = production_command(
                state_directory=state_path().parent, key_id=retained_args.key_id,
                public_key_base64=retained_args.ed25519_public_key_base64,
                request_interval=request_interval,
                max_operations=retained_args.max_operations)
            print('Retained Company event: ' + json.dumps(result, sort_keys=True))
            return 0 if result.get('state') == 'FIRST_PASS_RELEASED' and result.get('consumption') else 1
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
    if argv[0] == 'legacy-migration-preview':
        parser = argparse.ArgumentParser(
            prog='./job-search-scraper legacy-migration-preview')
        parser.add_argument('--cycle-id', required=True)
        parser.add_argument('--company-id', required=True)
        try:
            migration_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        try:
            _load_environment()
            from .exact_legacy_migration_runner import (
                preview_retained_legacy_migration,
            )
            database = state_path()
            report = preview_retained_legacy_migration(
                database.parent / 'inventories.sqlite3',
                helper_cli.job_database_path(), migration_args.cycle_id,
                migration_args.company_id)
            print('Exact legacy migration preview: '
                  + json.dumps(report, sort_keys=True))
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
            print(f'ERROR: {exc}', file=sys.stderr)
            return 1
    if argv[0] == 'legacy-migration-adopt':
        parser = argparse.ArgumentParser(
            prog='./job-search-scraper legacy-migration-adopt')
        parser.add_argument('--cycle-id', required=True)
        parser.add_argument('--company-id', required=True)
        parser.add_argument('--approval-file', required=True)
        parser.add_argument('--apply', action='store_true')
        try:
            migration_args = parser.parse_args(argv[1:])
        except SystemExit:
            return 2
        if not migration_args.apply:
            print('ERROR: legacy adoption is local-only but durable; rerun with '
                  '--apply after reviewing the exact approval file.', file=sys.stderr)
            return 2
        try:
            _load_environment()
            approval_path = Path(migration_args.approval_file).resolve()
            if not approval_path.is_file():
                raise ValueError('Exact legacy migration approval file is missing.')
            approval = json.loads(approval_path.read_text(encoding='utf-8'))
            from .exact_legacy_migration_runner import (
                adopt_retained_legacy_migration,
            )
            database = state_path()
            with writer_lock(database.parent / scraper_lock_name()):
                from .integration_release import assert_release_settled
                assert_release_settled(database.parent)
                report = adopt_retained_legacy_migration(
                    database.parent / 'inventories.sqlite3',
                    helper_cli.job_database_path(), migration_args.cycle_id,
                    migration_args.company_id, approval)
            print('Exact legacy migration adopted: '
                  + json.dumps(report, sort_keys=True))
            return 0
        except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError,
                json.JSONDecodeError) as exc:
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
    parser.add_argument("--resume-cycle-id")
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
            resume_cycle_id=args.resume_cycle_id,
        )
    except KeyboardInterrupt:
        print("Stopped. Run ./job-search-helper start --resume to continue this scan; start without --resume begins a fresh scan.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _guard_public_workflow_start(arguments):
    """Check before the broad workflow opens its preparation factories."""
    from .ordinary_company_event_command import guard_generic_ordinary_event

    _load_environment()
    resume = '--resume' in arguments
    exact_resume = any(
        (argument == '--resume-cycle-id' and index + 1 < len(arguments)
         and not arguments[index + 1].startswith('-'))
        or (argument.startswith('--resume-cycle-id=') and argument.partition('=')[2])
        for index, argument in enumerate(arguments)
    )
    guard_generic_ordinary_event(state_path(), allow_queued=resume and exact_resume, fresh=not resume)


def main(argv=None):
    """Route ordinary starts to the review controller and exact actions separately."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == 'start':
        forbidden = next((flag for flag in ('--cycle-id', '--company-id')
                          if any(value == flag or value.startswith(flag + '=')
                                 for value in arguments[1:])), None)
        if forbidden is not None:
            print(f'ERROR: {forbidden} applies to sync only.', file=sys.stderr)
            return 2
    if arguments and arguments[0] in {'start', '--admitted-workflow'}:
        pipeline_args = (
            ['run', '--scraper-args', *arguments[1:]] if arguments[0] == 'start' else arguments[1:]
        )
        wants_help = any(flag in arguments for flag in ('--help', '-h'))
        if arguments[0] == '--admitted-workflow' or not wants_help:
            if not wants_help:
                try:
                    _guard_public_workflow_start(arguments[1:])
                except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
                    print(f'ERROR: {exc}', file=sys.stderr)
                    return 1
            from .scrape_first_pass import main as pipeline_main
            return pipeline_main(pipeline_args)
    return scrape_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
