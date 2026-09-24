"""One-command scraper coordinator. AI review is performed separately in ChatGPT Work."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

from .cli import PROJECT_ROOT, get_repository, load_environment, project_path, state_path, writer_lock
from .engine import Engine, State
from .efficiency import load_title_blacklist

FINISHED = {"Complete", "Complete with exceptions"}


def print_help():
    print(
        """Usage: ./job-search-scraper <command>

Commands:
  start        Start or resume the automated scraper.
               - Resumes the newest unfinished local cycle if one exists.
               - Otherwise recovers an unfinished workbook cycle.
               - Otherwise starts a new full-company scan.
               - Writes to Google Sheets and requires no other sheet writers.

Options for start:
  --fetch-workers N
      Run N fetch-only workers while this process remains the only Google
      Sheets writer. Allowed: 1-5. Default: 1.

  --assignment-window N
      Read/queue up to N companies locally before refreshing Companies from
      Google Sheets. Allowed: 1-100. Default: 25.

  --sheet-request-interval SECONDS
      Minimum delay between Google Sheets requests made by the writer.
      Allowed: 0.5-5.0. Default: 1.1.

  help         Show this command list.
  --help       Show this command list.
  -h           Show this command list.

Related helper commands:
  ./job-search-helper preflight
      Validate Google Sheets access and workbook headers without changing cells.

  ./job-search-helper status [--cycle CYCLE_ID]
      Read saved local cycle status without creating or updating state.

  ./job-search-helper cleanup-blacklist [--apply --exclusive-writer]
      Set Job History "Added to Opportunities?" to No for current title-blacklist.txt matches.

  ./job-search-helper reviews --cycle CYCLE_ID --output FILE
      Export the saved pending review queue to a local JSONL file.

  ./job-search-helper auth [--write]
      Refresh Google OAuth credentials without spreadsheet writes.

  ./job-search-helper test
      Run the offline unittest suite.
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


def run_start(fetch_workers=1, assignment_window=25, sheet_request_interval=1.1):
    print("Starting job scraping", flush=True)
    if not 0.5 <= sheet_request_interval <= 5.0:
        raise ValueError("Sheet request interval must be between 0.5 and 5.0 seconds")
    _load_environment()
    load_title_blacklist()
    database = state_path()
    database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with writer_lock(database.parent / "writer.lock"):
        repo = get_repository(write=True, interactive=False, min_request_interval=sheet_request_interval)
        repo.validate_schema()
        state = State(str(database))
        os.chmod(database, 0o600)
        # Remove any legacy local AI queue. .state is cycle/checkpoint recovery only.
        state.purge_reviews()
        try:
            engine = Engine(repo, state, dry_run=False, batch_size=25)
            cycle_id, _ = resolve_cycle(engine, state, repo)
            engine.resume_parallel(cycle_id, fetch_workers=fetch_workers, assignment_window=assignment_window)
            final = engine.status(cycle_id)
            print(
                f"Finished scrape {cycle_id}: {final['status']} | "
                f"needs_review_or_in_progress={final['pending_reviews']} | "
                f"manual_review={final['manual_review']}",
                flush=True,
            )
            return 0
        finally:
            state.close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv in ([], ["help"], ["--help"], ["-h"]):
        print_help()
        return 0
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command")
    parser.add_argument("--fetch-workers", type=int, default=1)
    parser.add_argument("--assignment-window", type=int, default=25)
    parser.add_argument("--sheet-request-interval", type=float, default=1.1)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        print("Run ./job-search-scraper help for available commands.", file=sys.stderr)
        return 2
    if args.command != "start":
        print("ERROR: unknown command.", file=sys.stderr)
        print("Run ./job-search-scraper help for available commands.", file=sys.stderr)
        return 2
    try:
        return run_start(
            fetch_workers=args.fetch_workers,
            assignment_window=args.assignment_window,
            sheet_request_interval=args.sheet_request_interval,
        )
    except KeyboardInterrupt:
        print("Stopped. Run ./job-search-scraper start to continue.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, sqlite3.Error, ImportError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
