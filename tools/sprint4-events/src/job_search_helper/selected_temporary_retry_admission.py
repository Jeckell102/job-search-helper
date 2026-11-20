"""Admit one selected temporary retry into ordinary local cycle state only."""
from contextlib import closing
from datetime import timedelta
from pathlib import Path
import re

from .company_events import source_revision
from .engine import Engine, State
from .repository import _equivalent
from .retained_operator_journal import RetainedOperatorJournal
from .runner import _canonical_runtime_binding
from .scan_request import _cycle_views, _timestamp, _unfinished_from_views, cycle_metadata, request_fingerprint
from .sheet_profile import COMPACT_PROFILE
from .sqlite_repository import SQLiteRepository
from .temporary_retry import (
    MAX_RESCRAPES, SELECTED_COOLDOWN_SECONDS, SelectedTemporaryRetrySink, is_temporary_retry_request,
)


def admit_selected_temporary_retry_locked(sink, state, runtime_binding, *, workbook_snapshot=None):
    """Use the caller's inherited scraper lease and ordinary writer lock.

    Runtime comes from pre-import admission. A fresh start additionally needs
    trusted current main-workbook cycles and the exact Company row, observed
    by the caller inside that same ownership boundary. This module opens only
    local SQLite. A returned cycle is a checkpoint, never a fetch command.
    """
    if not isinstance(sink, SelectedTemporaryRetrySink):
        raise ValueError('Selected retry admission requires the exact selected sink.')
    root = sink.root
    state_path = root / 'state.db'
    reader = sink.reader
    jobs_path = root / 'jobs.sqlite3'
    if (not isinstance(state, State) or not state.readonly or Path(state.path).resolve() != state_path
            or not isinstance(reader, SQLiteRepository) or not reader.readonly or reader.path != jobs_path
            or state_path.is_symlink() or jobs_path.is_symlink()):
        raise ValueError('Selected retry admission requires the canonical read-only SQLite views.')
    runtime = _canonical_runtime_binding(runtime_binding)
    outcome, path, key = sink._selected()
    archived = RetainedOperatorJournal(root).read_archived_event(sink.request_sha256, sink.reservation_digest)
    if archived is None or archived['binding']['runtime'] != runtime:
        raise ValueError('Selected retry admission runtime differs from the signed reservation.')

    request_id = 'temporary-retry:' + outcome['outcome_id']
    entry = sink._read(path, key)
    local_cycles, mirror_cycles = _cycle_views(reader, state)
    saved = [cycle for cycle in local_cycles if cycle.get('start_request_id') == request_id]
    mirror = [row for row in mirror_cycles if cycle_metadata(row).get('start_request_id') == request_id]
    if len(saved) > 1 or len(mirror) > 1:
        raise ValueError('Selected retry admission has conflicting saved cycle identities.')
    if entry is None or entry['state'] != 'CLAIMED':
        if saved or mirror:
            raise ValueError('Selected retry has saved work without a durable dispatch claim.')
        if entry is None:
            return {'state': 'HELD_NOT_SCHEDULED', 'request_id': request_id}

    request = _bound_request(outcome, entry['scheduled_at'])
    if entry['state'] == 'CLAIMED':
        if not saved:
            # The ledger is written before Engine's separate State checkpoint.
            # Even an empty State cannot establish that a launch was absent.
            return {'state': 'HELD_CLAIM_WITHOUT_STATE', 'request_id': request_id}
        return _saved_admission(reader, saved[0], mirror, request, runtime, recovered=True)

    blockers = sorted(_unfinished_from_views(local_cycles, mirror_cycles))
    if blockers:
        return {'state': 'HELD_UNFINISHED_CYCLE', 'request_id': request_id, 'blocking_cycle_ids': blockers}
    due = _timestamp(entry['scheduled_at'], 'Selected retry scheduled time') + timedelta(
        seconds=SELECTED_COOLDOWN_SECONDS,
    )
    if sink._now() < due:
        return {'state': 'HELD_COOLDOWN', 'request_id': request_id, 'not_before': due.isoformat()}
    selected = reader.matches('Companies', {'Company ID': request['company_ids'][0]})
    if (len(selected) != 1 or not _company_ready(selected[0][1], request['company_ids'][0])
            or source_revision(selected[0][1]) != request['source_revision']):
        return {'state': 'HELD_LOCAL_COMPANY', 'request_id': request_id}
    holds = _workbook_hold(reader, workbook_snapshot, request, selected[0][1])
    if holds is not None:
        return {**holds, 'request_id': request_id}

    dispatch = sink.claim_dispatch_locked(state)
    if dispatch['state'] != 'SUCCESSOR_CLAIMED':
        return dispatch
    if dispatch.get('request') != request or not is_temporary_retry_request(request):
        raise ValueError('Selected retry dispatch did not match its immutable request.')

    admitted = {**request, 'request_fingerprint': request_fingerprint(request, request['company_ids'])}
    with (closing(SQLiteRepository(jobs_path, reader.spreadsheet_id)) as writer,
          closing(State(str(state_path))) as writable_state):
        engine = Engine(writer, writable_state, runtime_binding=runtime, fetcher=None, error_log_path=None)
        cycle_id = engine.start_cycle(company_ids=request['company_ids'], new_scan_request=admitted)
    saved_cycle = state.cycle(cycle_id)
    mirrors = [row for row in _cycle_views(reader, state)[1]
               if cycle_metadata(row).get('start_request_id') == request_id]
    return _saved_admission(reader, saved_cycle, mirrors, request, runtime, recovered=False)


