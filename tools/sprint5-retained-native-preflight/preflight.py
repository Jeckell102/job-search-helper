from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

project = Path('/home/chris/job-search-helper_old')
root = project / '.state'
paths = tuple(root / name for name in ('state.db', 'jobs.sqlite3', 'inventories.sqlite3'))
native_uris = {path.as_uri() for path in paths}
cycle = 'CYC-B639C6D864EC'
original_connect = sqlite3.connect


def snapshot():
    entries = sorted(root.iterdir()) + [root]
    return {str(path): (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            for path in entries if (s := path.lstat())}


def check_journals():
    for path in paths:
        for suffix in ('-wal', '-journal'):
            candidate = path.with_name(path.name + suffix)
            if candidate.exists() and candidate.stat().st_size:
                raise RuntimeError('Native SQLite journal is busy; no preview performed.')


def guard(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.spawn')):
        raise RuntimeError('Read-only preview attempted external activity.')
    if event == 'open' and len(args) == 3 and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        raise RuntimeError('Read-only preview attempted writable file open.')


def immutable_connect(database_uri, *args, **kwargs):
    path, separator, query = str(database_uri).partition('?')
    if not separator or path not in native_uris or 'mode=ro' not in query.split('&') or kwargs.get('uri') is not True:
        raise RuntimeError('Preview attempted another SQLite connection.')
    connection = original_connect(database_uri + '&immutable=1', *args, **kwargs)
    connection.execute('PRAGMA query_only=ON')
    return connection


check_journals()
before = snapshot()
sys.path.insert(0, str(project / 'src'))
sys.addaudithook(guard)
sqlite3.connect = immutable_connect
from job_search_helper.control_before_prefix_runner import preview_control_before_prefix_recovery
from job_search_helper.exact_control_before_prefix_recovery import (
    _explicit_ownership, _operation_value, _read_presence, _validate_ownership,
)
from job_search_helper.exact_legacy_migration_runner import _read_retained, preview_retained_legacy_migration
from job_search_helper.core import job_key as posting_key, material_hash
from job_search_helper.integration_release import digest
from job_search_helper.repository import _equivalent
from job_search_helper.selected_recovery_runner import preview_selected_recovery
from job_search_helper.sqlite_repository import SQLiteRepository

with closing(sqlite3.connect(paths[2].as_uri() + '?mode=ro', uri=True)) as inbox:
    plans = inbox.execute('SELECT company,cursor FROM sync_plans WHERE cycle=? ORDER BY company', (cycle,)).fetchall()

expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
results = []
for company, cursor in plans:
    assert re.fullmatch(r'COMP-[0-9A-F]+', company)
    result = {'company_id': company, 'legacy_cursor': cursor}
    for kind, run in (
        ('normal_preview', lambda: preview_retained_legacy_migration(paths[2], paths[1], cycle, company)),
        ('selected_preview', lambda: preview_selected_recovery(paths[2], paths[1], cycle, company, expires_at=expires)),
        ('control_before_prefix_preview', lambda: preview_control_before_prefix_recovery(
            paths[2], paths[1], cycle, company, expires_at=expires)),
    ):
        try:
            item = run()
        except (ValueError, RuntimeError, sqlite3.Error) as exc:
            message = str(exc)
            if (re.fullmatch(r'[a-z0-9_]{8,110}', message)
                    or re.fullmatch(r'Exact (?:legacy|retained) [A-Za-z0-9 .,-]{3,110}', message)):
                reason = message
            else:
                reason = {'type': type(exc).__name__, 'message_sha256': sha256(message.encode()).hexdigest()}
            result[kind] = {'state': 'HELD', 'reason': reason}
        else:
            columns = ('local_operation_count', 'remote_operation_count', 'protected_conflict_count',
                       'verified_prefix_cursor', 'remaining_operation_count')
            result[kind] = {'state': 'PREVIEW_ONLY', **{key: item[key] for key in columns if key in item}}
    results.append(result)

selected_company = 'COMP-0054'
destination, inventory, plan, cursor, _ = _read_retained(paths[2], cycle, selected_company)
operations = plan['operations']
with closing(SQLiteRepository(paths[1], destination, readonly=True)) as repository:
    rows, _ = _read_presence(repository, operations)

control_index, = [index for index, entry in enumerate(operations) if entry['tab'] == 'Companies']
control = operations[control_index]
control_row = rows[control_index]
ownership = []
for index, (operation, row) in enumerate(zip(operations, rows)):
    if operation['tab'] != 'Job History':
        continue
    try:
        _validate_ownership(selected_company, [operation, control], [row, control_row])
    except ValueError as exc:
        assert str(exc) == 'control_before_prefix_job_ownership_mismatch'
        item = {
            'plan_operation_number': index + 1,
            'in_verified_prefix': index < cursor,
            'operation_sha256': digest(operation),
            'local_row_present': row is not None,
        }
        try:
            declared = _explicit_ownership(operation)
        except ValueError:
            item['status'] = 'LEGACY_OPERATION_OWNERSHIP_INTERNALLY_CONFLICTS'
        else:
            if declared and row is not None:
                local_company = str(row.get('Company') or '').strip()
                planned_source = declared.get('Source Hash')
                local_source = str(row.get('Source Hash') or '').strip()
                job_key = str(row.get('Job Key') or '').strip()
                guards = operation.get('expected', {})
                expected_source = str(guards.get('Source Hash') or '').strip()
                retained_matches = [posting for posting in inventory['jobs'] if posting_key(
                    selected_company, posting['ats'], posting.get('posting_id', ''), posting['url'],
                ) == job_key]
                item.update({
                    'status': 'EXPLICIT_OWNERSHIP_DIFFERS',
                    'job_key_matches': job_key == str(operation['identity'].get('Job Key', '')).strip(),
                    'company_matches': local_company == declared.get('Company'),
                    'planned_source_present': bool(planned_source),
                    'current_source_present': bool(local_source),
                    'source_matches': planned_source == local_source,
                    'planned_source_fingerprint': digest(planned_source) if planned_source else None,
                    'local_source_fingerprint': digest(local_source) if local_source else None,
                    'expected_before_source_present': bool(expected_source),
                    'expected_before_source_matches_local': bool(expected_source and expected_source == local_source),
                    'expected_fields_match_local_count': sum(
                        _equivalent(header, expected, row.get(header)) for header, expected in guards.items()
                    ),
                    'expected_fields_total': len(guards),
                    'retained_matching_posting_count': len(retained_matches),
                    'retained_posting_hash_matches_planned': len(retained_matches) == 1
                    and material_hash(retained_matches[0]) == planned_source,
                    'append_if_missing': operation.get('append_if_missing') is True,
                })
                with closing(SQLiteRepository(paths[1], destination, readonly=True)) as repository:
                    for label, fingerprint in (('planned', planned_source), ('current', local_source)):
                        if not fingerprint or not job_key:
                            continue
                        item[label + '_matching_local_evidence_count'] = len(repository.matches(
                            'Job Evidence', {'Job Key': job_key, 'Source Hash': fingerprint},
                        ))
                        item[label + '_matching_legacy_evidence_operation_count'] = sum(
                            _operation_value(other, 'Job Key') == job_key
                            and _operation_value(other, 'Source Hash') == fingerprint
                            for other in operations if other['tab'] == 'Job Evidence'
                        )
            else:
                item['status'] = 'REQUIRED_METADATA_OWNER_GUARD_UNPROVED'
        ownership.append(item)

assert snapshot() == before
check_journals()
report = {
    'observed_at': datetime.now().astimezone().isoformat(timespec='seconds'),
    'cycle_id': cycle,
    'exact_plan_previews': results,
    'saronic_exact_job_history_ownership_holds': ownership,
    'stores_unchanged': True,
    'network_and_python_writes_denied': True,
}
print(json.dumps(report, indent=2))
