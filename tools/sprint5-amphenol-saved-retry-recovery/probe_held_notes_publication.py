"""Verify the exact held case through a disposable workbook and receipt."""

from contextlib import closing, nullcontext
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path[:0] = ['/home/chris/job-search-helper_old/src', str(Path(__file__).parent)]
from compare_confirmed_workbook import compare_confirmed_workbook
from probe_guard_adoption import copy_held_cut, copy_rows
from reproduce_held_plan import PROJECT, copy_row, forbid_network
import resume_verified_note_publication as continuation
from verify_notes_terminal import terminal_readback
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_receipt import repair_retry_has_confirmed_publication, repair_retry_receipt_binding
from job_search_helper.exact_cycle_recovery import close_published_repair_retry
from job_search_helper.exact_local_plan import exact_local_plan
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import JOURNAL_SCHEMA
from job_search_helper.repair_retry_status import _checkpointed_store_snapshot
from job_search_helper.repository import MemoryRepository, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository


class DisposableWorkbook(MemoryRepository):
    def __init__(self, repository, scope, *, lost_response):
        tabs = {}
        for item in json.loads(scope):
            tab = item['tab']
            old = repository.baseline(tab, item['row_id'])
            if old:
                tabs.setdefault(tab, []).append({field: old[field] for field in COMPACT_SCHEMAS[tab]
                                                 if field in old})
        super().__init__(tabs, schemas=COMPACT_SCHEMAS)
        self.spreadsheet_id = repository.spreadsheet_id
        self.commits = 0
        self.lost_response = lost_response

    def commit(self, operations):
        result = super().commit(operations)
        self.commits += 1
        if self.lost_response and self.commits == 1:
            raise UncertainWriteError('private fixture lost the response after writing')
        return result


def simulate(source, inbox, cycle, publisher, *, lost_response):
    with TemporaryDirectory(prefix='jsh-private-note-publish.') as directory:
        root = Path(directory)
        dest = source.spreadsheet_id
        with (closing(State(root / 'state.db')) as state,
              closing(SQLiteRepository(root / 'jobs.sqlite3', dest, initialize=True)) as work,
              closing(InventoryInbox(root / 'inventories.sqlite3', dest)) as scratch):
            work._ensure_exact_local_schema()
            key, scope, approval = copy_held_cut(source, inbox, cycle, scratch, work)
            archive_schema, = inbox.connection.execute(
                "SELECT sql FROM sqlite_schema WHERE name='rejected_retry_plan_archive'",
            ).fetchone()
            with scratch.connection:
                scratch.connection.execute(archive_schema)
                copy_rows(inbox.connection, scratch.connection, 'rejected_retry_plan_archive',
                          'WHERE cycle=? AND company=?', key)
            (row_id, row), = source.matches('Scan Cycles', {'Cycle ID': key[0]})
            with work.transaction():
                copy_row(work, source, 'Scan Cycles', row_id, row)
            state.save_cycle(cycle)
            release = cycle['repair_retry']['release']
            (root / 'integration-release-journal.json').write_text(json.dumps({
                'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE', 'release_id': release['release_id'],
                'release': release,
            }))
            remote = DisposableWorkbook(work, scope, lost_response=lost_response)
            plan, _ = scratch.plan(*key)
            engine = Engine(work, state, inbox=scratch, runtime_binding=cycle['runtime_binding'])
            owner = object()
            owner_calls = []
            remote_opens = []

            def verify_qualification(database, binding, actual_owner):
                assert database == root / 'state.db' and binding == cycle['repair_retry'] and actual_owner is owner
                owner_calls.append(database)

            def remote_factory():
                remote_opens.append(True)
                return nullcontext(remote)

            def send():
                with writer_lock(root / 'scraper.lock'), patch.object(
                        continuation, '_require_qualified_retry', verify_qualification):
                    return continuation.resume_notes_admitted(
                        engine, cycle['repair_retry'], approval, qualification_owner=owner,
                        remote_factory=remote_factory, synchronizer_type=publisher,
                        timestamp='2026-11-22T04:54:00Z',
                    )

            result = send()
            if lost_response:
                assert result['held'] == [{'company_id': key[1], 'reason': 'uncertain_write'}], result
                assert remote.commits == 1
                result = send()
            assert result == {'state': 'READY_FOR_CLOSEOUT', 'cycle_id': key[0]}, result
            assert remote.commits == 1
            refreshed = state.cycle(key[0])
            assert repair_retry_has_confirmed_publication(scratch, work, refreshed, key[1], require_complete=False)
            receipt = scratch.receipt({'binding': repair_retry_receipt_binding(refreshed, key[1])})
            application = exact_local_plan(work, *key)
            baselines = {(entry['tab'], entry['row_id']): work.baseline(entry['tab'], entry['row_id'])
                         for entry in application['row_scope']}
            readback = compare_confirmed_workbook(remote, receipt, application, baselines, archived_plan=plan)
            assert readback['matched_original_fingerprints'] == len(plan['remote_projection']), readback
            assert scratch.plan(*key) is None and scratch.get(*key) is None
            outcome = close_published_repair_retry(engine, *key, attempt_id=approval['attempt_id'],
                                                   release_id=approval['release_id'])
            assert outcome['outcome'] == 'COMPLETE'
            original = json.loads(Path('/tmp/jsh-guarded-amphenol-recovery.gpKL8cOe/exact-approval.json').read_bytes())
            terminal = terminal_readback(work, scratch, state.cycle(key[0]), approval, original['saved_retry'], remote=remote)
            assert terminal['workbook'] == readback and terminal['receipt_state'] == 'SYNC_CONFIRMED'
            assert send() == result
            assert len(owner_calls) == (3 if lost_response else 2) and len(remote_opens) == (2 if lost_response else 1)
            print(json.dumps({'lost_response': lost_response, 'workbook_commits': remote.commits,
                              'local_plan_digest': application['plan_digest'], **readback}, sort_keys=True))


def main():
    sys.addaudithook(forbid_network)
    if len(sys.argv) == 1:
        from job_search_helper.sheets_sync import SheetsSynchronizer as publisher
    else:
        candidate = Path(sys.argv[1])
        assert candidate.is_relative_to('/tmp') and candidate.resolve(strict=True) == candidate
        assert sha256(candidate.read_bytes()).hexdigest() == sys.argv[2]
        spec = spec_from_file_location('private_repair_notes_publisher', candidate)
        module = module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        publisher = getattr(module, sys.argv[3])
    root = PROJECT / '.state'
    paths = (root / 'state.db', root / 'jobs.sqlite3', root / 'inventories.sqlite3')
    before = _checkpointed_store_snapshot(paths)
    assert before is not None
    destination = InventoryInbox.destination_id(paths[2], immutable=True)
    with (closing(State(paths[0], readonly=True, immutable=True)) as state,
          closing(SQLiteRepository(paths[1], destination, readonly=True, immutable=True)) as source,
          closing(InventoryInbox(paths[2], destination, readonly=True, immutable=True)) as inbox):
        cycle = state.cycle('CYC-4650772EEE1E')
        for lost_response in (False, True):
            simulate(source, inbox, cycle, publisher, lost_response=lost_response)
    assert before == _checkpointed_store_snapshot(paths)


if __name__ == '__main__':
    main()
