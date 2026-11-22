"""Archive and supersede one approved, unapplied exact repair plan."""

from hashlib import sha256
import json

from job_search_helper.exact_cycle_receipt import (
    REPAIR_RETRY_PLAN_BINDING,
    _sealed_repair_retry_binding,
    repair_retry_has_confirmed_publication,
    repair_retry_receipt_binding,
)
from job_search_helper.exact_local_plan import _apply_id, _validate_plan
from job_search_helper.publication_receipts import _receipt_id


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(raw):
    return sha256(raw.encode('utf-8')).hexdigest()


def _check_selected(inbox, jobs, cycle, company, successor, candidate_raw, active, mirror):
    if active is None and mirror is None and repair_retry_has_confirmed_publication(
            inbox, jobs, cycle, company, require_complete=False):
        actual = jobs.db.execute(
            'SELECT plan_digest FROM exact_local_applications WHERE cycle=? AND company=?',
            (cycle['id'], company),
        ).fetchone()
        if actual == (successor,):
            return 'SUCCESSOR_ALREADY_CONFIRMED'
    if (active is None or active[0] != candidate_raw or mirror is None
            or mirror[0] != successor or inbox.exact_local_state(cycle['id'], company) is None):
        raise ValueError('The archived successor does not match current evidence.')
    return 'SUCCESSOR_ALREADY_SELECTED'


