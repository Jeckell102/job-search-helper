"""Ordinary-event receipt authority from an actual disposable admission archive."""
from contextlib import closing, contextmanager
import copy
import json
import socket
from unittest.mock import Mock

import pytest

from job_search_helper import ats, efficiency, publication_receipts
from job_search_helper.cli import writer_lock
from job_search_helper.engine import Engine, State
from job_search_helper.exact_cycle_planner import _digest, _exact_plan_digest, freeze_exact_cycle_plans
from job_search_helper.exact_cycle_receipt import (
    ORDINARY_EVENT_AUTHORITY, ORDINARY_EVENT_PLAN_BINDING, derive_receipt,
    load_ordinary_event_plan_context, ordinary_event_plan_payload, selected_retry_receipt_binding,
)
from job_search_helper.inbox import InventoryInbox
from job_search_helper.sqlite_repository import SQLiteRepository
from test_ordinary_company_event_fetch import (
    BOARD, OBSERVED, RUNTIME, observe, ordinary_cycle, workbook_reader,
)


CID = 'COMP-1'
STAMP = '2026-11-20T12:00:00+00:00'
POSTING = {
    'posting_id': '42', 'title': 'Implementation Manager', 'ats': 'Lever',
    'url': 'https://jobs.eu.lever.co/acme/42', 'location': 'Berlin, Germany',
    'description': 'Customer-facing implementation and deployment work.',
}
OPERATION = {
    'tab': 'Companies', 'identity': {'Company ID': CID},
    'values': {'Last Checked': '2026-11-20'},
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail('ordinary event planner test attempted network access')

    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(efficiency, 'load_title_blacklist', lambda: ())
    monkeypatch.setattr(efficiency, 'load_title_review_list', lambda: ())


def read_context(root, cycle_id, request_sha256, *, runtime=RUNTIME):
    with (closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet', readonly=True)) as local,
          closing(State(str(root / 'state.db'), readonly=True)) as state):
        return load_ordinary_event_plan_context(
            local, state, runtime, cycle_id=cycle_id, request_sha256=request_sha256,
        )


def frozen_context(ordinary_cycle, *, jobs=None, **options):
    root, cycle_id, request_hash = ordinary_cycle
    fetched = ats.Inventory(
        'complete', jobs=[POSTING] if jobs is None else jobs,
        source_url=OBSERVED, ats='Lever', **options,
    )
    provider = Mock(return_value=fetched)
    workbook = workbook_reader()
    status = observe(ordinary_cycle, provider, workbook)
    assert status['state'] == 'INVENTORY_FROZEN'
    assert workbook.return_value.service.batches == []
    provider.assert_called_once()
    return read_context(root, cycle_id, request_hash), status


@contextmanager
def planner_resources(root, *, runtime=RUNTIME):
    with (writer_lock(root / 'scraper.lock'), writer_lock(root / 'writer.lock'),
          closing(SQLiteRepository(root / 'jobs.sqlite3', 'sheet')) as local,
          closing(State(str(root / 'state.db'))) as state,
          closing(InventoryInbox(root / 'inventories.sqlite3', 'sheet')) as inbox):
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        yield Engine(local, state, inbox=inbox, runtime_binding=runtime)


def guard():
    return Mock(return_value={
        'company_id': CID, 'requested_url': BOARD, 'official_careers_url': BOARD,
        'company_status': 'Active', 'claimed_by': '', 'claim_token': '',
    })


def freeze(engine, cycle_id, gate, context=None):
    return freeze_exact_cycle_plans(engine, cycle_id, [CID], company_guard=gate,
                                    stamp=STAMP, ordinary_event_context=context)


def require_held(result, reason):
    assert result['planned'] == result['recovered'] == []
    [held] = result['held']
    assert held['company_id'] == CID
    assert reason in held['reason']


def test_exact_plan_and_receipt_freeze_with_original_authority_and_no_jobs_write(ordinary_cycle):
    root, cycle_id, request_hash = ordinary_cycle
    context, frozen = frozen_context(ordinary_cycle)
    observation = json.loads((root / 'ordinary-event-inventory' / f'{cycle_id}.json').read_bytes())
    payload = ordinary_event_plan_payload(context)
    altered = ordinary_event_plan_payload(context)
    altered['jobs'][0]['title'] = 'Different caller data'
    assert ordinary_event_plan_payload(context) == payload
    with planner_resources(root) as engine:
        engine.inbox.save(cycle_id, CID, payload)
        original = engine.state.cycle(cycle_id)
        before = engine.repo.db.total_changes
        gate = guard()
        result = freeze(engine, cycle_id, gate, context)
        assert result['planned'] == [CID], result
        plan, cursor = engine.inbox.plan(cycle_id, CID)
        binding = plan[ORDINARY_EVENT_PLAN_BINDING]
        assert binding == {
            'authority': ORDINARY_EVENT_AUTHORITY, 'cycle_id': cycle_id,
            'request_id': original['start_request_id'], 'request_sha256': request_hash,
            'request_fingerprint': original['request_fingerprint'],
            'company_event_id': original['company_event']['event_id'], 'company_id': CID,
            'source_revision': original['company_event']['source_revision'],
            'bridge_receipt_sha256': observation['binding']['bridge_receipt_sha256'],
            'observation_sha256': observation['sha256'], 'provider_inventory_sha256': frozen['inventory_sha256'],
            'workbook_id_sha256': _digest('sheet'), 'release_id': 'NO_RELEASE',
            'release_binding_sha256': _digest(RUNTIME),
        }
        assert plan['plan_digest'] == _exact_plan_digest(plan)
        assert plan['inventory_payload_digest'] == _digest(payload)
        assert cursor == 0
        receipt = derive_receipt(original, CID, payload, plan, STAMP, ordinary_event_context=context)
        assert receipt['binding'] == binding
        assert receipt['records'] == plan['remote_records']
        assert receipt['schedule'] == {'boundary': 'idle', 'enqueued_at': observation['binding']['request']['enqueued_at']}
        replay = derive_receipt(original, CID, payload, plan, 'later', ordinary_event_context=context)
        assert replay == {**receipt, 'timestamp': 'later'}
        assert freeze(engine, cycle_id, gate, context)['recovered'] == [CID]
        assert engine.inbox.plan(cycle_id, CID) == (plan, 0)
        assert engine.inbox.exact_local_state(cycle_id, CID)['state'] == 'FROZEN'
        assert engine.inbox.connection.execute('SELECT count(*) FROM publication_receipts').fetchone() == (0,)
        assert engine.repo.db.total_changes == before
        assert engine.state.cycle(cycle_id) == original


def test_scope_cannot_use_generic_legacy_or_compact_receipt(ordinary_cycle):
    root, cycle_id, request_hash = ordinary_cycle
    context, _ = frozen_context(ordinary_cycle)
    payload = ordinary_event_plan_payload(context)
    with planner_resources(root) as engine:
        before = engine.state.cycle(cycle_id)
        engine.inbox.save(cycle_id, CID, payload)
        gate = guard()
        require_held(freeze(engine, cycle_id, gate), 'verified plan context')
        gate.assert_not_called()
        assert engine.inbox.plan(cycle_id, CID) is None
        with pytest.raises(ValueError, match='no alternate lineage'):
            freeze_exact_cycle_plans(engine, cycle_id, [CID], company_guard=gate,
                                     bind_selected_retry=True, ordinary_event_context=context)
        with pytest.raises(ValueError, match='sole Company'):
            freeze_exact_cycle_plans(engine, cycle_id, [CID, 'COMP-2'], company_guard=gate,
                                     ordinary_event_context=context)
        with pytest.raises(ValueError, match='sealed exact plan'):
            derive_receipt(before, CID, payload, {'operations': [OPERATION]}, STAMP, ordinary_event_context=context)
        result = freeze(engine, cycle_id, gate, context)
        assert result['planned'] == [CID], result
        plan, _ = engine.inbox.plan(cycle_id, CID)

        for key, value in [('request_sha256', '0' * 64), ('observation_sha256', '0' * 64),
                           ('source_revision', '0' * 64), ('workbook_id_sha256', '0' * 64)]:
            forged = copy.deepcopy(plan)
            forged[ORDINARY_EVENT_PLAN_BINDING][key] = value
            forged['plan_digest'] = _exact_plan_digest(forged)
            with pytest.raises(ValueError, match='sealed exact plan'):
                derive_receipt(before, CID, payload, forged, STAMP, ordinary_event_context=context)

        unmarked = {key: value for key, value in plan.items() if key != ORDINARY_EVENT_PLAN_BINDING}
        unmarked['plan_digest'] = _exact_plan_digest(unmarked)
        with pytest.raises(ValueError, match='sealed exact plan'):
            derive_receipt(before, CID, payload, unmarked, STAMP, ordinary_event_context=context)
        with pytest.raises(ValueError, match='verified plan context'):
            derive_receipt(before, CID, payload, plan, STAMP)
        missing_event_field = {key: value for key, value in before.items() if key != 'company_event'}
        with pytest.raises(ValueError, match='verified plan context'):
            derive_receipt(missing_event_field, CID, payload, {'operations': [OPERATION]}, STAMP)
        with pytest.raises(ValueError, match='sealed exact plan'):
            derive_receipt(before, CID, payload, plan, STAMP, request_id=cycle_id, ordinary_event_context=context)
        with pytest.raises(ValueError, match='admitted source or runtime'):
            derive_receipt({**before, 'runtime_binding': {**RUNTIME, 'config_sha256': 'd' * 64}},
                           CID, payload, plan, STAMP, ordinary_event_context=context)
        with pytest.raises(ValueError, match='admitted cycle'):
            derive_receipt(before, 'COMP-2', payload, plan, STAMP, ordinary_event_context=context)
        assert engine.inbox.plan(cycle_id, CID) == (plan, 0)
    with pytest.raises(ValueError, match='exact admitted request digest'):
        read_context(root, cycle_id, '0' * 64)


def test_payload_mismatch_and_legacy_plan_stop_before_sheet_guard(ordinary_cycle):
    root, cycle_id, _ = ordinary_cycle
    context, _ = frozen_context(ordinary_cycle)
    payload = ordinary_event_plan_payload(context)
    corrupted = {**payload, 'jobs': [{**POSTING, 'posting_id': 'different-listing'}]}
    gate = guard()
    with planner_resources(root) as engine:
        engine.inbox.save(cycle_id, CID, corrupted)
        require_held(freeze(engine, cycle_id, gate, context), 'Inbox payload disagrees')
        assert engine.inbox.plan(cycle_id, CID) is None
        engine.inbox.acknowledge(cycle_id, CID)
        engine.inbox.save(cycle_id, CID, payload)
        legacy = {'operations': [OPERATION], 'final': {'stage': 'complete'}}
        engine.inbox.save_plan(cycle_id, CID, legacy)
        require_held(freeze(engine, cycle_id, gate, context), 'outside its exact receipt authority')
        assert engine.inbox.plan(cycle_id, CID) == (legacy, 0)
    gate.assert_not_called()


def test_profile_and_source_aba_hold_before_sheet_guard(ordinary_cycle):
    root, cycle_id, _ = ordinary_cycle
    context, _ = frozen_context(ordinary_cycle)
    gate = guard()
    with planner_resources(root) as engine:
        engine.inbox.save(cycle_id, CID, ordinary_event_plan_payload(context))
        engine.repo.set_meta('sheets_profile', '')
        require_held(freeze(engine, cycle_id, gate, context), 'verified compact workbook')
        engine.repo.set_meta('sheets_profile', 'compact-v1')
        for board in ('https://jobs.eu.lever.co/acme?location=Boston', BOARD):
            engine.repo.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': CID},
                'values': {'Official Careers URL': board},
            })
        require_held(freeze(engine, cycle_id, gate, context), 'source or owner changed')
        assert engine.inbox.plan(cycle_id, CID) is None
    gate.assert_not_called()


