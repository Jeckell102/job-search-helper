"""Command-line entry point. No command silently starts a paid model call."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile

from .engine import DEFAULT_BATCH_SIZE, MAX_BATCH_SIZE, Engine, State, now, run_demo
from .cleanup import cleanup_blacklisted_history
from .repair import repair_careers_urls
from .repository import GoogleRepository, MemoryRepository, authorize
from .review_queue import DEFAULT_THRESHOLD, export_review_queues


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OPERATIONAL_TABS = ("Companies", "Job History", "Job Evidence", "Opportunities", "Scan Cycles")


def load_environment(path: Path) -> None:
    """Read a deliberately small .env format; never execute or interpolate it."""
    if not path.exists():
        return
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env entry on line {line_number}; use NAME=value.")
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"Invalid environment variable name on line {line_number}.")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Unclosed .env quotation on line {line_number}.")
            value = value[1:-1]
        os.environ.setdefault(name, value)


def project_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def state_path() -> Path:
    return project_path(os.environ.get("STATE_DB_FILE", ".state/state.db"))


def storage_backend():
    marker = PROJECT_ROOT / '.storage-backend'
    default = marker.read_text().strip() if marker.exists() else 'sheets'
    backend = os.environ.get("JOB_STORAGE_BACKEND", default).strip().lower()
    if backend not in {"sheets", "sqlite"}:
        raise ValueError("JOB_STORAGE_BACKEND must be sheets or sqlite.")
    return backend


def job_database_path():
    return project_path(os.environ.get("JOB_DB_FILE", ".state/jobs.sqlite3"))


def scraper_lock_name():
    return "scraper.lock" if storage_backend() == "sqlite" else "writer.lock"


def review_lock_name():
    return "review-writeback.lock" if storage_backend() == "sqlite" else "writer.lock"


def get_repository(write: bool = False, interactive: bool = False, min_request_interval: float | None = None,
                   renew_both: bool = False):
    # Local scraping and reviewing must not authenticate with Google at all.
    if storage_backend() == "sqlite":
        from .sqlite_repository import SQLiteRepository
        spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
        if not spreadsheet_id or not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
            raise ValueError("Set SPREADSHEET_ID to the working spreadsheet ID in .env.")
        return SQLiteRepository(job_database_path(), spreadsheet_id, readonly=not write)
    return get_remote_repository(write=write, interactive=interactive,
                                 min_request_interval=min_request_interval, renew_both=renew_both)


def get_remote_repository(write: bool = False, interactive: bool = False, min_request_interval: float | None = None,
                   renew_both: bool = False, schemas=None, evidence_archives: bool = True) -> GoogleRepository:
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    if not spreadsheet_id or not re.fullmatch(r"[A-Za-z0-9_-]+", spreadsheet_id):
        raise ValueError("Set SPREADSHEET_ID to the working spreadsheet ID in .env.")
    if write and spreadsheet_id == "1avssxbKDXMrKS0oFHNAfhbQ2HWNz3T_jkn4DSUEmqv0":
        raise ValueError("Refusing to write to Job Search Master - Original. Configure the working copy instead.")
    if renew_both:
        service = authorize(write=write, interactive=interactive, renew_both=True)
    else:
        service = authorize(write=write, interactive=interactive)
    if min_request_interval is None:
        repo = GoogleRepository(service, spreadsheet_id, schemas=schemas)
    else:
        repo = GoogleRepository(service, spreadsheet_id, schemas=schemas, min_request_interval=min_request_interval)
    archive_file = os.environ.get("EVIDENCE_ARCHIVES_FILE", "").strip()
    if archive_file and evidence_archives:
        from .evidence_archives import EvidenceArchives
        return EvidenceArchives(repo, project_path(archive_file))
    return repo


def detached_repository(repo: GoogleRepository) -> MemoryRepository:
    """A dry run may read Sheets, but all proposed changes go to memory only."""
    return MemoryRepository(repo.read_many(OPERATIONAL_TABS))


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


class WriterLockBusy(RuntimeError):
    """Another local process currently owns this writer lock."""


@contextmanager
def writer_lock(path: Path):
    """Reject a second local writer; this is not a cross-machine claim lock."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = path.open("a", encoding="utf-8")
    os.chmod(path, 0o600)
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WriterLockBusy("Another local helper holds the writer lock.") from exc
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def require_single_writer(args: argparse.Namespace) -> None:
    if args.workers != 1:
        raise ValueError("Only one worker is supported. Atomic remote worker claims are not implemented.")
    if args.apply and not args.exclusive_writer:
        raise ValueError(
            "--apply requires --exclusive-writer. Stop other spreadsheet writers and do not sort, "
            "insert, or delete sheet rows during a commit. The local lock cannot lock other machines."
        )


