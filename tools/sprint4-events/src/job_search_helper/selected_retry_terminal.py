"""Commit one exact selected retry that has no publishable inventory."""
import copy
import json
import os
from pathlib import Path

from . import publication_receipts
from .ats import validate_outcome_failure
from .company_events import canonical_company_fact
from .company_sources import repair_source
from .exact_cycle_receipt import selected_retry_receipt_binding
from .outcomes import classify_outcome
from .repository import _url
from .integration_release import assert_release_settled
from .retained_event_outcome import retained_outcome_source_is_current
from .retained_work_runner import assert_normal_lifecycle_not_held
from .scan_request import _cycle_views, _timestamp, _unfinished_from_views, cycle_metadata
from .sheet_profile import COMPACT_PROFILE
from .selected_temporary_retry_execution import _selected_provider_identity, load_selected_retry_inventory
from .temporary_retry import _canonical, _selected_sha


def _settle_selected_retry_locked(sink, engine, cycle_id, frozen, workbook_guard):
    """Settle a returned no-work result while both caller-owned leases are held."""
    root, repo, inbox, state = sink.root, engine.repo, engine.inbox, engine.state
    if (any(Path(store.path).resolve() != root / name or (root / name).is_symlink()
            for store, name in ((repo, 'jobs.sqlite3'), (inbox, 'inventories.sqlite3'), (state, 'state.db')))
            or repo.spreadsheet_id != sink.reader.spreadsheet_id
            or repo.get_meta('sheets_profile') != COMPACT_PROFILE):
        raise ValueError('selected_retry_terminal_dependencies_changed')

    cycle = state.cycle(cycle_id)
    binding = frozen['binding']
    cid = binding['company_id']
    request = binding['request']
    parent, _ledger, parent_key = sink._selected()
    item = cycle['companies'][cid]
    decision = _decision(frozen, item['outcome_source_fact'], cid, item['company'])
    if decision is None:
        return {'state': 'HELD_NO_PUBLISHABLE_RETRY_INVENTORY', 'cycle_id': cycle_id,
                'inventory_status': frozen['inventory']['status']}
    disposition, stage, scan_state, evidence_code = decision
    facts = {
        'request_id': request['request_id'], 'company_id': cid, 'cycle_id': cycle_id,
        'source_revision': request['source_revision'], 'temporary_retry_outcome_id': parent['outcome_id'],
        'provider': frozen['inventory']['ats'], 'adapter_version': 'normal-scraper-v1',
        'source_current': True, 'company_status': 'Active', 'capability': 'unknown',
        'inventory_status': 'zero' if stage == 'complete' else frozen['inventory']['status'],
        'zero_openings_verified': stage == 'complete',
        'storage_status': 'not_required' if stage == 'complete' else 'not_attempted',
        'failure': {'category': 'none'} if stage == 'complete' else {
            'category': frozen['inventory']['outcome_failure']['category'], 'provider_code': evidence_code,
        },
    }
    outcome = classify_outcome(facts)
    fixed = {
        'schema': 'selected-retry-terminal-v1', 'cycle_id': cycle_id, 'company_id': cid,
        'request_id': request['request_id'], 'request_fingerprint': binding['request_fingerprint'],
        'parent': parent_key, 'runtime_sha256': _selected_sha(binding['runtime']),
        'inventory_sha256': frozen['inventory_sha256'], 'frozen_sha256': frozen['sha256'],
        'disposition': disposition, 'evidence_code': evidence_code, 'outcome': outcome,
    }
    engine.assert_runtime_binding(cycle_id, sync_only=True)
    _assert_no_publication(engine, cycle, cid)
    existing = _receipt(repo, fixed)
    if existing is not None:
        return _finish_state(engine, cycle, fixed, existing, stage, scan_state)
    if _outcome_rows(repo, outcome):
        raise ValueError('selected_retry_terminal_outcome_already_exists')
    if cycle.get('selected_retry_terminal_sha256') or item.get('stage') != 'queued':
        raise ValueError('selected_retry_terminal_state_conflicts')
    if not callable(workbook_guard):
        raise ValueError('selected_retry_terminal_requires_workbook_read')

    company, mirror = _before(sink, engine, cycle, cid, parent['identity'])
    workbook_guard(company)
    # Recheck the local facts with the Jobs transaction held after the remote read.
    with repo.transaction():
        assert_release_settled(root)
        assert_normal_lifecycle_not_held(root, repo.path, selected_retry_cycle_id=cycle_id)
        if (state.cycle(cycle_id) != cycle
                or load_selected_retry_inventory(sink, state, engine.runtime_binding, cycle_id=cycle_id) != frozen
                or _before(sink, engine, cycle, cid, parent['identity']) != (company, mirror)):
            raise ValueError('selected_retry_terminal_checkpoint_changed')
        _assert_no_publication(engine, cycle, cid)
        repo.db.execute(
            'CREATE TABLE IF NOT EXISTS selected_retry_terminal_receipts ('
            'parent_outcome_id TEXT PRIMARY KEY, cycle TEXT NOT NULL UNIQUE, company TEXT NOT NULL, '
            'outcome_id TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL, payload TEXT NOT NULL)')
        if _receipt(repo, fixed) is not None or _outcome_rows(repo, outcome):
            raise ValueError('selected_retry_terminal_outcome_already_exists')
        completed_at = sink._now().isoformat()
        terminal = _terminal_cycle(cycle, cid, stage, completed_at)
        company_update = {'Active Cycle ID': '', 'Scan State': scan_state}
        mirror_update = _mirror_update(stage, completed_at)
        receipt = {
            **fixed, 'recorded_at': completed_at, 'queued_state_sha256': _selected_sha(cycle),
            'terminal_state_sha256': _selected_sha(terminal), 'company_update': company_update,
            'mirror_update': mirror_update, 'mirror_sha256': _selected_sha({**mirror, **mirror_update}),
        }
        result = repo._record_scrape_outcome_in_transaction(facts, owned_selected_retry=True,
                                                            recorded_at=completed_at)
        if not result['recorded'] or result['outcome'] != outcome:
            raise ValueError('selected_retry_terminal_outcome_conflicts')
        repo._commit_in_transaction([
            {'tab': 'Companies', 'identity': {'Company ID': cid}, 'values': company_update,
             'expected': {'Active Cycle ID': cycle_id, 'Scan State': 'Queued'}},
            {'tab': 'Scan Cycles', 'identity': {'Cycle ID': cycle_id}, 'values': mirror_update,
             'expected': {'Cycle Status': 'In Progress'}},
        ])
        repo.db.execute('INSERT INTO selected_retry_terminal_receipts VALUES (?,?,?,?,?,?)',
                        (parent['outcome_id'], cycle_id, cid, outcome['outcome_id'],
                         _selected_sha(receipt), _canonical(receipt)))
        _verify_after(repo, cycle_id, cid, receipt)
    return _finish_state(engine, cycle, fixed, _receipt(repo, fixed), stage, scan_state)


