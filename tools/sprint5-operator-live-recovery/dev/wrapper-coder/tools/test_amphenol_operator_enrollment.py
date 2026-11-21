import importlib
import json
from pathlib import Path
from contextlib import closing, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from job_search_helper.acquiretm import SOURCE
from job_search_helper.ats import ACQUIRETM_PAGINATION_CODE
from job_search_helper.engine import State
from job_search_helper.operator_amphenol_settlement import read_operator_amphenol_settlement
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.temporary_retry import _selected_sha
from coordinator_store import Store


def _host():
    with patch.object(Path, 'read_text', return_value='fixture-token'):
        return importlib.import_module('host_server')


def _operator_case(choice):
    identity = {'cycle_id': 'CYC-ABCDEF123456', 'request_id': 'operator-amphenol-fixture',
                'company_id': 'COMP-0490', 'source_revision': 'a' * 64,
                'provider': 'AcquireTM', 'adapter_version': 'normal-scraper-v1'}
    record = {'outcome_id': 'OUT-' + 'a' * 24, 'identity': identity,
              'outcome': 'QUALIFIED_INTEGRATION_REPAIR', 'action': 'upsert_qualified_repair',
              'repair_category': 'pagination_regression'}
    witness = {'page': 2, 'advertised_total': 2, 'first_page_count': 1, 'refreshed_page_count': 1,
               'premature_elapsed_ms': 1, 'refreshed_elapsed_ms': 2,
               'first_page_ids_sha256': 'b' * 64, 'premature_page_ids_sha256': 'b' * 64,
               'refreshed_page_ids_sha256': 'c' * 64}
    inventory = {'outcome_failure': {'evidence': witness}}
    frozen = {'inventory': inventory, 'inventory_sha256': 'd' * 64}
    frozen['sha256'] = _selected_sha({key: value for key, value in frozen.items() if key != 'sha256'})
    binding = {'cycle_id': identity['cycle_id'], 'request_id': identity['request_id'],
               'company_id': 'COMP-0490', 'source_revision': 'a' * 64,
               'request_sha256': 'e' * 64, 'request_fingerprint': 'f' * 64,
               'observation_sha256': frozen['sha256'], 'provider_inventory_sha256': 'd' * 64}
    settlement = {'schema': 'operator-amphenol-partial-settlement-v1', 'binding': binding,
                  'outcome': record, 'terminal_state_sha256': '1' * 64,
                  'terminal_mirror_sha256': '2' * 64}
    receipt = {'sink_receipt_id': 'ODR-' + '3' * 24, 'sink_status': 'HELD_FOR_REPAIR_TRIAGE'}
    held = {'status': 'HELD_FOR_REPAIR_TRIAGE', 'task_id': None, 'company_id': 'COMP-0490',
            'source_revision': 'a' * 64, 'outcome_id': record['outcome_id'], 'outcome': record,
            'evidence_outcome_ids': [record['outcome_id']]}
    selection = {'cycle_id': identity['cycle_id'], 'request_id': identity['request_id'],
                 'source_revision': 'a' * 64, 'outcome_id': record['outcome_id'],
                 'request_sha256': 'e' * 64}
    return dict(selection=selection, company={'company_id': 'COMP-0490', 'source_revision': 'a' * 64,
                                               'company': 'Amphenol Aerospace',
                                               'official_careers_url': SOURCE, 'ats_source': 'acquiretm'},
                record=record, receipt=receipt, held=held, settlement=settlement, frozen=frozen, witness=witness)


def test_operator_enrollment_is_exact_and_default_off():
    host = _host()
    raw = json.dumps({'request_id': 'operator-amphenol-fixture', 'request_sha256': 'a' * 64,
                      'source_revision': 'b' * 64})
    enrolled = host.recipe_enrollment_from_process_environment(
        {'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT': raw})
    assert isinstance(enrolled, host.OperatorAmphenolRecipeEnrollment)
    assert enrolled.retry_approval is None
    assert enrolled.activate_approved_release is False
    assert enrolled.matches({'company_id': 'COMP-0490', 'request_id': 'operator-amphenol-fixture',
                             'source_revision': 'b' * 64})
    assert not enrolled.matches({'company_id': 'COMP-0490', 'request_id': 'operator-amphenol-fixture',
                                 'source_revision': 'c' * 64})


