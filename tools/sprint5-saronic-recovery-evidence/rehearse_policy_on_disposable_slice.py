"""Rehearse the saved two-operation delta on a disposable repository slice."""
from contextlib import closing
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote, urlparse

SOURCE = Path('/home/chris/.local/state/job-search-helper-backups/current-scraper-20261121-090919/project')
ROOT = Path(__file__).resolve().parent
target = ROOT / 'fixture.sqlite3'
state = SOURCE / '.state'
safe_read_db = {state / name for name in ('inventories.sqlite3', 'jobs.sqlite3')}
sys.path.insert(0, str(SOURCE / 'src'))


def audit(event, args):
    if event.startswith(('socket.', 'subprocess.', 'os.exec', 'os.fork', 'os.posix_spawn')):
        raise RuntimeError('External activity is forbidden in fixture rehearsal')
    if event == 'sqlite3.connect':
        parsed = urlparse(str(args[0]))
        path = Path(unquote(parsed.path))
        if not ((path in safe_read_db and parsed.query == 'mode=ro&immutable=1') or path == target):
            raise RuntimeError('Unexpected database')
    if event == 'open' and len(args) == 3 and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
        if not isinstance(args[0], int) and not Path(args[0]).resolve().is_relative_to(ROOT):
            raise RuntimeError('Writes are confined to the disposable fixture')


sys.addaudithook(audit)
from job_search_helper.core import job_key, material_hash
from job_search_helper.exact_control_before_prefix_recovery import _reconcile_present_suffix
from job_search_helper.repository import _equivalent
from job_search_helper.sqlite_repository import SQLiteRepository, REVIEW_FIELDS


def copied_db(name):
    db = sqlite3.connect((state / name).as_uri() + '?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA query_only=ON')
    return db


def main():
    with closing(copied_db('inventories.sqlite3')) as inbox:
        identity = ('CYC-B639C6D864EC', 'COMP-0054')
        plan_sql = 'SELECT payload,cursor FROM sync_plans WHERE cycle=? AND company=?'
        inventory_sql = 'SELECT payload FROM inventories WHERE cycle=? AND company=?'
        raw, cursor = inbox.execute(plan_sql, identity).fetchone()
        plan = json.loads(raw)['operations']
        inventory = json.loads(inbox.execute(inventory_sql, identity).fetchone()[0])
    assert cursor == 67 and len(plan) == 208
    operation, evidence = plan[193:195]
    key = operation['identity']['Job Key']
    with closing(copied_db('jobs.sqlite3')) as jobs:
        row_id, raw, raw_policies = jobs.execute(
            'SELECT r.row_id,r.data,r.policies FROM records r JOIN lookups l ON (r.tab,r.row_id)=(l.tab,l.row_id) '
            'WHERE l.tab=? AND l.header=? AND l.value=?', ('Job History', 'Job Key', key)).fetchone()
        old_row = json.loads(raw)
        assert jobs.execute('SELECT count(*) FROM manual_choices WHERE tab=? AND row_id=?',
                            ('Job History', row_id)).fetchone()[0] == 1
        old_evidence_rows = jobs.execute(
            'SELECT r.data,r.policies FROM records r JOIN lookups l ON (r.tab,r.row_id)=(l.tab,l.row_id) '
            'WHERE l.tab=? AND l.header=? AND l.value=?', ('Job Evidence', 'Job Key', key)).fetchall()
    assert operation['expected']['Source Hash'] == old_row['Source Hash']
    assert old_row['Decision'] and operation['values']['Decision'] == ''
    assert evidence['identity'] == {'Job Key': key, 'Source Hash': operation['values']['Source Hash']}
    [retained_posting] = [posting for posting in inventory['jobs'] if job_key(
        identity[1], posting['ats'], posting.get('posting_id', ''), posting['url']) == key]
    assert material_hash(retained_posting) == evidence['identity']['Source Hash']
    with closing(SQLiteRepository(target, 'disposable-local-fixture', initialize=True)) as fixture:
        fixture.import_rows('Job History', [(2, old_row)], policies={2: json.loads(raw_policies)},
                            protect_existing_choices=True)
        fixture.import_rows('Job Evidence', [(number, json.loads(raw)) for number,(raw,_) in enumerate(old_evidence_rows,2)],
                            policies={number: json.loads(policies) for number,(_,policies) in enumerate(old_evidence_rows,2)})
        before = fixture.matches('Job History', {'Job Key': key})[0][1]
        result = fixture.commit([operation, evidence])
        after = fixture.matches('Job History', {'Job Key': key})[0][1]
        changed = sorted(name for name in after if after[name] != before[name])
        assert not set(changed).intersection(REVIEW_FIELDS)
        assert after['Decision'] == before['Decision'] and after['Review Notes'] == before['Review Notes']
        assert after['Source Hash'] == evidence['identity']['Source Hash']
        assert len(fixture.matches('Job Evidence', evidence['identity'])) == 1
        assert len(fixture.matches('Job Evidence', {'Job Key': key, 'Source Hash': old_row['Source Hash']})) == 1
    # A recovery successor must treat this existing posting as update-only.
    # The frozen original operation remains unchanged and stays in the backup.
    authored = deepcopy(operation)
    authored['append_if_missing'] = False
    authored.pop('on_insert', None)
    values = authored['values']
    for field in REVIEW_FIELDS:
        values.pop(field, None)
    authored['expected'].update({
        'Company': old_row['Company'],
        'Job Key': key,
        'Salary / Range': old_row['Salary / Range'],
        'Decision': old_row['Decision'],
        'Review Status': old_row['Review Status'],
    })
    projected, _ = _reconcile_present_suffix([authored, evidence], [old_row, None])
    assert len(projected) == 2 and projected[1] == evidence
    effective = projected[0]
    assert effective['identity'] == operation['identity'] and not effective['append_if_missing']
    assert effective['expected']['Source Hash'] == old_row['Source Hash']
    assert effective['values']['Source Hash'] == evidence['identity']['Source Hash']
    effective_delta = sorted(name for name, value in effective['values'].items()
                             if not _equivalent(name, old_row.get(name, ''), value))
    assert effective_delta == changed
    assert set(effective['values']).isdisjoint(REVIEW_FIELDS)
    assert all(effective['expected'][name] == old_row[name]
               for name in ('Decision', 'Review Status', 'Added to Opportunities?', 'Salary / Range'))
    assert operation['append_if_missing'] is True

    summary = {'disposition': 'PASS_DISPOSABLE_NORMAL_REPOSITORY_ONLY',
               'retained_cursor': cursor, 'total_operations': len(plan),
               'fixture_local_inserts': result['inserted'], 'fixture_local_updates': result['updated'],
               'actual_changed_fields': changed, 'protected_review_and_decision_preserved': True,
               'old_and_new_evidence_survived': True,
               'isolated_update_only_proposal_matches_normal_local_delta': True,
               'proposal_guards_salary_old_source_review_and_manual_choice': True,
               'original_legacy_operation_unchanged': True, 'proposed_hash_matches_retained_posting': True,
               'retained_posting_declares_salary': bool(str(retained_posting.get('compensation') or '').strip()),
               'planned_salary_matches_posting_field': str(retained_posting.get('compensation') or '').strip()
                   == str(operation['values'].get('Salary / Range') or '').strip(),
               'no_network_or_live_store_access': True}
    (ROOT / 'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
