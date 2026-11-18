"""One-time exact-objective migration for pre-autopilot imported tasks."""
import argparse
import json
from pathlib import Path

from coordinator_store import Store, campaign_manifest_digest
from coordinator_acceptance import initial_scope, validate_scope, files as acceptance_files
from coordinator_identity import canonical_identity, canonical_requirements, bind_identity, validate_bound_identity


def backfill(store, items):
    records = {}
    for item in items:
        objective, integration = item.get('objective'), item.get('integration')
        if not isinstance(objective, str) or not isinstance(integration, dict):
            raise ValueError('Every campaign record needs an objective and structured integration identity.')
        canonical_identity(integration)
        if objective in records and records[objective] != integration:
            raise ValueError('Conflicting campaign metadata for one objective.')
        records[objective] = integration
    updated = matched = 0
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows = db.execute('SELECT id,state FROM tasks ORDER BY rowid').fetchall()
        for task_id, raw in rows:
            state = json.loads(raw)
            integration = records.get(state.get('objective'))
            if integration is None or not state.get('isolated_workspace'):
                continue
            matched += 1
            if state.get('integration'):
                if state['integration'] != integration:
                    raise ValueError('Existing task metadata conflicts: ' + task_id)
                continue
            state['integration'] = integration
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), task_id))
            updated += 1
    return {'records': len(records), 'matched': matched, 'updated': updated}


