"""Read live human choices before review work; never publish to Sheets here.

Only identity, selection and human notes are polled. Import changed rows through
the existing three-way merge so manual choices beat unsent model decisions.
The runtime's persisted gate also keeps off-sheet audit records out of review.
"""
from collections import Counter
from contextlib import contextmanager
import fcntl
import json
import hashlib
from datetime import datetime, timezone

from .repository import RepositoryError, _equivalent
from .sheets_sync import SheetsSynchronizer, unique_rows
from .sqlite_repository import timestamp
from .review_revisions import revision

FIELDS = ['Job Key', 'Added to Opportunities?', 'Review Notes']


def _signature(local, rows):
    stat = local.path.stat()
    return {'version': 1, 'database': [str(local.path), stat.st_dev, stat.st_ino],
            'spreadsheet_id': local.spreadsheet_id,
            'profile': local.get_meta('sheets_profile'),
            'remote': hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                                 separators=(',', ':')).encode()).hexdigest()}


def _reuse_controls(runtime, local, signature):
    # The caller has JUST read every remote control row. Only redundant local
    # merge/routing work may be skipped; no TTL or cached remote response.
    with local.transaction():
        current = revision(local, 'controls')
        cached = runtime.db.execute("SELECT value FROM metadata WHERE key='controls_cache'").fetchone()
        if current is None or cached is None:
            return None
        value = json.loads(cached[0])
        if value.get('signature') != signature or value.get('revision') != current:
            return None
        report = dict(value['report'], checked_at=datetime.now(timezone.utc).isoformat(),
                      cancelled_claims=0, reopened_jobs=0, changed_fields=0,
                      local_processing_skipped=True)
        local.set_meta('last_review_controls_pull', timestamp())
        with runtime.transaction():
            runtime.db.execute("UPDATE metadata SET value=? WHERE key='sheet_controls'", (json.dumps(report),))
        return report


@contextmanager
def controls_lock(runtime):
    with (runtime.directory / '.controls.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _local_rows(local):
    return {r[0]: {'choice': r[1], 'status': r[2], 'source': r[3],
                   'closed': str(r[4]).strip().casefold() == 'closed',
                   'frozen': str(r[5]).strip().casefold() == 'frozen after 2'}
            for r in local.db.execute('''SELECT
              json_extract(data,'$."Job Key"'),
              json_extract(data,'$."Added to Opportunities?"'),
              json_extract(data,'$."Review Status"'),
              json_extract(data,'$."Source Hash"'),
              json_extract(data,'$."Job Status"'),
              json_extract(data,'$."Reconsideration Status"')
              FROM records WHERE tab='Job History' ''')}


def refresh_sheet_controls(runtime, *, local=None, remote=None):
    """Fail closed on failed/ambiguous reads, with no new claims or decisions."""
    owned = local is None
    if local is None:
        from .runner import _load_environment
        from .cli import get_repository
        _load_environment()
        local = get_repository(write=True, interactive=False)
    try:
        with controls_lock(runtime):
            signature = None
            observed_revision = None
            if not getattr(local, 'is_local', False):
                # In direct-Sheets mode the repository itself is the live source.
                rows = unique_rows('Job History', list(local.read_columns(
                    'Job History', FIELDS + ['Review Status', 'Source Hash',
                                           'Job Status', 'Reconsideration Status'])))
                controls = []
                for _, row in rows:
                    choice = str(row.get('Added to Opportunities?', '')).strip()
                    eligible = (choice.casefold() == 'pending' and
                                row.get('Review Status') == 'Needs Review' and
                                str(row.get('Job Status', '')).casefold() != 'closed' and
                                row.get('Reconsideration Status') != 'Frozen after 2')
                    controls.append((row['Job Key'], choice, eligible,
                                     row.get('Source Hash', '')))
                changed = 0
                reopened = set()
            else:
                if remote is None:
                    from .cli import get_remote_repository
                    from .sheet_profile import profile_schemas
                    remote = get_remote_repository(write=False, interactive=False,
                        schemas=profile_schemas(local.get_meta('sheets_profile')),
                        evidence_archives=False)
                if remote.spreadsheet_id != local.spreadsheet_id:
                    raise RepositoryError('Live review workbook differs from local storage.')
                rows = unique_rows('Job History', list(remote.read_columns('Job History', FIELDS)))
                signature = _signature(local, rows)
                cached = _reuse_controls(runtime, local, signature)
                if cached is not None:
                    return cached
                bases = {r[0]: {'row_id': r[1], 'Added to Opportunities?': r[2] or '',
                                'Review Notes': r[3] or ''}
                         for r in local.db.execute('''SELECT
                           json_extract(data,'$."Job Key"'),row_id,
                           json_extract(data,'$."Added to Opportunities?"'),
                           json_extract(data,'$."Review Notes"')
                           FROM baseline WHERE tab='Job History' ''')}
                attempts = {r[0]: json.loads(r[1]) for r in local.db.execute(
                    "SELECT row_id,data FROM delivery_attempts WHERE tab='Job History'")}
                changed_rows = []
                reopened = set()
                for number, row in rows:
                    key = row['Job Key']
                    base = bases.get(key)
                    if base is None or any(not _equivalent(field, row.get(field, ''), base.get(field, ''))
                                           for field in FIELDS[1:]):
                        changed_rows.append((number, row))
                    choice = str(row.get('Added to Opportunities?', '')).strip().casefold()
                    if base and choice == 'pending' and str(base['Added to Opportunities?']).casefold() != 'pending':
                        sent = attempts.get(base['row_id'], {}).get('Added to Opportunities?')
                        if str(sent).strip().casefold() != 'pending':
                            reopened.add(key)
                merged = SheetsSynchronizer(local, remote).merge_remote(
                    'Job History', changed_rows, complete_snapshot=False)
                changed = merged['changed_fields']
                with local.transaction():
                    current = _local_rows(local)
                    observed_revision = revision(local, 'controls')
                controls = []
                for _, row in rows:
                    key = row['Job Key']
                    choice = str(row.get('Added to Opportunities?', '')).strip()
                    record = current.get(key, {})
                    eligible = (choice.casefold() == 'pending' and
                                str(record.get('choice', '')).casefold() == 'pending' and
                                record.get('status') == 'Needs Review' and
                                not record.get('closed') and not record.get('frozen'))
                    controls.append((key, choice, eligible, record.get('source', '')))
                with local.transaction():
                    local.set_meta('last_review_controls_pull', timestamp())
            target = 'local_database' if getattr(local, 'is_local', False) else 'google_sheets'
            report = runtime.set_sheet_controls(controls, reopened_keys=reopened, delivery_target=target)
            report = {**report, 'changed_fields': changed,
                    'sheet_choices': dict(Counter(str(row.get('Added to Opportunities?', '')).strip()
                                                 for _, row in rows)),
                    'scope': 'visible_sheet_jobs',
                    'delivery_target': target, 'local_processing_skipped': False}
            if signature is not None and observed_revision is not None:
                # Never stamp an old local projection with a newer revision if
                # another reviewer/scraper committed while this pull was merged.
                with local.transaction():
                    if revision(local, 'controls') == observed_revision:
                        with runtime.transaction():
                            runtime.db.execute("INSERT INTO metadata VALUES('controls_cache',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                                (json.dumps({'signature': signature, 'revision': observed_revision, 'report': report}),))
            return report
    finally:
        if owned and getattr(local, 'is_local', False):
            local.close()
