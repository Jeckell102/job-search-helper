"""Seal a published ordinary Company event and complete its exact cycle."""
import copy
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .ats import ACQUIRETM_PAGINATION_CODE, validate_outcome_failure
from .company_events import acknowledged_company_event_source_is_current, read_verified_ordinary_event_admission
from .engine import Engine, State, now
from .ordinary_event_publication_archive import (
    inbox_has_exact_work, read_ordinary_event_publication, verify_ordinary_event_publication,
)
from .outcomes import classify_outcome
from .scan_request import _cycle_views, _timestamp, _unfinished_from_views
from .scoped_provider_observation import no_publication_result
from .sqlite_repository import SQLiteRepository
from .temporary_retry import _canonical, _selected_sha


def _is_acquiretm_pagination_observation(inventory):
    failure = inventory.get('outcome_failure')
    return isinstance(failure, dict) and failure.get('evidence_code') == ACQUIRETM_PAGINATION_CODE


def ordinary_event_inventory_is_publishable(inventory):
    return (bool(inventory['jobs']) and inventory['status'] in {'complete', 'partial'}
            and not _is_acquiretm_pagination_observation(inventory))


def ordinary_no_publication_result(observation):
    """Recognize one local-only result from the ordinary owner's frozen observation."""
    admitted = observation['binding']
    fact = admitted['source_fact']
    cid, company = admitted['company_id'], admitted['company_name']
    inventory = observation['inventory']
    if not _is_acquiretm_pagination_observation(inventory):
        return no_publication_result(observation, fact, cid, company)

    from .acquiretm import SOURCE

    failure = validate_outcome_failure(inventory['outcome_failure'])
    if (observation['state'] == 'FROZEN' and cid == 'COMP-0490' and company == 'Amphenol Aerospace'
            and fact == {'company_id': cid, 'company_status': 'active', 'eligible': True,
                         'ats_source': 'acquiretm', 'official_careers_url': SOURCE}
            and inventory['ats'] == 'AcquireTM' and inventory['requested_url'] == SOURCE
            and inventory['source_url'] == SOURCE and inventory['status'] == 'partial'
            and inventory['jobs'] == [] and inventory['browser_pending_urls'] == []
            and inventory['browser_discovery_incomplete'] is False and inventory.get('verified_zero') is None
            and failure is not None and failure['category'] == 'pagination_regression'):
        return 'partial', 'Partial', ACQUIRETM_PAGINATION_CODE
    return None


