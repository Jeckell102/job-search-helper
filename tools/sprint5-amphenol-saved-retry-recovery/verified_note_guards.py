"""Recover missing local-only guards from the verified pre-apply note rows."""

from hashlib import sha256
import json

from job_search_helper.exact_cycle_receipt import repair_retry_receipt_binding
from job_search_helper.exact_local_plan import _apply_id, _digest, _final_identity, _validate_plan
from job_search_helper.publication_receipts import LOCAL_COMMITTED


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _sha(value):
    return sha256(value.encode('utf-8')).hexdigest()


def _read_verified_parent(jobs, cycle_id, company, plan):
    parent = jobs.db.execute(
        'SELECT apply_id,plan_digest,inventory_payload_digest,local_operations_digest,'
        'remote_projection_digest,row_scope,state FROM exact_local_applications WHERE cycle=? AND company=?',
        (cycle_id, company),
    ).fetchone()
    expected = (_apply_id(cycle_id, company, plan['plan_digest']), plan['plan_digest'],
                plan['inventory_payload_digest'], plan['local_operations_digest'], plan['remote_projection_digest'])
    if parent is None or parent[:5] != expected or parent[6] != 'VERIFIED':
        raise ValueError('The exact saved note application is not durably verified.')
    return parent


def _enriched_scope(jobs, apply_id, original_raw, local_operations):
    chunks = jobs.db.execute(
        'SELECT start_cursor,operation_count,operations_digest,before_records,state '
        'FROM exact_local_apply_chunks WHERE apply_id=? ORDER BY start_cursor', (apply_id,),
    ).fetchall()
    before = []
    for start, count, operation_digest, raw, state in chunks:
        entries = json.loads(raw)
        if (start != len(before) or state != 'VERIFIED' or count != len(entries) or count == 0
                or operation_digest != _digest(local_operations[start:start + count])):
            raise ValueError('The verified pre-apply note evidence does not match the original operations.')
        before.extend(zip(local_operations[start:start + count], entries))
    if len(before) != len(local_operations):
        raise ValueError('The verified note application has incomplete pre-apply evidence.')

    repaired = 0
    rows = json.loads(original_raw)
    for item in rows:
        if item['tab'] != 'Job History' or 'Source Hash' in item['guards']:
            continue
        pairs = [(op, row) for op, row in before
                 if op['tab'] == item['tab'] and _final_identity(op) == item['identity']]
        if len(pairs) != 1:
            raise ValueError('A missing note guard lacks one stable pre-apply identity.')
        op, holder = pairs[0]
        previous = holder['rows']
        if (holder['tab'] != item['tab'] or holder['identity'] != op['identity']
                or len(previous) != 1 or previous[0]['row_id'] != item['row_id']
                or op.get('append_if_missing') or set(op.get('append_notes', {})) != {'Review Notes'}
                or any('Source Hash' in op.get(field, {}) for field in ('values', 'on_insert', 'append_notes'))):
            raise ValueError('Only existing Job History note-appends can recover a Source Hash guard.')
        matches = jobs.matches('Job History', item['identity'])
        prior_hash = previous[0]['row'].get('Source Hash')
        if (len(matches) != 1 or matches[0][0] != item['row_id']
                or not isinstance(prior_hash, str) or not prior_hash.strip()
                or matches[0][1].get('Source Hash') != prior_hash):
            raise ValueError('The pre-apply note Source Hash is absent or no longer matches.')
        item['guards']['Source Hash'] = prior_hash
        repaired += 1
    if repaired != 4:
        raise ValueError('The approved Amphenol recovery requires exactly four unchanged note guards.')
    return _encode(rows), _sha(_encode(chunks))


def _measure(jobs, cycle_id, company, plan, *, original=None):
    _, operations, _ = _validate_plan(plan, cycle_id, company)
    parent = _read_verified_parent(jobs, cycle_id, company, plan)
    before = parent[5] if original is None else original
    enriched, chunk_digest = _enriched_scope(jobs, parent[0], before, operations)
    seal = {'apply_id': parent[0], 'before_scope_sha256': _sha(before),
            'enriched_scope_sha256': _sha(enriched), 'chunk_evidence_sha256': chunk_digest}
    return before, enriched, seal


