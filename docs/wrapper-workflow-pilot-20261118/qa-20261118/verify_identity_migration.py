"""Rehearse reviewed identity binding after membership on a disposable database."""
from verify_membership_migration import *
from backfill_campaign_metadata import backfill_campaign_identity
from coordinator_identity import validate_bound_identity


def verify(snapshot):
    items = [item for path in sorted((STAGE / 'backlog').glob('batch-*.json')) for item in json.loads(path.read_text())]
    ids = json.loads((HERE / 'reviewed-hold-ids.json').read_text())
    expected = json.loads((HERE / 'expected-legacy-cohort.json').read_text())
    audit = {'snapshot_sha256': sha(snapshot)}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tasks.sqlite3'
        shutil.copy2(snapshot, path)
        store = Store(tmp)
        migrate_campaign_membership(store, 'integration-backlog-20261118', items, apply=True,
                                    reviewed_hold_ids=ids, expected_cohort=expected)
        before_states = {s['id']: s for s in store.all()}
        before = sha(path)
        audit['dry_run'] = backfill_campaign_identity(store, items)
        assert sha(path) == before
        assert set(audit['dry_run']['matched']) == set(ids)
        audit['first_apply'] = backfill_campaign_identity(store, items, apply=True)
        after = sha(path)
        audit['second_apply'] = backfill_campaign_identity(store, items, apply=True)
        assert audit['second_apply']['changed'] == audit['second_apply']['registered'] == []
        assert sha(path) == after
        additions = {'integration_identity','integration_identity_digest','worker_assignment',
                     'worker_assignment_digest','identity_binding_digest','evidence_requirements_digest'}
        for state in store.all():
            old = before_states[state['id']]
            if state['id'] not in ids:
                assert state == old
                continue
            validate_bound_identity(state)
            for key, value in old.items():
                if key != 'evidence_requirements':
                    assert state[key] == value, (state['id'], key)
            assert set(state) - set(old) <= additions
        with store.connect() as db:
            audit['registry_count'] = db.execute('SELECT COUNT(*) FROM campaign_company_registry').fetchone()[0]
            audit['integrity'] = db.execute('PRAGMA quick_check').fetchone()[0]
            audit['controls'] = dict(db.execute('SELECT key,value FROM settings'))
        assert audit['registry_count'] == 102 and audit['integrity'] == 'ok'
        audit['db_before_sha256'], audit['db_after_sha256'] = before, after
    audit['result'] = 'PASS'
    (HERE / 'identity-migration-verification.json').write_text(json.dumps(audit, indent=2) + '\n')
    print('PASS: 102 exact identities and registry rows; dry run unchanged; second apply unchanged; old budgets/status/history preserved; integrity OK.')

if __name__ == '__main__':
    verify(Path(sys.argv[1]))
