"""The release bridge reuses one exactly admitted normal retry."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path

import pytest

from job_search_helper.cli import writer_lock
from job_search_helper.company_events import current_company_source_revision
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import JOURNAL_SCHEMA
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RELEASE_BINDING_SCHEMA, RepairRetryBridge, retry_attempt_id,
)
from job_search_helper.scan_request import requested_scan
from job_search_helper.sqlite_repository import SQLiteRepository


@pytest.fixture
def retry(tmp_path, monkeypatch):
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    state_path = tmp_path / 'state.db'
    company_id = 'COMP-0490'
    release = {
        'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-fixture',
        'source_manifest_sha256': 'a' * 64, 'dependency_manifest_sha256': 'b' * 64,
        'config_sha256': 'c' * 64,
    }
    (tmp_path / 'integration-release-journal.json').write_text(json.dumps({
        'schema': JOURNAL_SCHEMA, 'state': 'COMPLETE', 'release_id': release['release_id'], 'release': release,
    }))
    with (closing(State(state_path)) as state,
          closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet', initialize=True)) as jobs,
          closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'sheet')) as inbox):
        jobs.set_meta('ready', 'yes')
        jobs.import_rows('Companies', [(2, {
            'Company ID': company_id, 'Company': 'Fixture Company', 'Company Status': 'Active',
            'ATS / Source': 'AcquireTM', 'Official Careers URL': 'https://example.test/fixture',
        })])
        source = lambda cid: current_company_source_revision(jobs, cid)
        binding = {
            'schema': REPAIR_RETRY_SCHEMA, 'failed_request_id': 'fixture-original-request',
            'company_id': company_id, 'source_revision': source(company_id),
            'release': release, 'activated_at': '2026-11-19T12:00:00Z',
        }
        binding['attempt_id'] = retry_attempt_id(binding)
        engine = Engine(jobs, state, inbox=inbox, runtime_binding={
            'state': 'COMPLETE', **{key: value for key, value in release.items() if key != 'schema'},
        })
        bridge = RepairRetryBridge(state_path, current_source_revision=source)
        yield bridge, binding, engine, state


def admit(bridge, engine, state):
    with writer_lock(bridge.database.parent / 'scraper.lock'):
        return requested_scan(engine, state, bridge.database)


def test_real_consumed_retry_replays_without_recreating_request(retry):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    cycle_id = admit(bridge, engine, state)
    observed = state.cycle(cycle_id)
    assert not bridge.request_path.exists()
    assert bridge.deliver(binding) == {
        'attempt_id': binding['attempt_id'], 'state': 'REQUEST_ALREADY_ADMITTED',
    }
    assert not bridge.request_path.exists()
    assert state.cycles() == [observed]

    # Neither the audit receipt nor the shared last-consumed filename is the authority.
    (bridge.receipt_directory / (binding['attempt_id'] + '.json')).unlink()
    bridge.request_path.with_name('last-scan-request.json').write_text('{"request_id":"another-owner"}\n')
    assert bridge.deliver(binding)['state'] == 'REQUEST_ALREADY_ADMITTED'
    assert not bridge.request_path.exists() and state.cycles() == [observed]


def test_exact_pending_request_survives_cut_after_state_save(retry, monkeypatch):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    queued = bridge.request_path.read_bytes()
    replace = Path.replace

    def interrupted(path, destination):
        if path == bridge.request_path:
            raise OSError('cut before consuming the pending request')
        return replace(path, destination)

    with monkeypatch.context() as cut:
        cut.setattr(Path, 'replace', interrupted)
        with pytest.raises(OSError, match='cut before consuming'):
            admit(bridge, engine, state)
    [saved] = state.cycles()
    assert bridge.deliver(binding)['state'] == 'REQUEST_ALREADY_DURABLE'
    assert bridge.request_path.read_bytes() == queued
    assert admit(bridge, engine, state) == saved['id']
    assert not bridge.request_path.exists() and len(state.cycles()) == 1


@pytest.mark.parametrize('defect', [
    'fingerprint', 'scope', 'no_measurement', 'attempt_only', 'duplicate',
    'missing_runtime', 'foreign_runtime', 'retained_owner', 'partial_measurement',
])
def test_incomplete_or_ambiguous_saved_admission_holds_empty_slot(retry, defect):
    bridge, binding, engine, state = retry
    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    cycle_id = admit(bridge, engine, state)
    saved = state.cycle(cycle_id)
    if defect == 'fingerprint':
        saved['request_fingerprint'] = 'f' * 64
    elif defect == 'scope':
        saved['companies']['COMP-0001'] = deepcopy(saved['companies'][binding['company_id']])
    elif defect == 'no_measurement':
        saved.pop('intake_start_measurement')
    elif defect == 'attempt_only':
        saved.pop('start_request_id')
    elif defect == 'missing_runtime':
        saved.pop('runtime_binding')
    elif defect == 'foreign_runtime':
        saved['runtime_binding']['source_manifest_sha256'] = 'f' * 64
    elif defect == 'retained_owner':
        saved['retained_work_exception'] = {'state': 'another-owner'}
    elif defect == 'partial_measurement':
        measurement = saved['intake_start_measurement']
        saved['intake_start_measurement'] = {key: measurement[key] for key in ('condition', 'started_at')}
    else:
        saved['id'] = 'CYC-111111111111'
    state.save_cycle(saved)
    before = state.cycles()
    with pytest.raises(RuntimeError, match='admission evidence'):
        bridge.deliver(binding)
    assert not bridge.request_path.exists() and state.cycles() == before


def test_busy_measurement_from_normal_admission_replays(retry):
    bridge, binding, engine, state = retry
    earlier = engine.start_cycle(company_ids=[binding['company_id']])
    previous = state.cycle(earlier)
    previous['companies'][binding['company_id']]['stage'] = 'complete'
    engine._sync_cycle(previous)
    assert state.cycle(earlier)['status'] == 'Complete'

    assert bridge.deliver(binding)['state'] == 'REQUEST_WRITTEN'
    cycle_id = admit(bridge, engine, state)
    measurement = state.cycle(cycle_id)['intake_start_measurement']
    assert (measurement['condition'], measurement['safe_boundary_cycle_id']) == ('busy', earlier)
    before = state.cycles()
    assert bridge.deliver(binding)['state'] == 'REQUEST_ALREADY_ADMITTED'
    assert not bridge.request_path.exists() and state.cycles() == before