def test_operator_enrollment_rejects_event_or_release_mixing():
    host = _host()
    operator = json.dumps({'request_id': 'operator-amphenol-fixture', 'request_sha256': 'a' * 64,
                           'source_revision': 'b' * 64})
    event = json.dumps({'company_event_id': 'CEV-' + '1' * 32,
                        'request_id': 'company-event:CEV-' + '1' * 32, 'source_revision': 'b' * 64})
    import pytest
    with pytest.raises(ValueError, match='mutually exclusive'):
        host.recipe_enrollment_from_process_environment({
            'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT': operator,
            'WRAPPER_AMPHENOL_RECIPE_ENROLLMENT': event})
    with pytest.raises(ValueError, match='cannot authorize retry or release'):
        host.recipe_enrollment_from_process_environment({
            'WRAPPER_AMPHENOL_OPERATOR_RECIPE_ENROLLMENT': operator,
            'WRAPPER_AMPHENOL_RETRY_APPROVAL': '{}'})


def test_operator_uses_measured_installed_source_not_stale_task_workspace(tmp_path, monkeypatch):
    """The operator route holds before choice/pilot if installed source drifts."""
    host = _host()
    installed = tmp_path / 'installed'
    target = Path('src/job_search_helper/acquiretm.py')
    source = host.JOB_SEARCH_ROOT / target
    (installed / target).parent.mkdir(parents=True)
    (installed / target).write_bytes(source.read_bytes())
    stale_task = tmp_path / 'queue-base-88893583'
    (stale_task / target).parent.mkdir(parents=True)
    (stale_task / target).write_text('# stale task checkout\n')
    monkeypatch.setattr(host, 'JOB_SEARCH_ROOT', installed)
    enrolled = host.OperatorAmphenolRecipeEnrollment(
        request_id='operator-amphenol-fixture', request_sha256='e' * 64,
        source_revision='a' * 64)
    prepared = {'binding': {'company_id': 'COMP-0490',
                            'request_id': 'operator-amphenol-fixture',
                            'source_revision': 'a' * 64,
                            'outcome_id': 'OUT-' + 'a' * 24}}
    choice = importlib.import_module('amphenol_recipe_choice_input')
    reader_calls = []
    monkeypatch.setattr(choice, 'read_operator_owned_choice_input',
                        lambda *args, **kwargs: reader_calls.append((args, kwargs)) or prepared)
    coordinator = SimpleNamespace(store=object())
    assert enrolled._read(stale_task, coordinator, 'OUT-' + 'a' * 24) == prepared
    assert len(reader_calls) == 1
    # The stale task source remains unused: the compiler receives the installed root.
    captured = {}
    candidate = importlib.import_module('amphenol_recipe_candidate')
    monkeypatch.setattr(candidate, 'save_candidate',
                        lambda task_root, workspace, selected, receipt:
                        captured.update(task_root=task_root, workspace=workspace,
                                        selected=selected, receipt=receipt) or 'candidate')
    @contextmanager
    def owner_scope():
        yield stale_task, None, None
    monkeypatch.setattr(host.OperatorAmphenolRecipeEnrollment, 'owner_scope',
                        lambda self: owner_scope())
    receipt = {'request_id': 'model-request', 'accepted_recipe_choice': {}}
    state = {'id': 'TASK-1'}
    coordinator = SimpleNamespace(
        store=SimpleNamespace(base=tmp_path / 'receiver',
                              inference_receipt=lambda request_id: receipt,
                              pilot_task=lambda: 'TASK-1'),
        paused=lambda task_id: False,
        check_deadline=lambda task_id: None)
    assert enrolled.build_candidate(coordinator, state, prepared, receipt) == 'candidate'
    assert captured['workspace'] == installed

    (installed / target).write_text('# wrong installed source\n')
    assert enrolled._read(stale_task, coordinator, 'OUT-' + 'a' * 24) is None
    assert len(reader_calls) == 2  # the bad source held before the choice/model route


