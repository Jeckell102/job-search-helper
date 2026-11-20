"""Explicit operator entry for one ordinary Company event under scraper admission."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import re
import sqlite3

from . import cli
from .company_events import (
    _json_digest, canonical_company_fact, has_pending_eligible_company_event,
    read_verified_ordinary_event_admission, read_verified_queued_event,
)
from .engine import Engine, State
from .inbox import InventoryInbox
from .integration_release import assert_release_settled
from .retained_work_runner import assert_normal_lifecycle_not_held
from .scan_request import _cycle_views, _unfinished_from_views, cycle_metadata, requested_scan, request_fingerprint
from .sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from .sqlite_repository import SQLiteRepository


COMMAND = 'ordinary-company-event'
_HELP = 'Use ./job-search-scraper ordinary-company-event --help for the exact request and cycle commands.'
_TERMINAL = {'Complete', 'Complete with exceptions'}


class OrdinaryEventLifecycleHold(ValueError):
    """The exact ordinary event owns the work a generic entry requested."""


def _request_file(root):
    path = root / 'next-scan.json'
    if path.is_symlink():
        raise ValueError('Pending scan request may not be a symlink.')
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Pending scan request is not a regular file.')
    request = json.loads(path.read_bytes())
    if not isinstance(request, dict):
        raise ValueError('Pending scan request is not a JSON object.')
    return request


def _has_event_provenance(record, *, request_field):
    request = record.get(request_field)
    return record.get('company_event') is not None or (
        isinstance(request, str) and request.startswith('company-event:')
    )


def guard_generic_ordinary_event(database, *, allow_queued=False, fresh=False, selected_cycle_id=None):
    """Hold generic scraper routes before a queued or adopted event can enter them."""
    if cli.storage_backend() != 'sqlite':
        return
    database = Path(database)
    request = _request_file(database.parent)
    if (request is not None and _has_event_provenance(request, request_field='request_id')
            and 'manual_retained' not in request and not allow_queued):
        raise OrdinaryEventLifecycleHold('An ordinary Company-event request is waiting in the queue. ' + _HELP)
    if database.is_file():
        with closing(State(str(database), readonly=True)) as state:
            if any(_has_event_provenance(cycle, request_field='start_request_id')
                   and (cycle.get('status') not in _TERMINAL or cycle['id'] == selected_cycle_id)
                   for cycle in state.cycles()):
                raise OrdinaryEventLifecycleHold('An unsettled ordinary Company event requires its exact cycle. ' + _HELP)
    # An explicit manual/full request retains its existing behavior. An
    # unselected outbox event cannot implicitly turn a bare start into intake.
    jobs = cli.job_database_path()
    if fresh and request is None and jobs.is_file():
        with closing(sqlite3.connect(jobs.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            # Keep this first setup path compatible with pre-outbox databases.
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='company_event_outbox'").fetchone():
                with closing(cli.get_repository(write=False, interactive=False)) as local:
                    if has_pending_eligible_company_event(local):
                        raise OrdinaryEventLifecycleHold('An ordinary Company event is waiting for a bridged request. ' + _HELP)


def _digest_text(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _cycle_id(value):
    return isinstance(value, str) and re.fullmatch(r'CYC-[0-9A-F]{12}', value) is not None


def parse_ordinary_event_command(argv):
    parser = argparse.ArgumentParser(prog='./job-search-scraper ' + COMMAND, allow_abbrev=False)
    subcommands = parser.add_subparsers(dest='action', required=True)
    for name in ('admit-fetch', 'publish'):
        command = subcommands.add_parser(name, allow_abbrev=False)
        command.add_argument('--request-sha256', action='append', required=True, metavar='SHA256')
        command.add_argument('--cycle-id', action='append', required=name == 'publish', metavar='CYC-ID')
    args = parser.parse_args(argv)
    if len(args.request_sha256) != 1 or not _digest_text(args.request_sha256[0]):
        parser.error('--request-sha256 requires one lowercase SHA-256 digest')
    if args.cycle_id is not None and (len(args.cycle_id) != 1 or not _cycle_id(args.cycle_id[0])):
        parser.error('--cycle-id requires one ordinary CYC ID')
    args.request_sha256 = args.request_sha256[0]
    args.cycle_id = args.cycle_id[0] if args.cycle_id is not None else None
    return args


def _open_readers(stack, database, jobs, inbox_path):
    root = database.parent
    if (database != root / 'state.db' or jobs != root / 'jobs.sqlite3'
            or any(path.resolve(strict=True) != path or not path.is_file()
                   for path in (database, jobs, inbox_path))):
        raise ValueError('Ordinary Company-event commands require canonical existing SQLite stores.')
    workbook_id = InventoryInbox.destination_id(inbox_path)
    if workbook_id != os.environ.get('SPREADSHEET_ID') or not re.fullmatch(r'[A-Za-z0-9_-]+', workbook_id):
        raise ValueError('Ordinary Company-event configured workbook differs from its Inbox.')
    local = stack.enter_context(closing(SQLiteRepository(jobs, workbook_id, readonly=True)))
    state = stack.enter_context(closing(State(str(database), readonly=True)))
    if local.get_meta('sheets_profile') != COMPACT_PROFILE:
        raise ValueError('Ordinary Company-event commands require the compact Sheets profile.')
    return local, state


def _open_engine(stack, database, jobs, workbook_id, runtime, *, publication=False):
    repository = stack.enter_context(closing(SQLiteRepository(jobs, workbook_id)))
    state = stack.enter_context(closing(State(str(database))))
    inbox = (stack.enter_context(closing(InventoryInbox(database.parent / 'inventories.sqlite3', workbook_id)))
             if publication else None)
    return Engine(repository, state, inbox=inbox, runtime_binding=runtime)


def _archived_cycle(local, state, runtime, root, digest, cycle_id, local_cycles, mirrors):
    from .company_events import _read_ordinary_event_file

    path = root / 'company-event-bridge' / 'ordinary-admissions' / (digest + '.json')
    if not path.exists() and not path.is_symlink():
        raise ValueError('No queued or archived ordinary Company-event admission matches the exact digest.')
    saved = _read_ordinary_event_file(path)
    if not saved or _json_digest(saved) != digest:
        raise ValueError('Ordinary Company-event admission archive does not match the selected digest.')
    request_id = saved.get('request_id')
    found = [cycle for cycle in local_cycles if cycle.get('start_request_id') == request_id]
    found_mirrors = [row for row in mirrors if cycle_metadata(row).get('start_request_id') == request_id]
    if (not request_id or len(found) != 1 or len(found_mirrors) != 1
            or found_mirrors[0].get('Cycle ID') != found[0].get('id')
            or not _cycle_id(found[0].get('id')) or (cycle_id is not None and found[0]['id'] != cycle_id)):
        raise ValueError('Ordinary Company-event archive has no unique matching cycle.')
    cycle = found[0]
    Engine.validate_cycle_runtime_binding(cycle, runtime)
    admission = read_verified_ordinary_event_admission(local, state, cycle['id'])
    if admission['request_sha256'] != digest:
        raise ValueError('Ordinary Company-event archive changed after exact cycle selection.')
    return cycle, admission


def _queue_admission(local, runtime, root, digest, cycle_id, local_cycles, mirrors):
    raw, request = read_verified_queued_event(local, root)
    if _json_digest(request) != digest:
        raise ValueError('Queued ordinary Company-event request does not match the exact digest.')
    event = request['company_event']
    cid = event['company_id']
    found = [cycle for cycle in local_cycles if cycle.get('start_request_id') == request['request_id']]
    reflected = [row for row in mirrors if cycle_metadata(row).get('start_request_id') == request['request_id']]
    blockers = _unfinished_from_views(local_cycles, mirrors)
    matches = local.matches('Companies', {'Company ID': cid})
    company = matches[0][1] if len(matches) == 1 else {}
    if (str(company.get('Company Status', '')).strip().casefold() != 'active'
            or not company.get('Official Careers URL') or not company.get('Company')
            or any(str(company.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))
            or company.get('Scan State') == 'Blocked / Manual Review'):
        raise ValueError('Queued ordinary Company event has no eligible unclaimed Company.')
    if not found and not reflected and cycle_id is None:
        if blockers:
            raise ValueError('Ordinary Company-event admission is held behind unfinished work.')
        return raw, request, None
    if (len(found) != 1 or len(reflected) != 1 or not _cycle_id(found[0].get('id'))
            or (cycle_id is not None and cycle_id != found[0]['id'])
            or blockers != {found[0]['id']}):
        raise ValueError('Ordinary Company-event admission is held by conflicting cycle evidence.')
    cycle, mirror = found[0], reflected[0]
    Engine.validate_cycle_runtime_binding(cycle, runtime)
    notes = cycle_metadata(mirror)
    if (cycle.get('all') is not False or cycle.get('status') != 'In Progress'
            or cycle.get('company_event') != event or set(cycle.get('companies', {})) != {cid}
            or cycle['companies'][cid].get('stage') != 'queued'
            or cycle['companies'][cid].get('company') != company['Company']
            or cycle['companies'][cid].get('outcome_source_revision') != event['source_revision']
            or cycle['companies'][cid].get('outcome_source_fact') != canonical_company_fact(company)
            or cycle.get('request_fingerprint') != request_fingerprint(request, [cid])
            or mirror['Cycle ID'] != cycle['id'] or mirror.get('Cycle Status') != cycle['status']
            or notes.get('company_ids') != [cid] or notes.get('all') is not False
            or any(notes.get(key) != cycle.get(key) for key in (
                'company_event', 'request_fingerprint', 'runtime_binding',
            )) or company.get('Active Cycle ID') != cycle['id']):
        raise ValueError('Ordinary Company-event incomplete admission requires reconciliation.')
    return raw, request, cycle['id']


def _publish_preflight(local, state, runtime, cycle, admission, inbox_path):
    from .exact_cycle_receipt import (
        _ordinary_observation, load_ordinary_event_plan_context, ordinary_event_plan_payload,
        ordinary_event_receipt_binding,
    )
    from .ordinary_event_publication_archive import verify_ordinary_event_publication
    from .ordinary_event_settlement import _has_publication_evidence
    from .scoped_provider_observation import no_publication_result

    cid = admission['request']['company_ids'][0]
    cycle_id, digest = cycle['id'], admission['request_sha256']
    request_id = admission['request']['request_id']
    context = load_ordinary_event_plan_context(local, state, runtime, cycle_id=cycle_id, request_sha256=digest)
    observation = _ordinary_observation(context)
    inventory = observation['inventory']
    if inventory['status'] not in {'complete', 'partial'} or not inventory['jobs']:
        item = cycle['companies'][cid]
        if no_publication_result(observation, item['outcome_source_fact'], cid, item['company']) is None:
            return 'held'
        with closing(sqlite3.connect(inbox_path.as_uri() + '?mode=ro', uri=True)) as connection:
            if _has_publication_evidence(connection, local, cycle_id, request_id):
                raise ValueError('Ordinary Company-event local-only settlement conflicts with publication evidence.')
        existing = (local.db.execute(
            'SELECT cycle,request_id FROM ordinary_event_settlements WHERE cycle=? OR request_id=?',
            (cycle_id, request_id),
        ).fetchall() if local.db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='ordinary_event_settlements'",
        ).fetchone() else [])
        if existing and existing != [(cycle_id, request_id)]:
            raise ValueError('Ordinary Company-event no-publication settlement has a competing owner.')
        if not existing:
            rows = local.matches('Companies', {'Company ID': cid})
            company = rows[0][1] if len(rows) == 1 else {}
            if (not admission['source_current'] or cycle.get('status') != 'In Progress'
                    or cycle['companies'][cid].get('stage') != 'queued'
                    or company.get('Active Cycle ID') != cycle_id or company.get('Scan State') != 'Queued'
                    or company.get('Company') != cycle['companies'][cid].get('company')
                    or any(str(company.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))):
                raise ValueError('Ordinary Company-event no-publication source or ownership is held.')
        return 'no-publication'
    if (inventory.get('verified_zero') is not None or (inventory['status'] == 'complete'
            and (inventory['browser_pending_urls'] or inventory['browser_discovery_incomplete']))):
        return 'held'

    payload = ordinary_event_plan_payload(context)
    binding = ordinary_event_receipt_binding(cycle, cid, payload, context)
    with closing(sqlite3.connect(inbox_path.as_uri() + '?mode=ro', uri=True)) as connection:
        if verify_ordinary_event_publication(connection, local, cycle_id, cid, binding=binding):
            return 'publication'
        companies = local.matches('Companies', {'Company ID': cid})
        row = companies[0][1] if len(companies) == 1 else {}
        stage = cycle['companies'][cid].get('stage')
        if (not admission['source_current'] or stage not in {'queued', 'inventory', 'complete', 'partial'}
                or cycle.get('status') != 'In Progress' or row.get('Active Cycle ID') != cycle_id
                or row.get('Company') != cycle['companies'][cid].get('company')
                or row.get('Scan State') == 'Blocked / Manual Review'
                or any(str(row.get(key) or '').strip() for key in ('Claimed By', 'Claim Token'))):
            raise ValueError('Ordinary Company-event publication source, ownership or checkpoint is held.')
        saved = connection.execute(
            'SELECT company,payload,blocked FROM inventories WHERE cycle=?', (cycle_id,),
        ).fetchall()
        plans = connection.execute(
            'SELECT company,payload FROM sync_plans WHERE cycle=?', (cycle_id,),
        ).fetchall()
        if saved and (len(saved) != 1 or saved[0][0] != cid or saved[0][2]
                      or json.loads(saved[0][1]) != payload):
            raise ValueError('Ordinary Company-event publication has competing Inbox inventory.')
        if plans:
            plan = json.loads(plans[0][1])
            if (len(plans) != 1 or plans[0][0] != cid or not isinstance(plan, dict)
                    or plan.get('exact_plan_version') != 2 or plan.get('ordinary_company_event') != binding):
                raise ValueError('Ordinary Company-event publication has a competing Inbox plan.')
        if not saved and (plans or stage != 'queued'):
            raise ValueError('Ordinary Company-event exact inventory is missing after planning.')
    return 'publication'


def execute_ordinary_event(action, admission, *, request_sha256, cycle_id=None):
    """Run one explicit operation while the entry point owns scraper admission."""
    from .ats import fetch_inventory
    from .ordinary_company_event_fetch import freeze_ordinary_event_locked
    from .ordinary_company_event_publication import publish_ordinary_event_locked

    if (action not in {'admit-fetch', 'publish'} or not _digest_text(request_sha256)
            or (cycle_id is not None and not _cycle_id(cycle_id)) or (action == 'publish' and cycle_id is None)):
        raise ValueError('Ordinary Company-event action requires an exact request digest and cycle scope.')
    database, jobs, runtime = admission
    root = database.parent
    inbox_path = root / 'inventories.sqlite3'
    with cli.writer_lock(root / 'writer.lock'), ExitStack() as readers:
        assert_release_settled(root)
        local, state = _open_readers(readers, database, jobs, inbox_path)
        local_cycles, mirrors = _cycle_views(local, state)
        queued = _request_file(root)
        matching_queue = queued is not None and _json_digest(queued) == request_sha256
        if action == 'admit-fetch' and matching_queue:
            raw, request, retry_id = _queue_admission(
                local, runtime, root, request_sha256, cycle_id, local_cycles, mirrors,
            )
            assert_normal_lifecycle_not_held(root, jobs, ordinary_event_cycle_id=retry_id)
            with ExitStack() as writers:
                if (root / 'next-scan.json').read_bytes() != raw:
                    raise ValueError('Queued ordinary Company-event request changed before admission.')
                engine = _open_engine(writers, database, jobs, local.spreadsheet_id, runtime)
                selected = requested_scan(engine, engine.state, database)
                if not _cycle_id(selected) or (retry_id is not None and selected != retry_id):
                    raise ValueError('Ordinary Company-event admission returned a different cycle.')
                saved = engine.state.cycle(selected)
                if saved.get('start_request_id') != request['request_id']:
                    raise ValueError('Ordinary Company-event admission changed request identity.')
            cycle_id = selected
            local_cycles, mirrors = _cycle_views(local, state)
        elif matching_queue:
            raise ValueError('Ordinary Company-event publication requires a consumed admission. Run admit-fetch first.')

        cycle, verified = _archived_cycle(
            local, state, runtime, root, request_sha256, cycle_id, local_cycles, mirrors,
        )
        cycle_id = cycle['id']
        assert_normal_lifecycle_not_held(root, jobs, ordinary_event_cycle_id=cycle_id)
        if _unfinished_from_views(local_cycles, mirrors) - {cycle_id}:
            raise ValueError('Ordinary Company-event execution is held behind unfinished work.')

        def remote(*, write):
            return cli.get_remote_repository(
                write=write, interactive=False, schemas=COMPACT_SCHEMAS, evidence_archives=False,
            )

        if action == 'admit-fetch':
            if cycle.get('status') in _TERMINAL:
                return {'state': 'HELD_ADMISSION_ALREADY_TERMINAL', 'cycle_id': cycle_id,
                        'request_sha256': request_sha256}
            return freeze_ordinary_event_locked(
                local, state, runtime, cycle_id=cycle_id, request_sha256=request_sha256,
                fetcher=fetch_inventory, remote_reader=lambda: remote(write=False),
            )
        scope = _publish_preflight(local, state, runtime, cycle, verified, inbox_path)
        if scope == 'held':
            return {'state': 'HELD_NO_PUBLICATION_SCOPE', 'cycle_id': cycle_id,
                    'request_sha256': request_sha256}

        def remote_writer():
            if scope != 'publication':
                raise ValueError('Ordinary Company-event local-only settlement has no Sheets writer.')
            return remote(write=True)

        with ExitStack() as writers:
            engine = _open_engine(writers, database, jobs, local.spreadsheet_id, runtime, publication=True)
            return publish_ordinary_event_locked(
                engine, remote_writer, cycle_id=cycle_id, request_sha256=request_sha256,
                remote_reader=lambda: remote(write=False),
            )
