"""Exercise actual archived publication and capture with disposable stores."""

from contextlib import ExitStack, closing
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import os

import pytest

from job_search_helper import cli
from job_search_helper import ordinary_live_issuance_enrollment as enrollment
from job_search_helper import ordinary_live_issuance_slot as slots
from job_search_helper import ordinary_raw_capture as raw
from job_search_helper import ordinary_verification_pending as pending
from job_search_helper import ordinary_verification_worker as worker
from job_search_helper.company_events import source_revision
from job_search_helper.ordinary_verification_publisher import read_captured_ordinary_response
from job_search_helper.ordinary_verification_terminal import _published_marker
from job_search_helper.repository import RepositoryError
from job_search_helper.sqlite_repository import SQLiteRepository

from test_ordinary_verification_pending import CYCLE_ID, attempt
from test_s5_ordinary_publication_continuation import WORKBOOK, measured_scope
from test_s5_ordinary_verifier_handoff import COMPANY, COMPANY_ID, DEFAULT_BOARD, DEFAULT_RESPONSE, use_forterra_source
from test_s5_ordinary_worker_handoff import local_worker


PDW = {
    'Company ID': 'COMP-0178', 'Company': 'Performance Drone Works (PDW)',
    'Company Status': 'Active', 'Official Careers URL': 'https://www.pdw.ai/careers',
    'ATS / Source': 'Rippling',
}
NOW = 1_800_000_000_000


def update_control(jobs, **changes):
    with closing(SQLiteRepository(jobs, WORKBOOK)) as repository:
        repository.import_rows('Companies', [(3, {**PDW, **changes})])


@pytest.fixture
def published_dispatch(measured_scope, monkeypatch, tmp_path):
    use_forterra_source(measured_scope, monkeypatch, DEFAULT_BOARD, DEFAULT_RESPONSE)
    _, state, jobs, inbox = measured_scope
    update_control(jobs)
    monkeypatch.setattr(slots, '_now_ms', lambda: NOW)
    capture_path = tmp_path / 'private-capture'
    with ExitStack() as owned:
        descriptor = os.open(capture_path, os.O_RDONLY | os.O_DIRECTORY)
        owned.callback(os.close, descriptor)
        capture = owned.enter_context(raw.open_custody(capture_path, descriptor))
        owned.enter_context(cli.writer_lock(state.parent / 'writer.lock'))
        with pending.open_verification_stores(state, jobs, inbox, WORKBOOK, readonly=True) as stores:
            cycle, _, marker, publication = _published_marker(stores, CYCLE_ID, COMPANY_ID)
            captured = read_captured_ordinary_response(stores, CYCLE_ID, COMPANY_ID, capture)
        runtime = cycle['runtime_binding']
        approval = {
            'schema': 'ordinary-live-issuance-enrollment-v1',
            'scope': {
                'cycle_id': CYCLE_ID, 'request_id': marker['owner']['request_id'],
                'dispatch_sha256': marker['dispatch_sha256'],
                'publication_sha256': pending.digest(publication),
                'raw_capture_manifest_sha256': captured.manifest_sha256,
                'runtime_binding_sha256': pending.digest(runtime),
                'store_binding_sha256': marker['owner']['store_binding_sha256'],
                'company_projection_sha256': pending.digest(COMPANY),
                'company_source_revision': source_revision(COMPANY),
                'control_projection_sha256': pending.digest(PDW),
                'control_source_revision': source_revision(PDW),
            },
            'candidate': {'source_manifest_sha256': '1' * 64, 'config_sha256': '2' * 64,
                          'dependency_manifest_sha256': '3' * 64},
            'reviewed_tools_sha256': '4' * 64, 'collector_policy_sha256': '5' * 64,
            'worker_source_sha256': '6' * 64, 'measurement_tool_sha256': '7' * 64,
            'live_request_limit': 10, 'replay_request_limit': 8, 'capsule_bytes_limit': 131072,
            'deadline_unix_ms': NOW + 60_000,
        }
        yield (state, jobs, inbox), runtime, capture, approval, marker, captured


def snapshot(published_dispatch, *, runtime=None, approval=None, approved_sha256=None):
    files, current, capture, original, _, _ = published_dispatch
    raw_bytes = raw._encode(original if approval is None else approval)
    return enrollment.snapshot_live_issuance_binding(
        *files, WORKBOOK, runtime=current if runtime is None else runtime, capture=capture,
        approval_bytes=raw_bytes, approved_sha256=approved_sha256 or sha256(raw_bytes).hexdigest(),
    )


