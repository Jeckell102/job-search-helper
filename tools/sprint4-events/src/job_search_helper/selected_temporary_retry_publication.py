"""Publish only the verified durable inventory of one selected retry."""
import json
from pathlib import Path
import re

from . import publication_receipts
from .engine import Engine
from .exact_cycle_planner import _digest
from .exact_cycle_receipt import selected_retry_receipt_binding
from .exact_cycle_recovery import _recover_exact_cycle_locked, _validate_selected_retry_source
from .exact_cycle_sync import _local_acknowledgement
from .retained_event_outcome import retained_outcome_source_is_current
from .selected_temporary_retry_admission import _bound_request, _require_saved_retry_identity
from .scan_request import _cycle_views, _unfinished_from_views, cycle_metadata
from .sheet_profile import COMPACT_PROFILE
from .temporary_retry import SelectedTemporaryRetrySink


def publish_frozen_selected_retry_locked(sink, engine, remote_factory, *, cycle_id):
    """Project the private frozen provider result into its exact ordinary inbox."""
    from .integration_release import assert_release_settled
    from .retained_work_runner import assert_normal_lifecycle_not_held
    from .selected_temporary_retry_execution import load_selected_retry_inventory

    assert_release_settled(sink.root)
    assert_normal_lifecycle_not_held(sink.root, sink.reader.path, selected_retry_cycle_id=cycle_id)
    record = load_selected_retry_inventory(sink, engine.state, engine.runtime_binding, cycle_id=cycle_id)
    inventory = record['inventory']
    if inventory['status'] not in {'complete', 'partial'} or not inventory['jobs']:
        return {'state': 'HELD_NO_PUBLISHABLE_RETRY_INVENTORY', 'cycle_id': cycle_id,
                'inventory_status': inventory['status']}
    payload = {key: value for key, value in inventory.items()
               if key not in {'status', 'outcome_failure', 'verified_zero'}}
    payload['inventory_status'] = inventory['status']
    cid = record['binding']['company_id']
    cycle = engine.state.cycle(cycle_id)
    item = cycle['companies'][cid]
    if engine.inbox.get(cycle_id, cid) is None and item['stage'] in {'queued', 'inventory'}:
        outcome, _ledger, _key = sink._selected()
        if not retained_outcome_source_is_current(engine.repo, outcome['identity']):
            raise ValueError('selected_retry_publication_source_changed')
        _validate_selected_retry_source(engine, cycle, cid)
        if engine.inbox.plan(cycle_id, cid) is not None or engine.inbox.exact_remote_state(cycle_id, cid) is not None:
            raise ValueError('selected_retry_publication_inventory_missing_in_active_plan')
        engine.inbox.save(cycle_id, cid, payload)
    return publish_selected_temporary_retry_locked(sink, engine, remote_factory,
                                                   cycle_id=cycle_id, inventory_sha256=_digest(payload))


