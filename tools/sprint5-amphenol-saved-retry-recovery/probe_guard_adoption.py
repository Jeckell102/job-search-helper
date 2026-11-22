"""Exercise guarded metadata adoption on a private copy of the exact held cut."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path[:0] = ['/home/chris/job-search-helper_old/src', str(Path(__file__).parent)]
from reproduce_held_plan import PROJECT, copy_row, forbid_network
from verified_note_guards import adopt_note_guards, measure_note_guards
from job_search_helper.engine import State
from job_search_helper.exact_cycle_receipt import repair_retry_receipt_binding
from job_search_helper.exact_local_plan import _final_identity
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import _receipt_id
from job_search_helper.repair_retry_status import _checkpointed_store_snapshot
from job_search_helper.sqlite_repository import SQLiteRepository


def copy_rows(source, target, table, query='', key=()):
    for row in source.execute(f'SELECT * FROM {table} {query}', key):
        placeholders = ','.join('?' for _ in row)
        target.execute(f'INSERT INTO {table} VALUES ({placeholders})', row)


def expect_error(call, expected, error_type=ValueError):
    try:
        call()
    except error_type as error:
        assert expected in str(error), error
    else:
        raise AssertionError('Guard adoption did not stop: ' + expected)


def copy_held_cut(source, inbox, cycle, scratch, work):
    key = (cycle['id'], cycle['repair_retry']['company_id'])
    plan, cursor = inbox.plan(*key)
    assert cursor == len(plan['local_operations'])
    approval = {
        'cycle_id': key[0], 'company_id': key[1], 'attempt_id': cycle['repair_retry']['attempt_id'],
        'release_id': cycle['repair_retry']['release']['release_id'], 'plan_digest': plan['plan_digest'],
        'verified_scope': measure_note_guards(source, *key, plan),
    }
    prep = json.loads(Path('/tmp/jsh-guarded-amphenol-recovery.gpKL8cOe/exact-approval.json').read_bytes())
    approval['plan_file_sha256'] = prep['saved_retry']['successor_file_sha256']
    receipt = _receipt_id(repair_retry_receipt_binding(cycle, key[1]))
    apply_id = approval['verified_scope']['apply_id']
    scope, = source.db.execute('SELECT row_scope FROM exact_local_applications WHERE apply_id=?', (apply_id,)).fetchone()
    needed = {}
    for operation in plan['local_operations']:
        tab = operation['tab']
        (row_id, row), = source.matches(tab, _final_identity(operation))
        needed[tab, row_id] = row
    for tab, headers in source.schemas.items():
        columns = [column for column in headers if column not in work.schemas[tab]]
        if columns:
            work.ensure_columns(tab, columns)
    with work.transaction():
        work.set_meta('sheets_profile', source.get_meta('sheets_profile'))
        for (tab, row_id), row in needed.items():
            copy_row(work, source, tab, row_id, row)
            copy_rows(source.db, work.db, 'conflicts', 'WHERE tab=? AND row_id=?', (tab, row_id))
        copy_rows(source.db, work.db, 'exact_local_applications', 'WHERE apply_id=?', (apply_id,))
        copy_rows(source.db, work.db, 'exact_local_apply_chunks', 'WHERE apply_id=?', (apply_id,))
    with scratch.connection:
        for table in ('inventories', 'sync_plans', 'exact_plan_local_state'):
            copy_rows(inbox.connection, scratch.connection, table, 'WHERE cycle=? AND company=?', key)
        copy_rows(inbox.connection, scratch.connection, 'publication_receipts', 'WHERE receipt_id=?', (receipt,))
    return key, scope, approval


def verify_adoption(source, inbox, cycle, scratch, work):
    key, scope, approval = copy_held_cut(source, inbox, cycle, scratch, work)
    apply_id = approval['verified_scope']['apply_id']

    def adopt(claims=approval):
        return adopt_note_guards(scratch, work, cycle, key[1], claims, timestamp='2026-11-22T04:53:00Z')

    bad = {**approval, 'verified_scope': {**approval['verified_scope'], 'chunk_evidence_sha256': '0' * 64}}
    expect_error(lambda: adopt(bad), 'pre-apply note evidence changed')
    with scratch.connection:
        scratch.connection.execute('INSERT INTO exact_sync_chunks VALUES (?,?,?,?,?,?)',
                                   (*key, 0, 1, 'fixture', 'PENDING'))
    expect_error(adopt, 'Remote work already exists')
    with scratch.connection:
        scratch.connection.execute('DELETE FROM exact_sync_chunks WHERE cycle=? AND company=?', key)
    work.db.execute('''CREATE TRIGGER abort_note_guard BEFORE UPDATE ON exact_local_applications
        BEGIN SELECT RAISE(ABORT, 'injected scope crash'); END''')
    expect_error(adopt, 'injected scope crash', sqlite3.IntegrityError)
    assert work.db.execute("SELECT name FROM sqlite_schema WHERE name='exact_retry_note_guard_archive'").fetchone() is None
    assert work.db.execute('SELECT row_scope FROM exact_local_applications WHERE apply_id=?', (apply_id,)).fetchone() == (scope,)
    work.db.execute('DROP TRIGGER abort_note_guard')

    inbox_before = tuple(scratch.connection.iterdump())
    assert adopt() == 'NOTE_GUARDS_ADOPTED'
    assert adopt() == 'NOTE_GUARDS_ALREADY_ADOPTED'
    assert tuple(scratch.connection.iterdump()) == inbox_before
    print('Exact private note guard adoption passed, including prior intent, rollback and replay.')


def main():
    sys.addaudithook(forbid_network)
    root = PROJECT / '.state'
    paths = (root / 'state.db', root / 'jobs.sqlite3', root / 'inventories.sqlite3')
    before = _checkpointed_store_snapshot(paths)
    assert before is not None
    dest = InventoryInbox.destination_id(paths[2], immutable=True)
    with (TemporaryDirectory(prefix='jsh-private-verified-guard.') as directory,
          closing(State(paths[0], readonly=True, immutable=True)) as state,
          closing(SQLiteRepository(paths[1], dest, readonly=True, immutable=True)) as source,
          closing(InventoryInbox(paths[2], dest, readonly=True, immutable=True)) as inbox,
          closing(SQLiteRepository(Path(directory) / 'jobs.db', dest, initialize=True)) as work,
          closing(InventoryInbox(Path(directory) / 'inbox.db', dest)) as scratch):
        work._ensure_exact_local_schema()
        verify_adoption(source, inbox, state.cycle('CYC-4650772EEE1E'), scratch, work)
    assert before == _checkpointed_store_snapshot(paths)


if __name__ == '__main__':
    main()
