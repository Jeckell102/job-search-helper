"""Run the opt-in source transition preview with only immutable backup stores."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
BACKUP = Path('/home/chris/.local/state/job-search-helper-backups/current-scraper-20261121-090919/project/.state')
PATHS = {BACKUP / name for name in ('inventories.sqlite3', 'jobs.sqlite3')}
original_connect = sqlite3.connect


def unchanged_files():
    records = {}
    for database in PATHS:
        for suffix in ('', '-wal', '-journal', '-shm'):
            target = Path(str(database) + suffix)
            if not target.exists():
                records[target] = None
                continue
            st = target.stat()
            if suffix in ('-wal', '-journal') and st.st_size:
                raise RuntimeError('Copy has nonempty journals')
            records[target] = (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    return records


def audit(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.fork', 'os.posix_spawn')):
        raise RuntimeError('No external activity is expected from a preview')
    if event == 'sqlite3.connect':
        target = urlparse(str(args[0]))
        if Path(unquote(target.path)) not in PATHS or parse_qs(target.query) != {'mode': ['ro'], 'immutable': ['1']}:
            raise RuntimeError('Preview attempted another database connection')
    if event == 'open' and len(args) == 3 and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        raise RuntimeError('Preview attempted a writable file open')


def immutable_open(database_uri, *args, **kwargs):
    parsed = urlparse(database_uri)
    if Path(unquote(parsed.path)) not in PATHS or parse_qs(parsed.query) != {'mode': ['ro']} or not kwargs.get('uri'):
        raise RuntimeError('Preview requested an unexpected mode or store')
    db = original_connect(database_uri + '&immutable=1', *args, **kwargs)
    db.execute('PRAGMA query_only=ON')
    return db


def main():
    source = unchanged_files()
    sys.path.insert(0, str(ROOT / 'src'))
    sys.addaudithook(audit)
    sqlite3.connect = immutable_open
    from job_search_helper.control_before_prefix_runner import (
        preview_control_before_prefix_recovery,
        preview_control_before_prefix_source_transition,
    )
    from job_search_helper import exact_control_before_prefix_recovery as planner
    from job_search_helper.sqlite_repository import REVIEW_FIELDS
    inventory = BACKUP / 'inventories.sqlite3'
    jobs = BACKUP / 'jobs.sqlite3'
    identity = 'CYC-B639C6D864EC', 'COMP-0054'
    try:
        preview_control_before_prefix_recovery(
            inventory, jobs, *identity, expires_at='2026-12-01T00:00:00+00:00')
    except ValueError as error:
        assert str(error) == 'control_before_prefix_job_ownership_mismatch'
    else:
        raise AssertionError('Original v3 API unexpectedly accepted the source transition')
    finally:
        sqlite3.connect = original_connect
    captured = {}
    original_preview = planner.preview_control_before_prefix_source_transition

    def checked_preview(*args, **kwargs):
        result = original_preview(*args, **kwargs)
        captured['plan'] = result['plan']
        return result

    planner.preview_control_before_prefix_source_transition = checked_preview
    report = preview_control_before_prefix_source_transition(inventory, jobs, *identity)
    assert report.get('mutation_performed') is False
    assert report.get('local_write_performed') is False
    assert report.get('remote_write_performed') is False
    assert report.get('receipt_created') is False
    with closing(original_connect(inventory.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        saved, cursor = db.execute(
            'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?', identity).fetchone()
    retained = json.loads(saved)['operations']
    internal = captured['plan']
    successor = internal['operations']
    history_index, evidence_index = report['history_index'], report['evidence_index']
    assert len(successor) == len(retained) == report['operation_count']
    assert chronology_untouched(successor, retained, history_index)
    assert successor[:cursor] == retained[:cursor] and cursor == report['original_verified_prefix_cursor']
    assert retained[history_index]['append_if_missing'] is True
    assert successor[history_index]['append_if_missing'] is False
    assert not set(successor[history_index]['values']).intersection(REVIEW_FIELDS)
    assert successor[evidence_index] == retained[evidence_index]
    report['original_prefix_operations_preserved'] = cursor
    report['exact_preserved_review_fields'] = sorted(REVIEW_FIELDS)
    report['existing_job_update_only'] = True
    assert unchanged_files() == source
    print(json.dumps(report, indent=2, sort_keys=True))


def chronology_untouched(successor, retained, changed_index):
    return all(new == old for index, (new, old) in enumerate(zip(successor, retained))
               if index != changed_index)


if __name__ == '__main__':
    main()
