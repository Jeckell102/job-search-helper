"""Explicit, audited adoption of legacy imports; no inference or queue activation."""
import argparse
import hashlib
import json
from pathlib import Path

from coordinator_store import Store, campaign_manifest_digest


def entry_digest(item):
    return campaign_manifest_digest(dict(objective=item['objective'],
                                         tests=item['integration']['tests'], integration=item['integration']))


def migrate_campaign_membership(store, campaign_id, items, *, apply=False, reviewed_hold_ids=(), expected_cohort=None):
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise ValueError('A campaign ID is required.')
    report = dict(campaign_id=campaign_id, clean=True, held=[], user_paused=[],
                  skipped=[], excluded=[], selected=[], finished=[], conflicting=[], changed=[])
    records = {}
    companies = set()
    for item in items:
        identity = item.get('integration', {})
        company_id = identity.get('company_id')
        if (not isinstance(item.get('objective'), str) or not company_id
                or not identity.get('company') or not identity.get('configured_url')
                or not identity.get('tests') or not identity.get('source_targets')):
            raise ValueError('Every manifest entry requires complete integration identity.')
        if company_id in companies or item['objective'] in records:
            raise ValueError('Duplicate company or objective in campaign manifest.')
        companies.add(company_id)
        records[item['objective']] = item
    reviewed = set(reviewed_hold_ids)
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        controls = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM settings')}
        if (controls.get('queue_enabled', True) or controls.get('autopilot_enabled', False)
                or controls.get('pilot_task') is not None):
            raise ValueError('Migration requires queue and autopilot OFF and pilot unset.')
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity check failed.')
        states = [json.loads(raw) for (raw,) in db.execute('SELECT state FROM tasks ORDER BY rowid')]
        if expected_cohort is not None:
            cohort = []
            for item in items:
                for state in states:
                    if state['id'] in reviewed and state.get('objective') == item['objective']:
                        cohort.append(dict(task_id=state['id'], company_id=state.get('integration', {}).get('company_id'),
                                           objective=state['objective'], integration=state.get('integration')))
            digest = hashlib.sha256(json.dumps(cohort, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            original_batches = {digest: json.loads(ids) for digest, ids in db.execute('SELECT digest,task_ids FROM batches')}
            provenance = expected_cohort.get('original_batches', {})
            if (len(reviewed) != expected_cohort.get('count') or len(cohort) != len(reviewed)
                    or digest != expected_cohort.get('sha256') or not provenance
                    or any(original_batches.get(key) != value for key, value in provenance.items())
                    or not reviewed.issubset({task for ids in provenance.values() for task in ids})):
                raise ValueError('Reviewed legacy cohort or original batch provenance changed.')
            report['reviewed_cohort'] = dict(count=len(cohort), sha256=digest,
                                             original_batch_digests=sorted(provenance))
        if any(s['status'] in ('RUNNING', 'QUEUED', 'PAUSING') for s in states):
            raise ValueError('Migration requires no active tasks.')
        if db.execute('SELECT count(*) FROM receipts WHERE result IS NULL').fetchone()[0]:
            raise ValueError('Migration requires no unfinished receipts.')
        pending = []
        seen = set()
        matched_ids = set()
        for state in states:
            task_id = state['id']
            item = records.get(state.get('objective'))
            if item is None or not state.get('isolated_workspace'):
                report['skipped'].append(task_id)
                continue
            matched_ids.add(task_id)
            identity = item['integration']
            digest = entry_digest(item)
            if (state.get('integration') != identity or identity['company_id'] in seen
                    or state.get('campaign_id') not in (None, campaign_id)
                    or state.get('campaign_manifest_digest') not in (None, digest)):
                report['conflicting'].append(task_id)
                continue
            seen.add(identity['company_id'])
            if state.get('campaign_id') == campaign_id:
                disposition = state.get('campaign_disposition')
                labels = {'HELD_FOR_CAMPAIGN': 'held', 'USER_PAUSED': 'user_paused',
                          'EXCLUDED': 'excluded', 'SELECTED': 'selected', 'CAMPAIGN_FINISHED': 'finished'}
                if (disposition not in labels or state.get('campaign_company_id') != identity['company_id']
                        or state.get('campaign_manifest_digest') != digest):
                    report['conflicting'].append(task_id)
                else:
                    report[labels[disposition]].append(task_id)
                continue
            untouched = (state['status'] == 'PAUSED' and state['phase'] == 'baseline'
                         and state.get('activated_at') is None and state.get('selected_at') is None
                         and all(state.get(key, 0) == 0 for key in ('calls', 'tokens', 'sessions'))
                         and state.get('authorization_version') == 1 and state.get('mode') == 'develop'
                         and state.get('workflow_version') == 2
                         and not any(state.get(key) for key in ('manifest', 'checkpoint', 'workflow'))
                         and not db.execute('SELECT 1 FROM receipts WHERE task=? LIMIT 1', (task_id,)).fetchone())
            if expected_cohort is not None:
                untouched = (untouched and state.get('max_sessions') == 10
                             and state.get('tests') == identity['tests']
                             and state.get('evidence_requirements', {}).get('version') == 1
                             and all(state.get(key) == {} for key in ('manifest', 'checkpoint', 'workflow')))
            if not untouched:
                report['conflicting' if task_id in reviewed else 'skipped'].append(task_id)
                continue
            release = task_id in reviewed and state.get('stop_requested') is True and state.get('reason') in (
                'Pause requested.', 'Held for one-company campaign selection.')
            if task_id in reviewed and not release:
                report['conflicting'].append(task_id)
                continue
            disposition = 'HELD_FOR_CAMPAIGN' if release else 'USER_PAUSED'
            state.update(campaign_id=campaign_id, campaign_company_id=identity['company_id'],
                         campaign_disposition=disposition, campaign_manifest_digest=digest,
                         campaign_migration=dict(version=1, previous_reason=state.get('reason'),
                                                 reviewed_hold=release))
            if release:
                state.update(stop_requested=False, reason='Held for one-company campaign selection.')
            report['held' if release else 'user_paused'].append(task_id)
            report['changed'].append(task_id)
            pending.append(state)
        unknown_reviewed = reviewed - matched_ids
        report['conflicting'].extend(sorted(unknown_reviewed))
        report['clean'] = not report['conflicting']
        if apply:
            if not report['clean']:
                raise ValueError('Migration conflict: ' + ', '.join(report['conflicting']))
            for state in pending:
                db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(state), state['id']))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tasks', type=Path)
    parser.add_argument('campaign_id')
    parser.add_argument('batches', nargs='+', type=Path)
    parser.add_argument('--reviewed-hold-ids', type=Path, required=True)
    parser.add_argument('--expected-cohort', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    items = [item for path in args.batches for item in json.loads(path.read_text())]
    print(json.dumps(migrate_campaign_membership(Store(args.tasks), args.campaign_id, items,
          apply=args.apply, reviewed_hold_ids=json.loads(args.reviewed_hold_ids.read_text()),
          expected_cohort=json.loads(args.expected_cohort.read_text())), indent=2))


if __name__ == '__main__':
    main()
