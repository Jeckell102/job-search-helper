"""Read-only, private reproduction at the resumed Sheets preflight boundary."""
from contextlib import closing
import json
from pathlib import Path
import sys

project = Path('/home/chris/job-search-helper_old')
sys.path.insert(0, str(project / 'src'))
from job_search_helper.exact_local_plan import _final_identity
from job_search_helper.inbox import InventoryInbox
from job_search_helper.repair_retry_status import _checkpointed_store_snapshot
from job_search_helper.repository import MemoryRepository
from job_search_helper.sheets_sync import SheetsSynchronizer
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


class DisallowRemoteAccess(MemoryRepository):
    def __getattribute__(self, name):
        if name in {'read', 'read_columns', 'read_rows', 'commit'}:
            raise AssertionError('scope planning touched remote')
        return super().__getattribute__(name)


def main():
    root = project / '.state'
    files = (root / 'state.db', root / 'jobs.sqlite3', root / 'inventories.sqlite3')
    snapshot = _checkpointed_store_snapshot(files)
    assert snapshot is not None
    key = ('CYC-4650772EEE1E', 'COMP-0490')
    dest = InventoryInbox.destination_id(files[2], immutable=True)
    with (closing(SQLiteRepository(files[1], dest, readonly=True, immutable=True)) as jobs,
          closing(InventoryInbox(files[2], dest, readonly=True, immutable=True)) as inbox):
        plan, _ = inbox.plan(*key)
        scope, app = jobs.db.execute(
            'SELECT row_scope,apply_id FROM exact_local_applications WHERE cycle=? AND company=?', key,
        ).fetchone()
        chunks = jobs.db.execute('SELECT before_records FROM exact_local_apply_chunks '
                                 'WHERE apply_id=? AND state=?', (app, 'VERIFIED')).fetchall()
        before = [record for (raw,) in chunks for record in json.loads(raw)]
        scopes = json.loads(scope)
        remote = DisallowRemoteAccess({}, schemas=COMPACT_SCHEMAS)
        remote.spreadsheet_id = dest
        sync = SheetsSynchronizer(jobs, remote)
        try:
            sync.plan_exact_scope(scopes, plan['remote_projection'])
        except ValueError as error:
            print('Current snapshot rejection:', error)
        repaired = 0
        for item in scopes:
            if item['tab'] != 'Job History' or 'Source Hash' in item['guards']:
                continue
            op, = [op for op in plan['local_operations']
                   if op['tab'] == item['tab'] and _final_identity(op) == item['identity']]
            assert op.get('append_notes') and not any('Source Hash' in op.get(field, {})
                                                      for field in ('values', 'on_insert', 'append_notes'))
            previous, = [record for record in before
                         if record['tab'] == item['tab'] and record['identity'] == op['identity']]
            row, = previous['rows']
            assert row['row_id'] == item['row_id']
            value = row['row']['Source Hash']
            assert value and jobs.row(item['tab'], item['row_id'])['Source Hash'] == value
            item['guards']['Source Hash'] = value
            repaired += 1
            print('Note target scope:', sorted(op['append_notes']), 'expected:', sorted(item['expected']))
        print('Unchanged pre-application Source Hash values proven:', repaired)
        try:
            sync.plan_exact_scope(scopes, plan['remote_projection'])
        except ValueError as error:
            print('After read-only scope enrichment:', error)
        else:
            print('After read-only scope enrichment: accepted')
        positional = zip(sync._normalize_exact_scope(scopes), plan['remote_projection'])
        print('Durable reconstruction reordered targets:', sum(
            item['tab'] != operation['tab'] or item['identity'] != _final_identity(operation)
            for item, operation in positional
        ))
    assert snapshot == _checkpointed_store_snapshot(files)


if __name__ == '__main__':
    main()
