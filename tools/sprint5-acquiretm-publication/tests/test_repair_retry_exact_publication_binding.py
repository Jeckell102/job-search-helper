"""Exercise a released Company retry over the existing offline exact publisher."""

from contextlib import ExitStack, closing
from copy import deepcopy
import json

import pytest

from job_search_helper.ats import Inventory
from job_search_helper.company_events import canonical_company_fact, source_revision
from job_search_helper.engine import Engine, State, inventory_payload
from job_search_helper.exact_cycle_planner import freeze_exact_cycle_plans
from job_search_helper.exact_cycle_receipt import REPAIR_RETRY_PLAN_BINDING, derive_receipt
from job_search_helper.exact_cycle_recovery import _prepare_exact_v2_local, recover_exact_cycle
from job_search_helper.exact_cycle_sync import _company_guard, _fallback_receipt, publish_exact_cycle
from job_search_helper.inbox import InventoryInbox
from job_search_helper.integration_release import JOURNAL_SCHEMA
from job_search_helper.repair_retry import (
    REPAIR_RETRY_SCHEMA, RELEASE_BINDING_SCHEMA, release_binding_sha256, retry_attempt_id, retry_request,
)
from job_search_helper.scan_request import request_fingerprint
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from test_exact_cycle_recovery import RecordingRemote


AT = '2026-11-20T12:00:00Z'
FETCHED = '2026-11-20T12:01:00Z'
CYCLE = 'CYC-B01234567890'
COMPANY = 'COMP-1'
WORKBOOK = 'exact-repair-fixture'
BOARD = 'https://job-boards.greenhouse.io/synthetic-fixture'
ROW = {'Company ID': COMPANY, 'Company': 'Synthetic Fixture', 'Company Status': 'Active',
       'Official Careers URL': BOARD, 'ATS / Source': 'Greenhouse', 'Scan State': 'Queued'}


def active_release(path, release, state='COMPLETE'):
    path.write_text(json.dumps({
        'schema': JOURNAL_SCHEMA, 'state': state, 'release_id': release['release_id'], 'release': release,
    }))


@pytest.fixture
def retry_scope(tmp_path, monkeypatch):
    monkeypatch.setenv('JOB_STORAGE_BACKEND', 'sqlite')
    release = {'schema': RELEASE_BINDING_SCHEMA, 'release_id': 'REL-SYNTHETIC-F2',
               'source_manifest_sha256': '1' * 64, 'config_sha256': '2' * 64,
               'dependency_manifest_sha256': '3' * 64}
    revision = source_revision(ROW)
    retry = {'schema': REPAIR_RETRY_SCHEMA, 'failed_request_id': 'company-event:synthetic-original',
             'company_id': COMPANY, 'source_revision': revision, 'release': release, 'activated_at': AT}
    retry['attempt_id'] = retry_attempt_id(retry)
    request = retry_request(retry, enqueued_at=AT)
    runtime = {'state': 'COMPLETE', **{key: value for key, value in release.items() if key != 'schema'}}
    activation = tmp_path / 'integration-release-journal.json'
    active_release(activation, release)

    posting = {'posting_id': 'fixture-job-1', 'title': 'Implementation Manager',
               'url': BOARD + '/jobs/fixture-job-1', 'location': 'Remote',
               'description': 'Customer-facing implementation and deployment work.', 'ats': 'Greenhouse'}
    payload = inventory_payload(Inventory('complete', [posting], source_url=BOARD, ats='Greenhouse'), ROW)
    payload['fetched_at'] = FETCHED
    other = {**ROW, 'Company ID': 'COMP-OTHER', 'Company': 'Other Fixture',
             'Official Careers URL': 'https://job-boards.greenhouse.io/unrelated-fixture'}
    with ExitStack() as stack:
        local = stack.enter_context(closing(SQLiteRepository(tmp_path / 'jobs.sqlite3', WORKBOOK, initialize=True)))
        local.ensure_columns('Opportunities', ['Opportunity ID'])
        local.set_meta('ready', 'yes')
        local.set_meta('sheets_profile', COMPACT_PROFILE)
        local.import_rows('Companies', [(2, ROW), (3, other)])
        state = stack.enter_context(closing(State(tmp_path / 'state.db')))
        inbox = stack.enter_context(closing(InventoryInbox(tmp_path / 'inventories.sqlite3', WORKBOOK)))
        def forbidden_fetch(*args, **kwargs):
            pytest.fail('exact publication must not fetch')
        engine = Engine(local, state, inbox=inbox, runtime_binding=runtime, fetcher=forbidden_fetch)
        state.save_cycle({
            'id': CYCLE, 'all': False, 'status': 'In Progress', 'started_at': FETCHED,
            'start_request_id': request['request_id'], 'request_fingerprint': request_fingerprint(request, [COMPANY]),
            'runtime_binding': runtime, 'repair_retry': retry,
            'companies': {COMPANY: {'company': ROW['Company'], 'stage': 'queued',
                                    'outcome_source_revision': revision,
                                    'outcome_source_fact': canonical_company_fact(ROW)}},
        })
        inbox.save(CYCLE, COMPANY, payload)
        remote = RecordingRemote([ROW, other], schemas=COMPACT_SCHEMAS)
        remote.spreadsheet_id = WORKBOOK
        yield engine, remote, payload, request, activation


