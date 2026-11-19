"""Crash-durable exact-company local application for version-2 plans.

Every bounded mutation chunk and its APPLIED journal row share one SQLite
transaction.  APPLIED is therefore a no-replay boundary: recovery reads back
and verifies that chunk and never invokes the local commit again.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Mapping

from .publication_receipts import record_fingerprints
from .repository import RepositoryError, _equivalent
from .sqlite_repository import timestamp


APPLYING = 'APPLYING'
VERIFIED = 'VERIFIED'
LOCAL_COMMITTED = VERIFIED  # compatibility name; no publication receipt claim


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _apply_id(cycle_id, company_id, plan_digest):
    return 'ELA-' + _digest([cycle_id, company_id, plan_digest])[:32]


def _install(repository):
    if getattr(repository, 'readonly', True):
        raise RepositoryError('Exact local application requires a writable local repository.')
    repository._ensure_exact_local_schema()


def _validate_identity(cycle_id, company_id):
    if (not isinstance(cycle_id, str) or not cycle_id.strip()
            or not isinstance(company_id, str) or not company_id.strip()):
        raise ValueError('Exact local application requires cycle and Company IDs.')
    return cycle_id.strip(), company_id.strip()


def _validate_plan(plan, cycle_id=None, company_id=None):
    from .exact_cycle_planner import _exact_plan_digest
    if not isinstance(plan, Mapping) or plan.get('exact_plan_version') != 2:
        raise ValueError('Exact local application requires an immutable v2 plan.')
    local = plan.get('local_operations')
    remote = plan.get('remote_projection')
    fingerprint_version = plan.get('record_fingerprint_version', 1)
    if fingerprint_version not in {1, 2}:
        raise ValueError('Exact v2 plan record fingerprint version is invalid.')
    fingerprint_options = {'include_guard_only': fingerprint_version == 2}
    if not isinstance(local, list) or not local or not isinstance(remote, list) or not remote:
        raise ValueError('Exact v2 plan has no complete local/remote streams.')
    if not all((
        plan.get('plan_digest') == _exact_plan_digest(plan),
        plan.get('local_operations_digest') == _digest(local),
        plan.get('local_expected_records') == record_fingerprints(
            local, **fingerprint_options),
        plan.get('local_expected_records_digest') == _digest(plan.get('local_expected_records')),
        plan.get('remote_projection_digest') == _digest(remote),
        plan.get('remote_records') == record_fingerprints(
            remote, **fingerprint_options),
        plan.get('remote_records_digest') == _digest(plan.get('remote_records')),
    )):
        raise ValueError('Exact v2 plan digest or frozen record evidence is invalid.')
    if cycle_id is not None and plan.get('cycle_id') != cycle_id:
        raise ValueError('Exact v2 plan cycle identity mismatch.')
    if company_id is not None and plan.get('company_id') != company_id:
        raise ValueError('Exact v2 plan Company identity mismatch.')
    return dict(plan), local, remote


def _final_identity(operation):
    identity = dict(operation.get('identity', {}))
    if not identity:
        raise ValueError('Exact local operation requires a stable identity.')
    for values in (operation.get('on_insert', {}), operation.get('values', {})):
        if not isinstance(values, Mapping):
            raise ValueError('Exact local operation values must be mappings.')
        for key in tuple(identity):
            if key in values:
                identity[key] = values[key]
    return identity


def _rows_for_operations(repository, operations):
    rows, seen = {}, set()
    for operation in operations:
        tab = operation.get('tab')
        matches = repository.matches(tab, _final_identity(operation))
        if len(matches) != 1:
            raise ValueError('Exact local operation identity is missing or ambiguous.')
        row_id, row = matches[0]
        if (tab, row_id) in seen:
            raise ValueError('Exact local plan repeats one record across chunks.')
        rows.setdefault(tab, []).append(row)
        seen.add((tab, row_id))
    return rows


def _expected_records(plan, operations):
    expected = record_fingerprints(
        operations, include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
    if any(plan['local_expected_records'].get(key) != value
           for key, value in expected.items()):
        raise ValueError('Exact local chunk is not in the frozen record set.')
    return expected


def _capture_before(repository, operations):
    before, dirty = [], []
    for operation in operations:
        tab = operation['tab']
        identity = dict(operation['identity'])
        matches = repository.matches(tab, identity)
        before.append({'tab': tab, 'identity': identity,
                       'rows': [{'row_id': rid, 'row': row} for rid, row in matches]})
        for row_id, _row in matches:
            headers = [header for (header,) in repository.db.execute(
                'SELECT header FROM dirty WHERE tab=? AND row_id=? ORDER BY header',
                (tab, row_id))]
            if headers:
                dirty.append({'tab': tab, 'row_id': row_id, 'headers': headers})
    return before, dirty


def _row_scope(plan):
    scope = []
    guarded = {'Source Hash', 'Added to Opportunities?', 'Salary / Range'}
    migration = plan.get('legacy_migration', {})
    if migration:
        protected = migration.get('protected_fields')
        if (migration.get('version') != 'legacy-exact-plan-migration-v1'
                or not isinstance(protected, list)
                or protected != ['Decision', 'Review Status']):
            raise ValueError('Exact legacy migration guards are invalid.')
        guarded.update(protected)
    for operation in plan['remote_projection']:
        append_if_missing = operation.get('append_if_missing')
        if append_if_missing is None:
            # Older already-sealed test/compatibility projections omitted the
            # flag and could only express inserts through nonempty on_insert.
            # Materialize that deterministic meaning into the durable scope.
            append_if_missing = bool(operation.get('on_insert'))
        if type(append_if_missing) is not bool:
            raise ValueError('Exact remote scope requires sealed insert semantics.')
        fields = set()
        for key in ('on_insert', 'values', 'append_notes'):
            fields.update(operation.get(key, {}))
        identity = _final_identity(operation)
        matches = [local for local in plan['local_operations']
                   if local.get('tab') == operation.get('tab')
                   and _final_identity(local) == identity]
        if len(matches) != 1:
            raise ValueError('Exact remote scope has no unique frozen local operation.')
        local = matches[0]
        final = dict(local.get('expected', {}))
        final.update(local.get('on_insert', {}))
        final.update(local.get('values', {}))
        guards = {header: copy.deepcopy(value) for header, value in final.items()
                  if header in guarded}
        scope.append({'tab': operation['tab'],
                      'identity': identity,
                      'fields': sorted(fields),
                      'append_if_missing': append_if_missing,
                      'guards': guards,
                      'expected': copy.deepcopy(operation.get('expected', {}))})
    return scope


def _resolved_row_scope(repository, plan):
    """Resolve local row hints while retaining stable identity authority."""
    scope = _row_scope(plan)
    for item in scope:
        matches = repository.matches(item['tab'], item['identity'])
        if len(matches) != 1:
            raise ValueError('Exact row scope identity is missing or ambiguous.')
        item['row_id'] = matches[0][0]
        row = matches[0][1]
        if any(not _equivalent(header, row.get(header, ''), value)
               for header, value in item.get('guards', {}).items()):
            raise ValueError('Exact row scope guard changed before verification.')
    return scope


def _revalidate_row_scope(repository, scope):
    for item in scope:
        matches = repository.matches(item['tab'], item['identity'])
        if len(matches) != 1 or matches[0][0] != item.get('row_id'):
            raise ValueError('Exact row scope hint no longer matches its stable identity.')
        row = matches[0][1]
        if any(not _equivalent(header, row.get(header, ''), value)
               for header, value in item.get('guards', {}).items()):
            raise ValueError('Exact row scope guard changed after verification.')


def _ensure_parent(repository, cycle_id, company_id, plan, stamp):
    apply_id = _apply_id(cycle_id, company_id, plan['plan_digest'])
    row = repository.db.execute(
        'SELECT apply_id,plan_digest,inventory_payload_digest,local_operations_digest,'
        'remote_projection_digest,row_scope,state FROM exact_local_applications '
        'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
    expected = (apply_id, plan['plan_digest'], plan['inventory_payload_digest'],
                plan['local_operations_digest'], plan['remote_projection_digest'],
                _canonical(_row_scope(plan)))
    if row is not None:
        if tuple(row[:5]) != expected[:5]:
            raise ValueError('Exact local application conflicts with its journal.')
        scope = json.loads(row[5])
        if row[6] == VERIFIED:
            _revalidate_row_scope(repository, scope)
        elif row[5] != expected[5]:
            raise ValueError('Applying exact row scope changed before verification.')
        return apply_id, row[6]
    repository.db.execute(
        'INSERT INTO exact_local_applications VALUES (?,?,?,?,?,?,?,?,?,?,?)',
        (apply_id, cycle_id, company_id, plan['plan_digest'],
         plan['inventory_payload_digest'], plan['local_operations_digest'],
         plan['remote_projection_digest'], expected[5], stamp, None, APPLYING))
    return apply_id, APPLYING


def apply_exact_local_chunk(repository, cycle_id, company_id, plan, cursor,
                            *, max_operations=100):
    """Apply one bounded chunk atomically with its APPLIED journal row."""
    cycle_id, company_id = _validate_identity(cycle_id, company_id)
    plan, local, _remote = _validate_plan(plan, cycle_id, company_id)
    if type(cursor) is not int or cursor < 0 or cursor >= len(local):
        raise ValueError('Exact local chunk cursor is outside the frozen plan.')
    if type(max_operations) is not int or not 1 <= max_operations <= 100:
        raise ValueError('Exact local chunk bound must be between 1 and 100.')
    _install(repository)
    count = min(max_operations, len(local) - cursor)
    chunk = copy.deepcopy(local[cursor:cursor + count])
    operations_digest = _digest(chunk)
    expected = _expected_records(plan, chunk)
    expected_digest = _digest(expected)
    stamp = timestamp()
    with repository.transaction():
        apply_id, parent_state = _ensure_parent(
            repository, cycle_id, company_id, plan, stamp)
        existing = repository.db.execute(
            'SELECT operation_count,operations_digest,expected_records,'
            'expected_records_digest,state FROM exact_local_apply_chunks '
            'WHERE apply_id=? AND start_cursor=?', (apply_id, cursor)).fetchone()
        if existing is not None:
            if (existing[0] != count or existing[1] != operations_digest
                    or existing[2] != _canonical(expected)
                    or existing[3] != expected_digest):
                raise ValueError('Exact local chunk conflicts with its journal.')
            return {'apply_id': apply_id, 'cursor': cursor, 'count': count,
                    'state': existing[4], 'records_digest': expected_digest,
                    'recovered': True}
        if parent_state == VERIFIED:
            raise ValueError('Verified exact application is missing a chunk.')
        rows = repository.db.execute(
            'SELECT start_cursor,operation_count,state FROM exact_local_apply_chunks '
            'WHERE apply_id=? ORDER BY start_cursor', (apply_id,)).fetchall()
        boundary = 0
        for start, prior_count, state in rows:
            if start != boundary or state != VERIFIED:
                raise ValueError('Exact local chunks are not a verified prefix.')
            boundary += prior_count
        if cursor != boundary:
            raise ValueError('Exact local cursor is not the next verified boundary.')
        before, dirty = _capture_before(repository, chunk)
        repository._commit_in_transaction(chunk)
        observed = record_fingerprints(
            chunk, _rows_for_operations(repository, chunk),
            include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
        if observed != expected:
            raise ValueError('Local mutation readback differs from the frozen plan.')
        repository.db.execute(
            'INSERT INTO exact_local_apply_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (apply_id, cursor, count, operations_digest, _canonical(before),
             _canonical(expected), expected_digest, _canonical(dirty),
             stamp, None, 'APPLIED'))
    return {'apply_id': apply_id, 'cursor': cursor, 'count': count,
            'state': 'APPLIED', 'records_digest': expected_digest,
            'recovered': False}


def verify_exact_local_chunk(repository, cycle_id, company_id, plan, cursor):
    """Read back APPLIED evidence; never reapply an ambiguous chunk."""
    cycle_id, company_id = _validate_identity(cycle_id, company_id)
    plan, local, _remote = _validate_plan(plan, cycle_id, company_id)
    _install(repository)
    apply_id = _apply_id(cycle_id, company_id, plan['plan_digest'])
    row = repository.db.execute(
        'SELECT operation_count,operations_digest,expected_records,'
        'expected_records_digest,state FROM exact_local_apply_chunks '
        'WHERE apply_id=? AND start_cursor=?', (apply_id, cursor)).fetchone()
    if row is None or cursor < 0 or cursor + row[0] > len(local):
        raise ValueError('Exact local chunk journal is missing or invalid.')
    chunk = local[cursor:cursor + row[0]]
    if row[1] != _digest(chunk) or row[2] != _canonical(_expected_records(plan, chunk)):
        raise ValueError('Exact local chunk changed after persistence.')
    observed = record_fingerprints(
        chunk, _rows_for_operations(repository, chunk),
        include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
    if _canonical(observed) != row[2] or _digest(observed) != row[3]:
        raise ValueError('Exact local readback differs from APPLIED evidence.')
    if row[4] == VERIFIED:
        return {'apply_id': apply_id, 'cursor': cursor, 'count': row[0],
                'state': VERIFIED, 'records_digest': row[3], 'recovered': True}
    with repository.transaction():
        updated = repository.db.execute(
            'UPDATE exact_local_apply_chunks SET state=?,verified_at=? '
            'WHERE apply_id=? AND start_cursor=? AND state=?',
            (VERIFIED, timestamp(), apply_id, cursor, 'APPLIED')).rowcount
        if updated != 1:
            raise ValueError('Exact local chunk changed during verification.')
    return {'apply_id': apply_id, 'cursor': cursor, 'count': row[0],
            'state': VERIFIED, 'records_digest': row[3], 'recovered': False}


def verify_exact_local_plan(repository, cycle_id, company_id, plan):
    """Verify the complete local result and monotonically seal its parent."""
    cycle_id, company_id = _validate_identity(cycle_id, company_id)
    plan, local, _remote = _validate_plan(plan, cycle_id, company_id)
    _install(repository)
    apply_id = _apply_id(cycle_id, company_id, plan['plan_digest'])
    parent = repository.db.execute(
        'SELECT plan_digest,state FROM exact_local_applications WHERE apply_id=?',
        (apply_id,)).fetchone()
    if parent is None or parent[0] != plan['plan_digest']:
        raise ValueError('Exact local parent journal is missing or changed.')
    rows = repository.db.execute(
        'SELECT start_cursor,operation_count,state FROM exact_local_apply_chunks '
        'WHERE apply_id=? ORDER BY start_cursor', (apply_id,)).fetchall()
    boundary = 0
    for cursor, count, state in rows:
        if cursor != boundary or state != VERIFIED:
            raise ValueError('Exact local plan lacks a verified prefix.')
        boundary += count
    if boundary != len(local):
        raise ValueError('Exact local plan is not fully verified.')
    observed = record_fingerprints(
        local, _rows_for_operations(repository, local),
        include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
    if observed != plan['local_expected_records']:
        raise ValueError('Complete local readback differs from the frozen plan.')
    if parent[1] == VERIFIED:
        _revalidate_row_scope(repository, json.loads(repository.db.execute(
            'SELECT row_scope FROM exact_local_applications WHERE apply_id=?',
            (apply_id,)).fetchone()[0]))
        return {'apply_id': apply_id, 'state': VERIFIED,
                'records_digest': _digest(observed), 'recovered': True}
    resolved_scope = _canonical(_resolved_row_scope(repository, plan))
    with repository.transaction():
        updated = repository.db.execute(
            'UPDATE exact_local_applications SET state=?,verified_at=?,row_scope=? '
            'WHERE apply_id=? AND state=?',
            (VERIFIED, timestamp(), resolved_scope, apply_id, APPLYING)).rowcount
        if updated != 1:
            raise ValueError('Exact local parent changed during verification.')
    return {'apply_id': apply_id, 'state': VERIFIED,
            'records_digest': _digest(observed), 'recovered': False}


def commit_exact_local_plan(repository, cycle_id, company_id, plan, *, max_operations=100):
    """Apply/read back all chunks; APPLIED chunks are never reapplied."""
    cycle_id, company_id = _validate_identity(cycle_id, company_id)
    plan, local, _remote = _validate_plan(plan, cycle_id, company_id)
    _install(repository)
    cursor, recovered = 0, False
    while cursor < len(local):
        result = apply_exact_local_chunk(
            repository, cycle_id, company_id, plan, cursor,
            max_operations=max_operations)
        recovered = recovered or result['recovered']
        verify_exact_local_chunk(repository, cycle_id, company_id, plan, cursor)
        cursor += result['count']
    result = verify_exact_local_plan(repository, cycle_id, company_id, plan)
    result['recovered'] = recovered or result['recovered']
    return result


def adopt_verified_legacy_local_plan(repository, cycle_id, company_id, plan,
                                     *, timestamp_value):
    """Journal already-applied legacy rows as v2 without replaying a mutation."""
    cycle_id, company_id = _validate_identity(cycle_id, company_id)
    plan, local, _remote = _validate_plan(plan, cycle_id, company_id)
    migration = plan.get('legacy_migration')
    if (not isinstance(migration, Mapping)
            or migration.get('version') != 'legacy-exact-plan-migration-v1'
            or migration.get('cycle_id') != cycle_id
            or migration.get('company_id') != company_id
            or migration.get('original_local_cursor') != len(local)
            or migration.get('legacy_operation_count') != len(local)
            or not isinstance(timestamp_value, str) or not timestamp_value.strip()
            or len(local) > 100):
        raise ValueError('Exact legacy local adoption evidence is invalid.')
    _install(repository)
    from .exact_legacy_migration import _capture_full_snapshot
    apply_id = _apply_id(cycle_id, company_id, plan['plan_digest'])
    with repository.transaction():
        rows, snapshot_digest = _capture_full_snapshot(repository, local)
        if snapshot_digest != migration.get('current_local_snapshot_digest'):
            raise ValueError('Exact legacy local snapshot changed before adoption.')
        rows_by_tab = {
            tab: [row for operation, row in zip(local, rows)
                  if operation.get('tab') == tab]
            for tab in {operation.get('tab') for operation in local}
        }
        observed = record_fingerprints(
            local, rows_by_tab,
            include_guard_only=plan.get('record_fingerprint_version', 1) == 2)
        if observed != plan['local_expected_records']:
            raise ValueError('Exact legacy local records differ before adoption.')
        scope = _resolved_row_scope(repository, plan)
        for item in scope:
            baseline = repository.baseline(item['tab'], item['row_id'])
            if baseline is None or item['append_if_missing']:
                continue
            dirty = {header for (header,) in repository.db.execute(
                'SELECT header FROM dirty WHERE tab=? AND row_id=?',
                (item['tab'], item['row_id']))}
            missing = (set(item['fields']) - set(item['identity'])) - dirty
            if missing:
                raise ValueError(
                    'Exact legacy selected field is no longer pending publication: '
                    + ', '.join(sorted(missing)))
        existing = repository.db.execute(
            'SELECT plan_digest,inventory_payload_digest,local_operations_digest,'
            'remote_projection_digest,row_scope,state FROM exact_local_applications '
            'WHERE cycle=? AND company=?', (cycle_id, company_id)).fetchone()
        expected_parent = (
            plan['plan_digest'], plan['inventory_payload_digest'],
            plan['local_operations_digest'], plan['remote_projection_digest'],
            _canonical(scope), VERIFIED)
        if existing is not None:
            if tuple(existing) != expected_parent:
                raise ValueError('Exact legacy local adoption conflicts with its journal.')
            chunk = repository.db.execute(
                'SELECT operation_count,operations_digest,expected_records,'
                'expected_records_digest,state FROM exact_local_apply_chunks '
                'WHERE apply_id=? AND start_cursor=0', (apply_id,)).fetchone()
            expected_chunk = (len(local), _digest(local), _canonical(observed),
                              _digest(observed), VERIFIED)
            if chunk != expected_chunk:
                raise ValueError('Exact legacy adopted chunk evidence changed.')
            _revalidate_row_scope(repository, scope)
            return {'apply_id': apply_id, 'state': VERIFIED,
                    'records_digest': _digest(observed), 'recovered': True,
                    'snapshot_digest': snapshot_digest}
        if repository.db.execute(
                'SELECT 1 FROM exact_local_applications WHERE apply_id=? OR plan_digest=?',
                (apply_id, plan['plan_digest'])).fetchone():
            raise ValueError('Exact legacy local adoption identity already exists.')
        before, dirty_before = _capture_before(repository, local)
        stamp = timestamp_value.strip()
        repository.db.execute(
            'INSERT INTO exact_local_applications VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (apply_id, cycle_id, company_id, plan['plan_digest'],
             plan['inventory_payload_digest'], plan['local_operations_digest'],
             plan['remote_projection_digest'], _canonical(scope), stamp, stamp,
             VERIFIED))
        repository.db.execute(
            'INSERT INTO exact_local_apply_chunks VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            (apply_id, 0, len(local), _digest(local), _canonical(before),
             _canonical(observed), _digest(observed), _canonical(dirty_before),
             stamp, stamp, VERIFIED))
    return {'apply_id': apply_id, 'state': VERIFIED,
            'records_digest': _digest(observed), 'recovered': False,
            'snapshot_digest': snapshot_digest}


def exact_local_plan(repository, cycle_id, company_id):
    """Return one authoritative application without discovering other work."""
    cycle_id, company_id = _validate_identity(cycle_id, company_id)
    _install(repository)
    row = repository.db.execute(
        'SELECT apply_id,plan_digest,inventory_payload_digest,local_operations_digest,'
        'remote_projection_digest,row_scope,created_at,verified_at,state '
        'FROM exact_local_applications WHERE cycle=? AND company=?',
        (cycle_id, company_id)).fetchone()
    if row is None:
        return None
    keys = ('apply_id', 'plan_digest', 'inventory_payload_digest',
            'local_operations_digest', 'remote_projection_digest', 'row_scope',
            'created_at', 'verified_at', 'state')
    result = dict(zip(keys, row)); result['row_scope'] = json.loads(result['row_scope'])
    if result['state'] == VERIFIED:
        _revalidate_row_scope(repository, result['row_scope'])
    result.update(cycle_id=cycle_id, company_id=company_id)
    return result
