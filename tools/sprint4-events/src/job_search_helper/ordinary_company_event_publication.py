"""Publish a previously frozen ordinary Company event through exact-v2 only."""
from contextlib import closing
from pathlib import Path

from .company_events import read_verified_ordinary_event_admission
from .engine import Engine, State
from .exact_cycle_recovery import _recover_exact_cycle_locked
from .exact_cycle_sync import _company_guard
from .integration_release import assert_release_settled
from .ordinary_event_publication_archive import read_ordinary_event_publication
from .ordinary_event_settlement import settle_ordinary_event
from .repository import GoogleRepository
from .retained_work_runner import assert_normal_lifecycle_not_held
from .scan_request import _cycle_views, _unfinished_from_views, cycle_metadata
from .sheet_profile import COMPACT_SCHEMAS
from .sqlite_repository import SQLiteRepository


def publish_ordinary_event_locked(engine, remote_factory, *, cycle_id, request_sha256, remote_reader=None):
    """Use the caller's scraper and writer leases, with no provider on this path."""
    from .exact_cycle_receipt import (
        _ordinary_observation, load_ordinary_event_plan_context, ordinary_event_plan_payload,
        ordinary_event_receipt_binding,
    )

    if not isinstance(engine, Engine) or not callable(remote_factory):
        raise ValueError('Ordinary event publication requires its exact engine and workbook writer.')
    root = Path(engine.state.path).resolve().parent
    stores = ((engine.state, 'state.db'), (engine.repo, 'jobs.sqlite3'),
              (engine.inbox, 'inventories.sqlite3'))
    if (any(store is None or Path(store.path).resolve() != root / name or (root / name).is_symlink()
            for store, name in stores)
            or not isinstance(engine.repo, SQLiteRepository)):
        raise ValueError('Ordinary event publication requires its canonical local stores.')
    assert_release_settled(root)
    assert_normal_lifecycle_not_held(root, engine.repo.path, ordinary_event_cycle_id=cycle_id)

    def reopen():
        with (closing(SQLiteRepository(engine.repo.path, engine.repo.spreadsheet_id, readonly=True)) as reader,
              closing(State(str(engine.state.path), readonly=True)) as state):
            return load_ordinary_event_plan_context(
                reader, state, engine.runtime_binding, cycle_id=cycle_id, request_sha256=request_sha256,
            )

    context = reopen()
    cycle = engine.state.cycle(cycle_id)
    event = cycle['company_event']
    cid = event['company_id']
    inventory = _ordinary_observation(context)['inventory']
    if not inventory['jobs'] or inventory['status'] not in {'complete', 'partial'}:
        return settle_ordinary_event(
            engine, cycle_id=cycle_id, request_sha256=request_sha256, remote_reader=remote_reader,
        )
    payload = ordinary_event_plan_payload(context)
    binding = ordinary_event_receipt_binding(cycle, cid, payload, context)

    archived = read_ordinary_event_publication(engine.inbox, engine.repo, cycle_id, cid, binding=binding)
    if archived is not None:
        return settle_ordinary_event(engine, cycle_id=cycle_id, request_sha256=request_sha256)

    def current_company():
        local_cycles, mirrors = _cycle_views(engine.repo, engine.state)
        company = engine.repo.matches('Companies', {'Company ID': cid})
        request = [row for row in local_cycles if row.get('start_request_id') == binding['request_id']]
        mirror = [row for row in mirrors if cycle_metadata(row).get('start_request_id') == binding['request_id']]
        if (len(request) != 1 or len(mirror) != 1 or len(company) != 1
                or request[0]['id'] != cycle_id or mirror[0].get('Cycle ID') != cycle_id
                or _unfinished_from_views(local_cycles, mirrors) != {cycle_id}
                or not read_verified_ordinary_event_admission(engine.repo, engine.state, cycle_id)['source_current']
                or reopen() != context):
            raise ValueError('Ordinary event publication source, admission or cycle scope changed.')
        row = company[0][1]
        if (row.get('Active Cycle ID') != cycle_id
                or row.get('Scan State') == 'Blocked / Manual Review'
                or any(str(row.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))
                or row.get('Company') != request[0]['companies'][cid].get('company')):
            raise ValueError('Ordinary event publication Company ownership changed.')
        return row

    current_company()
    if cycle['companies'][cid].get('stage') not in {'queued', 'inventory', 'complete', 'partial'}:
        raise ValueError('Ordinary event publication requires its exact inventory checkpoint.')
    saved = engine.inbox.get(cycle_id, cid)
    if saved is None:
        if (cycle['companies'][cid].get('stage') != 'queued' or engine.inbox.plan(cycle_id, cid) is not None
                or engine.inbox.exact_remote_state(cycle_id, cid) is not None):
            raise ValueError('Ordinary event publication inventory is missing after planning.')
        engine.inbox.save(cycle_id, cid, payload)
    elif saved != (payload, False):
        raise ValueError('Ordinary event publication has a conflicting stored inventory.')

    remote = remote_factory()
    if (not isinstance(remote, GoogleRepository) or remote.schemas != COMPACT_SCHEMAS
            or remote.spreadsheet_id != context.spreadsheet_id):
        raise ValueError('Ordinary event publication requires the exact compact Sheets writer.')
    remote.validate_schema()

    def guard(company_id, requested_url):
        if company_id != cid or requested_url != payload['requested_url']:
            raise ValueError('Ordinary event publication guard has a foreign scope.')
        previous = current_company()
        control = _company_guard(engine.repo, remote, cid, requested_url, additional_fields=('ATS / Source',))
        if current_company() != previous:
            raise ValueError('Ordinary event publication Company source changed during workbook verification.')
        return control

    report = _recover_exact_cycle_locked(
        engine, remote, cycle_id, [cid], ordinary_event_context=context, ordinary_event_guard=guard,
    )
    if report['held'] or report['skipped']:
        return {'state': 'PUBLICATION_HELD', **report}
    if reopen() != context:
        raise ValueError('Ordinary event publication observation changed before settlement.')
    return settle_ordinary_event(engine, cycle_id=cycle_id, request_sha256=request_sha256)
