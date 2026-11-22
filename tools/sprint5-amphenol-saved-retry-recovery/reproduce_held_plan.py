"""Reproduce one held local apply in private SQLite, without modifying its stores."""

from contextlib import closing
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


PROJECT = Path('/home/chris/job-search-helper_old')
ROOT = PROJECT / '.state'
CYCLE = 'CYC-4650772EEE1E'
COMPANY = 'COMP-0490'
PLAN_SHA = '04c05d9c789a415161b9af3ca08eb66f94b672db04493c2d2ca5c8a091a892e7'

sys.path.insert(0, str(PROJECT / 'src'))
sys.path.insert(0, str(Path(__file__).parent))
from rejected_retry_plan import _encode, _sha, select_successor
from job_search_helper.batching import PlanningRepository
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_receipt import REPAIR_RETRY_PLAN_BINDING
from job_search_helper.exact_local_plan import _final_identity
from job_search_helper.inbox import InventoryInbox
from job_search_helper.publication_receipts import local_committed
from job_search_helper.repair_retry_status import _checkpointed_store_snapshot
from job_search_helper.repository import ReviewFieldsChangedError
from job_search_helper.sqlite_repository import SQLiteRepository


def forbid_network(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen'}:
        raise AssertionError(f'Unexpected offline probe action: {event}')


def copy_row(target, original, tab, row_id, row):
    policy = original.db.execute(
        'SELECT policies FROM records WHERE tab=? AND row_id=?', (tab, row_id)
    ).fetchone()
    target._put(tab, row_id, row, json.loads(policy[0]))
    baseline = original.baseline(tab, row_id)
    if baseline is not None:
        target._baseline(tab, row_id, baseline)
    for table in ('manual_choices', 'dirty'):
        for record in original.db.execute(
            f'SELECT * FROM {table} WHERE tab=? AND row_id=?', (tab, row_id)
        ):
            placeholders = ','.join('?' for _ in record)
            target.db.execute(f'INSERT INTO {table} VALUES ({placeholders})', record)


def relevant_rows(jobs, operations):
    for operation in operations:
        tab = operation['tab']
        candidates = [operation['identity'], _final_identity(operation)]
        values = {**operation['identity'], **operation.get('on_insert', {}),
                  **operation.get('values', {})}
        if tab == 'Job History' and values.get('Company') and values.get('Official Job URL'):
            candidates.append({key: values[key] for key in ('Company', 'Official Job URL')})
        for identity in candidates:
            for row_id, row in jobs.matches(tab, identity):
                yield (tab, row_id), row


def load_candidate(path, pin):
    path = Path(path)
    assert path.is_absolute() and path.is_relative_to('/tmp')
    assert path.resolve(strict=True) == path and sha256(path.read_bytes()).hexdigest() == pin
    name = 'job_search_helper._private_reproduction_candidate'
    spec = spec_from_file_location(name, path)
    module = module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def exercise_adoption(inbox, jobs, cycle, frozen, payload, candidate):
    key = (CYCLE, COMPANY)
    timestamp = '2026-11-22T04:20:00Z'
    with TemporaryDirectory(prefix='jsh-publish-adoption.') as directory, closing(
            InventoryInbox(Path(directory) / 'inbox.db', 'scratch-adoption')) as scratch:
        before_plan = inbox.connection.execute('SELECT * FROM sync_plans WHERE cycle=? AND company=?', key).fetchone()
        before_marker = inbox.connection.execute(
            'SELECT * FROM exact_plan_local_state WHERE cycle=? AND company=?', key).fetchone()
        before_inventory = inbox.connection.execute(
            'SELECT * FROM inventories WHERE cycle=? AND company=?', key).fetchone()
        scratch.save(*key, payload)
        scratch.save_exact_plan(*key, frozen, timestamp=timestamp)
        db = scratch.connection
        with db:
            db.execute('UPDATE sync_plans SET payload=? WHERE cycle=? AND company=?', (before_plan[2], *key))
            db.execute('UPDATE inventories SET payload=? WHERE cycle=? AND company=?', (before_inventory[2], *key))
            db.execute('UPDATE exact_plan_local_state SET created_at=?,updated_at=? '
                       'WHERE cycle=? AND company=?', (*before_marker[-2:], *key))
        assert scratch.plan(*key) == (frozen, 0)
        approval = {
            'cycle_id': CYCLE, 'company_id': COMPANY,
            'attempt_id': cycle['repair_retry']['attempt_id'],
            'release_id': cycle['repair_retry']['release']['release_id'],
            'successor_plan_sha256': candidate['plan_digest'],
            'successor_file_sha256': _sha(_encode(candidate)),
            'original_plan_sha256': frozen['plan_digest'],
            'original_file_sha256': _sha(before_plan[2]),
            'original_local_state_sha256': _sha(_encode(before_marker[2:])),
            'inventory_file_sha256': _sha(before_inventory[2]),
        }

        def select():
            return select_successor(scratch, jobs, cycle, COMPANY, candidate, approval, timestamp=timestamp)

        def expect_hold(expected, exc_type=ValueError):
            try:
                select()
            except exc_type as exc:
                assert expected in str(exc), exc
            else:
                raise AssertionError(f'Successor did not hold on {expected}')

        jobs._ensure_exact_local_schema()
        with db:
            db.execute('UPDATE sync_plans SET cursor=1 WHERE cycle=? AND company=?', key)
        expect_hold('zero-apply')
        with db:
            db.execute('UPDATE sync_plans SET cursor=0 WHERE cycle=? AND company=?', key)
            binding = frozen[REPAIR_RETRY_PLAN_BINDING]
            local_committed(db, binding, frozen['remote_records'],
                            {'boundary': 'idle', 'enqueued_at': cycle['repair_retry']['activated_at']},
                            timestamp=timestamp)
        expect_hold('receipt')
        with db:
            db.execute('DELETE FROM publication_receipts')
            db.execute('''CREATE TRIGGER abort_switch BEFORE UPDATE ON exact_plan_local_state
                BEGIN SELECT RAISE(ABORT, 'private fixture crash'); END''')
        expect_hold('private fixture crash', sqlite3.IntegrityError)
        assert scratch.plan(*key) == (frozen, 0)
        assert db.execute("SELECT name FROM sqlite_schema WHERE name='rejected_retry_plan_archive'").fetchone() is None
        with db:
            db.execute('DROP TRIGGER abort_switch')
        assert select() == 'SUCCESSOR_SELECTED'
        assert select() == 'SUCCESSOR_ALREADY_SELECTED'
        assert scratch.plan(*key) == (candidate, 0)
        saved = db.execute('SELECT original_plan,original_cursor,original_local_state,inventory,successor '
                           'FROM rejected_retry_plan_archive').fetchone()
        assert saved == (before_plan[2], 0, _encode(before_marker[2:]), before_inventory[2], _encode(candidate))
        print('Private archive and switch passed: existing commitment holds, injected failure rolls back, replay is stable')
        return approval


def build_successor(candidate, repository, state, inbox, cycle, frozen, payload):
    engine = Engine(repository, state, inbox=inbox, runtime_binding=cycle['runtime_binding'])
    [stamp] = [operation['values']['Record Updated'] for operation in frozen['local_operations']
               if operation['tab'] == 'Companies']
    planner = PlanningRepository(repository)
    # Compare both read-only planning fixtures at the original save time.
    with patch('job_search_helper.engine.now', return_value=stamp):
        plan = candidate._freeze(engine, planner, cycle, COMPANY, payload,
                                 drop_noops=True, protect_ordinary_source=True)
    for field in ('control_evidence', 'control_evidence_version', 'control_evidence_digest'):
        plan[field] = frozen[field]
    plan = candidate._seal_exact_plan_v2(plan, payload, repository, CYCLE, COMPANY)
    plan[REPAIR_RETRY_PLAN_BINDING] = frozen[REPAIR_RETRY_PLAN_BINDING]
    plan['plan_digest'] = candidate._exact_plan_digest(plan)
    return plan


def reproduce(candidate, stage=None):
    paths = (ROOT/'state.db', ROOT/'jobs.sqlite3', ROOT/'inventories.sqlite3')
    before = _checkpointed_store_snapshot(paths)
    assert before is not None
    destination = InventoryInbox.destination_id(paths[2], immutable=True)
    with (TemporaryDirectory(prefix='jsh-amphenol-repro-data.') as directory,
          closing(State(paths[0], readonly=True, immutable=True)) as state,
          closing(SQLiteRepository(paths[1], destination, readonly=True, immutable=True)) as jobs,
          closing(InventoryInbox(paths[2], destination, readonly=True, immutable=True)) as inbox,
          closing(SQLiteRepository(Path(directory)/'jobs.sqlite3', destination, initialize=True)) as work):
        frozen, cursor = inbox.plan(CYCLE, COMPANY)
        payload, blocked = inbox.get(CYCLE, COMPANY)
        assert frozen['plan_digest'] == PLAN_SHA and cursor == 0 and not blocked
        assert payload['inventory_status'] == 'complete' and len(payload['jobs']) == 39
        work.set_meta('sheets_profile', jobs.get_meta('sheets_profile'))
        for tab, headers in jobs.schemas.items():
            extra = [field for field in headers if field not in work.schemas[tab]]
            if extra:
                work.ensure_columns(tab, extra)
        rows = dict(relevant_rows(jobs, frozen['local_operations']))
        if candidate is not None:
            cycle = state.cycle(CYCLE)
            company = cycle['companies'][COMPANY]['company']
            for tab in ('Job History', 'Opportunities'):
                rows.update(((tab, row_id), row) for row_id, row in jobs.matches(tab, {'Company': company}))
            for (tab, _), row in list(rows.items()):
                if tab == 'Job History':
                    rows.update((('Job Evidence', row_id), evidence) for row_id, evidence in
                                jobs.matches('Job Evidence', {'Job Key': row['Job Key']}))
        with work.transaction():
            for (tab, row_id), row in rows.items():
                copy_row(work, jobs, tab, row_id, row)

        plan = frozen
        if candidate is not None:
            plan = build_successor(candidate, work, state, inbox, cycle, frozen, payload)
            assert plan == build_successor(candidate, jobs, state, inbox, cycle, frozen, payload)
            print('The isolated successor matches the full immutable planning snapshot')
            proposal = exercise_adoption(inbox, work, cycle, frozen, payload, plan)
        count = len(plan['local_operations'])
        print(json.dumps({'fixture_rows': len(rows), 'planned_local_operations': count,
                          'planned_compact_operations': len(plan['remote_projection'])}))
        try:
            for start in range(0, count, 100):
                work.apply_exact_local_plan(CYCLE, COMPANY, plan, start)
                work.verify_exact_local_plan(CYCLE, COMPANY, plan, cursor=start)
            work.verify_exact_local_plan(CYCLE, COMPANY, plan)
        except ReviewFieldsChangedError:
            if candidate is not None:
                raise
            print('Reproduced ReviewFieldsChangedError before any local apply committed')
            assert work.db.execute('SELECT count(*) FROM exact_local_applications').fetchone()[0] == 0
        else:
            assert candidate is not None, 'The original failure did not reproduce'
            print('Candidate local apply and verification passed in private SQLite')
    assert before == _checkpointed_store_snapshot(paths)
    if stage is not None:
        stage = Path(stage)
        assert stage.is_relative_to('/tmp') and stage.resolve(strict=True) == stage
        assert stage.stat().st_mode & 0o077 == 0 and stage.stat().st_uid == os.getuid()
        for name, content in (('proposed-successor.json', plan), ('proposal-evidence.json', proposal)):
            descriptor = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                output.write(_encode(content))
                output.flush()
                os.fsync(output.fileno())
        print(json.dumps(proposal, sort_keys=True))


if __name__ == '__main__':
    assert sys.flags.isolated and sys.flags.dont_write_bytecode
    sys.addaudithook(forbid_network)
    args = sys.argv[1:]
    assert len(args) in {0, 2, 3}
    reproduce(load_candidate(*args[:2]) if args else None, stage=args[2] if len(args) == 3 else None)