@pytest.mark.parametrize(('jobs', 'options', 'expected'), [
    ([], {}, 'nonempty plannable'),
    ([POSTING], {'browser_discovery_incomplete': True}, 'unresolved browser work'),
])
def test_nonpublishing_provider_evidence_never_gets_a_plan(ordinary_cycle, jobs, options, expected):
    context, _ = frozen_context(ordinary_cycle, jobs=jobs, **options)
    with pytest.raises(ValueError, match=expected):
        ordinary_event_plan_payload(context)


@pytest.mark.parametrize('kind', ['legacy', 'compact-default', 'selected-retry'])
def test_existing_receipt_wire_bytes_and_id_stay_unchanged(kind):
    cycle_id = 'CYC-UNCHANGED'
    cycle = {'id': cycle_id, 'start_request_id': 'old-request', 'companies': {CID: {}},
             'started_at': STAMP, 'runtime_binding': RUNTIME}
    payload = {'source_revision': 'legacy-source', 'fetched_at': STAMP}
    plan = {'final': {'stage': 'complete'}, 'operations': [OPERATION]}
    options = {}
    if kind != 'legacy':
        plan.update(exact_plan_version=2, remote_projection=[OPERATION])
        options['request_id'] = cycle_id
    records = publication_receipts.record_fingerprints([OPERATION])
    binding = {'request_id': options.get('request_id', 'old-request'), 'company_id': CID,
               'source_revision': 'legacy-source', 'release_id': _digest({'records': records, 'final': plan['final']})}
    if kind == 'selected-retry':
        outcome = 'OUT-' + '1' * 24
        cycle['start_request_id'] = 'temporary-retry:' + outcome
        cycle['temporary_retry'] = {'schema': 'temporary-scrape-retry-v1', 'company_id': CID,
                                    'outcome_id': outcome, 'source_revision': '9' * 64,
                                    'retry_index': 1, 'retry_cap': 1}
        cycle['companies'][CID]['outcome_source_revision'] = '9' * 64
        options = {}
        binding = {'request_id': cycle['start_request_id'], 'company_id': CID,
                   'source_revision': '9' * 64, 'release_id': 'NO_RELEASE', 'release_binding_sha256': _digest(RUNTIME)}
        plan['selected_retry_receipt_binding'] = binding
        assert selected_retry_receipt_binding(cycle, CID) == binding
    expected = {'binding': binding, 'records': records,
                'schedule': {'boundary': 'idle', 'enqueued_at': STAMP}, 'timestamp': STAMP}
    got = derive_receipt(cycle, CID, payload, plan, STAMP, **options)
    canonical = lambda obj: json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    assert canonical(got).encode() == canonical(expected).encode()
    assert publication_receipts._receipt_id(got['binding']) == _digest(binding)