def backfill_campaign_identity(store, items, *, apply=False, baseline_root=None, expected_baseline_manifest=None, expected_assignment_manifest=None):
    """Bind only exact reviewed campaign members; never resume or reset work."""
    records = {}
    companies = set()
    for item in items:
        identity = canonical_identity(item.get('integration'))
        objective = item.get('objective')
        if not isinstance(objective, str) or not objective:
            raise ValueError('Reviewed identity manifest needs an objective.')
        if objective in records or identity['company_id'] in companies:
            raise ValueError('Duplicate reviewed identity manifest entry.')
        records[objective] = item
        companies.add(identity['company_id'])
    report = dict(matched=[], changed=[], skipped=[], registered=[])
    baseline_verified = False
    assignment_verified = False
    from coordinator_baseline import files as baseline_files, binding
    if expected_assignment_manifest is not None:
        if baseline_root is None or baseline_files(Path(baseline_root)) != expected_assignment_manifest:
            raise ValueError('Reviewed whole baseline differs from current source.')
        assignment_verified = True
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        controls = {key: json.loads(value) for key, value in db.execute('SELECT key,value FROM settings')}
        if (controls.get('queue_enabled', True) or controls.get('campaign_enabled', False)
                or controls.get('autopilot_enabled', False) or controls.get('pilot_task')):
            raise ValueError('Identity backfill requires all scheduling controls OFF.')
        states = [json.loads(raw) for (raw,) in db.execute('SELECT state FROM tasks ORDER BY rowid')]
        if any(s['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for s in states):
            raise ValueError('Identity backfill requires no active tasks.')
        if db.execute('SELECT 1 FROM receipts WHERE result IS NULL LIMIT 1').fetchone():
            raise ValueError('Identity backfill requires no unfinished receipt.')
        if db.execute("SELECT 1 FROM inference_receipts WHERE status IN ('DISPATCHING','UNCERTAIN') LIMIT 1").fetchone():
            raise ValueError('Migration requires no unresolved inference receipt.')
        provenance = {}
        for batch, raw in db.execute('SELECT digest,task_ids FROM batches'):
            for task_id in json.loads(raw):
                provenance.setdefault(task_id, []).append(batch)
        seen = set()
        pending = []
        for state in states:
            if not state.get('campaign_id'):
                report['skipped'].append(state['id'])
                continue
            item = records.get(state.get('objective'))
            if (item is None or item['integration'] != state.get('integration')
                    or state.get('tests') != item['integration']['tests']
                    or state.get('campaign_company_id') != item['integration']['company_id']
                    or state.get('campaign_manifest_digest') != campaign_manifest_digest(state)):
                raise ValueError('Reviewed identity disagrees with campaign member: ' + state['id'])
            key = (state['campaign_id'], state['campaign_company_id'])
            if key in seen:
                raise ValueError('Duplicate campaign/company identity during backfill.')
            seen.add(key)
            if len(provenance.get(state['id'], [])) != 1:
                raise ValueError('Campaign member needs exactly one original import provenance.')
            existing = db.execute('SELECT current_task_id,identity_digest,import_digest FROM campaign_company_registry WHERE campaign_id=? AND company_id=?', key).fetchone()
            updated = json.loads(json.dumps(state))
            updated['evidence_requirements'] = canonical_requirements(state['integration'], state['evidence_requirements'])
            updated = bind_identity(updated)
            if state.get('integration_identity_digest'):
                validate_bound_identity(state)
                if updated != state:
                    raise ValueError('Existing immutable identity differs from reviewed binding.')
            if not updated.get('edit_scope'):
                if any(updated.get(k, 0) for k in ('calls', 'tokens', 'sessions')) or db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1', (state['id'],)).fetchone():
                    raise ValueError('Legacy edit-scope binding requires an untouched reviewed task.')
                updated['edit_scope'] = initial_scope(updated)
            validate_scope(updated)
            if 'acceptance_baseline_manifest' not in updated:
                if (baseline_root is None or not expected_baseline_manifest
                        or (not baseline_verified and acceptance_files(Path(baseline_root)) != expected_baseline_manifest)):
                    raise ValueError('Legacy acceptance baseline requires a reviewed exact source manifest.')
                if any(updated.get(k, 0) for k in ('calls', 'tokens', 'sessions')) or db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1', (state['id'],)).fetchone():
                    raise ValueError('Legacy acceptance binding requires an untouched task.')
                baseline_verified = True
                updated['acceptance_baseline_manifest'] = expected_baseline_manifest
            if 'assignment_baseline' not in updated:
                if (baseline_root is None or not expected_assignment_manifest
                        or (not assignment_verified and baseline_files(Path(baseline_root)) != expected_assignment_manifest)):
                    raise ValueError('Legacy assignment baseline requires a reviewed whole source manifest.')
                if any(updated.get(k, 0) for k in ('calls', 'tokens', 'sessions')) or db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1', (state['id'],)).fetchone():
                    raise ValueError('Legacy assignment binding requires an untouched reviewed task.')
                assignment_verified = True
                updated['assignment_baseline'] = binding(expected_assignment_manifest)
            elif (updated['assignment_baseline'] != binding(updated['assignment_baseline'].get('manifest', {}))
                    or expected_assignment_manifest is not None and updated['assignment_baseline'] != binding(expected_assignment_manifest)):
                raise ValueError('Existing assignment baseline binding differs from reviewed inputs.')
            digest = updated['integration_identity_digest']
            original_batch = provenance[state['id']][0]
            if existing and existing != (state['id'], digest, original_batch):
                raise ValueError('Existing registry conflicts with reviewed identity.')
            report['matched'].append(state['id'])
            if updated != state:
                report['changed'].append(state['id'])
            if not existing:
                report['registered'].append(state['id'])
            pending.append((updated, key, digest, original_batch, existing))
        if baseline_verified and acceptance_files(Path(baseline_root)) != expected_baseline_manifest:
            raise ValueError('Reviewed baseline changed during migration.')
        if assignment_verified and baseline_files(Path(baseline_root)) != expected_assignment_manifest:
            raise ValueError('Reviewed whole baseline changed during migration.')
        if apply:
            for state, key, digest, original_batch, existing in pending:
                if state['id'] in report['changed']:
                    db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), state['id']))
                if not existing:
                    db.execute('INSERT INTO campaign_company_registry(campaign_id,company_id,current_task_id,identity_digest,import_digest,retry_of) VALUES(?,?,?,?,?,NULL)',
                               (*key, state['id'], digest, original_batch))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tasks', type=Path)
    parser.add_argument('batches', nargs='+', type=Path)
    parser.add_argument('--identity', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--baseline-root', type=Path)
    parser.add_argument('--baseline-manifest', type=Path)
    parser.add_argument('--assignment-manifest', type=Path)
    args = parser.parse_args()
    items = []
    for path in args.batches:
        items.extend(json.loads(path.read_text()))
    if args.identity:
        result = backfill_campaign_identity(Store(args.tasks), items, apply=args.apply, baseline_root=args.baseline_root,
            expected_baseline_manifest=json.loads(args.baseline_manifest.read_text()) if args.baseline_manifest else None,
            expected_assignment_manifest=json.loads(args.assignment_manifest.read_text()) if args.assignment_manifest else None)
    else:
        result = backfill(Store(args.tasks), items)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