def _decision(frozen, fact, cid, company_name):
    inventory = frozen['inventory']
    expected_ats, board, _ = repair_source(fact['ats_source'], inventory['requested_url'], cid, company_name)
    provider = _selected_provider_identity(expected_ats, board)
    if (inventory['jobs'] != [] or inventory['browser_pending_urls'] != []
            or inventory['browser_discovery_incomplete'] is not False
            or not provider or _selected_provider_identity(inventory['ats'], inventory['source_url']) != provider
            or _url(inventory['requested_url']) != fact['official_careers_url']
            or _timestamp(frozen['fetch_started_at'], 'Selected retry fetch start')
            > _timestamp(inventory['fetched_at'], 'Selected retry fetch end')):
        return None
    code = inventory.get('verified_zero')
    if inventory['status'] == 'complete' and inventory.get('outcome_failure') is None:
        if ((code == 'greenhouse_explicit_total_zero' and provider.startswith('greenhouse:'))
                or (code == 'samtec_jobvite_explicit_zero' and cid == 'COMP-0739'
                    and fact['official_careers_url'].rstrip('/') == 'https://jobs.jobvite.com/samtec/search')):
            return 'VERIFIED_ZERO', 'complete', 'Complete', code
    failure = validate_outcome_failure(inventory.get('outcome_failure'))
    if code is not None or failure is None:
        return None
    if failure['category'] == 'temporary_transport' and inventory['status'] in {'failed', 'partial'}:
        return 'HELD_TEMPORARY_RETRY_CAP', 'failed', 'Failed', failure['evidence_code']
    if failure['category'] == 'access_denied' and inventory['status'] == 'blocked':
        return 'HELD_ACCESS_DENIED', 'blocked', 'Blocked / Manual Review', failure['evidence_code']
    return None


