"""Local catalog maintenance and explicit scan/recovery commands."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from .config import load_settings, workspace_path
from .catalog_commands import CATALOG_COMMANDS, add_catalog_commands, execute_catalog
from .database import Database
from .dates import readable_timestamp
from .catalog_export import CatalogExporter, HEADERS
from .models import new_id, utc_now
from .scan_lock import ScanBusyError, scan_lock
from .scan_service import ScanService
from .screening_commands import SCREENING_COMMANDS, add_screening_commands, execute_screening


LOCAL_COMMANDS = frozenset({"init", "doctor", "backup", "db", "local"})


def _options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", help="Local workspace; defaults to JSH_WORKSPACE or the current directory.")
    parser.add_argument("--database", help="Catalog path, relative to the workspace unless absolute.")
    parser.add_argument("--settings", help="Explicit TOML settings path, relative to the workspace.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result.")


def add_commands(commands) -> None:
    initialize = commands.add_parser("init", help="Initialize the local catalog without scanning or importing.")
    _options(initialize)
    doctor = commands.add_parser("doctor", help="Check local settings and database integrity without changing records.")
    _options(doctor)
    backup = commands.add_parser("backup", help="Create and verify a complete local database backup.")
    backup.add_argument("destination", help="New backup filename, relative to the workspace unless absolute.")
    _options(backup)
    database = commands.add_parser("db", help="Local database maintenance.")
    actions = database.add_subparsers(dest="database_command", required=True)
    migrate = actions.add_parser("migrate", help="Apply supported catalog schema upgrades.")
    _options(migrate)
    local = commands.add_parser("local", help="Scan and inspect the local catalog.")
    actions = local.add_subparsers(dest="local_command", required=True)
    add_catalog_commands(actions, _options)
    add_screening_commands(actions, _options)
    export = actions.add_parser("export", help="Write a readable CSV snapshot to a new directory.")
    export.add_argument("kind", nargs="?", choices=tuple(HEADERS), help="Omit to export all four views.")
    export.add_argument("--output", help="New output directory; defaults to a unique directory under exports/.")
    export.add_argument("--company-id", action="append", help="Explicitly restrict records to selected companies; repeatable.")
    export.add_argument("--encoding", choices=("utf-8-sig", "utf-8"), default="utf-8-sig", help="Default includes a UTF-8 BOM for spreadsheet import.")
    _options(export)
    scan = actions.add_parser("scan", help="Fetch selected local companies and save their results.")
    selection = scan.add_mutually_exclusive_group(required=True)
    selection.add_argument("--all", action="store_true", help="Scan all active companies with a current source.")
    selection.add_argument("--company-id", action="append", help="Local company ID; may be repeated.")
    _options(scan)
    resume = actions.add_parser("resume", help="Apply saved results and continue an interrupted local cycle.")
    resume.add_argument("--cycle", required=True)
    resume.add_argument("--retry-exceptions", action="store_true", help="Explicitly retry partial, blocked, failed or unsupported fetches.")
    _options(resume)
    status = actions.add_parser("status", help="Read local cycle progress without fetching or writing.")
    status.add_argument("--cycle")
    _options(status)


def _scan_command(args, settings) -> tuple[dict, str]:
    from .local_scanner import run_cycle, scan_options

    if args.local_command == "status":
        with Database(settings.database, readonly=True) as database:
            result = ScanService(database).status(args.cycle)
    else:
        with Database(settings.database) as database, scan_lock(database.path):
            if args.local_command == "scan":
                options = scan_options(settings)
                cycle = ScanService(database).start_cycle(args.company_id, all_companies=args.all,
                            missing_threshold=settings.missing_threshold, run_settings=options)
            else:
                cycle = args.cycle
            result = run_cycle(database, cycle, retry_exceptions=getattr(args, "retry_exceptions", False))
    cycle = result["cycle"]
    if cycle is None:
        return result, "No local scans yet."
    message = (f"Local cycle {cycle['cycle_id']}: {cycle['status']}\n"
               f"Started: {readable_timestamp(cycle['started_at'])}\n"
               f"Companies: {cycle['companies_total']}; remaining: {cycle['companies_remaining']}")
    for member in result["companies"]:
        message += f"\n{member['company_name_at_start']}: {member['status']}"
        if member.get("reason"):
            message += f" - {member['reason']}"
    return result, message


def execute(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(workspace=args.workspace, database=args.database, settings_file=args.settings)
        if args.command == "local" and args.local_command == "export":
            stamp = utc_now().replace(":", "").replace("-", "").split(".")[0]
            destination = workspace_path(settings.workspace, args.output or f"exports/{stamp}-{new_id()[:8]}")
            with Database(settings.database, readonly=True) as database:
                result = CatalogExporter(database).export(destination, kinds=(args.kind,) if args.kind else None,
                    company_ids=args.company_id or (), encoding=args.encoding)
            message = f"Export saved: {result['directory']}"
            for item in result["files"]:
                message += f"\n{item['name']}: {item['rows']} rows"
        elif args.command == "local" and args.local_command in SCREENING_COMMANDS:
            result, message = execute_screening(args, settings)
        elif args.command == "local":
            result, message = (execute_catalog(args, settings) if args.local_command in CATALOG_COMMANDS
                               else _scan_command(args, settings))
        elif args.command == "init":
            with Database.initialize(settings.database) as database:
                result = database.check()
            message = f"Local catalog ready: {settings.database}"
        elif args.command == "db":
            with Database.migrate(settings.database) as database:
                result = database.check()
            message = f"Local catalog schema is current: {settings.database}"
        else:
            with Database(settings.database, readonly=True) as database:
                if args.command == "backup":
                    path = database.backup(workspace_path(settings.workspace, args.destination))
                    result = {"ok": True, "backup": str(path), "database_id": database.database_id}
                    message = f"Verified backup created: {path}"
                else:
                    result = database.check()
                    message = (f"Local catalog checks passed: {settings.database}\n"
                               f"Companies: {result['counts']['companies']}; jobs: {result['counts']['jobs']}; "
                               f"applications: {result['counts']['applications']}\n"
                               f"Saved results waiting: {result['scan_recovery']['pending']}; "
                               f"results needing inspection: {result['scan_recovery']['quarantined']}")
        print(json.dumps(result, indent=2) if args.json else message)
        if not result.get("ok", True):
            return 2
        if args.command == "local" and args.local_command in {"scan", "resume"} and result["cycle"]["status"] == "completed_with_exceptions":
            return 1
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        busy = isinstance(exc, ScanBusyError) or isinstance(exc, sqlite3.OperationalError) and getattr(exc, "sqlite_errorcode", None) in (
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED,
        )
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 3 if busy else 2
