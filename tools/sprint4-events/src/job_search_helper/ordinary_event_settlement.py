"""Seal a published ordinary Company event and complete its exact cycle."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .ats import validate_outcome_failure
from .company_events import read_verified_ordinary_event_admission
from .engine import Engine, State, now
from .ordinary_event_publication_archive import read_ordinary_event_publication
from .outcomes import classify_outcome
from .scan_request import _timestamp
from .sqlite_repository import SQLiteRepository
from .temporary_retry import _canonical, _selected_sha


def settle_published_ordinary_event(engine, *, cycle_id, request_sha256):
    """Record one owned outcome and mirror, then checkpoint State last."""
    from .exact_cycle_receipt import (
        _ordinary_observation, load_ordinary_event_plan_context,
        ordinary_event_plan_payload, ordinary_event_receipt_binding,
    )

    if (not isinstance(engine, Engine) or not isinstance(engine.repo, SQLiteRepository)
            or engine.repo.readonly or engine.inbox is None or not isinstance(engine.state, State)):
        raise ValueError('Ordinary event settlement requires its canonical writable Jobs store.')
    repo, state = engine.repo, engine.state
    root = repo.path.resolve().parent
    if (repo.path != root / 'jobs.sqlite3' or repo.path.is_symlink() or state.readonly
            or Path(state.path) != root / 'state.db' or Path(state.path).is_symlink()
            or Path(engine.inbox.path) != root / 'inventories.sqlite3' or Path(engine.inbox.path).is_symlink()):
        raise ValueError('Ordinary event settlement dependencies changed.')

    def reopen():
        with (closing(SQLiteRepository(repo.path, repo.spreadsheet_id, readonly=True)) as reader,
              closing(State(str(state.path), readonly=True)) as checkpoint):
            return load_ordinary_event_plan_context(
                reader, checkpoint, engine.runtime_binding, cycle_id=cycle_id, request_sha256=request_sha256,
            )

    context = reopen()
    cycle = state.cycle(cycle_id)
    company_id = cycle['company_event']['company_id']
    observation = _ordinary_observation(context)
    binding = ordinary_event_receipt_binding(cycle, company_id, ordinary_event_plan_payload(context), context)
    proof = read_ordinary_event_publication(engine.inbox, repo, cycle_id, company_id, binding=binding)
    if (proof is None
            or observation['sha256'] != binding['observation_sha256']
            or observation['inventory_sha256'] != binding['provider_inventory_sha256']
            or cycle['companies'][company_id].get('stage') != proof['final_stage']):
        raise ValueError('Ordinary event settlement has no exact terminal publication proof.')
    fixed = {'schema': 'ordinary-company-event-settlement-v1', 'binding': binding,
             'publication_sha256': _selected_sha(proof), 'stage': proof['final_stage']}
    saved = _read_settlement(repo, cycle_id, binding['request_id'])
    if saved is None:
        with repo.transaction():
            if (_read_settlement(repo, cycle_id, binding['request_id']) is not None
                    or state.cycle(cycle_id) != cycle or cycle.get('status') != 'In Progress' or reopen() != context
                    or read_ordinary_event_publication(engine.inbox, repo, cycle_id, company_id, binding=binding) != proof
                    or _outcome_rows(repo, binding)):
                raise ValueError('Ordinary event settlement conflicts with its prior state or outcome.')
            admission = read_verified_ordinary_event_admission(repo, state, cycle_id)
            matches = repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
            if len(matches) != 1 or matches[0][1].get('Cycle Status') != 'In Progress':
                raise ValueError('Ordinary event settlement requires its exact unfinished mirror.')
            stamp = now()
            outcome = repo._record_scrape_outcome_in_transaction(
                _facts(binding, observation, proof['final_stage'], admission['source_current']),
                owned_company_event=True, recorded_at=stamp,
            )['outcome']
            terminal = _terminal(cycle, proof['final_stage'], stamp)
            values = _mirror_values(proof['final_stage'], stamp)
            repo._commit_in_transaction([{
                'tab': 'Scan Cycles', 'identity': {'Cycle ID': cycle_id}, 'values': values,
                'expected': {'Cycle Status': 'In Progress'},
            }])
            mirror = repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
            if len(mirror) != 1 or any(mirror[0][1].get(key) != value for key, value in values.items()):
                raise ValueError('Ordinary event settlement mirror did not persist.')
            saved = {
                **fixed, 'recorded_at': stamp, 'outcome': outcome,
                'pre_state_sha256': _selected_sha(cycle), 'terminal_state_sha256': _selected_sha(terminal),
                'mirror_sha256': _selected_sha(mirror[0][1]),
            }
            repo.db.execute(
                'CREATE TABLE IF NOT EXISTS ordinary_event_settlements ('
                'cycle TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE, '
                'outcome_id TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, payload TEXT NOT NULL)',
            )
            repo.db.execute('INSERT INTO ordinary_event_settlements VALUES (?,?,?,?,?)',
                            (cycle_id, binding['request_id'], outcome['outcome_id'],
                             _selected_sha(saved), _canonical(saved)))
    _finish(engine, cycle, fixed, observation, saved)
    return {'state': 'SYNC_CONFIRMED', **proof, 'outcome': saved['outcome'],
            'settlement_sha256': _selected_sha(saved)}


def _facts(binding, observation, stage, current):
    inventory = observation['inventory']
    envelope = validate_outcome_failure(inventory.get('outcome_failure'))
    failure = ({'category': envelope['category'], 'provider_code': envelope['evidence_code']}
               if envelope is not None else {'category': 'none' if stage == 'complete' else 'unknown'})
    return {
        **{key: binding[key] for key in ('request_id', 'company_event_id', 'company_id',
                                        'source_revision', 'cycle_id')},
        'source_current': current, 'company_status': 'Active', 'provider': inventory['ats'],
        'adapter_version': 'normal-scraper-v1', 'storage_status': 'confirmed',
        'inventory_status': stage, 'failure': failure, 'capability': 'unknown',
    }


def _read_settlement(repo, cycle_id, request_id):
    if repo.db.execute("SELECT 1 FROM sqlite_master WHERE name='ordinary_event_settlements'").fetchone() is None:
        return None
    rows = repo.db.execute(
        'SELECT cycle,request_id,outcome_id,sha256,payload FROM ordinary_event_settlements '
        'WHERE cycle=? OR request_id=?', (cycle_id, request_id),
    ).fetchall()
    if not rows:
        return None
    value = json.loads(rows[0][-1])
    if (not isinstance(value, dict) or set(value) != {
            'schema', 'binding', 'publication_sha256', 'stage', 'recorded_at', 'outcome',
            'pre_state_sha256', 'terminal_state_sha256', 'mirror_sha256',
        } or rows != [(cycle_id, request_id, value['outcome']['outcome_id'],
                        _selected_sha(value), _canonical(value))]):
        raise ValueError('Ordinary event settlement stored identity is inconsistent.')
    return value


def ordinary_event_mirror_ahead(repository, cycle, mirror):
    """Recognize the Jobs commit before its separate State checkpoint."""
    if cycle.get('status') != 'In Progress' or not cycle.get('start_request_id'):
        return False
    receipt = _read_settlement(repository, cycle['id'], cycle['start_request_id'])
    if receipt is None:
        return False
    expected = _mirror_values(receipt['stage'], receipt['recorded_at'])
    return (receipt['schema'] == 'ordinary-company-event-settlement-v1'
            and receipt['binding']['cycle_id'] == cycle['id']
            and receipt['binding']['request_id'] == cycle['start_request_id']
            and receipt['pre_state_sha256'] == _selected_sha(cycle)
            and receipt['mirror_sha256'] == _selected_sha(mirror)
            and all(mirror.get(key) == value for key, value in expected.items()))


def ordinary_event_outcome_settled(repository, record):
    """Fence delivery until the ordinary event's owning cycle is terminal."""
    identity = record['identity']
    cycle_id, request_id = identity.get('cycle_id'), identity['request_id']
    saved = _read_settlement(repository, cycle_id, request_id)
    if saved is None or saved['outcome'] != record:
        return False
    root = repository.path.resolve().parent
    state_path, inbox_path = root / 'state.db', root / 'inventories.sqlite3'
    if any(path.is_symlink() or not path.is_file() for path in (state_path, inbox_path)):
        return False
    with closing(State(str(state_path), readonly=True)) as state:
        cycle = state.cycle(cycle_id)
    if cycle is None or cycle.get('ordinary_event_settlement_sha256') != _selected_sha(saved):
        return False
    core = {key: value for key, value in cycle.items() if key != 'ordinary_event_settlement_sha256'}
    mirrors = repository.matches('Scan Cycles', {'Cycle ID': cycle_id})
    if (_selected_sha(core) != saved['terminal_state_sha256'] or len(mirrors) != 1
            or _selected_sha(mirrors[0][1]) != saved['mirror_sha256']):
        return False
    with closing(sqlite3.connect(inbox_path.as_uri() + '?mode=ro', uri=True)) as inbox:
        if not inbox.execute(
                "SELECT 1 FROM sqlite_master WHERE name='ordinary_event_publication_archive'").fetchone():
            return False
        row = inbox.execute(
            'SELECT proof_sha256,evidence FROM ordinary_event_publication_archive '
            'WHERE cycle=? AND company=? AND request_id=?',
            (cycle_id, identity['company_id'], request_id),
        ).fetchone()
    return bool(row and row[0] == _selected_sha(json.loads(row[1])) == saved['publication_sha256'])