def _before(sink, engine, cycle, cid, parent_identity):
    repo, state = engine.repo, engine.state
    cycle_id = cycle['id']
    local, mirror = _cycle_views(repo, state)
    mirrors = repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
    companies = repo.matches('Companies', {'Company ID': cid})
    request_id = cycle['start_request_id']
    if (os.path.lexists(sink.root / 'next-scan.json') or cycle['status'] != 'In Progress'
            or len(mirrors) != 1 or len(companies) != 1
            or [row.get('id') for row in local if row.get('start_request_id') == request_id] != [cycle_id]
            or [row.get('Cycle ID') for row in mirror
                if cycle_metadata(row).get('start_request_id') == request_id] != [cycle_id]
            or _unfinished_from_views(local, mirror) != {cycle_id}):
        raise ValueError('selected_retry_terminal_scope_changed')
    row = mirrors[0][1]
    notes = cycle_metadata(row)
    if (row.get('Cycle Status') != 'In Progress' or notes.get('company_ids') != [cid]
            or any(notes.get(key) != cycle.get(key) for key in (
                'all', 'start_request_id', 'request_fingerprint', 'temporary_retry', 'runtime_binding',
                'start_last', 'supersedes', 'selected_retry_reservation_sha256'))):
        raise ValueError('selected_retry_terminal_mirror_changed')
    company = companies[0][1]
    item = cycle['companies'][cid]
    if (company.get('Active Cycle ID') != cycle_id or company.get('Scan State') != 'Queued'
            or str(company.get('Automatic Retry?') or '').strip().casefold() == 'no'
            or any(str(company.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))
            or company.get('Company') != item['company']
            or canonical_company_fact(company) != item['outcome_source_fact']
            or not retained_outcome_source_is_current(repo, parent_identity)):
        raise ValueError('selected_retry_terminal_source_changed')
    return company, row


def _assert_no_publication(engine, cycle, cid):
    def has_cycle(db, tables):
        return any(
            db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            and db.execute(f'SELECT 1 FROM {table} WHERE cycle=? LIMIT 1', (cycle['id'],)).fetchone()
            for table in tables
        )

    repo, inbox = engine.repo, engine.inbox
    with inbox.lock:
        db = inbox.connection
        binding = selected_retry_receipt_binding(cycle, cid)
        if (db.execute('SELECT id FROM destination').fetchall() != [(repo.spreadsheet_id,)]
                or has_cycle(db, ('inventories', 'sync_plans', 'exact_sync_chunks', 'exact_plan_local_state',
                                  'exact_remote_plans', 'exact_legacy_plan_migrations',
                                  'exact_selected_legacy_recoveries', 'selected_retry_publication_archive'))
                or publication_receipts.receipt(db, binding) is not None
                or db.execute(
                    "SELECT 1 FROM publication_receipts WHERE CASE WHEN json_valid(binding) "
                    "THEN json_extract(binding, '$.request_id') END=? LIMIT 1",
                    (binding['request_id'],)).fetchone()
                or has_cycle(repo.db, ('exact_local_applications',))):
            raise ValueError('selected_retry_terminal_publication_present')


def _outcome_rows(repo, outcome):
    identity = outcome['identity']
    return repo.db.execute(
        'SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload,recorded_at '
        "FROM scrape_outcomes WHERE request_id=? OR outcome_id=? OR CASE WHEN json_valid(payload) "
        "THEN json_extract(payload, '$.identity.cycle_id') END=?",
        (identity['request_id'], outcome['outcome_id'], identity['cycle_id'])).fetchall()


