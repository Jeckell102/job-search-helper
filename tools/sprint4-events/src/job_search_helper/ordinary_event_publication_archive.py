"""Keep ordinary Company-event publication evidence across exact Inbox cleanup."""
import json
import re

from . import publication_receipts
from .exact_cycle_planner import _digest, _exact_plan_digest
from .exact_cycle_sync import _remote_intent_id


_SCHEMA = 'ordinary-company-event-exact-publication-v1'
_DIGEST_FIELDS = {
    'plan_digest', 'inventory_payload_digest', 'local_records_digest', 'local_operations_digest',
    'planned_projection_digest', 'projection_digest', 'remote_records_digest', 'selected_fields_digest',
    'receipt_id', 'acknowledgement_id',
}
_TABLE = 'ordinary_event_publication_archive'
_ACK_TABLE = 'ordinary_event_exact_ack_proofs'
_INBOX_WORK_TABLES = (
    'inventories', 'sync_plans', 'exact_remote_plans', 'exact_sync_chunks', 'exact_plan_local_state',
    'exact_legacy_plan_migrations', 'exact_selected_legacy_recoveries', 'exact_control_before_prefix_recoveries',
    'exact_legacy_delivery_evidence',
)
_INBOX_OTHER_ARCHIVE_TABLES = (
    'exact_legacy_plan_migration_archive', 'exact_legacy_delivery_evidence_archive',
    'exact_selected_legacy_recovery_archive', 'selected_retry_publication_archive',
)


def _digest_text(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _row(db, cycle_id, company_id, request_id):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_TABLE,)).fetchone() is None:
        return None
    rows = db.execute(
        'SELECT cycle,company,request_id,receipt_id,proof_sha256,evidence '
        'FROM ordinary_event_publication_archive WHERE cycle=? OR request_id=?',
        (cycle_id, request_id),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1 or rows[0][:3] != (cycle_id, company_id, request_id):
        raise ValueError('Ordinary event publication archive has a competing owner.')
    return rows[0]


def _verify(db, local, evidence, cycle_id, company_id, binding):
    from .inbox import InventoryInbox
    required = _DIGEST_FIELDS | {'schema', 'cycle_id', 'company_id', 'binding',
                                  'apply_id', 'intent_id', 'final_stage'}
    if (not isinstance(evidence, dict) or set(evidence) != required
            or evidence['schema'] != _SCHEMA or evidence['cycle_id'] != cycle_id
            or evidence['company_id'] != company_id
            or evidence['binding'] != binding or binding['company_id'] != company_id
            or binding.get('authority') != 'ordinary-company-event-exact-v2'
            or binding.get('cycle_id') != cycle_id
            or not binding['request_id'].startswith('company-event:')
            or evidence['final_stage'] not in {'complete', 'partial'}
            or any(not _digest_text(evidence[key]) for key in _DIGEST_FIELDS)
            or not isinstance(evidence['apply_id'], str) or not evidence['apply_id']
            or evidence['intent_id'] != _remote_intent_id(
                cycle_id, company_id, evidence['plan_digest'], evidence['projection_digest'])):
        raise ValueError('Ordinary event publication archive identity or evidence changed.')
    receipt = publication_receipts.receipt(db, binding)
    if (receipt is None or receipt['binding'] != binding or receipt['receipt_id'] != evidence['receipt_id']
            or receipt['state'] != publication_receipts.SYNC_CONFIRMED
            or receipt['acknowledgement_id'] != evidence['acknowledgement_id']
            or _digest(receipt['records']) != evidence['remote_records_digest']):
        raise ValueError('Ordinary event publication archive lacks the exact confirmed Sheets receipt.')
    acknowledgement = InventoryInbox._verify_exact_local_acknowledgement(
        db, local, cycle_id, company_id, evidence['plan_digest'], evidence['receipt_id'],
        evidence['acknowledgement_id'], expected_apply_id=evidence['apply_id'],
    )
    if acknowledgement['selected_fields_digest'] != evidence['selected_fields_digest']:
        raise ValueError('Ordinary event publication archive lacks the exact Jobs acknowledgement.')
    applied = local.db.execute(
        'SELECT inventory_payload_digest,local_operations_digest,remote_projection_digest '
        'FROM exact_local_applications WHERE apply_id=?', (evidence['apply_id'],),
    ).fetchone()
    if applied != (evidence['inventory_payload_digest'], evidence['local_operations_digest'],
                   evidence['planned_projection_digest']):
        raise ValueError('Ordinary event publication archive lacks the exact local plan digests.')
    witness = _local_ack_proof(local.db, evidence['apply_id'])
    if witness != (evidence['apply_id'], evidence['receipt_id'], evidence['acknowledgement_id'],
                   evidence['plan_digest'], evidence['local_records_digest'],
                   evidence['projection_digest'], evidence['intent_id']):
        raise ValueError('Ordinary event publication archive disagrees with its durable readback proof.')


def _local_ack_proof(db, apply_id):
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_ACK_TABLE,)).fetchone() is None:
        return None
    return db.execute(
        'SELECT apply_id,receipt_id,acknowledgement_id,plan_digest,local_records_digest,'
        'projection_digest,intent_id FROM ordinary_event_exact_ack_proofs WHERE apply_id=?',
        (apply_id,),
    ).fetchone()


