"""Exercise a qualified fixture through the exact published ordinary route."""

from contextlib import ExitStack, contextmanager
import json
import os

import pytest

from job_search_helper import cli, ordinary_verification_finisher as finish
from job_search_helper import ordinary_verification_pending as pending
from job_search_helper import runtime_mapping_facts as facts
from job_search_helper import source_configuration_snapshot as configuration
from job_search_helper.ordinary_live_mapping_verdict import open_live_mapping_verdict_owner
from job_search_helper.ordinary_raw_capture import open_custody
from job_search_helper.ordinary_verification_publisher import read_captured_ordinary_response
from job_search_helper.ordinary_verification_terminal import TERMINAL, _published_marker
from job_search_helper.repository import RepositoryError

from test_ordinary_verification_pending import CYCLE_ID, attempt
from test_s5_ordinary_publication_continuation import WORKBOOK, measured_scope
from test_s5_ordinary_verifier_handoff import COMPANY, COMPANY_ID, DEFAULT_BOARD, DEFAULT_RESPONSE, digest, pack, use_forterra_source
from test_s5_ordinary_worker_handoff import local_worker


_TOOLS = '6' * 64


@pytest.fixture
def published(measured_scope, monkeypatch, tmp_path):
    use_forterra_source(measured_scope, monkeypatch, DEFAULT_BOARD, DEFAULT_RESPONSE)
    _, state, jobs, inbox = measured_scope
    with ExitStack() as stack:
        capture_path = tmp_path / 'private-capture'
        descriptor = os.open(capture_path, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, descriptor)
        capture = stack.enter_context(open_custody(capture_path, descriptor))
        stores = stack.enter_context(pending.open_verification_stores(state, jobs, inbox, WORKBOOK, writable_jobs=True))
        stack.enter_context(cli.writer_lock(state.parent / 'writer.lock'))
        cycle, _, marker, proof = _published_marker(stores, CYCLE_ID, COMPANY_ID)
        source = cycle['companies'][COMPANY_ID]['installed_source_configuration']
        qualification = {key: source[key] for key in (
            'company_id', 'source_revision', 'capability_id', 'capability_digest', 'mapping_digest',
            'configuration_digest',
        )}
        qualification.update(category='same_provider_source_mapping', evidence_code='rippling_verified_mapping_divergence')
        reviewed = {'qualification': qualification, 'matrix_digest': marker['admission']['matrix_digest']}
        for module in (configuration, facts):
            monkeypatch.setattr(module, '_resolve_authoritative_installed_source_configuration',
                                lambda repo, company_id: source)
            monkeypatch.setattr(module, 'qualification_for_snapshot', lambda candidate: reviewed)
        captured = read_captured_ordinary_response(stores, CYCLE_ID, COMPANY_ID, capture)
        selected = {key: marker[key] for key in ('schema', 'owner', 'admission', 'observation')}
        verdict = {
            'schema': 'ordinary-live-mapping-verdict-v1', 'mode': 'live_normal_dispatch',
            'result': 'VERIFIED_MISMATCH', 'application_authority': True,
            'dispatch_sha256': marker['dispatch_sha256'], 'publication_sha256': pending.digest(proof),
            'verifier_input_sha256': pending.digest(selected),
            'raw_capture_manifest_sha256': captured.manifest_sha256,
            'reviewed_tools_sha256': _TOOLS, 'live_capture_sha256': '7' * 64,
            'candidate_validation_sha256': '8' * 64,
            'authority_extraction_digest': '9' * 64, 'candidate_inventory_digest': 'a' * 64,
            'regression_inventory_digest': 'b' * 64,
        }
        yield stores, cycle['runtime_binding'], capture, verdict


@contextmanager
def approved(tmp_path, verdict, *, tools=_TOOLS):
    folder = tmp_path / 'approved-live-fixture'
    folder.mkdir(mode=0o700)
    receipt = folder / (verdict['dispatch_sha256'] + '.json')
    raw = pack(verdict)
    receipt.write_bytes(raw)
    receipt.chmod(0o600)
    info = folder.stat()
    descriptor = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with open_live_mapping_verdict_owner(
            folder, descriptor, expected_owner_identity=(info.st_dev, info.st_ino),
            approved_verdict_sha256=digest(raw), reviewed_tools_sha256=tools,
        ) as owner:
            yield owner, receipt
    finally:
        os.close(descriptor)


