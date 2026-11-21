"""Synthetic reviewed transport and a disposable committed-attempt ledger."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
from email.utils import formatdate
from hashlib import sha256
from importlib import import_module
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from job_search_helper import ats
from job_search_helper.company_events import source_revision
from job_search_helper.ordinary_live_issuance_slot import IssuanceWindow


NOW = 1_800_000_000_000
ELAPSED = 10_000_000_000
BOOT = 'ec5706da-4907-4b15-af59-279244098e26'
DEADLINE = NOW + 90_000


def hydration(props):
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({'props': {'pageProps': props}}) + '</script>').encode()


def listing(tenant, page, items):
    return hydration({
        'apiData': {'jobBoardSlug': tenant, 'jobBoard': {'slug': tenant}},
        'dehydratedState': {'queries': [{
            'queryKey': ['board', tenant, 'job-posts', False, {
                'city': '', 'country': '', 'departments': [], 'page': page, 'pageSize': 20,
                'searchQuery': '', 'state': '', 'workplaceType': None,
            }],
            'state': {'data': {'page': page, 'pageSize': 20, 'totalItems': len(items),
                               'totalPages': (len(items) + 19) // 20,
                               'items': items[page * 20:(page + 1) * 20]}},
        }]},
    })


def detail(tenant, url, item):
    return hydration({'apiData': {'jobBoardSlug': tenant, 'jobBoard': {'slug': tenant}, 'workLocations': [], 'jobPost': {
        'uuid': item['id'], 'url': url, 'name': item['name'], 'unlistedFromSearch': False,
        'description': {'company': '<p>Employer information.</p>', 'role': '<p>Fixture role details.</p>'},
    }}})


def headers(*, status=200, date=NOW, extra=()):
    lines = [f'HTTP/2 {status}', f'Date: {formatdate(date / 1000, usegmt=True)}',
             'content-type: text/html; charset=utf-8', *extra, '', '']
    return '\r\n'.join(lines).encode()


class FixtureLedger:
    """Persist the current disposable records before returning each acknowledgement."""

    def __init__(self, module, path):
        self.module = module
        self.path = path

    def read_attempts(self):
        if not self.path.exists():
            return ()
        return tuple((self.module.Attempt(**item[0]), self.module.Receipt(**item[1]) if item[1] else None)
                     for item in json.loads(self.path.read_bytes()))

    def _commit(self, records):
        with self.path.open('w', encoding='utf-8') as stream:
            json.dump([(asdict(attempt), asdict(receipt) if receipt else None) for attempt, receipt in records],
                      stream)
            stream.flush()
            os.fsync(stream.fileno())
        return self.read_attempts()

    def begin_attempt(self, attempt):
        previous = self.read_attempts()
        if any(receipt is None for _, receipt in previous) or attempt.sequence != len(previous) + 1:
            raise OSError('Fixture attempt collision')
        return self._commit((*previous, (attempt, None)))[-1][0]

    def finish_attempt(self, attempt, receipt):
        previous = self.read_attempts()
        if previous[-1] != (attempt, None):
            raise OSError('Fixture completion collision')
        return self._commit((*previous[:-1], (attempt, receipt)))[-1][1]


class FixtureTransport:
    def __init__(self, ledger, routes):
        self.ledger = ledger
        self.routes = routes
        self.called = []

    @contextmanager
    def open_get(self, url, **limits):
        index = len(self.called)
        attempt, receipt = self.ledger.read_attempts()[-1]
        assert (attempt.sequence, attempt.url, receipt) == (index + 1, url, None)
        assert url == self.routes[index][0]
        self.called.append((url, limits))
        yield self.routes[index][1]


def response(url, entity, *, status=200, raw_headers=None, final_url=None):
    return SimpleNamespace(final_url=final_url or url, status=status, headers=raw_headers or headers(status=status),
                           entity=(entity,) if entity else ())


@pytest.fixture
def owned(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'dev/pre_release_validation'))
    module = import_module('rippling_public_capture')
    authority = module.authority
    # Exercise the actual witness parser with hashes of two synthetic scripts.
    scripts = {
        'const jobBoardSlug = "forterra"': authority.FORTERRA_MOUNT,
        'const jobBoardSlug = "gotenna-inc"': authority.GOTENNA_MOUNT,
    }
    monkeypatch.setattr(authority, 'FORTERRA_SCRIPTS',
                        {sha256(script.encode()).hexdigest(): mount for script, mount in scripts.items()})
    forterra = ''.join(f'<div id="{mount}"></div><script>{script}</script>' for script, mount in scripts.items())
    pdw = f'<a href="{authority.PDW_BOARD}">Jobs</a><a href="{authority.PDW_ALIAS}">Careers</a>'
    companies = tuple({
        'Company ID': cid, 'Company': name, 'Company Status': 'Active',
        'Official Careers URL': url, 'ATS / Source': 'Rippling',
    } for cid, name, url in (
        ('COMP-0066', 'Forterra', authority.FORTERRA_CAREERS),
        ('COMP-0178', 'Performance Drone Works (PDW)', authority.PDW_CAREERS),
    ))
    policy = {'entity_bytes_limit': 128 * 1024, 'max_age_seconds': 30, 'future_skew_seconds': 1,
              'transport_policy_sha256': '1' * 64}
    binding = {'deadline_unix_ms': DEADLINE, 'dispatch_sha256': '2' * 64, 'live_request_limit': 31,
               'replay_request_limit': 32, 'capsule_bytes_limit': 1024 * 1024,
               'collector_policy_sha256': module.digest(policy),
               'company_projection_sha256': module.digest(companies[0]),
               'control_projection_sha256': module.digest(companies[1]),
               'candidate': {'source_manifest_sha256': '3' * 64, 'config_sha256': '4' * 64,
                             'dependency_manifest_sha256': '5' * 64}}

    routes = []

    def add(url, entity, **options):
        routes.append((url, response(url, entity, **options)))

    def board_responses(board, start, number):
        tenant = board.split('/')[-2]
        items = [{'id': str(UUID(int=start + offset)), 'name': f'Posting — {start + offset}'}
                 for offset in range(number)]
        pages = [(board if page == 0 else f'{board}?page={page}', listing(tenant, page, items))
                 for page in range((number + 19) // 20)]
        for url, body in pages:
            add(url, body)
        for item in items:
            url = f"{board}/{item['id']}"
            add(url, detail(tenant, url, item))
        for url, body in pages:
            add(url, body)

    add(authority.FORTERRA_CAREERS, forterra.encode(),
        raw_headers=b'HTTP/2 103\r\nlink: </preload.css>; rel=preload\r\n\r\n'
                    + headers(extra=('x-fixture: first', 'x-fixture: second')))
    board_responses(authority.FORTERRA_BOARD, 1, 21)
    add(authority.PDW_CAREERS, pdw.encode())
    add(authority.PDW_ALIAS, b'non-followed alias body', status=308,
        raw_headers=headers(status=308, extra=(f'Location: {authority.PDW_LOCATION}',
                                                f'Refresh: 0;url={authority.PDW_LOCATION}')))
    board_responses(authority.PDW_BOARD, 50, 1)

    ledger = FixtureLedger(module, tmp_path / 'attempts.json')
    return SimpleNamespace(module=module, authority=authority, binding=binding, policy=policy, companies=companies,
                           ledger=ledger, transport=FixtureTransport(ledger, routes), routes=routes,
                           window=IssuanceWindow(BOOT, NOW, ELAPSED, ELAPSED + 90_000_000_000),
                           clock=lambda: (BOOT, NOW, ELAPSED))


def collect(owned):
    return owned.module.collect_public_capture(
        owned.binding, owned.window, owned.companies,
        ledger=owned.ledger, transport=owned.transport, read_clock=owned.clock, response_policy=owned.policy,
    )


def test_two_exact_scopes_preserve_body_ledger_and_replay_full_details(owned):
    module = owned.module
    validator = import_module('validate_candidate')
    result = collect(owned)
    manifest, capture = json.loads(result.manifest), json.loads(result.candidate_capture)
    assert manifest['candidate_capture_sha256'] == sha256(result.candidate_capture).hexdigest()
    assert manifest['binding_sha256'] == module.digest(owned.binding)
    assert manifest['response_policy'] == owned.policy
    assert capture['schema'] == validator.PUBLIC_CAPTURE_SCHEMA
    assert len(result.exchanges) == len(owned.transport.called) == 31
    assert tuple((exchange.attempt, exchange.receipt) for exchange in result.exchanges) == owned.ledger.read_attempts()
    assert [exchange.attempt.url for exchange in result.exchanges] == [url for url, _ in owned.routes]
    for record, exchange in zip(manifest['exchanges'], result.exchanges, strict=True):
        assert record == {'attempt': asdict(exchange.attempt), 'receipt': asdict(exchange.receipt)}
        assert exchange.receipt.headers_sha256 == sha256(exchange.headers).hexdigest()
        assert exchange.receipt.entity_sha256 == sha256(exchange.entity).hexdigest()
    assert b'x-fixture: first\r\nx-fixture: second\r\n' in result.exchanges[0].headers
    assert [item.entity for item in result.exchanges if item.receipt.status == 308] == [b'non-followed alias body']
    assert sum(len(exchange.headers) + len(exchange.entity) for exchange in result.exchanges
               ) + len(result.manifest) + len(result.candidate_capture) <= owned.binding['capsule_bytes_limit']
    assert all(limits['deadline_elapsed_ns'] == owned.window.deadline_elapsed_ns
               for _, limits in owned.transport.called)

    def dispatch(*args, **kwargs):
        inventory = ats.fetch_inventory(*args, **kwargs)
        assert inventory.status == 'complete', inventory.reason
        return inventory

    replay_io = []
    with validator.prohibit_io(replay_io):
        for case, count in zip(capture['cases'], (21, 1), strict=True):
            projection = case['company']
            scope = {'role': case['role'], 'company': projection['Company'], 'company_id': projection['Company ID'],
                     'company_row_sha256': module.digest(projection), 'source_revision': source_revision(projection),
                     'authority_url': case['authority']['url'], 'board_url': case['board_url']}
            received = {}
            validator.validate_company(case, scope, received, source_revision, module.oracle,
                                       dispatch, ats.HTTPResponse, owned.authority)
            assert received['posting_count'] == count
            assert [read['total'] for read in received['listing_reads']] == [count, count]
    assert not replay_io


@pytest.mark.parametrize(('mode', 'reason'), [
    ('redirected', 'URL or status'),
    ('status', 'URL or status'),
    ('location', 'redirect target'),
    ('stale', 'cache age'),
    ('duplicate_age', 'absent or ambiguous'),
])
def test_first_response_mismatch_spends_one_attempt_with_no_retry(owned, mode, reason):
    url, original = owned.routes[0]
    replacements = {
        'redirected': {'final_url': owned.authority.PDW_CAREERS},
        'status': {'status': 302},
        'location': {'headers': headers(extra=(f'Location: {owned.authority.PDW_CAREERS}',))},
        'stale': {'headers': headers(date=NOW - 31_000)},
        'duplicate_age': {'headers': headers(extra=('Age: 1', 'age: 2'))},
    }
    owned.routes[0] = url, SimpleNamespace(**{**vars(original), **replacements[mode]})
    with pytest.raises(owned.module.oracle.CaptureError, match=reason):
        collect(owned)
    assert len(owned.transport.called) == 1
    assert owned.ledger.read_attempts()[0][1] is None
    with pytest.raises(owned.module.oracle.CaptureError, match='already attempted'):
        collect(owned)
    assert len(owned.transport.called) == 1


def test_pdw_wrong_alias_location_does_not_reach_pdw_board(owned):
    index = next(i for i, (url, _) in enumerate(owned.routes) if url == owned.authority.PDW_ALIAS)
    url, value = owned.routes[index]
    value.headers = headers(status=308, extra=('Location: /forterra/jobs',))
    with pytest.raises(owned.module.oracle.CaptureError, match='redirect target'):
        collect(owned)
    assert len(owned.transport.called) == index + 1
    assert owned.ledger.read_attempts()[-1][1] is None


def test_unreviewed_forterra_script_stops_before_any_board_request(owned):
    response = owned.routes[0][1]
    response.entity = (response.entity[0].replace(b'"forterra"', b'"gotenna-inc"', 1),)
    with pytest.raises(owned.module.oracle.CaptureError, match='Reviewed widget script precedes'):
        collect(owned)
    assert [item[0] for item in owned.transport.called] == [owned.authority.FORTERRA_CAREERS]


@pytest.mark.parametrize(('offset', 'reason'), [
    (2, 'different board'), (3, 'visibility differs'), (24, 'complete reread'),
])
def test_foreign_tenant_detail_and_order_drift_stop_without_more_requests(owned, offset, reason):
    url, value = owned.routes[offset]
    if offset == 2:
        items = [{'id': str(UUID(int=i)), 'name': str(i)} for i in range(1, 22)]
        value.entity = (listing('pdwcareers', 1, items),)
    elif offset == 3:
        value.entity = (value.entity[0].replace(b'"unlistedFromSearch": false', b'"unlistedFromSearch": true'),)
    else:
        items = [{'id': str(UUID(int=i)), 'name': f'Posting — {i}'} for i in range(1, 22)]
        items[0], items[1] = items[1], items[0]
        value.entity = (listing('forterra', 0, items),)
    with pytest.raises(owned.module.oracle.CaptureError, match=reason):
        collect(owned)
    assert [item[0] for item in owned.transport.called] == [item[0] for item in owned.routes[:len(owned.transport.called)]]
    assert len(owned.transport.called) == offset + (2 if offset == 24 else 1)


def test_valid_explicit_zero_stops_without_positive_capture(owned):
    owned.routes[1][1].entity = (listing('forterra', 0, []),)
    with pytest.raises(owned.module.oracle.CaptureError, match='empty inventory'):
        collect(owned)
    assert len(owned.transport.called) == 2


@pytest.mark.parametrize(('budget', 'limit', 'reason', 'calls'), [
    ('live_request_limit', 2, 'request budget', 2),
    ('capsule_bytes_limit', 20, 'header or capsule', 1),
    ('capsule_bytes_limit', 30_000, 'capsule byte limit', 31),
])
def test_request_and_combined_byte_limits_hold(owned, budget, limit, reason, calls):
    owned.binding[budget] = limit
    with pytest.raises(owned.module.oracle.CaptureError, match=reason):
        collect(owned)
    assert len(owned.transport.called) == calls
    assert len(owned.ledger.read_attempts()) == calls


def test_entity_limit_and_policy_pin(owned):
    owned.policy['entity_bytes_limit'] = 2
    with pytest.raises(owned.module.oracle.CaptureError, match='enrolled policy'):
        collect(owned)
    assert not owned.transport.called
    owned.binding['collector_policy_sha256'] = owned.module.digest(owned.policy)
    with pytest.raises(owned.module.oracle.CaptureError, match='entity or capsule'):
        collect(owned)
    assert owned.transport.called[0][1]['max_entity_bytes'] == 2
    assert len(owned.ledger.read_attempts()) == 1


def test_durable_append_refusal_prevents_transport(owned, monkeypatch):
    monkeypatch.setattr(owned.ledger, 'begin_attempt', lambda attempt: replace(attempt, sequence=3))
    with pytest.raises(owned.module.oracle.CaptureError, match='attempt did not durably read back'):
        collect(owned)
    assert not owned.transport.called


@pytest.mark.parametrize('changed', ['dispatch', 'nested_candidate'])
def test_binding_change_after_durable_completion_holds_without_more_reads(owned, monkeypatch, changed):
    initial = deepcopy(owned.binding)
    finish = owned.ledger.finish_attempt

    def complete_then_change(attempt, receipt):
        confirmed = finish(attempt, receipt)
        if changed == 'dispatch':
            owned.binding['dispatch_sha256'] = 'a' * 64
        else:
            owned.binding['candidate']['config_sha256'] = 'b' * 64
        return confirmed

    monkeypatch.setattr(owned.ledger, 'finish_attempt', complete_then_change)
    with pytest.raises(owned.module.oracle.CaptureError, match='enrolled public capture inputs changed'):
        collect(owned)
    assert len(owned.transport.called) == 1
    attempts = owned.ledger.read_attempts()
    assert len(attempts) == 1 and attempts[0][1] is not None
    owned.binding.update(initial)
    with pytest.raises(owned.module.oracle.CaptureError, match='already attempted'):
        collect(owned)
    assert owned.ledger.read_attempts() == attempts
    assert len(owned.transport.called) == 1


def test_limits_changed_during_durable_append_prevent_transport(owned, monkeypatch):
    begin = owned.ledger.begin_attempt

    def append_then_change(attempt):
        confirmed = begin(attempt)
        owned.binding['live_request_limit'] += 1
        return confirmed

    monkeypatch.setattr(owned.ledger, 'begin_attempt', append_then_change)
    with pytest.raises(owned.module.oracle.CaptureError, match='enrolled public capture inputs changed'):
        collect(owned)
    assert not owned.transport.called
    assert [receipt for _, receipt in owned.ledger.read_attempts()] == [None]


def test_input_drift_during_final_ledger_read_prevents_handoff(owned, monkeypatch):
    read = owned.ledger.read_attempts

    def read_then_change():
        records = read()
        if len(records) == 31 and all(receipt for _, receipt in records):
            owned.companies[1]['Company'] = 'PDW'
        return records

    monkeypatch.setattr(owned.ledger, 'read_attempts', read_then_change)
    with pytest.raises(owned.module.oracle.CaptureError, match='enrolled public capture inputs changed'):
        collect(owned)
    assert len(owned.transport.called) == 31
    assert all(receipt is not None for _, receipt in read())


def test_ledger_drift_holds_before_replay_handoff(owned, monkeypatch):
    read = owned.ledger.read_attempts
    original_clock = owned.clock
    # The post-final-page check is the last clock read before the ledger handoff.
    def final_ledger():
        return read()[:-1]

    def clock_with_drift():
        if len(owned.transport.called) == 31 and all(receipt for _, receipt in read()):
            monkeypatch.setattr(owned.ledger, 'read_attempts', final_ledger)
        return original_clock()

    owned.clock = clock_with_drift
    with pytest.raises(owned.module.oracle.CaptureError, match='ledger changed'):
        collect(owned)
    assert len(owned.transport.called) == 31


def test_elapsed_expiry_during_entity_read_preserves_unfinished_attempt(owned):
    elapsed = ELAPSED

    def stream():
        nonlocal elapsed
        elapsed = owned.window.deadline_elapsed_ns
        yield b'withheld'

    owned.routes[0][1].entity = stream()
    owned.clock = lambda: (BOOT, NOW, elapsed)
    with pytest.raises(owned.module.oracle.CaptureError, match='clock changed or its deadline expired'):
        collect(owned)
    assert len(owned.transport.called) == 1
    assert owned.ledger.read_attempts()[0][1] is None


def test_stream_failure_preserves_unfinished_attempt_and_never_retries(owned):
    def stream():
        yield b'partial entity'
        raise OSError('simulated transfer failure')

    owned.routes[0][1].entity = stream()
    with pytest.raises(owned.module.oracle.CaptureError, match='did not complete'):
        collect(owned)
    assert len(owned.transport.called) == 1
    assert owned.ledger.read_attempts()[0][1] is None


def test_wall_rollback_between_durable_append_and_transport_holds(owned):
    owned.clock = lambda: (BOOT, NOW - bool(owned.ledger.read_attempts()), ELAPSED)
    with pytest.raises(owned.module.oracle.CaptureError, match='clock changed'):
        collect(owned)
    assert not owned.transport.called
    assert len(owned.ledger.read_attempts()) == 1


def test_expiry_during_final_ledger_read_prevents_handoff(owned, monkeypatch):
    read = owned.ledger.read_attempts
    elapsed = ELAPSED

    def expire_after_readback():
        nonlocal elapsed
        records = read()
        if len(records) == 31 and all(receipt for _, receipt in records):
            elapsed = owned.window.deadline_elapsed_ns
        return records

    monkeypatch.setattr(owned.ledger, 'read_attempts', expire_after_readback)
    owned.clock = lambda: (BOOT, NOW, elapsed)
    with pytest.raises(owned.module.oracle.CaptureError, match='deadline expired'):
        collect(owned)
    assert len(owned.transport.called) == 31
    assert all(receipt is not None for _, receipt in read())


def test_foreign_company_never_opens_transport_or_spends_attempt(owned):
    owned.companies[1]['Company'] = 'PDW'
    with pytest.raises(owned.module.oracle.CaptureError, match='enrolled projection'):
        collect(owned)
    assert not owned.transport.called
    assert not owned.ledger.read_attempts()