def record_ordinary_event_ack_proof(inbox, local, cycle_id, company_id, *, apply_id, plan_digest,
                                   receipt_id, acknowledgement_id, projection_digest, intent_id):
    """Bind full readback evidence within the trusted Jobs acknowledgement transaction."""
    saved = inbox.plan(cycle_id, company_id)
    plan = saved[0] if saved else None
    if not isinstance(plan, dict) or 'ordinary_company_event' not in plan:
        return
    local_state = inbox.exact_local_state(cycle_id, company_id)
    digest = plan.get('local_expected_records_digest')
    if (not local.db.in_transaction or local_state is None or local_state['state'] != 'LOCAL_VERIFIED'
            or local_state['local_apply_id'] != apply_id or local_state['plan_digest'] != plan_digest
            or plan.get('plan_digest') != _exact_plan_digest(plan)
            or not _digest_text(digest) or local_state['local_records_digest'] != digest
            or _digest(plan.get('local_expected_records')) != digest):
        raise ValueError('Ordinary event lacks the verified local conditions for acknowledgement.')
    witness = (apply_id, receipt_id, acknowledgement_id, plan_digest, digest, projection_digest, intent_id)
    local.db.execute(
        'CREATE TABLE IF NOT EXISTS ordinary_event_exact_ack_proofs ('
        'apply_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE, acknowledgement_id TEXT NOT NULL, '
        'plan_digest TEXT NOT NULL, local_records_digest TEXT NOT NULL, '
        'projection_digest TEXT NOT NULL, intent_id TEXT NOT NULL)',
    )
    existing = _local_ack_proof(local.db, apply_id)
    if existing is None:
        local.db.execute('INSERT INTO ordinary_event_exact_ack_proofs VALUES (?,?,?,?,?,?,?)', witness)
    elif existing != witness:
        raise ValueError('Ordinary event acknowledgement conflicts with its existing exact proof.')


