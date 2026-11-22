"""Preflight or apply only the approved Allen source correction after installation."""

import argparse
from contextlib import closing
import fcntl
import json
import os
from pathlib import Path
import stat
import sys


PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
RELEASE_ID = 'REL-d37d7d64a0fd3788e02e699f'
BEFORE_REVISION = 'af09ccc00f9f125e8fe7d6bce5dcdbfccc2660f82513931fe5c8822c3e82851d'


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('action', choices=('preflight', 'apply'))
    args = parser.parse_args()
    if (not sys.flags.isolated or not sys.flags.dont_write_bytecode
            or sys.pycache_prefix != '/dev/null' or Path(sys.prefix).resolve() != PROJECT / '.venv'):
        raise ValueError('Use the installed isolated release Python.')
    sys.path[:0] = [str(PROJECT), str(PROJECT / 'src')]

    from release_admission_bootstrap import _load_environment, _validate_runtime

    _load_environment(PROJECT / '.env')
    path = ROOT / 'scraper.lock'
    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as guard:
        info = os.fstat(guard.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or not os.path.samestat(info, path.stat(follow_symlinks=False))):
            raise ValueError('Allen admission does not identify the normal scraper lock.')
        fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _validate_runtime(PROJECT, ROOT).get('release_id') != RELEASE_ID:
            raise ValueError('The reviewed Allen runtime is not active.')
        return reconcile(args.action)


def reconcile(action):
    from job_search_helper.cli import get_remote_repository, writer_lock
    from job_search_helper.engine import State
    from job_search_helper.inbox import InventoryInbox
    from job_search_helper.retained_work_runner import assert_normal_lifecycle_not_held
    from job_search_helper.runner import active_inbox_cycles
    from job_search_helper.scan_request import _cycle_views, _unfinished_from_views
    from job_search_helper.sheet_profile import COMPACT_SCHEMAS
    from job_search_helper.sqlite_repository import SQLiteRepository

    from job_search_helper.allen_source_reconciliation import (
        AFTER, BEFORE, COMPANY_ID, COMPANY_NAME, continue_allen_source_reconciliation,
        preflight_allen_source_reconciliation,
    )

    with writer_lock(ROOT / 'writer.lock'):
        assert_normal_lifecycle_not_held(ROOT, ROOT / 'jobs.sqlite3')
        queue = ROOT / 'next-scan.json'
        if queue.exists() or queue.is_symlink():
            raise ValueError('The exact Allen source correction needs an idle scrape queue.')
        destination = InventoryInbox.destination_id(ROOT / 'inventories.sqlite3')
        intent = {'schema': 'allen-source-reconciliation-v1', 'spreadsheet_id': destination,
                  'company_id': COMPANY_ID, 'company': COMPANY_NAME, 'company_status': 'Active',
                  'before': BEFORE, 'after': AFTER, 'expected_source_revision': BEFORE_REVISION}
        with (closing(SQLiteRepository(ROOT / 'jobs.sqlite3', destination, readonly=True)) as reader,
              closing(State(str(ROOT / 'state.db'), readonly=True)) as state,
              closing(InventoryInbox(ROOT / 'inventories.sqlite3', destination, readonly=True)) as inbox):
            if _unfinished_from_views(*_cycle_views(reader, state)) or active_inbox_cycles(inbox, state):
                raise ValueError('An unfinished scrape still owns the application.')
            remote = get_remote_repository(interactive=False, schemas=COMPACT_SCHEMAS, evidence_archives=False)
            preview = preflight_allen_source_reconciliation(reader, remote, intent)
        if action == 'preflight':
            print(json.dumps(preview, sort_keys=True))
            return 0
        if preview['state'] != 'READY':
            raise ValueError('The approved source correction is still held.')
        with closing(SQLiteRepository(ROOT / 'jobs.sqlite3', destination)) as local:
            remote = get_remote_repository(write=True, interactive=False, schemas=COMPACT_SCHEMAS,
                                           evidence_archives=False)
            result = continue_allen_source_reconciliation(local, remote, intent)
        print(json.dumps(result, sort_keys=True))
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