def _outcome_rows(repo, binding):
    return repo.db.execute(
        "SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload,recorded_at "
        "FROM scrape_outcomes WHERE request_id=? OR CASE WHEN json_valid(payload) "
        "THEN json_extract(payload, '$.identity.cycle_id') END=?",
        (binding['request_id'], binding['cycle_id']),
    ).fetchall()


def _mirror_values(stage, stamp):
    return {
        'Cycle Status': 'Complete' if stage == 'complete' else 'Complete with exceptions',
        'Companies Complete': int(stage == 'complete'), 'Companies Partial': int(stage == 'partial'),
        'Companies Blocked': 0, 'Companies Remaining': 0, 'Completed At': stamp, 'Last Checkpoint At': stamp,
    }


def _terminal(cycle, stage, stamp):
    terminal = copy.deepcopy(cycle)
    terminal['status'] = _mirror_values(stage, stamp)['Cycle Status']
    terminal['completed_at'] = stamp
    return terminal


def _finish(engine, cycle, fixed, observation, saved):
    repo, state = engine.repo, engine.state
    if (saved is None or any(saved.get(key) != value for key, value in fixed.items())
            or _read_settlement(repo, cycle['id'], fixed['binding']['request_id']) != saved):
        raise ValueError('Ordinary event settlement does not match its durable publication.')
    binding, stage, stamp = fixed['binding'], fixed['stage'], saved['recorded_at']
    outcome = saved['outcome']
    _timestamp(stamp, 'Ordinary event settlement time')
    expected = (outcome['outcome_id'], binding['request_id'], binding['company_id'],
                binding['source_revision'], outcome['outcome'], outcome['action'], _canonical(outcome), stamp)
    if (outcome not in [classify_outcome(_facts(binding, observation, stage, current))
                        for current in (True, False)] or _outcome_rows(repo, binding) != [expected]):
        raise ValueError('Ordinary event settlement lacks its exact immutable scrape outcome.')
    mirrors = repo.matches('Scan Cycles', {'Cycle ID': cycle['id']})
    if (len(mirrors) != 1 or _selected_sha(mirrors[0][1]) != saved['mirror_sha256']
            or state.cycle(cycle['id']) != cycle):
        raise ValueError('Ordinary event settlement mirror or State changed.')
    digest = _selected_sha(saved)
    if 'ordinary_event_settlement_sha256' in cycle:
        core = {key: value for key, value in cycle.items() if key != 'ordinary_event_settlement_sha256'}
        if (cycle['ordinary_event_settlement_sha256'] != digest
                or _selected_sha(core) != saved['terminal_state_sha256']):
            raise ValueError('Ordinary event settlement terminal checkpoint changed.')
        return
    terminal = _terminal(cycle, stage, stamp)
    if (_selected_sha(cycle) != saved['pre_state_sha256']
            or _selected_sha(terminal) != saved['terminal_state_sha256']):
        raise ValueError('Ordinary event settlement cannot finish a different State checkpoint.')
    terminal['ordinary_event_settlement_sha256'] = digest
    state.save_cycle(terminal)
    if state.cycle(cycle['id']) != terminal:
        raise ValueError('Ordinary event settlement checkpoint readback failed.')
