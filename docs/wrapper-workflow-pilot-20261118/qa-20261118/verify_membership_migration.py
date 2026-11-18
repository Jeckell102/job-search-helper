"""Rehearse exact legacy migration on a disposable backup copy; never production."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

HERE = Path(__file__).resolve().parent
STAGE = HERE.parent / 'wrapper-workflow-20261118'
sys.path.insert(0, str(STAGE / 'host'))
from coordinator_store import Store
from migrate_campaign_membership import migrate_campaign_membership


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(snapshot):
    paths = sorted((STAGE / 'backlog').glob('batch-*.json'))
    items = [item for path in paths for item in json.loads(path.read_text())]
    ids = json.loads((HERE / 'reviewed-hold-ids.json').read_text())
    with sqlite3.connect('file:' + str(snapshot) + '?mode=ro', uri=True) as db:
        batches = {key: json.loads(value) for key, value in db.execute('SELECT digest,task_ids FROM batches')}
    expected = dict(count=102, sha256='e3237070c6c895675a1ae57caa0a35d1cb150938bf0d3b6b4a9425478c740b02',
                    original_batches={key: value for key, value in batches.items() if set(value) & set(ids)})
    (HERE / 'expected-legacy-cohort.json').write_text(json.dumps(expected, indent=2) + '\n')
    audit = dict(snapshot_sha256=sha(snapshot), batch_files={path.name: sha(path) for path in paths},
                 reviewed_ids_sha256=sha(HERE / 'reviewed-hold-ids.json'), expected_cohort=expected)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'tasks.sqlite3'
        shutil.copy2(snapshot, path)
        store = Store(tmp)
        before = sha(path)
        kw = dict(reviewed_hold_ids=ids, expected_cohort=expected)
        audit['dry_run'] = migrate_campaign_membership(store, 'integration-backlog-20261118', items, **kw)
        assert audit['dry_run']['clean'] and len(audit['dry_run']['held']) == 102
        assert before == sha(path), 'Dry run modified database bytes'
        audit['db_before_sha256'] = before
        audit['db_after_dry_run_sha256'] = sha(path)
        audit['first_apply'] = migrate_campaign_membership(store, 'integration-backlog-20261118', items, apply=True, **kw)
        audit['db_after_apply_sha256'] = sha(path)
        audit['second_apply'] = migrate_campaign_membership(store, 'integration-backlog-20261118', items, apply=True, **kw)
        assert audit['second_apply']['changed'] == []
        audit['db_after_second_apply_sha256'] = sha(path)
        assert audit['db_after_apply_sha256'] == audit['db_after_second_apply_sha256']
        with store.connect() as db:
            audit['integrity'] = db.execute('PRAGMA quick_check').fetchone()[0]
            audit['controls'] = dict(db.execute('SELECT key,value FROM settings'))
        try:
            migrate_campaign_membership(store, 'integration-backlog-20261118', items,
                                        reviewed_hold_ids=ids[:-1], expected_cohort=expected, apply=True)
        except ValueError:
            audit['shortened_reviewed_cohort_rejected'] = True
        else:
            raise AssertionError('Shortened reviewed cohort accepted')
    audit['result'] = 'PASS'
    (HERE / 'membership-migration-verification.json').write_text(json.dumps(audit, indent=2) + '\n')
    print('PASS: exact 102-task cohort; dry run unchanged; second apply unchanged; shortened cohort rejected; integrity OK.')


if __name__ == '__main__':
    run(Path(sys.argv[1]))