def test_operator_choice_accepts_only_exact_operator_continuity(monkeypatch):
    import amphenol_recipe_choice_input as choice
    case = _operator_case(choice)
    monkeypatch.setattr(choice, '_valid_receipt', lambda receipt, consumer, outcome_id, digest: receipt)
    monkeypatch.setattr(choice, 'ordinary_no_publication_result',
                        lambda frozen: ('partial', 'Partial', ACQUIRETM_PAGINATION_CODE))
    prepared = choice.prepare_operator_choice_input(enabled=True, **{
        key: value for key, value in case.items() if key != 'witness'})
    assert prepared is not None
    assert prepared['binding']['request_id'] == 'operator-amphenol-fixture'
    assert 'company_event_id' not in prepared['binding']
    case['settlement']['binding']['request_sha256'] = '9' * 64
    assert choice.prepare_operator_choice_input(enabled=True, **{
        key: value for key, value in case.items() if key != 'witness'}) is None


def test_operator_choice_rejects_foreign_event_identity(monkeypatch):
    import amphenol_recipe_choice_input as choice
    case = _operator_case(choice)
    case['record']['identity']['company_event_id'] = 'CEV-' + '2' * 32
    monkeypatch.setattr(choice, '_valid_receipt', lambda receipt, consumer, outcome_id, digest: receipt)
    monkeypatch.setattr(choice, 'ordinary_no_publication_result',
                        lambda frozen: ('partial', 'Partial', ACQUIRETM_PAGINATION_CODE))
    assert choice.prepare_operator_choice_input(enabled=True, **{
        key: value for key, value in case.items() if key != 'witness'}) is None


def test_operator_source_rejects_real_terminal_state_drift(tmp_path, monkeypatch, capsys):
    from test_operator_amphenol_fetch import test_selected_observation_preserves_request_before_admission

    test_selected_observation_preserves_request_before_admission(tmp_path, monkeypatch, capsys, True)
    jobs = tmp_path / 'jobs.sqlite3'
    with closing(SQLiteRepository(jobs, 'sheet')) as repository:
        [record] = repository.scrape_outcomes(company_id='COMP-0490')
        identity = record['identity']
        settlement = read_operator_amphenol_settlement(
            repository, identity['cycle_id'], identity['request_id'])
        store = Store(tmp_path / 'receiver',
                      company_revision_resolver=lambda _: identity['source_revision'])
        sink = SimpleNamespace(
            ingest_immutable=lambda value: store.ingest_scrape_outcome_delivery_v1(CONSUMER, value))
        assert OutcomeDelivery(repository, sink).drain(outcome_id=record['outcome_id']) == [
            {'outcome_id': record['outcome_id'], 'disposition': 'ACCEPTED'}]

    import amphenol_recipe_choice_input as choice
    options = dict(outcome_id=record['outcome_id'],
                   request_sha256=settlement['binding']['request_sha256'], enabled=True)
    assert choice.read_operator_owned_choice_input(tmp_path, store, **options) is not None

    archived, pending = tmp_path / 'last-scan-request.json', tmp_path / 'next-scan.json'
    archived.replace(pending)
    with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repository:
        enrolled = _host().OperatorAmphenolRecipeEnrollment(
            request_id=identity['request_id'], request_sha256=options['request_sha256'],
            source_revision=identity['source_revision'])
        assert enrolled.settled(repository, record) is False
    assert choice.read_operator_owned_choice_input(tmp_path, store, **options) is None
    pending.replace(archived)

    with closing(State(str(tmp_path / 'state.db'))) as state:
        cycle = state.cycle(identity['cycle_id'])
        cycle['companies']['COMP-0490']['stage'] = 'queued'
        state.save_cycle(cycle)
    with closing(SQLiteRepository(jobs, 'sheet', readonly=True)) as repository:
        assert enrolled.settled(repository, record) is False
    assert choice.read_operator_owned_choice_input(tmp_path, store, **options) is None