@pytest.mark.parametrize(('values', 'changed_field'), [
    ({'Company Status': 'active', 'ATS / Source': 'LEVER'}, None),
    ({'ATS / Source': 'Greenhouse'}, 'ATS / Source'),
    ({'Official Careers URL': 'https://jobs.eu.lever.co/acme?location=Paris'}, 'Official Careers URL'),
    ({'Company': 'Different Company'}, 'Company'),
    ({'Company ID': 'COMP-2'}, 'Company ID'),
    ({'Company Status': 'Paused'}, 'Company Status'),
])
def test_finisher_cannot_change_pinned_company_fields(ordinary_cycle, monkeypatch, values, changed_field):
    root, cycle_id, _ = ordinary_cycle
    context, _ = frozen_context(ordinary_cycle)
    with planner_resources(root) as engine:
        engine.inbox.save(cycle_id, CID, ordinary_event_plan_payload(context))
        prior = engine.repo.matches('Companies', {'Company ID': CID})
        real_finish = engine._finish_company

        def finish_with_source_proposal(cycle, company):
            real_finish(cycle, company)
            engine._commit(engine._company_op(company, values))

        monkeypatch.setattr(engine, '_finish_company', finish_with_source_proposal)
        result = freeze(engine, cycle_id, guard(), context)
        if changed_field:
            require_held(result, 'protected Company source field: ' + changed_field)
            assert engine.inbox.plan(cycle_id, CID) is None
        else:
            assert result['planned'] == [CID], result
            plan, _ = engine.inbox.plan(cycle_id, CID)
            for stream in ('local_operations', 'remote_projection'):
                for operation in plan[stream]:
                    if operation['tab'] == 'Companies':
                        assert not set(values).intersection(operation.get('values', {}))
        assert engine.repo.matches('Companies', {'Company ID': CID}) == prior