def _receipt(repo, fixed):
    db = repo.db
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                      "AND name='selected_retry_terminal_receipts'").fetchone():
        return None
    outcome = fixed['outcome']
    identifiers = (fixed['parent']['outcome_id'], fixed['cycle_id'], fixed['company_id'], outcome['outcome_id'])
    rows = db.execute(
        'SELECT parent_outcome_id,cycle,company,outcome_id,sha256,payload FROM selected_retry_terminal_receipts '
        'WHERE parent_outcome_id=? OR cycle=? OR outcome_id=?',
        (identifiers[0], identifiers[1], identifiers[3])).fetchall()
    if not rows:
        return None
    payload = json.loads(rows[0][-1])
    if (set(payload) != set(fixed) | {'recorded_at', 'queued_state_sha256', 'terminal_state_sha256',
                                    'company_update', 'mirror_update', 'mirror_sha256'}
            or any(payload.get(key) != value for key, value in fixed.items())
            or rows != [(*identifiers, _selected_sha(payload), _canonical(payload))]):
        raise ValueError('selected_retry_terminal_receipt_conflicts')
    identity = outcome['identity']
    expected = (outcome['outcome_id'], identity['request_id'], identity['company_id'],
                identity['source_revision'], outcome['outcome'], outcome['action'],
                _canonical(outcome), payload['recorded_at'])
    if _outcome_rows(repo, outcome) != [expected]:
        raise ValueError('selected_retry_terminal_outcome_conflicts')
    return payload


def _mirror_update(stage, stamp):
    return {
        'Cycle Status': 'Complete' if stage == 'complete' else 'Complete with exceptions',
        'Companies Remaining': 0, 'Companies Complete': int(stage == 'complete'),
        'Companies Blocked': int(stage in {'failed', 'blocked'}),
        'Last Checkpoint At': stamp, 'Completed At': stamp,
    }


def _terminal_cycle(cycle, cid, stage, stamp):
    terminal = copy.deepcopy(cycle)
    terminal['status'] = _mirror_update(stage, stamp)['Cycle Status']
    terminal['completed_at'] = stamp
    terminal['companies'][cid]['stage'] = stage
    return terminal


def _verify_after(repo, cycle_id, cid, receipt):
    companies = repo.matches('Companies', {'Company ID': cid})
    mirrors = repo.matches('Scan Cycles', {'Cycle ID': cycle_id})
    if (len(companies) != 1 or len(mirrors) != 1
            or _selected_sha(mirrors[0][1]) != receipt['mirror_sha256']
            or any(companies[0][1].get(key) != value for key, value in receipt['company_update'].items())):
        raise ValueError('selected_retry_terminal_owned_rows_changed')


def _finish_state(engine, cycle, fixed, receipt, stage, scan_state):
    if receipt is None:
        raise ValueError('selected_retry_terminal_receipt_missing')
    cid, cycle_id = fixed['company_id'], fixed['cycle_id']
    receipt_sha = _selected_sha(receipt)
    if (receipt['company_update'] != {'Active Cycle ID': '', 'Scan State': scan_state}
            or receipt['mirror_update'] != _mirror_update(stage, receipt['recorded_at'])):
        raise ValueError('selected_retry_terminal_receipt_controls_changed')
    _timestamp(receipt['recorded_at'], 'Selected retry terminal time')
    current = engine.state.cycle(cycle_id)
    if current != cycle:
        raise ValueError('selected_retry_terminal_checkpoint_changed')
    if 'selected_retry_terminal_sha256' in cycle:
        core = {key: value for key, value in cycle.items() if key != 'selected_retry_terminal_sha256'}
        if (cycle['selected_retry_terminal_sha256'] != receipt_sha
                or _selected_sha(core) != receipt['terminal_state_sha256']):
            raise ValueError('selected_retry_terminal_checkpoint_conflicts')
    else:
        _verify_after(engine.repo, cycle_id, cid, receipt)
        terminal = _terminal_cycle(cycle, cid, stage, receipt['recorded_at'])
        if (_selected_sha(cycle) != receipt['queued_state_sha256']
                or _selected_sha(terminal) != receipt['terminal_state_sha256']):
            raise ValueError('selected_retry_terminal_checkpoint_conflicts')
        terminal['selected_retry_terminal_sha256'] = receipt_sha
        engine.state.save_cycle(terminal)
        if engine.state.cycle(cycle_id) != terminal:
            raise ValueError('selected_retry_terminal_checkpoint_readback_failed')
    return {'state': fixed['disposition'], 'cycle_id': cycle_id, 'company_id': cid,
            'outcome_id': fixed['outcome']['outcome_id'], 'receipt_sha256': receipt_sha}