def guard(engine, remote):
    return lambda company_id, url: _company_guard(engine.repo, remote, company_id, url)


def freeze(engine, remote):
    return freeze_exact_cycle_plans(engine, CYCLE, [COMPANY], company_guard=guard(engine, remote), stamp=FETCHED)


def test_released_retry_one_exact_receipt_through_normal_compact_publication(retry_scope):
    engine, remote, payload, request, _ = retry_scope
    assert freeze(engine, remote)['planned'] == [COMPANY]
    plan, _ = engine.inbox.plan(CYCLE, COMPANY)
    expected_binding = {'request_id': request['request_id'], 'company_id': COMPANY,
                        'source_revision': request['source_revision'],
                        'release_id': request['repair_retry']['release']['release_id'],
                        'release_binding_sha256': release_binding_sha256(request['repair_retry']['release'])}
    assert plan[REPAIR_RETRY_PLAN_BINDING] == expected_binding
    e = derive_receipt(engine.state.cycle(CYCLE), COMPANY, payload, plan, FETCHED)
    assert e['binding'] == expected_binding and e['schedule']['enqueued_at'] == AT
    assert _fallback_receipt(engine.state.cycle(CYCLE), COMPANY, plan, payload)['binding'] == expected_binding
    with pytest.raises(ValueError, match='exact compact-v2 frozen binding'):
        derive_receipt(engine.state.cycle(CYCLE), COMPANY, payload, plan, FETCHED, request_id=CYCLE)
    result = recover_exact_cycle(engine, remote, CYCLE, [COMPANY])
    assert result['confirmed'] == [COMPANY], result
    assert len(remote.commits) == 1 and len(remote.snapshot('Job History')) == 1
    assert len(remote.snapshot('Companies')) == 2
    receipt = engine.inbox.receipt(e)
    assert receipt['binding'] == expected_binding and receipt['state'] == 'SYNC_CONFIRMED'
    assert engine.inbox.connection.execute('SELECT receipt_id FROM main.publication_receipts').fetchall() == [
        (receipt['receipt_id'],),
    ]


def test_unbound_v2_retry_plan_is_held_without_rewriting_the_plan(retry_scope):
    engine, remote, payload, _, _ = retry_scope
    admitted = engine.state.cycle(CYCLE)
    generic = {key: value for key, value in admitted.items() if key not in ('repair_retry', 'start_request_id')}
    engine.state.save_cycle(generic)
    assert freeze(engine, remote)['planned'] == [COMPANY]
    old = engine.inbox.plan(CYCLE, COMPANY)
    assert old[0]['exact_plan_version'] == 2 and REPAIR_RETRY_PLAN_BINDING not in old[0]
    engine.state.save_cycle(admitted)
    held = freeze(engine, remote)['held']
    assert held and 'missing its exact frozen receipt binding' in held[0]['reason']
    with pytest.raises(ValueError, match='exact compact-v2 frozen binding'):
        _fallback_receipt(admitted, COMPANY, old[0], payload)
    assert engine.inbox.plan(CYCLE, COMPANY) == old
    assert not engine.inbox.connection.execute('SELECT 1 FROM main.publication_receipts').fetchall()
    assert not remote.commits


@pytest.mark.parametrize('change', ['cycle_alias', 'actual_request_alias', 'release', 'company'])
def test_repair_publication_holds_conflicting_prior_receipt_or_currentness_drift(retry_scope, change):
    engine, remote, payload, request, activation = retry_scope
    assert freeze(engine, remote)['planned'] == [COMPANY]
    plan, _ = engine.inbox.plan(CYCLE, COMPANY)
    _prepare_exact_v2_local(engine, CYCLE, COMPANY, plan, payload)
    expected = derive_receipt(engine.state.cycle(CYCLE), COMPANY, payload, plan, FETCHED)
    if change in {'cycle_alias', 'actual_request_alias'}:
        legacy = deepcopy(expected)
        legacy['binding'].pop('release_binding_sha256')
        legacy['binding']['release_id'] = 'historical-synthetic-release-digest'
        if change == 'cycle_alias':
            legacy['binding']['request_id'] = CYCLE
        engine.inbox.ensure_receipt(legacy)
    elif change == 'release':
        active_release(activation, request['repair_retry']['release'], state='ROLLED_BACK')
    else:
        engine.repo.commit([{'tab': 'Companies', 'identity': {'Company ID': COMPANY},
                             'values': {'ATS / Source': 'Lever'}}])

    before = engine.inbox.connection.execute('SELECT * FROM main.publication_receipts ORDER BY receipt_id').fetchall()
    result = publish_exact_cycle(
        engine.inbox, CYCLE, remote, company_ids=[COMPANY], state=engine.state,
        company_guard=guard(engine, remote), local=engine.repo,
    )
    assert not result['confirmed'] and result['held'], result
    reason = result['held'][0]['reason']
    assert {'cycle_alias': 'conflicting legacy publication receipt', 'actual_request_alias': 'conflicting legacy publication receipt',
            'release': 'active COMPLETE release', 'company': 'no longer current'}[change] in reason
    assert engine.inbox.connection.execute('SELECT * FROM main.publication_receipts ORDER BY receipt_id').fetchall() == before
    assert not remote.commits and engine.inbox.exact_remote_state(CYCLE, COMPANY) is None