def measure_note_guards(jobs, cycle_id, company, plan):
    """Produce non-content fingerprints from the exact held application readback."""
    return _measure(jobs, cycle_id, company, plan)[2]


def adopt_note_guards(inbox, jobs, cycle, company, approval, *, timestamp):
    """The measured caller owns both ordinary locks and current qualifications."""
    key = (cycle['id'], company)
    binding = repair_retry_receipt_binding(cycle, company)
    if (approval['cycle_id'], approval['company_id'], approval['attempt_id'], approval['release_id']) != (
            *key, cycle['repair_retry']['attempt_id'], binding['release_id']):
        raise ValueError('The note guard approval belongs to another retry.')
    claims = _encode(approval)
    with inbox.lock, jobs.transaction():
        active = inbox.plan(*key)
        if active is None:
            raise ValueError('The exact note plan is no longer active.')
        plan, cursor = active
        mirror = inbox.exact_local_state(*key)
        receipt = inbox.receipt({'binding': binding})
        if (plan['plan_digest'] != approval['plan_digest'] or cursor != len(plan['local_operations'])
                or not mirror or mirror['state'] != 'LOCAL_VERIFIED' or mirror['plan_digest'] != plan['plan_digest']
                or not receipt or receipt['binding'] != binding or receipt['records'] != plan['remote_records']):
            raise ValueError('The saved verified note plan or receipt no longer matches approval.')
        raw = inbox.connection.execute('SELECT payload FROM sync_plans WHERE cycle=? AND company=?', key).fetchone()[0]
        if _sha(raw) != approval['plan_file_sha256']:
            raise ValueError('The saved verified note plan bytes changed.')
        db = jobs.db
        db.execute('''CREATE TABLE IF NOT EXISTS exact_retry_note_guard_archive (
            apply_id TEXT PRIMARY KEY, approval TEXT NOT NULL, original_scope TEXT NOT NULL,
            selected_scope TEXT NOT NULL, archived_at TEXT NOT NULL)''')
        parent = _read_verified_parent(jobs, *key, plan)
        existing = db.execute('SELECT approval,original_scope,selected_scope FROM exact_retry_note_guard_archive '
                              'WHERE apply_id=?', (parent[0],)).fetchone()
        before, enriched, seal = _measure(jobs, *key, plan, original=existing[1] if existing else None)
        if seal != approval['verified_scope'] or mirror['local_apply_id'] != parent[0]:
            raise ValueError('The verified pre-apply note evidence changed after approval.')
        if existing is not None:
            if existing != (claims, before, enriched) or parent[5] != enriched:
                raise ValueError('The archived note guard adoption changed.')
            return 'NOTE_GUARDS_ALREADY_ADOPTED'
        if (receipt['state'] != LOCAL_COMMITTED or receipt['acknowledgement_id']
                or inbox.exact_remote_state(*key) is not None
                or inbox.connection.execute('SELECT 1 FROM exact_sync_chunks WHERE cycle=? AND company=?', key).fetchone()
                or db.execute('SELECT 1 FROM exact_local_acknowledgements WHERE apply_id=?', (parent[0],)).fetchone()):
            raise ValueError('Remote work already exists before note guard adoption.')
        db.execute('INSERT INTO exact_retry_note_guard_archive VALUES (?,?,?,?,?)',
                   (parent[0], claims, before, enriched, timestamp))
        changed = db.execute('UPDATE exact_local_applications SET row_scope=? '
                             'WHERE apply_id=? AND plan_digest=? AND state=? AND row_scope=?',
                             (enriched, parent[0], plan['plan_digest'], 'VERIFIED', before)).rowcount
        if changed != 1:
            raise ValueError('Verified note guards changed before the update.')
    return 'NOTE_GUARDS_ADOPTED'
