"""Retain exact operator origin after the qualified retry adopts the Company."""

from contextlib import closing
import json
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from amphenol_retry_completion import (
    RetryReleaseApproval, _historical_operator_origin_matches, deliver_qualified_operator_retry,
)
from host_server import OperatorAmphenolRecipeEnrollment
from job_search_helper.acquiretm import SOURCE
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.inbox import InventoryInbox
from job_search_helper.operator_amphenol_settlement import settle_operator_amphenol
from job_search_helper.operator_company_request import _digest, queue_operator_company_request
from job_search_helper.ordinary_event_settlement import ACQUIRETM_PAGINATION_CODE
from job_search_helper.scan_request import requested_scan
from job_search_helper.sqlite_repository import SQLiteRepository


@pytest.fixture
def completed_origin(tmp_path, monkeypatch):
    jobs = tmp_path / 'jobs.sqlite3'
    database = tmp_path / 'state.db'
    company = {'Company ID': 'COMP-0490', 'Company': 'Amphenol Aerospace',
               'Company Status': 'Active', 'ATS / Source': 'AcquireTM',
               'Official Careers URL': SOURCE}
    request_id = 'operator-amphenol-fixture'
    runtime = {'state': 'NO_RELEASE', 'source_manifest_sha256': 'a' * 64}
    with (closing(SQLiteRepository(jobs, 'fixture-sheet', initialize=True)) as repository,
          closing(State(database)) as state,
          closing(InventoryInbox(tmp_path / 'inventories.sqlite3', 'fixture-sheet')) as inbox):
        repository.set_meta('ready', 'yes')
        repository.import_rows('Companies', [(2, company)])
        queue_operator_company_request(repository, tmp_path, 'COMP-0490', request_id)
        request = json.loads((tmp_path / 'next-scan.json').read_text())
        request_digest = _digest(request)
        engine = Engine(repository, state, inbox=inbox, runtime_binding=runtime)
        with writer_lock(tmp_path / 'scraper.lock'), writer_lock(tmp_path / 'writer.lock'):
            original_cycle = requested_scan(engine, state, database)
            monkeypatch.setattr(
                'job_search_helper.operator_amphenol_settlement.load_operator_amphenol_partial',
                lambda *_: {
                    'sha256': 'b' * 64, 'inventory_sha256': 'c' * 64,
                    'inventory': {'outcome_failure': {'evidence_code': ACQUIRETM_PAGINATION_CODE}},
                },
            )
            result = settle_operator_amphenol(engine, request_sha256=request_digest)
        assert result['cycle_id'] == original_cycle
        assert result['state'] == 'FETCH_REPAIR_QUALIFIED'
        repository.commit([{
            'tab': 'Companies', 'identity': {'Company ID': 'COMP-0490'},
            'values': {'Active Cycle ID': 'CYC-ABCDEF123456', 'Scan State': 'Complete'},
        }])
        (tmp_path / 'last-scan-request.json').write_text(json.dumps({'request_id': 'company-retry:fixture'}))
    with (closing(SQLiteRepository(jobs, 'fixture-sheet', readonly=True)) as repository,
          closing(State(database, readonly=True)) as state):
        yield repository, state, result['outcome'], request_digest


def test_uses_retained_evidence_after_retry_adopts_company(completed_origin):
    assert _historical_operator_origin_matches(*completed_origin)


def test_holds_when_permanent_receipt_disagrees(completed_origin):
    repository, _, _, _ = completed_origin
    receipt = next((Path(repository.path).parent / 'operator-company-requests' / 'receipts').glob('*.json'))
    record = json.loads(receipt.read_text())
    receipt.write_text(json.dumps({**record, 'source_revision': 'd' * 64}))
    assert not _historical_operator_origin_matches(*completed_origin)


def test_explicit_completion_cannot_omit_operator_request_pin(tmp_path, monkeypatch):
    """A directly constructed enrollment must not fall through to event handling."""
    enrollment = OperatorAmphenolRecipeEnrollment(
        request_id='operator-amphenol-fixture', source_revision='a' * 64, request_sha256=None,
    )
    coordinator = SimpleNamespace(stop=Event(), workspace_lock=Lock(), control_lock=Lock())
    approval = RetryReleaseApproval('REL-' + '1' * 24, str(tmp_path), 1, 1, 'b' * 64)

    def unexpected_scope(_):
        pytest.fail('A missing operator pin must hold before opening the scope')

    monkeypatch.setattr(OperatorAmphenolRecipeEnrollment, 'owner_scope', unexpected_scope)
    assert deliver_qualified_operator_retry(
        enrollment, coordinator, original_outcome='OUT-' + '1' * 24, approval=approval,
    ) == {'state': 'HELD_EXACT_RETRY_TERMINAL'}
