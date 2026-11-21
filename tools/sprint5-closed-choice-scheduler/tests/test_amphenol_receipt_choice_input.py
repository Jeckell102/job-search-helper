"""Compose the real ordinary event and receipt authorities without a worker."""
from contextlib import closing
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

from amphenol_recipe_choice_input import (
    COMPANY_ID, SOURCE, _verified_readbacks, prepare_choice_input, read_owned_choice_input,
)
from coordinator import Coordinator
from coordinator_store import Store
from job_search_helper.ats import validate_outcome_failure
from job_search_helper.company_events import _json_digest, read_verified_ordinary_event_admission
from job_search_helper.engine import State
from job_search_helper.retained_operator_journal import provider_inventory_digest
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.temporary_retry import _selected_sha
import test_ordinary_event_no_publication as ordinary_fixture


@pytest.mark.parametrize('continuation', [False, True])
def test_owned_ordinary_witness_prepares_one_disabled_by_default_recipe_call(tmp_path, monkeypatch, capsys, continuation):
    model = Mock(side_effect=AssertionError('A handoff must not call a model'))
    coordinator = Coordinator(base=tmp_path / 'coordinator', model=model)
    receive = Mock(wraps=coordinator.command)

    def deliver(record):
        return receive({'action': 'ingest-scrape-outcome-delivery-v1',
                        'consumer': CONSUMER, 'record': record})['receipt']

    class InProcessDelivery(OutcomeDelivery):
        def __init__(self, repository, sink):
            sink.ingest_immutable.side_effect = deliver
            super().__init__(repository, sink)

    with monkeypatch.context() as fixture_patch:
        fixture_patch.setattr(ordinary_fixture, 'OutcomeDelivery', InProcessDelivery)
        ordinary_fixture.test_named_amphenol_pagination_settlement_is_exact_and_never_publishes(
            tmp_path, fixture_patch, capsys, 'owned',
        )
    receive.assert_called_once()
    [held] = coordinator.store.held_repair_intake()
    record = held['outcome']
    cycle_id = record['identity']['cycle_id']
    with (closing(State(str(tmp_path / 'state.db'), readonly=True)) as state,
          closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet', readonly=True)) as jobs):
        admission = read_verified_ordinary_event_admission(jobs, state, cycle_id)
    request = admission['request']
    selection = {'cycle_id': cycle_id, 'request_id': request['request_id'],
                 'request_sha256': _json_digest(request), 'company_event_id': request['company_event']['event_id'],
                 'source_revision': request['source_revision'], 'outcome_id': record['outcome_id']}

    outcome_id = selection['outcome_id']
    assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id) is None
    monkeypatch.setenv('SPREADSHEET_ID', 'foreign-environment-destination')
    with patch.object(coordinator.store, 'connect', side_effect=AssertionError('Use a read-only receiver')):
        readback = _verified_readbacks(tmp_path, coordinator.store, outcome_id)
        offered = read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id, enabled=True)
    assert readback is not None
    assert prepare_choice_input(**readback) is None
    assert offered is not None
    assert (offered['mode'], offered['phase'], offered['max_calls']) == ('review', 'inspect', 1)
    [tool] = offered['tools']
    assert tool['type'] == 'function' and tool['function']['name'] == 'worker_checkpoint'
    assert tool['function']['parameters'] == {
        'type': 'object', 'additionalProperties': False,
        'required': ['summary', 'next_action', 'outcome'],
        'properties': {'summary': {'type': 'string', 'enum': ['W1']},
                       'next_action': {'type': 'string', 'enum': ['listing_membership_change', 'fixed_delay', 'hold']},
                       'outcome': {'type': 'string', 'enum': ['phase_done', 'blocked']}},
    }
    provider = readback['frozen']['inventory']
    witness = provider['outcome_failure']['evidence']
    prompt = json.loads(offered['messages'][1]['content'])
    assert prompt['W1'] == witness and provider['reason'] not in offered['messages'][1]['content']
    assert offered['binding'] == {**selection, 'company_id': COMPANY_ID, 'board': SOURCE,
                                  'sink_receipt_id': readback['receipt']['sink_receipt_id'],
                                  'record_sha256': _selected_sha(record),
                                  'observation_sha256': readback['frozen']['sha256'],
                                  'witness_sha256': _selected_sha(witness)}
    assert prepare_choice_input(**readback, enabled=True) == offered

    for field, change in (
        ('selection', {'request_sha256': '0' * 64}),
        ('selection', {'company_event_id': 'CEV-foreign'}),
        ('company', {'company_id': 'COMP-0491'}),
        ('company', {'official_careers_url': SOURCE.replace('home.aspx', 'other.aspx')}),
        ('receipt', {'record_sha256': '0' * 64}),
        ('held', {'task_id': 'fixture-already-promoted'}),
        ('frozen', {'inventory': {**provider, 'jobs': [{'posting_id': 'unexpected'}]}}),
        ('frozen', {'inventory': {**provider, 'outcome_failure': None}}),
    ):
        changed = {**readback, field: {**readback[field], **change}}
        assert prepare_choice_input(**changed, enabled=True) is None, field

    # A structurally valid timing change is still foreign to the owned receipt.
    altered = deepcopy(readback['frozen'])
    altered['inventory']['outcome_failure']['evidence']['premature_elapsed_ms'] += 1
    assert validate_outcome_failure(altered['inventory']['outcome_failure']) is not None
    altered['inventory_sha256'] = provider_inventory_digest(altered['inventory'], event_scope=True)
    altered['sha256'] = _selected_sha({key: value for key, value in altered.items() if key != 'sha256'})
    assert prepare_choice_input(**{**readback, 'frozen': altered}, enabled=True) is None

    if continuation:
        project = Path(__file__).resolve().parents[1]
        with (patch('coding_tools.root', return_value=project),
              patch('coordinator_workspace.batch_source', return_value=project)):
            response = coordinator.command({
                'action': 'promote-repair', 'repair_key': held['repair_key'],
                'source_revision': selection['source_revision'], 'mode': 'develop',
                'objective': 'Inspect src/job_search_helper/acquiretm.py and run tests/test_acquiretm.py.',
                'integration': {
                    'company_id': COMPANY_ID, 'company': 'Amphenol Aerospace', 'configured_url': SOURCE,
                    'ats': 'AcquireTM', 'tests': ['tests/test_acquiretm.py'],
                    'source_targets': ['src/job_search_helper/acquiretm.py'],
                },
            })
        task_id = response['id']
        saved_task = coordinator.store.get(task_id)
        assert saved_task['status'] == 'PAUSED' and saved_task['stop_requested'] is True
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id, enabled=True) is None
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id,
                                       expected_task_id=task_id) is None
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id, enabled=True,
                                       expected_task_id='WRAP-' + '0' * 10) is None
        with patch.object(coordinator.store, 'connect', side_effect=AssertionError('Use the receiver read snapshot')):
            continued = read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id,
                                                enabled=True, expected_task_id=task_id)
        assert continued == offered
        unavailable = Store(tmp_path / 'unavailable-owner')
        assert read_owned_choice_input(tmp_path, unavailable, outcome_id=outcome_id,
                                       enabled=True, expected_task_id=task_id) is None
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id='legacy-outcome',
                                       enabled=True, expected_task_id=task_id) is None
        assert coordinator.store.get(task_id) == saved_task
        # A task may accumulate unrelated progress. Reading its immutable input
        # must not replace that actual row with a projected pre-promotion task.
        progressed = {**saved_task, 'phase': 'inspect', 'workflow': {'retained_operator_note': 'keep'}}
        with coordinator.store.connect() as db:
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(progressed), task_id))
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id,
                                       enabled=True, expected_task_id=task_id) == offered
        assert coordinator.store.get(task_id) == progressed
        for replacement in (
            # Removing both lets the generic validator's legacy branch return;
            # a promoted owner must still retain its actual canonical binding.
            {key: value for key, value in progressed.items()
             if key not in {'integration', 'integration_identity_digest'}},
            {**progressed, 'repair_provenance': {**progressed['repair_provenance'], 'outcome_id': 'foreign'}},
            {**progressed, 'held_repair_key': '0' * 64},
            {**progressed, 'integration_identity': {**progressed['integration_identity'], 'configured_url': SOURCE + '?foreign'}},
        ):
            with coordinator.store.connect() as db:
                db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(replacement), task_id))
            assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id,
                                           enabled=True, expected_task_id=task_id) is None
        with coordinator.store.connect() as db:
            db.execute('UPDATE tasks SET state=? WHERE id=?', (json.dumps(progressed), task_id))
            db.execute('UPDATE repair_intake SET task_id=? WHERE repair_key=?', ('WRAP-' + '1' * 10, held['repair_key']))
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id,
                                       enabled=True, expected_task_id=task_id) is None
        with coordinator.store.connect() as db:
            db.execute('UPDATE repair_intake SET task_id=? WHERE repair_key=?', (task_id, held['repair_key']))
        with closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet')) as jobs:
            jobs.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
                'values': {'Official Careers URL': SOURCE.replace('home.aspx', 'other.aspx')},
            })
        assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id,
                                       enabled=True, expected_task_id=task_id) is None
        assert len(coordinator.store.all()) == 1 and coordinator.store.get(task_id) == progressed
        assert coordinator.scheduler_thread is None
        model.assert_not_called()
        return

    foreign = Store(tmp_path / 'foreign-coordinator')
    assert read_owned_choice_input(tmp_path, foreign, outcome_id=outcome_id, enabled=True) is None
    # An internally valid receiver receipt for different intake disposition
    # still disagrees with the sender's acknowledged bytes.
    receipt = foreign.ingest_scrape_outcome_delivery_v1(CONSUMER, record)
    receipt['sink_status'] = 'RECORDED_NO_REPAIR'
    text = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    with foreign.connect() as db:
        db.execute('UPDATE scrape_outcome_delivery_receipts SET receipt=?,receipt_sha256=?,sink_status=? '
                   'WHERE consumer=? AND outcome_id=?',
                   (text, sha256(text.encode()).hexdigest(), receipt['sink_status'], CONSUMER, outcome_id))
    assert read_owned_choice_input(tmp_path, foreign, outcome_id=outcome_id, enabled=True) is None
    with closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet')) as jobs:
        jobs.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
            'values': {'Official Careers URL': SOURCE.replace('home.aspx', 'other.aspx')},
        })
    assert read_owned_choice_input(tmp_path, coordinator.store, outcome_id=outcome_id, enabled=True) is None
    assert coordinator.store.all() == [] and coordinator.scheduler_thread is None
    model.assert_not_called()