def settle_ordinary_event(engine, *, cycle_id, request_sha256, remote_reader=None):
    """Record one owned outcome and mirror, then checkpoint State last."""
    from .exact_cycle_receipt import (
        _ordinary_observation, load_ordinary_event_plan_context, ordinary_event_observation_binding,
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
    binding = ordinary_event_observation_binding(cycle, company_id, context)
    inventory = observation['inventory']
    published = ordinary_event_inventory_is_publishable(inventory)
    decision = None
    if published:
        proof = read_ordinary_event_publication(engine.inbox, repo, cycle_id, company_id, binding=binding)
        if proof is None or cycle['companies'][company_id].get('stage') != proof['final_stage']:
            raise ValueError('Ordinary event settlement has no exact terminal publication proof.')
        stage = proof['final_stage']
    else:
        decision = ordinary_no_publication_result(observation)
        if decision is None:
            return {'state': 'HELD_NO_PUBLISHABLE_EVENT_INVENTORY', 'cycle_id': cycle_id,
                    'company_id': company_id, 'inventory_status': inventory['status']}
        stage, scan_state, code = decision
        binding = {**binding, 'authority': 'ordinary-company-event-no-publication-v1'}
        proof = None
        _require_no_publication(engine, cycle_id, binding['request_id'])
    fixed = {
        'schema': 'ordinary-company-event-settlement-v1', 'binding': binding,
        'publication_sha256': _selected_sha(proof) if proof else None, 'stage': stage,
        'no_publication': {'scan_state': scan_state, 'evidence_code': code} if decision else None,
    }
    saved = _read_settlement(repo, cycle_id, binding['request_id'])
    if saved is None:
        company_snapshot = None
        if decision:
            if not callable(remote_reader):
                raise ValueError('Ordinary event local-only settlement requires the compact workbook reader.')
            from .ordinary_company_event_fetch import _verify_workbook
            company_snapshot = _no_publication_company(engine, cycle, company_id)
            _verify_workbook(repo, remote_reader, company_snapshot)
        with repo.transaction():
            if (_read_settlement(repo, cycle_id, binding['request_id']) is not None
                    or state.cycle(cycle_id) != cycle or cycle.get('status') != 'In Progress' or reopen() != context
                    or _outcome_rows(repo, binding)):
                raise ValueError('Ordinary event settlement conflicts with its prior state or outcome.')
            if decision:
                _require_no_publication(engine, cycle_id, binding['request_id'])
                if _no_publication_company(engine, cycle, company_id) != company_snapshot:
                    raise ValueError('Ordinary event Company changed during the workbook read.')
            elif read_ordinary_event_publication(engine.inbox, repo, cycle_id, company_id, binding=binding) != proof:
                raise ValueError('Ordinary event publication changed before settlement.')
            admission = read_verified_ordinary_event_admission(repo, state, cycle_id)
            if not published and code == ACQUIRETM_PAGINATION_CODE and not admission['source_current']:
                raise ValueError('Ordinary event repair evidence no longer owns the current Company.')
            matches = repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
            if len(matches) != 1 or matches[0][1].get('Cycle Status') != 'In Progress':
                raise ValueError('Ordinary event settlement requires its exact unfinished mirror.')
            stamp = now()
            outcome = repo._record_scrape_outcome_in_transaction(
                _facts(binding, observation, stage, admission['source_current'], published=published),
                owned_company_event=True, recorded_at=stamp,
            )['outcome']
            terminal = _terminal(cycle, company_id, stage, stamp)
            values = _mirror_values(stage, stamp)
            operations = [{
                'tab': 'Scan Cycles', 'identity': {'Cycle ID': cycle_id}, 'values': values,
                'expected': {'Cycle Status': 'In Progress'},
            }]
            if decision:
                operations.append({
                    'tab': 'Companies', 'identity': {'Company ID': company_id},
                    'values': {'Scan State': scan_state},
                    'expected': {'Active Cycle ID': cycle_id, 'Scan State': 'Queued'},
                })
            repo._commit_in_transaction(operations)
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
    result = {'outcome': saved['outcome'], 'settlement_sha256': _selected_sha(saved)}
    if published:
        return {'state': 'SYNC_CONFIRMED', **proof, **result}
    return {'state': {'complete': 'VERIFIED_ZERO', 'failed': 'FETCH_TEMPORARY', 'blocked': 'FETCH_BLOCKED',
                      'partial': 'FETCH_REPAIR_QUALIFIED'}[stage],
            'cycle_id': cycle_id, 'company_id': company_id, 'evidence_code': code, **result}


def _no_publication_company(engine, cycle, company_id):
    admission = read_verified_ordinary_event_admission(engine.repo, engine.state, cycle['id'])
    rows = engine.repo.matches('Companies', {'Company ID': company_id})
    if (not admission['source_current'] or len(rows) != 1
            or _unfinished_from_views(*_cycle_views(engine.repo, engine.state)) != {cycle['id']}
            or cycle['companies'][company_id].get('stage') != 'queued'):
        raise ValueError('Ordinary event local-only settlement requires the current sole owning cycle.')
    row = rows[0][1]
    if (row.get('Active Cycle ID') != cycle['id'] or row.get('Scan State') != 'Queued'
            or row.get('Company') != cycle['companies'][company_id]['company']
            or any(str(row.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))):
        raise ValueError('Ordinary event local-only settlement has different Company ownership.')
    return row


def _require_no_publication(engine, cycle_id, request_id):
    with engine.inbox.lock:
        if _has_publication_evidence(engine.inbox.connection, engine.repo, cycle_id, request_id):
            raise ValueError('Ordinary event local-only settlement conflicts with publication evidence.')


def _has_publication_evidence(db, repository, cycle_id, request_id):
    return (inbox_has_exact_work(db, cycle_id)
            or db.execute(
                "SELECT 1 FROM publication_receipts WHERE CASE WHEN json_valid(binding) "
                "THEN (trim(json_extract(binding,'$.request_id')) IN (?,?) "
                "OR trim(json_extract(binding,'$.cycle_id'))=?) ELSE 0 END LIMIT 1",
                (cycle_id, request_id, cycle_id),
            ).fetchone() is not None
            or (db.execute("SELECT 1 FROM sqlite_master WHERE name='ordinary_event_publication_archive'").fetchone()
                is not None and db.execute(
                    'SELECT 1 FROM ordinary_event_publication_archive WHERE cycle=? OR request_id=?',
                    (cycle_id, request_id),
                ).fetchone() is not None)
            or repository.db.execute(
                'SELECT 1 FROM exact_local_applications WHERE cycle=? LIMIT 1', (cycle_id,),
            ).fetchone() is not None)


def _facts(binding, observation, stage, current, *, published):
    inventory = observation['inventory']
    envelope = validate_outcome_failure(inventory.get('outcome_failure'))
    failure = ({'category': envelope['category'], 'provider_code': envelope['evidence_code']}
               if envelope is not None else {'category': 'none' if stage == 'complete' else 'unknown'})
    zero = not published and stage == 'complete'
    qualified = (not published and stage == 'partial'
                 and ordinary_no_publication_result(observation) == ('partial', 'Partial', ACQUIRETM_PAGINATION_CODE))
    return {
        **{key: binding[key] for key in ('request_id', 'company_event_id', 'company_id',
                                        'source_revision', 'cycle_id')},
        'source_current': current, 'company_status': 'Active', 'provider': inventory['ats'],
        'adapter_version': 'normal-scraper-v1',
        'storage_status': 'confirmed' if published else ('not_required' if zero else 'not_attempted'),
        'inventory_status': 'zero' if zero else stage, 'zero_openings_verified': zero,
        'failure': failure, 'capability': 'qualified' if qualified else 'unknown',
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
            'schema', 'binding', 'publication_sha256', 'stage', 'no_publication', 'recorded_at', 'outcome',
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
    """Verify the terminal cycle against its original frozen provider observation."""
    from .exact_cycle_receipt import (
        _ordinary_observation, load_ordinary_event_plan_context, ordinary_event_observation_binding,
    )

    identity = record['identity']
    cycle_id, request_id = identity.get('cycle_id'), identity['request_id']
    company_id = identity['company_id']
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
        with closing(SQLiteRepository(repository.path, repository.spreadsheet_id, readonly=True)) as reader:
            context = load_ordinary_event_plan_context(
                reader, state, cycle['runtime_binding'], cycle_id=cycle_id,
                request_sha256=saved['binding']['request_sha256'],
            )
    binding = ordinary_event_observation_binding(cycle, company_id, context)
    no_publication = saved['no_publication']
    if no_publication is not None:
        binding['authority'] = 'ordinary-company-event-no-publication-v1'
    if binding != saved['binding']:
        return False
    with closing(sqlite3.connect(inbox_path.as_uri() + '?mode=ro', uri=True)) as inbox:
        if no_publication is not None:
            observation = _ordinary_observation(context)
            observed = ordinary_no_publication_result(observation)
            if (observed != (saved['stage'], no_publication['scan_state'], no_publication['evidence_code'])
                    or saved['publication_sha256'] is not None
                    or _has_publication_evidence(inbox, repository, cycle_id, request_id)):
                return False
            if no_publication['evidence_code'] == ACQUIRETM_PAGINATION_CODE:
                return (acknowledged_company_event_source_is_current(repository, identity)
                        and record == classify_outcome(_facts(binding, observation, saved['stage'], True,
                                                              published=False)))
            return True
        proof = verify_ordinary_event_publication(inbox, repository, cycle_id, company_id, binding=binding)
    return proof is not None and _selected_sha(proof) == saved['publication_sha256']


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
        'Companies Blocked': int(stage in {'failed', 'blocked'}), 'Companies Remaining': 0, 'Completed At': stamp, 'Last Checkpoint At': stamp,
    }


def _terminal(cycle, company_id, stage, stamp):
    terminal = copy.deepcopy(cycle)
    terminal['status'] = _mirror_values(stage, stamp)['Cycle Status']
    terminal['completed_at'] = stamp
    terminal['companies'][company_id]['stage'] = stage
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
    decision = fixed['no_publication']
    current_states = (True,) if decision and decision['evidence_code'] == ACQUIRETM_PAGINATION_CODE else (True, False)
    if (outcome not in [classify_outcome(_facts(binding, observation, stage, current, published=decision is None))
                        for current in current_states] or _outcome_rows(repo, binding) != [expected]):
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
    if fixed['no_publication'] is not None:
        companies = repo.matches('Companies', {'Company ID': binding['company_id']})
        if (len(companies) != 1 or companies[0][1].get('Active Cycle ID') != cycle['id']
                or companies[0][1].get('Scan State') != fixed['no_publication']['scan_state']):
            raise ValueError('Ordinary event settlement Company controls changed before State completion.')
    terminal = _terminal(cycle, binding['company_id'], stage, stamp)
    if (_selected_sha(cycle) != saved['pre_state_sha256']
            or _selected_sha(terminal) != saved['terminal_state_sha256']):
        raise ValueError('Ordinary event settlement cannot finish a different State checkpoint.')
    terminal['ordinary_event_settlement_sha256'] = digest
    state.save_cycle(terminal)
    if state.cycle(cycle['id']) != terminal:
        raise ValueError('Ordinary event settlement checkpoint readback failed.')