def select_successor(inbox, jobs, cycle, company, candidate, approval, *, timestamp):
    """Switch exact active slots together. Caller owns both normal writer leases.

    The measured operator entry must verify the independent approval, active
    release and saved retry before calling this internal transaction.
    """
    cycle_id = cycle['id']
    retry = cycle['repair_retry']
    binding = repair_retry_receipt_binding(cycle, company)
    _validate_plan(candidate, cycle_id, company)
    successor = candidate['plan_digest']
    candidate_raw = _encode(candidate)
    if (candidate[REPAIR_RETRY_PLAN_BINDING] != binding
            or approval['cycle_id'] != cycle_id or approval['company_id'] != company
            or approval['attempt_id'] != retry['attempt_id']
            or approval['release_id'] != binding['release_id']
            or approval['successor_plan_sha256'] != successor
            or approval['successor_file_sha256'] != _sha(candidate_raw)):
        raise ValueError('The successor does not match this approved repair retry.')

    key = (cycle_id, company)
    db = inbox.connection
    recovery = _encode(approval)
    with inbox.lock, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS rejected_retry_plan_archive (
            cycle TEXT NOT NULL, company TEXT NOT NULL, approval TEXT NOT NULL,
            original_plan TEXT NOT NULL, original_cursor INTEGER NOT NULL CHECK(original_cursor=0),
            original_local_state TEXT NOT NULL, inventory TEXT NOT NULL,
            successor TEXT NOT NULL,
            archived_at TEXT NOT NULL, PRIMARY KEY (cycle, company))''')
        previous = db.execute(
            'SELECT approval,original_plan,original_cursor,original_local_state,inventory,successor '
            'FROM rejected_retry_plan_archive '
            'WHERE cycle=? AND company=?', key).fetchone()
        active = db.execute(
            'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?', key).fetchone()
        mirror = db.execute(
            'SELECT plan_digest,local_operations_digest,remote_projection_digest,state,local_apply_id,'
            'local_records_digest,created_at,updated_at FROM exact_plan_local_state '
            'WHERE cycle=? AND company=?', key).fetchone()

        if previous is not None:
            if (previous[0] != recovery or _sha(previous[1]) != approval['original_file_sha256']
                    or previous[2] != 0 or _sha(previous[3]) != approval['original_local_state_sha256']
                    or _sha(previous[4]) != approval['inventory_file_sha256']
                    or previous[5] != candidate_raw):
                raise ValueError('A different recovery already holds this attempt.')
            return _check_selected(inbox, jobs, cycle, company, successor, candidate_raw, active, mirror)

        inventory = db.execute(
            'SELECT payload,blocked FROM inventories WHERE cycle=? AND company=?', key).fetchone()
        if (inventory is None or inventory[1] != 0
                or _sha(inventory[0]) != approval['inventory_file_sha256']
                or active is None or active[1] != 0
                or _sha(active[0]) != approval['original_file_sha256']
                or mirror is None or mirror[3:6] != ('FROZEN', None, None)
                or mirror[0] != approval['original_plan_sha256']
                or mirror[0] == successor
                or _sha(_encode(mirror)) != approval['original_local_state_sha256']):
            raise ValueError('The approved original zero-apply evidence changed.')
        original = json.loads(active[0])
        _validate_plan(original, cycle_id, company)
        saved_payload = json.loads(inventory[0])
        if (saved_payload.get('inventory_status') != 'complete' or not saved_payload.get('jobs')
                or saved_payload.get('browser_pending_urls') or saved_payload.get('browser_discovery_incomplete')):
            raise ValueError('The archived inventory is not a complete saved retry.')
        for plan in (original, candidate):
            _sealed_repair_retry_binding(cycle, company, saved_payload, plan, binding['request_id'])
            if inbox.find_receipt(company, plan['remote_records']) is not None:
                raise ValueError('An existing receipt matches the frozen records.')
        if (original['plan_digest'] != mirror[0]
                or inbox.exact_local_state(*key) is None):
            raise ValueError('The successor changed the saved inventory or retry authority.')

        for table in ('exact_remote_plans', 'exact_sync_chunks',
                      'exact_legacy_plan_migrations', 'exact_selected_legacy_recoveries',
                      'exact_control_before_prefix_recoveries'):
            if db.execute(f'SELECT 1 FROM {table} WHERE cycle=? AND company=?', key).fetchone():
                raise ValueError('Existing publication or recovery evidence prevents plan selection.')
        if db.execute(
            "SELECT 1 FROM publication_receipts WHERE receipt_id=? OR "
            "(json_extract(binding,'$.company_id')=? AND json_extract(binding,'$.request_id') IN (?,?))",
            (_receipt_id(binding), company, binding['request_id'], cycle_id),
        ).fetchone():
            raise ValueError('Existing receipt prevents plan selection.')
        if jobs.db.execute(
            'SELECT 1 FROM exact_local_applications WHERE cycle=? AND company=?', key
        ).fetchone():
            raise ValueError('An existing Jobs application prevents plan selection.')
        apply_ids = (_apply_id(cycle_id, company, mirror[0]), _apply_id(cycle_id, company, successor))
        for table in ('exact_local_apply_chunks', 'exact_local_acknowledgements'):
            if jobs.db.execute(f'SELECT 1 FROM {table} WHERE apply_id IN (?,?)', apply_ids).fetchone():
                raise ValueError('Existing Jobs apply evidence prevents plan selection.')
        if jobs.db.execute(
            'SELECT 1 FROM scrape_outcomes WHERE request_id=? AND company_id=?',
            (binding['request_id'], company),
        ).fetchone():
            raise ValueError('An existing retry outcome prevents plan selection.')

        archived = (recovery, active[0], active[1], _encode(mirror), inventory[0], candidate_raw)
        db.execute('INSERT INTO rejected_retry_plan_archive VALUES (?,?,?,?,?,?,?,?,?)',
                   (*key, *archived, timestamp))
        db.execute('UPDATE sync_plans SET payload=? WHERE cycle=? AND company=?', (candidate_raw, *key))
        db.execute(
            'UPDATE exact_plan_local_state SET plan_digest=?,local_operations_digest=?,'
            'remote_projection_digest=?,created_at=?,updated_at=? WHERE cycle=? AND company=?',
            (successor, candidate['local_operations_digest'],
             candidate['remote_projection_digest'], timestamp, timestamp, *key),
        )
        if inbox.exact_local_state(*key)['plan_digest'] != successor:
            raise ValueError('Successor plan and its exact marker differ.')
    with inbox.lock:
        saved = db.execute(
            'SELECT approval,original_plan,original_cursor,original_local_state,inventory,successor '
            'FROM rejected_retry_plan_archive WHERE cycle=? AND company=?', key).fetchone()
        if saved != archived or inbox.plan(*key) != (candidate, 0):
            raise ValueError('Committed successor and archive failed readback.')
    return 'SUCCESSOR_SELECTED'