def publish_selected_temporary_retry_locked(sink, engine, remote_factory, *, cycle_id, inventory_sha256):
    """Use exact local application and readback after a verified selected fetch.

    The caller holds the inherited scraper lease and writer lock continuously.
    The supplied inventory digest must come from the selected fetch result's
    durable owner. A missing inventory cannot start another provider call.
    """
    if (not isinstance(sink, SelectedTemporaryRetrySink) or not isinstance(engine, Engine)
            or not callable(remote_factory) or not isinstance(inventory_sha256, str)
            or re.fullmatch(r'[0-9a-f]{64}', inventory_sha256) is None):
        raise ValueError('selected_retry_publication_requires_verified_fetch')
    root = sink.root
    if (Path(engine.state.path).resolve() != root / 'state.db'
            or Path(engine.repo.path).resolve() != root / 'jobs.sqlite3'
            or Path(engine.inbox.path).resolve() != root / 'inventories.sqlite3'
            or engine.repo.spreadsheet_id != sink.reader.spreadsheet_id
            or engine.repo.get_meta('sheets_profile') != COMPACT_PROFILE):
        raise ValueError('selected_retry_publication_dependencies_changed')
    outcome, path, key = sink._selected()
    claim = sink._read(path, key)
    if claim is None or claim['state'] != 'CLAIMED':
        raise ValueError('selected_retry_publication_claim_missing')
    request = _bound_request(outcome, claim['scheduled_at'])
    cid = request['company_ids'][0]
    cycle = engine.state.cycle(cycle_id)
    identity = _require_saved_retry_identity(cycle, request, engine.runtime_binding, reservation=sink.reservation_digest)
    engine.assert_runtime_binding(cycle_id, sync_only=True)

    archived = _confirmed_archive(engine, cycle, cid, inventory_sha256)
    if archived is not None:
        _complete_cycle(engine, cycle, cid)
        return {'state': 'SYNC_CONFIRMED', **archived}

    local_cycles, mirror_cycles = _cycle_views(engine.repo, engine.state)
    mirrors = [row for row in mirror_cycles if row.get('Cycle ID') == cycle_id]
    if (len(mirrors) != 1 or mirrors[0].get('Cycle Status') != cycle['status']
            or cycle_metadata(mirrors[0]).get('company_ids') != [cid]
            or any(cycle_metadata(mirrors[0]).get(field) != value for field, value in identity.items())
            or _unfinished_from_views(local_cycles, mirror_cycles) != {cycle_id}):
        raise ValueError('selected_retry_publication_cycle_scope_changed')
    if not retained_outcome_source_is_current(engine.repo, outcome['identity']):
        raise ValueError('selected_retry_publication_source_changed')
    _validate_selected_retry_source(engine, cycle, cid)
    saved = engine.inbox.get(cycle_id, cid)
    if (saved is None or saved[1] or _digest(saved[0]) != inventory_sha256
            or saved[0].get('inventory_status') not in {'complete', 'partial'}):
        raise ValueError('selected_retry_publication_inventory_changed')
    remote = remote_factory()
    if remote.spreadsheet_id != sink.reader.spreadsheet_id:
        raise ValueError('selected_retry_publication_workbook_changed')
    report = _recover_exact_cycle_locked(engine, remote, cycle_id, [cid], bind_selected_retry=True)
    if report['held'] or report['skipped']:
        return {'state': 'PUBLICATION_HELD', **report}
    cycle = engine.state.cycle(cycle_id)
    archived = _confirmed_archive(engine, cycle, cid, inventory_sha256)
    if archived is None:
        raise ValueError('selected_retry_publication_terminal_proof_missing')
    _complete_cycle(engine, cycle, cid)
    return {'state': 'SYNC_CONFIRMED', **archived}


def _confirmed_archive(engine, cycle, cid, inventory_sha256):
    with engine.inbox.lock:
        connection = engine.inbox.connection
        if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='selected_retry_publication_archive'",
        ).fetchone():
            return None
        row = connection.execute(
            'SELECT evidence FROM selected_retry_publication_archive WHERE cycle=? AND company=?',
            (cycle['id'], cid),
        ).fetchone()
        if row is None:
            return None
        evidence = json.loads(row[0])
        binding = selected_retry_receipt_binding(cycle, cid)
        receipt = publication_receipts.receipt(connection, binding)
    if (evidence['cycle_id'] != cycle['id'] or evidence['company_id'] != cid
            or evidence['inventory_sha256'] != inventory_sha256
            or evidence['binding'] != binding or receipt is None or receipt['binding'] != binding
            or receipt['state'] != publication_receipts.SYNC_CONFIRMED
            or receipt['receipt_id'] != evidence['receipt_id']
            or receipt['acknowledgement_id'] != evidence['acknowledgement_id']
            or not _local_acknowledgement(
                engine.repo, cycle['id'], cid, evidence['plan_digest'],
                evidence['receipt_id'], evidence['acknowledgement_id'])):
        raise ValueError('selected_retry_publication_archive_unverified')
    return evidence


def _complete_cycle(engine, cycle, cid):
    stage = cycle['companies'][cid]['stage']
    if stage not in {'complete', 'partial'}:
        raise ValueError('selected_retry_publication_final_checkpoint_missing')
    expected = 'Complete' if stage == 'complete' else 'Complete with exceptions'
    mirror = engine.repo.matches('Scan Cycles', {'Cycle ID': cycle['id']})
    if cycle['status'] != expected or len(mirror) != 1 or mirror[0][1].get('Cycle Status') != expected:
        engine._sync_cycle(cycle)