def open_readonly_state() -> State:
    path = state_path()
    if not path.is_file():
        raise ValueError("No saved local state exists. Run an explicitly applied small cycle first, or use demo.")
    return State(str(path), readonly=True)


def execute_work(args: argparse.Namespace) -> None:
    require_single_writer(args)
    if not args.apply:
        print("DRY RUN: read-only Google access; no spreadsheet or saved checkpoint changes.")
        repo = detached_repository(get_repository(write=False, interactive=args.authenticate))
        if args.command == "start" or not state_path().is_file():
            state = State(":memory:")
        else:
            saved_state = open_readonly_state()
            try:
                state = saved_state.clone()
            finally:
                saved_state.close()
        try:
            engine = Engine(repo, state, dry_run=True, batch_size=args.batch_size)
            execute_engine_command(engine, args)
        finally:
            state.close()
        return

    print("APPLY: one controlled writer. Model calls remain disabled.")
    database = state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with writer_lock(database.parent / scraper_lock_name()):
        repo = get_repository(write=True, interactive=args.authenticate)
        repo.validate_schema()
        state = State(str(database))
        os.chmod(database, 0o600)
        try:
            engine = Engine(repo, state, dry_run=False, batch_size=args.batch_size)
            execute_engine_command(engine, args)
        finally:
            state.close()


def execute_engine_command(engine: Engine, args: argparse.Namespace) -> None:
    if args.command == "start":
        cycle = engine.start_cycle(company_ids=None if args.all else args.company_id)
        print(f"Cycle ID: {cycle}")
        print_json(engine.resume(cycle))
    elif args.command == "resume":
        print_json(engine.resume(args.cycle, retry_blocked=args.retry_blocked))
    elif args.command == "import-decisions":
        print_json(engine.import_decisions(args.cycle, str(Path(args.file).expanduser().resolve())))
    else:
        raise ValueError(f"Unsupported work command: {args.command}")


def execute_cleanup(args: argparse.Namespace) -> None:
    require_single_writer(args)
    if not args.apply:
        print("DRY RUN: reading Job History titles; no spreadsheet cells will change.")
        repo = get_repository(write=False, interactive=args.authenticate)
        repo.validate_schema()
        print_json(cleanup_blacklisted_history(repo, apply=False))
        return

    print("APPLY: setting Added to Opportunities? to No for excluded titles; reporting potential matches and uncertain titles.")
    database = state_path()
    with writer_lock(database.parent / scraper_lock_name()):
        repo = get_repository(write=True, interactive=args.authenticate)
        repo.validate_schema()
        print_json(cleanup_blacklisted_history(repo, apply=True))



def execute_repair_careers(args: argparse.Namespace) -> None:
    require_single_writer(args)
    if not args.apply:
        print("DRY RUN: checking blocked Companies for valid replacement careers boards; no spreadsheet cells will change.")
        repo = get_repository(write=False, interactive=args.authenticate)
        repo.validate_schema()
        print_json(repair_careers_urls(repo, apply=False))
        return

    print("APPLY: validating replacement careers boards, queueing proven fixes, and recording unvalidated candidates for review.")
    database = state_path()
    with writer_lock(database.parent / scraper_lock_name()):
        repo = get_repository(write=True, interactive=args.authenticate)
        repo.validate_schema()
        print_json(repair_careers_urls(repo, apply=True))


