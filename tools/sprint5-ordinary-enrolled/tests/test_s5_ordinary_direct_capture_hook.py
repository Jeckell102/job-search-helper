"""Private direct observation fixtures with an in-memory urllib HTTPS handler."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import copy_context
from email.message import Message
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import ssl
from urllib.request import HTTPSHandler
from urllib.response import addinfourl

import pytest

import job_search_helper

OVERLAY = Path(__file__).resolve().parents[1] / 'src/job_search_helper'
CUSTODY = Path('/tmp/jsh-s5-ordinary-raw-capture-custody.WFtLV5HK/src/job_search_helper')
job_search_helper.__path__[:0] = [str(OVERLAY), str(CUSTODY)]
from job_search_helper import shared_boards
from job_search_helper.ats import HTTPResponse, Inventory, RipplingTenantMismatch, fetch_inventory
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.engine import inventory_payload
from job_search_helper.ordinary_capture_context import bind_direct_capture, capture_policy_sha256
from job_search_helper.ordinary_raw_capture import CaptureError, open_custody
from job_search_helper.ordinary_verification_pending import SCHEMA, digest


ORIGIN = 'https://www.forterra.example/careers'
CONFIGURED = 'https://ats.rippling.com/retired-fixture/jobs'
FOREIGN = 'unrelated-tenant'
EXPECTED = 'retired-fixture'
COMPANY = 'Forterra'
CID = 'COMP-0066'
SOURCE = '8' * 64
PRIVATE_SENTINEL = b'<!doctype html>\r\n<!-- synthetic custody marker -->\r\n'


def listing(slug, page=0, count=0):
    filters = {'searchQuery': '', 'departments': [], 'workplaceType': None, 'country': '',
               'state': '', 'city': '', 'page': page, 'pageSize': 20}
    rows = [{'id': f'00000000-0000-4000-8000-{index:012x}', 'name': 'Synthetic posting'}
            for index in range(page * 20, min(count, page * 20 + 20))]
    record = {'props': {'pageProps': {'apiData': {'jobBoardSlug': slug, 'jobBoard': {'slug': slug}},
              'dehydratedState': {'queries': [{'queryKey': ['board', slug, 'job-posts', True, filters, 'en-US'],
              'state': {'data': {'totalItems': count, 'totalPages': (count + 19) // 20, 'page': page,
                                 'pageSize': 20, 'items': rows}}}]}}}}
    return PRIVATE_SENTINEL + b'<script type="application/json" id="__NEXT_DATA__">' + json.dumps(record).encode() + b'</script>\r\n'


BODY = listing(FOREIGN, count=1)


@pytest.fixture(autouse=True)
def closed_network(monkeypatch):
    from job_search_helper.company_sources import REPAIRS

    def deny(*args, **kwargs):
        pytest.fail('No network path is allowed in this fixture')

    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy',
                 'all_proxy', 'no_proxy', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'SSLKEYLOGFILE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(socket.socket, 'connect_ex', deny)
    monkeypatch.setattr(socket, 'getaddrinfo', deny)
    monkeypatch.setattr(socket, 'create_connection', deny)
    monkeypatch.setitem(REPAIRS, CID, {'company': COMPANY, 'expected_url': ORIGIN, 'ats': 'Rippling',
                                      'url': CONFIGURED, 'evidence': 'synthetic direct-hook fixture'})


@pytest.fixture
def wire(monkeypatch):
    """Intercept the HTTPS handler below the real Transport and opener policy."""
    responses, requests = [], []

    def https_open(handler, request):
        tls = handler._context
        requests.append({'url': request.full_url, 'host': request.host, 'method': request.get_method(),
                         'encoding': request.get_header('Accept-encoding'), 'tls': tls,
                         'tunnel': getattr(request, '_tunnel_host', None)})
        assert responses, 'Unexpected request beyond the local fixture sequence'
        spec = responses.pop(0)
        headers = Message()
        for key, value in spec.get('headers', {}).items():
            headers[key] = value
        result = addinfourl(BytesIO(spec.get('body', BODY)), headers, spec.get('url', request.full_url), spec.get('status', 200))
        result.msg = 'Local HTTPS response fixture'
        return result

    monkeypatch.setattr(HTTPSHandler, 'https_open', https_open)
    return responses, requests


def armed(generation):
    return {'schema': SCHEMA, 'state': 'ARMED', 'owner': {
        'cycle_id': 'CYC-000000000001', 'cycle_started_at': '2026-11-20T18:13:00+00:00',
        'request_id': 'SCAN-001', 'request_fingerprint': '1' * 64, 'company_id': CID,
        'source_revision': '2' * 64, 'company_source_sha256': '3' * 64,
        'store_binding_sha256': '4' * 64, 'observation_generation': generation,
    }, 'admission': {
        'authority_url': ORIGIN, 'configured_url': CONFIGURED, 'capability_id': 'rippling-shared-v1',
        'capability_digest': '5' * 64, 'mapping_digest': '6' * 64, 'configuration_digest': '7' * 64,
        'matrix_digest': '9' * 64, 'runtime_binding_sha256': 'a' * 64,
    }}


@contextmanager
def reserved(tmp_path, *, generation=1, policy=None):
    root = tmp_path / 'custody'
    root.mkdir(mode=0o700, exist_ok=True)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    dispatch = armed(generation)
    pins = {'source_manifest_sha256': SOURCE,
            'capture_policy_sha256': capture_policy_sha256() if policy is None else policy}
    try:
        with open_custody(root, root_fd) as custody, custody.reserve(dispatch, digest(dispatch), **pins) as ticket:
            yield (root, dispatch, pins, custody, ticket)
    finally:
        os.close(root_fd)


def current_fetch(**kwargs):
    return fetch_inventory('Rippling', ORIGIN, CID, COMPANY, **kwargs)


def seal(reservation, inventory):
    root, arm, pins, custody, ticket = reservation
    payload = inventory_payload(inventory, {'Company ID': CID, 'Official Careers URL': ORIGIN})
    manifest = ticket.seal(inventory, payload)
    prepared = {**arm, 'state': 'PREPARED', 'dispatch_sha256': digest(arm),
                'inventory_sha256': digest(payload), 'failure': None,
                'observation': inventory.rippling_tenant_mismatch.to_record()}
    result = custody.read_prepared(prepared, payload, blocked=False, **pins)
    assert result.manifest_sha256 == manifest
    return result, payload, root / digest(arm)


def test_scoped_opener_uses_verified_tls_without_proxy_or_key_logging(tmp_path, wire, monkeypatch):
    responses, requests = wire
    keylog = tmp_path / 'must-not-be-created.keylog'
    monkeypatch.setenv('https_proxy', 'http://not-an-approved-proxy.example:8081')
    monkeypatch.setenv('SSLKEYLOGFILE', str(keylog))
    responses.append({})
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        assert set(p.name for p in (reservation[0] / digest(reservation[1])).iterdir()) == {'reservation.json'}
        result, payload, _ = seal(reservation, inventory)
        assert result.body == BODY and result.response_sha256 == sha256(BODY).hexdigest()
        assert 'rippling_tenant_mismatch' not in payload and 'response_sha256' not in json.dumps(payload)
        assert PRIVATE_SENTINEL not in json.dumps(payload).encode()
        assert not keylog.exists()
    assert len(requests) == 1
    request, = requests
    assert request['url'] == CONFIGURED and request['method'] == 'GET' and request['encoding'] == 'identity'
    assert request['host'] == 'ats.rippling.com' and request['tunnel'] is None
    assert request['tls'].check_hostname and request['tls'].verify_mode == ssl.CERT_REQUIRED
    assert request['tls'].keylog_filename is None


def test_default_opener_preserves_ambient_proxy_behavior(tmp_path, wire, monkeypatch):
    responses, requests = wire
    monkeypatch.setenv('https_proxy', 'http://ordinary-proxy.example:8082')
    responses.append({})
    inventory = current_fetch()
    assert inventory.rippling_tenant_mismatch is not None
    request, = requests
    assert request['host'] == 'ordinary-proxy.example:8082' and request['tunnel'] == 'ats.rippling.com'
    assert request['tls'] is None


@pytest.mark.parametrize('override', ['SSL_CERT_FILE', 'SSL_CERT_DIR'])
def test_ca_override_never_attests_a_response(tmp_path, wire, monkeypatch, override):
    responses, requests = wire
    responses.append({})
    monkeypatch.setenv(override, '/tmp/ambient-ca-fixture')
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        assert inventory.rippling_tenant_mismatch is not None
        with pytest.raises(CaptureError, match='observation_not_owned'):
            reservation[-1].seal(inventory, inventory_payload(inventory, {'Official Careers URL': ORIGIN}))
    assert len(requests) == 1 and requests[0]['tls'] is None


def test_scoped_tls_loads_only_compiled_ca_paths(tmp_path, wire, monkeypatch):
    responses, requests = wire
    responses.append({})
    paths = ssl.get_default_verify_paths()
    selected = paths._replace(cafile='/tmp/unapproved-ca.pem', capath='/tmp/unapproved-ca')
    load_original = ssl.SSLContext.load_verify_locations
    loads = []

    def load_locations(context, *, cafile, capath):
        loads.append((cafile, capath))
        with monkeypatch.context() as ambient:
            ambient.setenv('SSL_CERT_FILE', selected.cafile)
            ambient.setenv('SSL_CERT_DIR', selected.capath)
            return load_original(context, cafile=cafile, capath=capath)

    monkeypatch.setattr(ssl, 'get_default_verify_paths', lambda: selected)
    monkeypatch.setattr(ssl.SSLContext, 'load_verify_locations', load_locations)
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        assert seal(reservation, inventory)[0].body == BODY
    assert loads == [(paths.openssl_cafile if Path(paths.openssl_cafile).is_file() else None,
                      paths.openssl_capath if Path(paths.openssl_capath).is_dir() else None)]
    assert len(requests) == 1 and requests[0]['tls'].verify_mode == ssl.CERT_REQUIRED


@pytest.mark.parametrize('header', ['Location', 'Refresh'])
def test_200_redirect_indicators_never_supply_capture(tmp_path, wire, header):
    responses, requests = wire
    responses.append({'headers': {header: '/other/jobs'}})
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        assert inventory.rippling_tenant_mismatch is not None
        with pytest.raises(CaptureError, match='observation_not_owned'):
            reservation[-1].seal(inventory, inventory_payload(inventory, {'Official Careers URL': ORIGIN}))
    assert len(requests) == 1


def test_scoped_redirect_is_not_followed(tmp_path, wire):
    responses, requests = wire
    responses.append({'status': 302, 'headers': {'Location': CONFIGURED + '/other'}})
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        assert inventory.rippling_tenant_mismatch is None
        assert reservation[-1].seal(inventory, {}) is None
    assert [request['url'] for request in requests] == [CONFIGURED]


@pytest.mark.parametrize('kind', ['injected', 'subclass', 'falsey', 'replaced_factory', 'patched_request'])
def test_unreviewed_transport_never_supplies_capture(tmp_path, wire, monkeypatch, kind):
    responses, requests = wire
    original = shared_boards.Transport
    board = shared_boards.board_link(CONFIGURED)
    parameters = {}
    if kind == 'injected':
        parameters['transport'] = original(board)
        responses.append({})
    elif kind == 'subclass':
        class CallerTransport(original):
            pass
        parameters['transport'] = CallerTransport(board)
        responses.append({})
    elif kind == 'falsey':
        class FalseyTransport(original):
            def __bool__(self):
                return False
        parameters['transport'] = FalseyTransport(board)
        responses.append({})
    elif kind == 'replaced_factory':
        monkeypatch.setattr(shared_boards, 'Transport', lambda selected: original(selected))
        responses.append({})
    else:
        monkeypatch.setattr(original, 'request', lambda *a: HTTPResponse(200, BODY, response_url=CONFIGURED))
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch(**parameters)
        assert inventory.rippling_tenant_mismatch is not None
        with pytest.raises(CaptureError, match='observation_not_owned'):
            reservation[-1].seal(inventory, inventory_payload(inventory, {'Official Careers URL': ORIGIN}))
    assert all(request['tls'] is None for request in requests)


def test_preselected_transport_cannot_carry_proof_into_an_explicit_call(tmp_path, wire, monkeypatch):
    responses, requests = wire
    responses.append({})
    selected = []

    def skip_download(board, transport, *args, **kwargs):
        selected.append(transport)
        return Inventory('partial', ats='Rippling')

    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            with monkeypatch.context() as temporary:
                temporary.setattr(shared_boards, '_fetch', skip_download)
                assert current_fetch().rippling_tenant_mismatch is None
            inventory = current_fetch(transport=selected[0])
        assert inventory.rippling_tenant_mismatch is not None
        with pytest.raises(CaptureError, match='observation_not_owned'):
            reservation[-1].seal(inventory, inventory_payload(inventory, {'Official Careers URL': ORIGIN}))
    assert len(requests) == 1 and requests[0]['tls'] is None


@pytest.mark.parametrize('changed', ['body', 'headers'])
def test_altered_httpresponse_does_not_supply_original_capture(tmp_path, wire, monkeypatch, changed):
    responses, requests = wire
    responses.append({})
    get_original = shared_boards.Transport.get
    foreign_bytes = BODY + b'<!-- replacement after the actual response -->'

    def alter(transport, url):
        result = get_original(transport, url)
        if changed == 'body':
            result.body = foreign_bytes
        else:
            result.headers['Location'] = '/other/jobs'
        return result

    monkeypatch.setattr(shared_boards.Transport, 'get', alter)
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        expected_body = foreign_bytes if changed == 'body' else BODY
        assert inventory.rippling_tenant_mismatch.response_sha256 == sha256(expected_body).hexdigest()
        with pytest.raises(CaptureError, match='observation_not_owned'):
            reservation[-1].seal(inventory, inventory_payload(inventory, {'Official Careers URL': ORIGIN}))
    assert len(requests) == 1 and requests[0]['tls'] is not None


@pytest.mark.parametrize('second', ['later_page', 'reread'])
def test_later_or_reread_mismatch_is_not_a_capture(tmp_path, wire, second):
    responses, requests = wire
    count = 21 if second == 'later_page' else 0
    responses.extend([{'body': listing(EXPECTED, count=count)}, {}])
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = current_fetch()
        assert inventory.rippling_tenant_mismatch is None
        assert reservation[-1].seal(inventory, {}) is None
    second_url = CONFIGURED + '?page=1' if second == 'later_page' else CONFIGURED
    assert [request['url'] for request in requests] == [CONFIGURED, second_url]
    assert requests[0]['tls'] is not None and requests[1]['tls'] is None


def test_noncanonical_source_does_not_claim_exact_ticket(tmp_path, wire):
    responses, requests = wire
    responses.extend([{}, {}])
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            alias = fetch_inventory('Rippling', CONFIGURED + '?page=0', CID, COMPANY)
            exact = current_fetch()
        assert alias.rippling_tenant_mismatch is None
        assert seal(reservation, exact)[0].body == BODY
    assert [request['tls'] is not None for request in requests] == [False, True]


def test_stale_context_copy_and_ticket_rebinding_hold(tmp_path, wire):
    responses, requests = wire
    responses.append({})
    with reserved(tmp_path) as reservation:
        ticket = reservation[-1]
        with bind_direct_capture(ticket):
            saved = copy_context()
        stale = saved.run(current_fetch)
        assert stale.rippling_tenant_mismatch is not None and requests[0]['tls'] is None
        with pytest.raises(ValueError, match='already used'):
            with bind_direct_capture(ticket):
                pytest.fail('A ticket may be bound only once')
        with pytest.raises(CaptureError, match='observation_not_owned'):
            ticket.seal(stale, inventory_payload(stale, {'Official Careers URL': ORIGIN}))


def test_live_copy_on_another_thread_cannot_claim_private_ticket(tmp_path, wire):
    responses, requests = wire
    responses.extend([{}, {}])
    with reserved(tmp_path) as reservation, ThreadPoolExecutor(1) as pool:
        with bind_direct_capture(reservation[-1]):
            copied = copy_context()
            unrelated = pool.submit(copied.run, current_fetch).result(timeout=5)
            owned = current_fetch()
        assert unrelated.rippling_tenant_mismatch is not None
        assert seal(reservation, owned)[0].body == BODY
    assert [request['tls'] is not None for request in requests] == [False, True]


def test_nested_distinct_scopes_restore_exact_outer_ticket(tmp_path, wire):
    responses, requests = wire
    responses.extend([{}, {}])
    with reserved(tmp_path) as outer, reserved(tmp_path, generation=2) as inner:
        with bind_direct_capture(outer[-1]):
            with bind_direct_capture(inner[-1]):
                inner_result = current_fetch()
            outer_result = current_fetch()
        assert seal(inner, inner_result)[0].body == BODY
        assert seal(outer, outer_result)[0].body == BODY
    assert len(requests) == 2 and all(request['tls'] is not None for request in requests)


def test_policy_mismatch_and_wrong_ticket_rejected_before_network(tmp_path, wire):
    responses, requests = wire
    assert capture_policy_sha256() == '6194f04b9112c7677b1502b4fdf68fd7d8ba938de5a00dd52c8242423facddb3'
    with reserved(tmp_path, policy='b' * 64) as reservation:
        for ticket in (object(), reservation[-1]):
            with pytest.raises(ValueError, match='current policy'):
                with bind_direct_capture(ticket):
                    pytest.fail('Invalid policy or ticket must not enter capture context')
    assert not requests


@pytest.mark.parametrize('browser_outcome', ['corroborated', 'blocked', 'complete'])
def test_browser_final_selection_preserves_existing_precedence_without_capture(tmp_path, wire, monkeypatch, browser_outcome):
    responses, requests = wire
    responses.append({})
    browser_calls = []
    browser_body = BODY + b'<!-- unrelated browser encoding -->'

    def browser(*args, **kwargs):
        browser_calls.append(args)
        if browser_outcome != 'corroborated':
            return Inventory(browser_outcome, ats='Rippling')
        observation = RipplingTenantMismatch(CONFIGURED, EXPECTED, FOREIGN, sha256(browser_body).hexdigest())
        return Inventory('partial', ats='Rippling', source_url=CONFIGURED, rippling_tenant_mismatch=observation)

    monkeypatch.setattr(shared_boards, 'fetch_shared_browser', browser)
    with reserved(tmp_path) as reservation:
        with bind_direct_capture(reservation[-1]):
            inventory = with_browser_fallback(fetch_inventory)('Rippling', ORIGIN, CID, COMPANY)
        assert len(browser_calls) == 1 and len(requests) == 1
        if browser_outcome == 'corroborated':
            assert seal(reservation, inventory)[0].body == BODY
        else:
            assert inventory.status == browser_outcome and inventory.rippling_tenant_mismatch is None
            assert reservation[-1].seal(inventory, {}) is None
