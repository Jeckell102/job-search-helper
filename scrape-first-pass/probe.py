"""Read-only, compact inspection using the installed scraper's configuration."""
import fcntl
import json
import sqlite3
import sys
from collections import Counter

from job_search_helper.runner import _load_environment
from job_search_helper.cli import state_path, job_database_path, storage_backend


def locked(path):
    if not path.exists():
        return False
    with path.open('r') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def inspect():
    _load_environment()
    path = state_path()
    cycles = []
    if path.exists():
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
            for (raw,) in db.execute('SELECT data FROM cycles ORDER BY rowid'):
                item = json.loads(raw)
                cycles.append({'id': item['id'], 'status': item['status'],
                               'started_at': item.get('started_at'),
                               'stages': dict(Counter(c['stage'] for c in item.get('companies', {}).values()))})
    return {'state_dir': str(path.parent), 'backend': storage_backend(),
            'job_database': str(job_database_path()), 'cycles': cycles,
            'scraper_busy': locked(path.parent / ('scraper.lock' if storage_backend() == 'sqlite' else 'writer.lock'))}


if __name__ == '__main__':
    if sys.argv[1:] == ['remote-preflight']:
        from job_search_helper.cli import get_repository, get_remote_repository
        from job_search_helper.sheet_profile import profile_schemas
        _load_environment()
        local = get_repository(write=False)
        try:
            schemas = profile_schemas(local.get_meta('sheets_profile'))
        finally:
            local.close()
        # Renew both saved grants, but perform only schema/header reads.
        remote = get_remote_repository(write=True, interactive=False, renew_both=True,
                                       schemas=schemas, evidence_archives=False)
        print(json.dumps({'remote_schema': remote.validate_schema(), 'write_test': 'not performed'}))
    else:
        print(json.dumps(inspect()))