def close(published, owner=None):
    stores, runtime, capture, _ = published
    return finish.finish_published_ordinary(stores, runtime, CYCLE_ID, COMPANY_ID,
                                            qualified_owner=owner, capture=capture)


def fact_row(stores):
    return facts._row(stores.state.connection, CYCLE_ID, COMPANY_ID)


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_live_shape_fixture_stores_one_exact_fact_seal_and_qualified_outcome(published, tmp_path):
    stores, _, _, verdict = published
    assert close(published) == {'state': 'VERIFICATION_PENDING'}
    with approved(tmp_path, verdict) as (owner, receipt):
        first = close(published, owner)
        row = fact_row(stores)
        written = stores.state.cycle(CYCLE_ID)['companies'][COMPANY_ID]
        assert first['state'] == 'OUTCOME_STORED'
        assert json.loads(row[2])['binding']['ordinary_verification'] == {
            'dispatch_sha256': verdict['dispatch_sha256'], 'publication_sha256': verdict['publication_sha256'],
            'qualified_verdict_sha256': digest(receipt.read_bytes()),
        }
        assert written['source_configuration_mapping_fact']['candidate_inventory_digest'] == 'a' * 64
        assert written['source_configuration_mapping_fact'] == json.loads(row[2])['fact']
        assert written['source_configuration_defect']['category'] == 'same_provider_source_mapping'
        assert written['source_configuration_qualification_evidence']['matrix_digest']
        replay = close(published, owner)
        assert replay['state'] == 'ALREADY_STORED' and replay['terminal'] == first['terminal']
    assert fact_row(stores) == row
    result, = stores.jobs.scrape_outcomes()
    assert (result['outcome'], result['action'], result['repair_category']) == (
        'QUALIFIED_INTEGRATION_REPAIR', 'upsert_qualified_repair', 'same_provider_source_mapping',
    )
    assert result['outcome_id'] == first['terminal']['outcome_id']


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
@pytest.mark.parametrize('field,value', [
    ('mode', 'offline_saved_captures'), ('application_authority', False),
    ('result', 'CHANGED_INPUT'), ('verifier_input_sha256', '0' * 64),
    ('publication_sha256', '0' * 64), ('raw_capture_manifest_sha256', '0' * 64),
    ('reviewed_tools_sha256', '0' * 64),
])
def test_mismatched_or_offline_evidence_never_writes_fact_seal_or_outcome(published, tmp_path, field, value):
    stores, _, _, verdict = published
    before = stores.state.cycle(CYCLE_ID)
    with approved(tmp_path, {**verdict, field: value}) as (owner, _):
        with pytest.raises(RepositoryError, match='not an exact approved live mapping verdict'):
            close(published, owner)
    assert fact_row(stores) is None and stores.state.cycle(CYCLE_ID) == before
    assert stores.jobs.scrape_outcomes() == []


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_legacy_runtime_writer_does_not_accept_an_enrolled_mapping(published):
    stores, runtime, _, verdict = published
    with pytest.raises(ValueError, match='requires its exact live verification'):
        facts.persist_runtime_mapping_fact(stores.state, stores.jobs, runtime,
                                           cycle_id=CYCLE_ID, company_id=COMPANY_ID, fact=verdict)
    assert fact_row(stores) is None and stores.jobs.scrape_outcomes() == []


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_state_error_leaves_fact_and_seal_absent_together(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published
    before = stores.state.cycle(CYCLE_ID)

    def fail(*args, **kwargs):
        assert stores.state.connection.in_transaction
        raise RuntimeError('cut before State commit')

    with approved(tmp_path, verdict) as (owner, _):
        with monkeypatch.context() as cut:
            cut.setattr(facts, '_read_owned_runtime_fact', fail)
            with pytest.raises(RuntimeError, match='before State commit'):
                close(published, owner)
        assert fact_row(stores) is None and stores.state.cycle(CYCLE_ID) == before
        assert stores.jobs.scrape_outcomes() == []
        assert close(published, owner)['state'] == 'OUTCOME_STORED'


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_restart_after_state_commit_reuses_the_original_fact_and_seal(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published

    def fail(*args, **kwargs):
        raise RuntimeError('cut before Jobs commit')

    with approved(tmp_path, verdict) as (owner, _):
        with monkeypatch.context() as cut:
            cut.setattr(stores.jobs, 'transaction', fail)
            with pytest.raises(RuntimeError, match='before Jobs commit'):
                close(published, owner)
        original = fact_row(stores)
        assert original is not None and stores.jobs.scrape_outcomes() == []
        assert 'source_configuration_mapping_fact' in stores.state.cycle(CYCLE_ID)['companies'][COMPANY_ID]
        assert close(published) == {'state': 'VERIFICATION_PENDING'}
        assert close(published, owner)['state'] == 'OUTCOME_STORED'
    assert fact_row(stores) == original and len(stores.jobs.scrape_outcomes()) == 1


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_withdrawn_verdict_at_jobs_write_leaves_only_the_exact_state_seal(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published
    writer = stores.jobs._record_scrape_outcome_in_transaction
    with approved(tmp_path, verdict) as (owner, receipt):
        withdrawn = receipt.with_suffix('.withdrawn')

        def withdraw(*args, **kwargs):
            receipt.rename(withdrawn)
            return writer(*args, **kwargs)

        with monkeypatch.context() as cut:
            cut.setattr(stores.jobs, '_record_scrape_outcome_in_transaction', withdraw)
            with pytest.raises(RepositoryError, match='live verdict is unavailable'):
                close(published, owner)
        row = fact_row(stores)
        assert row is not None and stores.jobs.scrape_outcomes() == []
        withdrawn.rename(receipt)
        assert close(published, owner)['state'] == 'OUTCOME_STORED'
    assert fact_row(stores) == row and len(stores.jobs.scrape_outcomes()) == 1


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_matrix_changed_at_jobs_write_prevents_qualified_outcome(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published
    writer = stores.jobs._record_scrape_outcome_in_transaction
    reviewed = configuration.qualification_for_snapshot(None)

    with approved(tmp_path, verdict) as (owner, _):
        with monkeypatch.context() as cut:
            def write(*args, **kwargs):
                cut.setattr(configuration, 'qualification_for_snapshot',
                            lambda snapshot: {**reviewed, 'matrix_digest': '0' * 64})
                return writer(*args, **kwargs)
            cut.setattr(stores.jobs, '_record_scrape_outcome_in_transaction', write)
            with pytest.raises(RepositoryError, match='require their exact verification finisher'):
                close(published, owner)
        row = fact_row(stores)
        assert row is not None and stores.jobs.scrape_outcomes() == []
        assert close(published, owner)['state'] == 'OUTCOME_STORED'
    assert fact_row(stores) == row


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_restart_after_jobs_commit_needs_only_exact_terminal_reconciliation(published, tmp_path, monkeypatch):
    stores, _, _, verdict = published

    def fail(*args, **kwargs):
        raise RuntimeError('cut before terminal checkpoint')

    with approved(tmp_path, verdict) as (owner, receipt):
        with monkeypatch.context() as cut:
            cut.setattr(finish, 'checkpoint_existing_outcome', fail)
            with pytest.raises(RuntimeError, match='before terminal checkpoint'):
                close(published, owner)
        existing, = stores.jobs.scrape_outcomes()
        assert TERMINAL not in stores.state.cycle(CYCLE_ID)['companies'][COMPANY_ID]
        receipt.rename(receipt.with_suffix('.expired'))
        recovered = close(published, owner)
        assert recovered['state'] == 'ALREADY_STORED'
        assert recovered['terminal']['outcome_id'] == existing['outcome_id']
        assert stores.jobs.scrape_outcomes() == [existing]


@pytest.mark.parametrize('measured_scope', [True], indirect=True)
def test_current_pause_stops_before_the_qualified_state_transaction(published, tmp_path):
    stores, _, _, verdict = published
    stores.jobs.import_rows('Companies', [(2, {**COMPANY, 'Company Status': 'Paused'})])
    with approved(tmp_path, verdict) as (owner, receipt):
        receipt.rename(receipt.with_suffix('.withdrawn'))
        assert close(published, owner)['state'] == 'OUTCOME_STORED'
    result, = stores.jobs.scrape_outcomes()
    assert result['outcome'] == 'STALE_OR_PAUSED'
    assert fact_row(stores) is None
