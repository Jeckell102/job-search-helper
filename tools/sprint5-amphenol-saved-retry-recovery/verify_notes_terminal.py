"""Read independently accepted Amphenol local and optional Sheets evidence."""

from argparse import ArgumentParser
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sys

PROJECT = Path('/home/chris/job-search-helper_old')
sys.path[:0] = [str(PROJECT / 'src'), str(Path(__file__).parent)]
from compare_confirmed_workbook import compare_confirmed_workbook
from job_search_helper.engine import State
from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication, repair_retry_receipt_binding
from job_search_helper.exact_local_plan import _revalidate_row_scope
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repair_retry_status import _checkpointed_store_snapshot
from job_search_helper.sqlite_repository import SQLiteRepository


def digest(raw):
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    return sha256(raw).hexdigest()


def terminal_readback(jobs, inbox, cycle, selected, original, *, remote=None):
    company = selected['company_id']
    key = (selected['cycle_id'], company)
    if (cycle['id'] != key[0] or cycle['repair_retry']['attempt_id'] != selected['attempt_id']
            or cycle['repair_retry']['release']['release_id'] != selected['release_id']
            or not repair_retry_has_confirmed_publication(inbox, jobs, cycle, company)):
        raise ValueError('The approved note retry has no terminal Jobs and Sheets confirmation.')
    old_plan, zero, old_marker, inventory, selected_plan = inbox.connection.execute(
        'SELECT original_plan,original_cursor,original_local_state,inventory,successor '
        'FROM rejected_retry_plan_archive WHERE cycle=? AND company=?', key,
    ).fetchone()
    if (zero != 0 or digest(old_plan) != original['original_file_sha256']
            or digest(old_marker) != original['original_local_state_sha256']
            or digest(inventory) != original['inventory_file_sha256']
            or digest(selected_plan) != selected['plan_file_sha256']):
        raise ValueError('The preserved original and selected application differ from approval.')
    plan = json.loads(selected_plan)
    row = jobs.db.execute(
        'SELECT apply_id,plan_digest,remote_projection_digest,row_scope,state '
        'FROM exact_local_applications WHERE cycle=? AND company=?', key,
    ).fetchone()
    prior_scope, final_scope = jobs.db.execute(
        'SELECT original_scope,selected_scope FROM exact_retry_note_guard_archive WHERE apply_id=?', (row[0],),
    ).fetchone()
    expected_scope = selected['verified_scope']
    if (row[:3] != (expected_scope['apply_id'], selected['plan_digest'], plan['remote_projection_digest'])
            or row[4] != 'VERIFIED' or digest(prior_scope) != expected_scope['before_scope_sha256']
            or digest(final_scope) != expected_scope['enriched_scope_sha256'] or row[3] != final_scope):
        raise ValueError('The acknowledged application differs from the approved guarded scope.')
    scope = json.loads(row[3])
    _revalidate_row_scope(jobs, scope)
    receipt = inbox.receipt({'binding': repair_retry_receipt_binding(cycle, company)})
    evidence = {'attempt_id': selected['attempt_id'], 'cycle_id': key[0], 'apply_id': row[0],
                'receipt_id': receipt['receipt_id'], 'acknowledgement_id': receipt['acknowledgement_id'],
                'receipt_records': len(receipt['records']), 'receipt_state': receipt['state']}
    if remote is not None:
        if remote.spreadsheet_id != jobs.spreadsheet_id:
            raise ValueError('Independent readback opened another workbook.')
        application = {'cycle_id': key[0], 'company_id': company, 'plan_digest': row[1],
                       'remote_projection_digest': row[2], 'row_scope': scope, 'state': row[4]}
        baselines = {(item['tab'], item['row_id']): jobs.baseline(item['tab'], item['row_id']) for item in scope}
        evidence['workbook'] = compare_confirmed_workbook(remote, receipt, application, baselines, archived_plan=plan)
    return evidence


def main():
    parser = ArgumentParser(allow_abbrev=False)
    parser.add_argument('--workbook', action='store_true')
    args = parser.parse_args()
    original = Path('/tmp/jsh-guarded-amphenol-recovery.gpKL8cOe/exact-approval.json').read_bytes()
    selected = Path('/tmp/jsh-verified-amphenol-notes.V8NmUM9e/exact-approval.json').read_bytes()
    if (digest(original) != 'f6f00de050f076b544cd0dee83d7f7d8093b62f2399f4560920955da418aff00'
            or digest(selected) != '8b4f278075104a82f42b2ad2e0078e62645eea49d5c5acf966a8488ee35a4cd1'):
        raise ValueError('The exact note verification approval changed.')
    original, selected = json.loads(original)['saved_retry'], json.loads(selected)['note_publication']
    root = PROJECT / '.state'
    paths = (root / 'state.db', root / 'jobs.sqlite3', root / 'inventories.sqlite3')
    snapshot = _checkpointed_store_snapshot(paths)
    if snapshot is None:
        raise RuntimeError('The terminal local stores are still busy.')
    dest = InventoryInbox.destination_id(paths[2], immutable=True)
    with (closing(State(paths[0], readonly=True, immutable=True)) as state,
          closing(SQLiteRepository(paths[1], dest, readonly=True, immutable=True)) as jobs,
          closing(InventoryInbox(paths[2], dest, readonly=True, immutable=True)) as inbox):
        remote = None
        if args.workbook:
            from job_search_helper.cli import get_remote_repository, load_environment
            from job_search_helper.sheet_profile import COMPACT_SCHEMAS

            load_environment(PROJECT / '.env')
            remote = get_remote_repository(write=False, schemas=COMPACT_SCHEMAS, evidence_archives=False)
        evidence = terminal_readback(jobs, inbox, state.cycle(selected['cycle_id']), selected, original, remote=remote)
    if snapshot != _checkpointed_store_snapshot(paths):
        raise RuntimeError('The terminal local stores changed during independent verification.')
    print(json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    main()