def execute_setup_evidence_tab(args: argparse.Namespace) -> None:
    if not args.apply:
        print("DRY RUN: checking whether the Job Evidence tab exists; no spreadsheet cells will change.")
        repo = get_repository(write=False, interactive=args.authenticate)
        try:
            repo.read_columns("Job Evidence", ["Job Key", "Source Hash"])
            print_json({"tab": "Job Evidence", "exists": True, "changes": 0})
        except Exception as exc:
            print_json({"tab": "Job Evidence", "exists": False, "required_headers": repo.schemas["Job Evidence"], "reason": str(exc)})
        return
    if not args.exclusive_writer:
        raise ValueError("--apply requires --exclusive-writer. Stop other spreadsheet writers before changing workbook structure.")
    print("APPLY: creating or repairing the Job Evidence tab and moving existing descriptions out of Job History.")
    database = state_path()
    with writer_lock(database.parent / scraper_lock_name()):
        repo = get_repository(write=True, interactive=args.authenticate, min_request_interval=1.1)
        setup = repo.ensure_tab("Job Evidence")
        # Prime narrow commit layouts. Without this, each batch would reload the
        # full Job Evidence tab after it starts filling with long descriptions.
        repo.read_columns("Job Evidence", ["Job Key", "Source Hash"])
        moved = skipped = 0
        operations = []
        stamp = now()
        pending_bytes = 0
        def flush():
            nonlocal operations, pending_bytes
            if not operations:
                return
            repo.commit(operations)
            print_json({"event": "evidence_migration_progress", "migrated_descriptions": moved, "skipped_rows": skipped})
            operations = []
            pending_bytes = 0

        history_rows = repo.read_many(["Job History"])["Job History"]
        for row in history_rows:
            key = str(row.get("Job Key") or "").strip()
            source_hash = str(row.get("Source Hash") or row.get("Description Hash") or "").strip()
            description = str(row.get("Job Description") or "")
            if not key or not source_hash or not description or description.startswith("See Job Evidence tab:"):
                skipped += 1
                continue
            pointer = f"See Job Evidence tab: {key} / {source_hash[:12]}"
            pair = [
                {"tab": "Job Evidence", "identity": {"Job Key": key, "Source Hash": source_hash},
                 "append_if_missing": True, "values": {"Company": row.get("Company", ""),
                 "Job Title": row.get("Job Title", ""), "Official Job URL": row.get("Official Job URL", ""),
                 "Captured At": stamp, "Job Description": description}},
                {"tab": "Job History", "identity": {"Job Key": key}, "values": {"Job Description": pointer}},
            ]
            operations.extend(pair)
            pending_bytes += len(description.encode("utf-8"))
            moved += 1
            if len(operations) >= 120 or pending_bytes >= 1_200_000:
                flush()
        flush()
        print_json({**setup, "migrated_descriptions": moved, "skipped_rows": skipped})