def test_measured_terminal_capture_derives_exact_slot_binding_without_store_writes(published_dispatch):
    files, _, _, approval, marker, captured = published_dispatch
    before = tuple(path.read_bytes() for path in files)
    binding = snapshot(published_dispatch)
    expected = {
        **{key: value for key, value in approval.items() if key not in {'schema', 'scope'}},
        **{key: value for key, value in approval['scope'].items() if key in slots._BINDING_DIGESTS},
        'verifier_input_sha256': pending.digest(
            {key: marker[key] for key in ('schema', 'owner', 'admission', 'observation')}),
        'raw_response_sha256': sha256(captured.body).hexdigest(),
        'inventory_sha256': marker['inventory_sha256'],
    }
    assert binding == expected
    assert set(binding) == slots._BINDING_DIGESTS | slots._LIMITS.keys() | {'candidate', 'deadline_unix_ms'}
    assert snapshot(published_dispatch) == expected
    assert tuple(path.read_bytes() for path in files) == before


def test_foreign_approval_and_stale_measured_runtime_hold(published_dispatch):
    files, runtime, _, _, _, _ = published_dispatch
    before = tuple(path.read_bytes() for path in files)
    with pytest.raises(RepositoryError, match='independent exact'):
        snapshot(published_dispatch, approved_sha256='0' * 64)
    with pytest.raises(RepositoryError, match='runtime'):
        snapshot(published_dispatch, runtime={**runtime, 'config_sha256': '0' * 64})
    assert tuple(path.read_bytes() for path in files) == before


def test_stale_control_label_requires_a_new_independent_projection_pin(published_dispatch):
    files, _, _, _, _, _ = published_dispatch
    update_control(files[1], Company='PDW')
    assert source_revision({**PDW, 'Company': 'PDW'}) == source_revision(PDW)
    before = tuple(path.read_bytes() for path in files)
    with pytest.raises(RepositoryError, match='Company projections'):
        snapshot(published_dispatch)
    assert tuple(path.read_bytes() for path in files) == before


def test_current_qualification_drift_holds(published_dispatch, monkeypatch):
    monkeypatch.setattr(worker, 'qualification_for_snapshot', lambda _: {'matrix_digest': '0' * 64})
    with pytest.raises(RepositoryError, match='source or its qualification changed'):
        snapshot(published_dispatch)


def test_capture_drift_at_final_readback_holds(published_dispatch, monkeypatch):
    files, _, _, _, _, _ = published_dispatch
    before = tuple(path.read_bytes() for path in files)
    read = enrollment.read_captured_ordinary_response

    def changed(*args):
        return replace(read(*args), manifest_sha256='0' * 64)

    monkeypatch.setattr(enrollment, 'read_captured_ordinary_response', changed)
    with pytest.raises(RepositoryError, match='changed during readback'):
        snapshot(published_dispatch)
    assert tuple(path.read_bytes() for path in files) == before


def test_prior_outcome_preserves_jobs_and_holds_new_enrollment(published_dispatch, tmp_path):
    files, _, _, _, marker, _ = published_dispatch
    jobs = files[1]
    owner = marker['owner']
    # An already committed historical outcome wins even if the State
    # terminal checkpoint was not yet recorded.
    with closing(SQLiteRepository(tmp_path / 'historical.sqlite3', WORKBOOK, initialize=True)) as historical:
        historical.record_scrape_outcome({
            **{key: owner[key] for key in ('cycle_id', 'request_id', 'company_id', 'source_revision')},
            'source_current': True, 'company_status': 'Active', 'inventory_status': 'partial',
            'storage_status': 'confirmed', 'failure': {'category': 'unknown'},
        })
        row = historical.db.execute('SELECT * FROM main.scrape_outcomes').fetchone()
    with closing(SQLiteRepository(jobs, WORKBOOK)) as repository, repository.transaction():
        repository.db.execute('INSERT INTO main.scrape_outcomes VALUES (?,?,?,?,?,?,?,?)', row)
    before = tuple(path.read_bytes() for path in files)
    with pytest.raises(RepositoryError, match='immutable outcome'):
        snapshot(published_dispatch)
    assert tuple(path.read_bytes() for path in files) == before


def test_expired_or_out_of_contract_budget_holds(published_dispatch):
    _, _, _, original, _, _ = published_dispatch
    expired = deepcopy(original)
    expired['deadline_unix_ms'] = NOW
    with pytest.raises(RepositoryError, match='expired'):
        snapshot(published_dispatch, approval=expired)
    too_many = {**original, 'live_request_limit': slots._LIMITS['live_request_limit'] + 1}
    with pytest.raises(RepositoryError, match='limits'):
        snapshot(published_dispatch, approval=too_many)


pytestmark = pytest.mark.parametrize('measured_scope', [True], indirect=True)
