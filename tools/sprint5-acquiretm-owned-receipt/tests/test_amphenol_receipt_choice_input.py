"""Compose the real ordinary event and receipt authorities without a worker."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
from unittest.mock import Mock

from amphenol_recipe_choice_input import COMPANY_ID, SOURCE, prepare_choice_input
from coordinator import Coordinator
from coordinator_store import Store
from job_search_helper.ats import validate_outcome_failure
from job_search_helper.company_events import (
    _json_digest, current_company_repair_snapshot, read_verified_ordinary_event_admission,
)
from job_search_helper.engine import State
from job_search_helper.ordinary_company_event_fetch import load_ordinary_event_observation
from job_search_helper.ordinary_event_settlement import _read_settlement, ordinary_event_outcome_settled
from job_search_helper.retained_operator_journal import provider_inventory_digest
from job_search_helper.scrape_outcome_delivery import CONSUMER, OutcomeDelivery
from job_search_helper.sqlite_repository import SQLiteRepository
from job_search_helper.temporary_retry import _selected_sha
import test_ordinary_event_no_publication as ordinary_fixture


def _verified_readbacks(root, store, selection):
    """Fixture-only composition of owner APIs and exact persisted receipt rows."""
    with (closing(State(str(root / 'state.db'), readonly=True)) as state,
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as jobs):
        [row] = jobs._outcome_delivery_rows(CONSUMER, outcome_id=selection['outcome_id'])
        record, digest, stale, acknowledged, _ = OutcomeDelivery(jobs, None)._preflight(row)
        if stale or not acknowledged or not ordinary_event_outcome_settled(jobs, record):
            return None
        cycle_id, request_id = selection['cycle_id'], selection['request_id']
        cycle = state.cycle(cycle_id)
        settlement = _read_settlement(jobs, cycle_id, request_id)
        frozen = load_ordinary_event_observation(
            jobs, state, cycle['runtime_binding'], cycle_id=cycle_id,
            request_sha256=selection['request_sha256'],
        )
        company = current_company_repair_snapshot(jobs, COMPANY_ID)
    with closing(sqlite3.connect(store.path.as_uri() + '?mode=ro', uri=True)) as db:
        receipt_row = db.execute(
            'SELECT record_sha256,receipt_id,receipt,receipt_sha256,sink_status '
            'FROM scrape_outcome_delivery_receipts WHERE consumer=? AND outcome_id=?',
            (CONSUMER, selection['outcome_id']),
        ).fetchone()
        intake_row = db.execute(
            'SELECT company_id,source_revision,outcome,payload FROM scrape_outcome_intake WHERE outcome_id=?',
            (selection['outcome_id'],),
        ).fetchone()
    if receipt_row is None or intake_row is None:
        return None
    store._validate_delivery_intake(
        intake_row, canonical=record, record_sha256=digest,
        legacy_text=json.dumps(record, sort_keys=True, separators=(',', ':')),
    )
    receipt = store._validate_delivery_receipt(receipt_row, consumer=CONSUMER, canonical=record, record_sha256=digest)
    if receipt != json.loads(row[6]):
        return None
    [held] = [item for item in store.held_repair_intake() if item['outcome_id'] == selection['outcome_id']]
    return dict(selection=selection, company=company, record=record, receipt=receipt,
                held=held, settlement=settlement, frozen=frozen)


def test_owned_ordinary_witness_prepares_one_disabled_by_default_recipe_call(tmp_path, monkeypatch, capsys):
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

    readback = _verified_readbacks(tmp_path, coordinator.store, selection)
    assert readback is not None
    assert prepare_choice_input(**readback) is None
    offered = prepare_choice_input(**readback, enabled=True)
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

    assert _verified_readbacks(tmp_path, Store(tmp_path / 'empty-coordinator'), selection) is None
    with closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', 'sheet')) as jobs:
        jobs.mutate_company_with_event({
            'tab': 'Companies', 'identity': {'Company ID': COMPANY_ID},
            'values': {'Official Careers URL': SOURCE.replace('home.aspx', 'other.aspx')},
        })
    assert _verified_readbacks(tmp_path, coordinator.store, selection) is None
    assert coordinator.store.all() == [] and coordinator.scheduler_thread is None
    model.assert_not_called()
