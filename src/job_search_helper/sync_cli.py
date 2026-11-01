"""Explicit local-storage maintenance and a single controlled Sheets publisher."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sqlite3
import sys
import time

from .cli import (get_remote_repository, job_database_path, state_path,
                  storage_backend, writer_lock)
from .runner import _load_environment
from .sheets_sync import SheetsSynchronizer
from .sqlite_repository import SQLiteRepository, timestamp


def print_status(value):
    print(json.dumps(value, ensure_ascii=False, default=str), flush=True)


def cycle(sync, *, max_batches=20, max_seconds=60):
    started = time.monotonic()
    pulled = sync.pull()
    rows = batches = 0
    for _ in range(max_batches):
        result = sync.publish_batch()
        count = result.get('published_rows', 0)
        rows += count
        batches += 1
        if not count or time.monotonic() - started >= max_seconds:
            break
    with sync.local.transaction():
        sync.local.set_meta('last_sync', timestamp())
        sync.local.set_meta('last_error', '')
    return {'at': timestamp(), 'pull': pulled, 'published_rows': rows,
            'batches': batches, **sync.local.status()}


def main(argv=None):
    parser = argparse.ArgumentParser(description='SQLite job storage and Google Sheets synchronization; no model calls.')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', help='Show local counts and delivery health, without Google access.')
    commands.add_parser('conflicts', help='Show held changes without clearing them.')
    for name in ('once', 'watch'):
        sub = commands.add_parser(name, help='Import manual edits and publish queued local changes.')
        sub.add_argument('--interval', type=float, default=60)
        sub.add_argument('--max-batches', type=int, default=20)
        sub.add_argument('--authenticate', action='store_true', help='Allow Google sign-in in a foreground terminal.')
    migration = commands.add_parser('import', help='Read the workbook into a NEW local database. Never writes Google Sheets.')
    migration.add_argument('--destination', required=True)
    migration.add_argument('--shadow', action='store_true', help='Produce a non-operational test import while the old scraper continues.')
    migration.add_argument('--exclusive-writer', action='store_true', help='Confirm all other writers and manual edits are stopped during cutover.')
    migration.add_argument('--chunk-size', type=int, default=500)
    migration.add_argument('--authenticate', action='store_true')
    backup = commands.add_parser('backup', help='Make a consistent new SQLite backup without copying a live WAL file.')
    backup.add_argument('destination')
    args = parser.parse_args(argv)
    _load_environment()
    import os
    spreadsheet_id = os.environ.get('SPREADSHEET_ID', '').strip()
    local = None
    try:
        if args.command == 'import':
            if not args.shadow and not args.exclusive_writer:
                raise ValueError('An operational import requires --exclusive-writer. Stop the old scraper and other reviewers first.')
            with ExitStack() as stack:
                if not args.shadow:
                    for name in ('writer.lock', 'scraper.lock', 'review-writeback.lock'):
                        stack.enter_context(writer_lock(state_path().parent / name))
                from .sqlite_bootstrap import bootstrap
                remote = get_remote_repository(write=False, interactive=args.authenticate)
                result = bootstrap(remote, Path(args.destination).expanduser(), shadow=args.shadow,
                                   chunk_size=args.chunk_size, progress=print_status)
                print_status(result)
            return 0
        local = SQLiteRepository(job_database_path(), spreadsheet_id,
                                 readonly=args.command in {'status', 'conflicts', 'backup'})
        if args.command == 'status':
            print_status({'configured_backend': storage_backend(), 'database': str(local.path), **local.status()})
            return 0
        if args.command == 'conflicts':
            for tab, rid, field, detail, at in local.db.execute('SELECT tab,row_id,header,detail,at FROM conflicts ORDER BY tab,row_id,header'):
                row = local.row(tab, rid) or {}
                print_status({'tab': tab, 'job_key': row.get('Job Key'), 'company': row.get('Company'),
                              'field': field, 'detail': detail, 'at': at})
            return 0
        if args.command == 'backup':
            print_status({'backup': local.backup(Path(args.destination).expanduser())})
            return 0
        if storage_backend() != 'sqlite':
            raise ValueError('Publication is disabled until JOB_STORAGE_BACKEND=sqlite is explicitly activated.')
        if not 5 <= args.interval <= 3600 or not 1 <= args.max_batches <= 100:
            raise ValueError('Sync interval must be 5–3600 seconds and max batches 1–100.')
        with writer_lock(state_path().parent / 'writer.lock'):
            from .sheet_profile import profile_schemas
            schemas = profile_schemas(local.get_meta('sheets_profile'))
            remote = get_remote_repository(write=True, interactive=args.authenticate,
                                           schemas=schemas, evidence_archives=schemas is None)
            sync = SheetsSynchronizer(local, remote)
            failures = 0
            while True:
                started = time.monotonic()
                try:
                    print_status(cycle(sync, max_batches=args.max_batches, max_seconds=args.interval))
                    failures = 0
                except Exception as exc:
                    failures += 1
                    with local.transaction():
                        local.set_meta('last_error', f'{timestamp()} {type(exc).__name__}: {exc}')
                    print_status({'at': timestamp(), 'state': 'SYNC_ERROR_LOCAL_WORK_RETAINED',
                                  'error': str(exc), **local.status()})
                    if args.command == 'once':
                        return 1
                if args.command == 'once':
                    return 0
                delay = max(1, args.interval - (time.monotonic() - started))
                if failures:
                    delay = max(delay, min(300, 5 * (2 ** min(failures, 6))))
                time.sleep(delay)
    except KeyboardInterrupt:
        print_status({'state': 'STOPPED', 'detail': 'Queued local changes are retained.'})
        return 130
    except (OSError, ValueError, RuntimeError, sqlite3.Error, ImportError) as exc:
        print_status({'state': 'BLOCKED_NOT_COMPLETE', 'error': str(exc)})
        return 1
    finally:
        if local:
            local.close()


if __name__ == '__main__':
    raise SystemExit(main())