def _bound_request(outcome, scheduled_at):
    identity = outcome['identity']
    cid, revision, outcome_id = identity['company_id'], identity['source_revision'], outcome['outcome_id']
    return {'request_id': 'temporary-retry:' + outcome_id, 'mode': 'company-only', 'company_ids': [cid],
            'source_revision': revision, 'start_last': [], 'enqueued_at': scheduled_at,
            'temporary_retry': {'schema': 'temporary-scrape-retry-v1', 'outcome_id': outcome_id,
                                'company_id': cid, 'source_revision': revision,
                                'retry_index': 1, 'retry_cap': MAX_RESCRAPES}}


def _company_ready(row, company_id):
    return (isinstance(row, dict) and row.get('Company ID') == company_id
            and str(row.get('Company Status') or '').strip().casefold() == 'active'
            and row.get('Scan State') != 'Blocked / Manual Review'
            and str(row.get('Automatic Retry?') or '').strip().casefold() != 'no'
            and not any(str(row.get(key) or '').strip() for key in ('Active Cycle ID', 'Claimed By', 'Claim Token')))


def _workbook_hold(reader, snapshot, request, local_company):
    if snapshot is None:
        return {'state': 'HELD_WORKBOOK_SNAPSHOT_REQUIRED'}
    profile = reader.get_meta('sheets_profile') or 'full'
    if (not isinstance(snapshot, dict) or set(snapshot) != {'spreadsheet_id', 'profile', 'cycles', 'company'}
            or snapshot['spreadsheet_id'] != reader.spreadsheet_id or snapshot['profile'] != profile):
        raise ValueError('Selected retry workbook snapshot does not match the canonical destination.')
    rows = snapshot['cycles']
    if rows is None and profile == COMPACT_PROFILE:
        # The verified compact workbook has no Scan Cycles projection. Its
        # authority stays in the State and local mirror already checked above.
        rows = []
    if not isinstance(rows, list):
        raise ValueError('Selected retry workbook cycle authority is unavailable.')
    if any(not isinstance(row, dict) or not isinstance(row.get('Cycle ID'), str)
           or not row['Cycle ID'].strip() or not isinstance(row.get('Cycle Status'), str) for row in rows):
        raise ValueError('Selected retry workbook snapshot contains an invalid cycle.')
    if len({row['Cycle ID'] for row in rows}) != len(rows):
        raise ValueError('Selected retry workbook snapshot contains ambiguous cycles.')
    blockers = sorted(_unfinished_from_views([], rows))
    if blockers:
        return {'state': 'HELD_WORKBOOK_UNFINISHED_CYCLE', 'blocking_cycle_ids': blockers}
    if any(cycle_metadata(row).get('start_request_id') == request['request_id'] for row in rows):
        return {'state': 'HELD_WORKBOOK_SUCCESSOR_EXISTS'}
    company = snapshot['company']
    shared = ['Company ID', 'Company Status', 'Official Careers URL']
    if isinstance(company, dict) and 'ATS / Source' in company:
        shared.append('ATS / Source')
    if (not _company_ready(company, request['company_ids'][0])
            or any(key not in company or not _equivalent(key, company[key], local_company.get(key, ''))
                   for key in shared)):
        return {'state': 'HELD_WORKBOOK_COMPANY'}
    return None


def _saved_admission(reader, cycle, mirrors, request, runtime, *, recovered):
    cid = request['company_ids'][0]
    request_id = request['request_id']
    fingerprint = request_fingerprint(request, [cid])
    identity = {'start_request_id': request_id, 'request_fingerprint': fingerprint,
                'temporary_retry': request['temporary_retry'], 'runtime_binding': runtime,
                'all': False, 'supersedes': [], 'start_last': []}
    if (not isinstance(cycle, dict) or not isinstance(cycle.get('id'), str)
            or not re.fullmatch(r'CYC-[0-9A-F]{12}', cycle['id'])
            or any(cycle.get(key) != value for key, value in identity.items()) or cycle['all'] is not False
            or not isinstance(cycle.get('companies'), dict) or set(cycle['companies']) != {cid}
            or any(key in cycle for key in ('operator_request', 'repair_retry', 'company_event', 'recovery_pause'))):
        raise ValueError('Selected retry saved State does not match its exact pinned request.')
    item = cycle['companies'][cid]
    if item.get('outcome_source_revision') != request['source_revision']:
        raise ValueError('Selected retry saved source no longer matches its admission.')
    evidence = {'request_id': request_id, 'cycle_id': cycle['id'], 'company_id': cid}
    if item.get('stage') != 'queued' or cycle.get('status') != 'In Progress':
        return {'state': 'HELD_SUCCESSOR_PROGRESS', **evidence}
    company = reader.matches('Companies', {'Company ID': cid})
    if not mirrors or len(company) == 1 and not company[0][1].get('Active Cycle ID'):
        return {'state': 'HELD_ADMISSION_PARTIAL', **evidence}
    if len(mirrors) != 1 or len(company) != 1 or company[0][1].get('Active Cycle ID') != cycle['id']:
        raise ValueError('Selected retry saved membership conflicts with the pinned cycle.')
    mirror = mirrors[0]
    notes = cycle_metadata(mirror)
    if (mirror.get('Cycle ID') != cycle['id'] or mirror.get('Cycle Status') != cycle['status']
            or notes.get('company_ids') != [cid] or notes.get('all') is not False
            or any(notes.get(key) != value for key, value in identity.items())):
        raise ValueError('Selected retry saved local mirror conflicts with the pinned cycle.')
    return {'state': 'ADMITTED_LOCAL_CYCLE', **evidence, 'request_fingerprint': fingerprint,
            'recovered': recovered}