def test_source_change_during_workbook_guard_stops_before_plan_save(ordinary_cycle):
    root, cycle_id, _ = ordinary_cycle
    context, _ = frozen_context(ordinary_cycle)
    with planner_resources(root) as engine:
        engine.inbox.save(cycle_id, CID, ordinary_event_plan_payload(context))
        workbook = guard()

        def source_advances(*args):
            engine.repo.mutate_company_with_event({
                'tab': 'Companies', 'identity': {'Company ID': CID},
                'values': {'Official Careers URL': 'https://jobs.eu.lever.co/acme?location=Paris'},
            })
            return workbook(*args)

        require_held(freeze(engine, cycle_id, source_advances, context), 'source or owner changed')
        assert engine.inbox.plan(cycle_id, CID) is None
        workbook.assert_called_once_with(CID, BOARD)


def test_resealed_plan_with_a_company_source_write_cannot_derive_receipt(ordinary_cycle):
    root, cycle_id, _ = ordinary_cycle
    context, _ = frozen_context(ordinary_cycle)
    payload = ordinary_event_plan_payload(context)
    with planner_resources(root) as engine:
        engine.inbox.save(cycle_id, CID, payload)
        result = freeze(engine, cycle_id, guard(), context)
        assert result['planned'] == [CID], result
        plan, _ = engine.inbox.plan(cycle_id, CID)
        for operation in plan['remote_projection']:
            if operation['tab'] == 'Companies':
                operation.setdefault('values', {})['ATS / Source'] = 'Greenhouse'
                break
        else:
            pytest.fail('fixture needs a Company projection')
        plan['remote_projection_digest'] = _digest(plan['remote_projection'])
        plan['remote_records'] = publication_receipts.record_fingerprints(plan['remote_projection'])
        plan['remote_records_digest'] = _digest(plan['remote_records'])
        plan['plan_digest'] = _exact_plan_digest(plan)
        with pytest.raises(ValueError, match='changes protected Company scope or source'):
            derive_receipt(engine.state.cycle(cycle_id), CID, payload, plan, STAMP,
                           ordinary_event_context=context)