def archive_before_cleanup(inbox, local, cycle_id, company_id, plan, *, binding):
    """Persist the terminal proof in the caller's Inbox cleanup transaction."""
    db = inbox.connection
    if not db.in_transaction:
        raise ValueError('Ordinary event publication archive requires the Inbox cleanup transaction.')
    local_state = inbox.exact_local_state(cycle_id, company_id)
    remote = inbox.exact_remote_state(cycle_id, company_id)
    if (plan.get('exact_plan_version') != 2 or plan.get('cycle_id') != cycle_id
            or plan.get('company_id') != company_id or plan.get('plan_digest') != _exact_plan_digest(plan)
            or local_state is None or local_state['state'] != 'LOCAL_VERIFIED'
            or local_state['plan_digest'] != plan['plan_digest']
            or remote is None or remote['state'] != 'LOCAL_ACKNOWLEDGED'
            or remote['local_plan_digest'] != plan['plan_digest'] or remote['delivery_mode'] != 'write_once'
            or not isinstance(remote['projection'], list) or not remote['projection']
            or remote['remote_cursor'] != len(remote['projection'])
            or remote['projection_digest'] != _digest(remote['projection'])):
        raise ValueError('Ordinary event publication cleanup has no verified terminal plan and intent.')
    stored_inventory = inbox.get(cycle_id, company_id)
    if (stored_inventory is None or stored_inventory[1]
            or _digest(stored_inventory[0]) != plan['inventory_payload_digest']):
        raise ValueError('Ordinary event publication cleanup has no exact original inventory.')
    acknowledgement = inbox._require_exact_local_acknowledgement(
        local, cycle_id, company_id, plan['plan_digest'], remote['receipt_id'],
        remote['acknowledgement_id'], expected_apply_id=local_state['local_apply_id'],
    )
    evidence = {
        'schema': _SCHEMA, 'cycle_id': cycle_id, 'company_id': company_id,
        'binding': binding, 'plan_digest': plan['plan_digest'],
        'inventory_payload_digest': plan['inventory_payload_digest'],
        'local_records_digest': local_state['local_records_digest'],
        'local_operations_digest': local_state['local_operations_digest'],
        'planned_projection_digest': local_state['remote_projection_digest'],
        'projection_digest': remote['projection_digest'], 'remote_records_digest': _digest(plan['remote_records']),
        'receipt_id': remote['receipt_id'], 'intent_id': remote['intent_id'],
        'acknowledgement_id': remote['acknowledgement_id'], 'apply_id': acknowledgement['apply_id'],
        'selected_fields_digest': acknowledgement['selected_fields_digest'], 'final_stage': plan['final']['stage'],
    }
    _verify(db, local, evidence, cycle_id, company_id, binding)
    db.execute(
        'CREATE TABLE IF NOT EXISTS ordinary_event_publication_archive ('
        'cycle TEXT PRIMARY KEY, company TEXT NOT NULL, request_id TEXT NOT NULL UNIQUE, '
        'receipt_id TEXT NOT NULL UNIQUE, proof_sha256 TEXT NOT NULL, evidence TEXT NOT NULL)',
    )
    row = (cycle_id, company_id, binding['request_id'], evidence['receipt_id'], _digest(evidence), _encode(evidence))
    existing = _row(db, cycle_id, company_id, binding['request_id'])
    if existing is None:
        db.execute('INSERT INTO ordinary_event_publication_archive VALUES (?,?,?,?,?,?)', row)
    elif existing != row:
        raise ValueError('Ordinary event publication archive conflicts with exact cleanup.')
    return evidence


def read_ordinary_event_publication(inbox, local, cycle_id, company_id, *, binding):
    """Recheck both durable acknowledgements against the independently reopened event."""
    with inbox.lock:
        return verify_ordinary_event_publication(inbox.connection, local, cycle_id, company_id, binding=binding)


def verify_ordinary_event_publication(db, local, cycle_id, company_id, *, binding):
    """Use the same terminal proof from either an open Inbox or a read-only connection."""
    row = _row(db, cycle_id, company_id, binding['request_id'])
    if row is None:
        return None
    evidence = json.loads(row[-1])
    if (not isinstance(evidence, dict)
            or row[3:] != (evidence.get('receipt_id'), _digest(evidence), _encode(evidence))):
        raise ValueError('Ordinary event publication archive bytes do not match its stored evidence.')
    if inbox_has_exact_work(db, cycle_id):
        raise ValueError('Ordinary event publication archive conflicts with active Inbox work.')
    _verify(db, local, evidence, cycle_id, company_id, binding)
    return evidence


def inbox_has_exact_work(db, cycle_id):
    if any(db.execute(f'SELECT 1 FROM {table} WHERE cycle=? LIMIT 1', (cycle_id,)).fetchone()
           for table in _INBOX_WORK_TABLES):
        return True
    return any(
        db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (table,)).fetchone()
        and db.execute(f'SELECT 1 FROM {table} WHERE cycle=? LIMIT 1', (cycle_id,)).fetchone()
        for table in _INBOX_OTHER_ARCHIVE_TABLES
    )