def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manual, resumable job inventory and reviewed-decision helper.")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("test", help="Run offline unittest suite; no credentials or network needed.")
    demo = commands.add_parser("demo", help="Run an isolated offline end-to-end demonstration.")
    demo.add_argument("--output", help="New/empty output directory; defaults to a temporary directory.")
    preflight = commands.add_parser("preflight", help="Validate access and workbook headers; never change cells.")
    preflight.add_argument("--authenticate", action="store_true", help="Allow interactive read-only Google OAuth.")
    auth = commands.add_parser("auth", help="Renew both Google OAuth credentials; no spreadsheet writes.")
    auth_scope = auth.add_mutually_exclusive_group()
    auth_scope.add_argument("--write", action="store_true", help="Renew only the separate write credential.")
    auth_scope.add_argument("--read-only", action="store_true", help="Renew only the separate read-only credential.")
    status = commands.add_parser("status", help="Read local cycle status without creating or updating state.")
    status.add_argument("--cycle")
    reviews = commands.add_parser("reviews", help="Export the saved pending review queue to a new local file.")
    reviews.add_argument("--cycle", required=True)
    reviews.add_argument("--output", required=True)
    review_queue = commands.add_parser("review-queue", help="Build read-only weighted AI review queues from Job History.")
    review_queue.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    review_queue.add_argument("--output-dir", default=str(PROJECT_ROOT / ".state" / "review-queue"))
    review_queue.add_argument("--overwrite", action="store_true")
    review_queue.add_argument("--authenticate", action="store_true", help="Permit OAuth if credentials are absent.")
    cleanup = commands.add_parser(
        "cleanup-blacklist",
        aliases=["cleanup-titles"],
        help="Set Job History Added to Opportunities? to No for titles matching title-blacklist.txt.",
    )
    cleanup.add_argument("--apply", action="store_true", help="Actually commit the cell changes; off by default.")
    cleanup.add_argument("--dry-run", action="store_true", help="Explicitly select the default read-only preview.")
    cleanup.add_argument("--exclusive-writer", action="store_true", help="Confirm all other sheet writers are stopped.")
    cleanup.add_argument("--workers", type=int, default=1, help=argparse.SUPPRESS)
    cleanup.add_argument("--authenticate", action="store_true", help="Permit OAuth if credentials are absent.")

    closed = commands.add_parser("cleanup-closed", help="Deterministically change eligible Closed + Pending rows to No; no AI review.")
    closed.add_argument("--apply", action="store_true", help="Apply guarded cleanup and verify scoped Sheet delivery.")
    closed.add_argument("--dry-run", action="store_true", help="Preview without changes (the default).")
    closed.add_argument("--limit", type=int, default=100, help="Bounded cleanup size, 1–100.")
    closed.add_argument("--authenticate", action="store_true", help="Permit interactive Google authorization if needed.")

    repair = commands.add_parser(
        "repair-careers-urls",
        help="Find valid replacement careers boards for blocked companies and queue proven fixes.",
    )
    repair.add_argument("--apply", action="store_true", help="Write proven fixes and candidate URLs; off by default.")
    repair.add_argument("--dry-run", action="store_true", help="Explicitly select the default read-only preview.")
    repair.add_argument("--exclusive-writer", action="store_true", help="Confirm all other sheet writers are stopped.")
    repair.add_argument("--workers", type=int, default=1, help=argparse.SUPPRESS)
    repair.add_argument("--authenticate", action="store_true", help="Permit OAuth if credentials are absent.")

    evidence = commands.add_parser("setup-evidence-tab", help="Create or repair the Job Evidence tab used for full descriptions.")
    evidence.add_argument("--apply", action="store_true", help="Actually create/repair the tab; off by default.")
    evidence.add_argument("--dry-run", action="store_true", help="Explicitly select the default read-only preview.")
    evidence.add_argument("--exclusive-writer", action="store_true", help="Confirm all other sheet writers are stopped.")
    evidence.add_argument("--authenticate", action="store_true", help="Permit OAuth if credentials are absent.")

    for name, description in (
        ("start", "Start a new, explicitly scoped cycle; dry-run by default."),
        ("resume", "Resume the named existing cycle; never start another full sweep."),
        ("import-decisions", "Validate reviewed decisions individually and save in atomic batches."),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("--apply", action="store_true", help="Actually commit changes; off by default.")
        command.add_argument("--dry-run", action="store_true", help="Explicitly select the default dry run.")
        command.add_argument("--exclusive-writer", action="store_true", help="Confirm all other sheet writers are stopped.")
        command.add_argument("--workers", type=int, default=1)
        command.add_argument("--batch-size", type=int, choices=range(1, MAX_BATCH_SIZE + 1), default=DEFAULT_BATCH_SIZE,
                             help=f"Jobs per atomic write/checkpoint, 1-{MAX_BATCH_SIZE} (default: {DEFAULT_BATCH_SIZE}).")
        command.add_argument("--authenticate", action="store_true", help="Permit OAuth if credentials are absent.")
        if name == "start":
            scope = command.add_mutually_exclusive_group(required=True)
            scope.add_argument("--company-id", action="append", help="Company ID to include; repeat for a small group.")
            scope.add_argument("--all", action="store_true", help="Explicitly include all eligible companies.")
        else:
            command.add_argument("--cycle", required=True)
        if name == "resume":
            command.add_argument("--retry-blocked", action="store_true", help="Explicitly allow another attempt at blocked companies.")
        if name == "import-decisions":
            command.add_argument("--file", required=True, help="UTF-8 decisions JSONL file.")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if getattr(args, "apply", False) and getattr(args, "dry_run", False):
        print("ERROR: --apply and --dry-run cannot be used together.", file=sys.stderr)
        return 2
    try:
        if args.command == "test":
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
            return subprocess.call(
                [sys.executable, "-m", "unittest", "discover", "-s", str(PROJECT_ROOT / "tests"), "-v"],
                cwd=PROJECT_ROOT, env=environment,
            )
        if args.command == "demo":
            output = Path(args.output).expanduser().resolve() if args.output else Path(tempfile.mkdtemp(prefix="job-search-demo-"))
            if output.exists() and any(output.iterdir()):
                raise ValueError("Demo output must be a new or empty directory; existing files will not be replaced.")
            print_json(run_demo(output))
            return 0

        load_environment(PROJECT_ROOT / ".env")
        for variable, default in (
            ("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
            ("GOOGLE_TOKEN_READ_FILE", ".secrets/token-readonly.json"),
            ("GOOGLE_TOKEN_WRITE_FILE", ".secrets/token-write.json"),
        ):
            os.environ[variable] = str(project_path(os.environ.get(variable, default)))

        if args.command == "auth":
            authorize(write=args.write, interactive=True, renew_both=not (args.write or args.read_only))
            label = "write" if args.write else "read-only" if args.read_only else "read and write"
            print(f"Google {label} authorization saved. No spreadsheet cells were modified.")
        elif args.command == "preflight":
            repo = get_repository(interactive=args.authenticate)
            validation = repo.validate_schema()
            print_json({"schema": validation, "spreadsheet_id": os.environ["SPREADSHEET_ID"], "write_test": "not performed"})
        elif args.command == "status":
            if not state_path().exists():
                print_json({"cycles": [], "message": "No local state yet; nothing was created."})
            else:
                state = open_readonly_state()
                try:
                    print_json(Engine(MemoryRepository(), state).status(args.cycle))
                finally:
                    state.close()
        elif args.command == "reviews":
            output = Path(args.output).expanduser().resolve()
            if output.exists():
                raise ValueError("Review export already exists; select a new filename to preserve prior work.")
            state = open_readonly_state()
            try:
                count = Engine(MemoryRepository(), state).export_reviews(args.cycle, str(output))
            finally:
                state.close()
            print_json({"reviews": count, "output": str(output)})
        elif args.command == "review-queue":
            repo = get_repository(write=False, interactive=args.authenticate)
            print_json(export_review_queues(
                repo, args.output_dir, threshold=args.threshold, overwrite=args.overwrite,
                inventory_database=state_path().parent / "inventories.sqlite3"
            ))
        elif args.command in {"cleanup-blacklist", "cleanup-titles"}:
            execute_cleanup(args)
        elif args.command == "cleanup-closed":
            from .closed_jobs import execute_cleanup
            execute_cleanup(args)
        elif args.command == "repair-careers-urls":
            execute_repair_careers(args)
        elif args.command == "setup-evidence-tab":
            execute_setup_evidence_tab(args)
        else:
            execute_work(args)
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
        # Do not dump tokens, OAuth responses, or credential contents in tracebacks.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Saved decisions remain saved; resume the same cycle ID.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Third-party OAuth/HTTP exceptions may embed response payloads. Keep
        # them out of terminal output; leave the user's recorded state intact.
        print(
            f"ERROR: {type(exc).__name__}: external operation failed. Check authorization, "
            "network access, and the saved cycle status before resuming.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
