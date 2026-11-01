"""Shared refresh coordination; readers only wait for the final file swap."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import time

from .review_revisions import revision


@contextmanager
def refresh_lock(destination):
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (destination / '.refresh.lock').open('a') as handle:
        started = time.monotonic()
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield time.monotonic() - started
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def file_identity(path):
    path = Path(path)
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]


def fingerprint(repo, threshold, inventory_database):
    source = revision(repo, 'queue')
    if source is None:
        return None
    module = Path(__file__).resolve().parent
    policy_files = [module / name for name in (
        'review_queue.py', 'review_refresh.py', 'review_revisions.py',
        'screening.py', 'efficiency.py', 'core.py', 'title_audit.py', 'adp_myjobs.py')]
    from .efficiency import BLACKLIST_PATH, REVIEW_LIST_PATH
    policy_files += [BLACKLIST_PATH, REVIEW_LIST_PATH]
    policies = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in policy_files}
    inventory = None
    if inventory_database is not None:
        path = Path(inventory_database).resolve()
        inventory = [str(path), file_identity(path), file_identity(str(path) + '-wal')]
    db_stat = Path(repo.path).stat()
    return {'version': 1, 'database': [str(repo.path), db_stat.st_dev, db_stat.st_ino],
            'spreadsheet_id': repo.spreadsheet_id, 'revision': source,
            'threshold': threshold, 'inventory': inventory, 'policies': policies}


def reusable(destination, current):
    if current is None:
        return None
    from .review_runtime import publication_lock
    with publication_lock(destination):
        try:
            summary = json.loads((destination / 'summary.json').read_text())
            if not isinstance(summary, dict):
                return None
            if summary.get('source_fingerprint') != current:
                return None
            for name in ('first-pass.jsonl', 'second-pass.jsonl', 'deterministic-filtered.jsonl'):
                expected = summary.get('file_sha256', {}).get(name)
                if not expected or hashlib.sha256((destination / name).read_bytes()).hexdigest() != expected:
                    return None
            return summary
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            return None
