"""Use scripted socket/TLS I/O only; no DNS lookups or network connections."""

import errno
from types import SimpleNamespace

import pytest

import rippling_public_transport as transport
from test_s5_rippling_public_capture import collect, owned


DEADLINE = 10_000_000_000
SELECTED = {
    'www.forterra.com': '11.0.0.1',
    'www.pdw.ai': '11.0.0.2',
    'ats.rippling.com': '2001:4860::10',
}
FOR = transport.authority.FORTERRA_CAREERS
PDW = transport.authority.PDW_ALIAS
BOARD = transport.authority.FORTERRA_BOARD
LIMITS = {'deadline_elapsed_ns': DEADLINE, 'max_response_bytes': 1024,
          'max_header_bytes': 256, 'max_entity_bytes': 256}


class _Raw:
    def __init__(self, network, family, kind, protocol):
        self.network = network
        self.socket_type = (family, kind, protocol)
        self.addresses = []
        self.blocking = None
        self.closed = False

    def setblocking(self, value):
        self.blocking = value

    def connect_ex(self, address):
        assert self.blocking is False
        self.addresses.append(address)
        return self.network.connect_result

    def getsockopt(self, level, name):
        assert (level, name) == (transport.socket.SOL_SOCKET, transport.socket.SO_ERROR)
        return self.network.connect_error

    def close(self):
        self.closed = True


class _TLS:
    def __init__(self, network, wire):
        self.network = network
        self.wire = wire
        self.received = 0
        self.sent = bytearray()
        self.closed = False

    def _pause(self, phase):
        if self.network.pause == phase:
            error = transport.ssl.SSLWantWriteError if phase == 'send' else transport.ssl.SSLWantReadError
            raise error('synthetic pending I/O')

    def do_handshake(self):
        self._pause('handshake')
        if self.network.handshake_error is not None:
            raise self.network.handshake_error

    def selected_alpn_protocol(self):
        return self.network.alpn

    def send(self, data):
        self._pause('send')
        size = min(17, len(data))
        self.sent.extend(data[:size])
        return size

    def recv(self, count):
        boundary = self.wire.find(b'\r\n\r\n') + 4
        self._pause('headers' if self.received < boundary else 'entity')
        data = self.wire[self.received:self.received + count]
        self.received += len(data)
        return data

    def close(self):
        self.closed = True
        if self.network.expire_on_close is not None:
            self.network.now = self.network.expire_on_close


class _Network:
    def __init__(self):
        self.responses = []
        self.raw = []
        self.tls = []
        self.wrapping = []
        self.waits = []
        self.now = 0
        self.connect_result = 0
        self.connect_error = 0
        self.alpn = 'http/1.1'
        self.handshake_error = None
        self.pause = None
        self.expire_on_wait = None
        self.expire_on_close = None

    def socket(self, family, kind, protocol):
        channel = _Raw(self, family, kind, protocol)
        self.raw.append(channel)
        return channel

    def wrap_socket(self, raw, **options):
        assert raw is self.raw[-1]
        self.wrapping.append(options)
        channel = _TLS(self, self.responses.pop(0))
        self.tls.append(channel)
        return channel

    def select(self, readable, writable, errors, timeout):
        assert not errors and bool(readable) != bool(writable)
        assert 0 < timeout <= 0.1
        self.waits.append((bool(readable), bool(writable)))
        if self.expire_on_wait is not None:
            self.now = self.expire_on_wait
            return [], [], []
        self.pause = None
        return readable, writable, []


@pytest.fixture
def network(monkeypatch):
    fake = _Network()
    monkeypatch.setattr(transport.socket, 'socket', fake.socket)
    monkeypatch.setattr(transport.socket, 'getaddrinfo', lambda *args: pytest.fail('Unexpected DNS lookup'))
    monkeypatch.setattr(transport, '_verified_tls', lambda: fake)
    monkeypatch.setattr(transport.select, 'select', fake.select)
    monkeypatch.setattr(transport.time, 'clock_gettime_ns', lambda clock: fake.now)
    return fake


def _header(fields=(), *, status=200):
    return (f'HTTP/1.1 {status}\r\n'.encode() + b''.join(line + b'\r\n' for line in fields) + b'\r\n')


def _get(url=FOR, **limits):
    adapter = transport.PublicCaptureTransport(SELECTED)
    with adapter.open_get(url, **{**LIMITS, **limits}) as response:
        entity = b''.join(response.entity)
    return response, entity


def test_direct_get_preserves_exact_informational_and_final_headers_and_entity(network):
    early = _header([b'Link: </fixture.css>; rel=preload'], status=103)
    final = _header([b'Content-Length: 5', b'X-Witness: \xe9', b'x-witness:\tsecond',
                     b'Content-Encoding: identity'])
    network.responses = [early + final + b'\xe2\x98\x83\r\n']

    response, body = _get()
    assert (response.final_url, response.status, response.headers, body) == (FOR, 200, early + final,
                                                                             b'\xe2\x98\x83\r\n')
    raw, = network.raw
    secured, = network.tls
    assert raw.addresses == [('11.0.0.1', 443)]
    assert network.wrapping == [{'server_hostname': 'www.forterra.com',
                                 'do_handshake_on_connect': False, 'suppress_ragged_eofs': False}]
    assert secured.sent == (b'GET /careers HTTP/1.1\r\nHost: www.forterra.com\r\nUser-Agent: JobSearchHelper/1.0\r\n'
                            b'Accept-Encoding: identity\r\nConnection: close\r\n\r\n')
    assert raw.closed and secured.closed


def test_chunked_alias_returns_only_entity_and_does_not_follow_location(network):
    raw = _header([b'Transfer-Encoding: chunked', b'Location: /pdwcareers/jobs',
                   b'Refresh: 0;url=/pdwcareers/jobs'], status=308)
    network.responses = [raw + b'3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n']

    response, body = _get(PDW)
    assert (response.final_url, response.status, response.headers, body) == (PDW, 308, raw, b'abcde')
    assert network.raw[0].addresses == [('2001:4860::10', 443, 0, 0)]
    assert network.wrapping[0]['server_hostname'] == 'ats.rippling.com'
    assert network.tls[0].sent.startswith(b'GET /pdwcareers HTTP/1.1\r\n')
    assert len(network.raw) == len(network.tls) == 1


@pytest.mark.parametrize('url', [
    'https://ats.rippling.com/other/jobs',
    'https://www.forterra.com:443/careers',
    'https://www.forterra.com/careers#extra',
    'https://ats.rippling.com@www.forterra.com/careers',
    BOARD + '?page=0',
    BOARD + '?page=01',
    BOARD + '?page=500',
    BOARD + '?page=2&other=true',
    BOARD + '/%30',
    BOARD + '/00000000-0000-0000-0000-00000000000A',
])
def test_foreign_or_noncanonical_url_refuses_before_socket(network, url):
    with pytest.raises(transport.CaptureError, match='outside the reviewed routes'):
        _get(url)
    assert not network.raw


@pytest.mark.parametrize('address', [
    '127.0.0.1', '169.254.1.2', '::ffff:11.0.0.1', '2002:b00:1::', 'hostname.invalid',
])
def test_scope_requires_an_approved_numeric_public_endpoint(network, address):
    with pytest.raises(transport.CaptureError, match='selected numeric address|canonical public address'):
        transport.PublicCaptureTransport({**SELECTED, 'www.forterra.com': address})
    assert not network.raw


@pytest.mark.parametrize(('fields', 'body', 'error'), [
    ([b'Content-Length: 5'], b'ab', 'ended before'),
    ([b'Content-Length: 2', b'content-length: 2'], b'ab', 'one explicit valid content length'),
    ([b'Content-Length: 2', b'Transfer-Encoding: chunked'], b'ab', 'unsupported transfer framing'),
    ([b'Content-Length: 2', b'Content-Encoding: gzip'], b'ab', 'identity content encoding'),
    ([], b'ab', 'one explicit valid content length'),
    ([b'Transfer-Encoding: chunked'], b'2\r\na', 'ended before'),
    ([b'Transfer-Encoding: chunked'], b'2\r\nab\r\n0\r\n', 'ended before'),
    ([b'Transfer-Encoding: chunked'], b'2;test=1\r\nab\r\n0\r\n\r\n', 'unsupported chunk framing'),
    ([b'Transfer-Encoding: chunked'], b'0\r\nX-Witness: extra\r\n\r\n', 'framing byte limit'),
    ([b'Transfer-Encoding: chunked', b'Trailer: X-Witness'], b'0\r\n\r\n', 'unsupported transfer framing'),
])
def test_ambiguous_partial_or_unsupported_framing_holds(network, fields, body, error):
    network.responses = [_header(fields) + body]
    with pytest.raises(transport.CaptureError, match=error):
        _get()
    assert len(network.raw) == len(network.tls) == 1
    assert all(channel.closed for channel in (*network.raw, *network.tls))


@pytest.mark.parametrize(('url', 'wire', 'error'), [
    (FOR, _header([b'Location: /careers', b'Content-Length: 0'], status=301), 'HTTP status'),
    (FOR, _header([b'Content-Length: 1'], status=103) + _header([b'Content-Length: 0']),
     'informational status'),
    (PDW, _header([b'Content-Length: 0', b'Location: /forterra/jobs'], status=308), 'redirect evidence'),
])
def test_status_or_redirect_drift_never_issues_another_get(network, url, wire, error):
    network.responses = [wire]
    with pytest.raises(transport.CaptureError, match=error):
        _get(url)
    assert len(network.raw) == 1
    assert network.tls[0].sent.count(b'GET ') == 1


@pytest.mark.parametrize(('changes', 'read_bytes'), [
    ({'max_header_bytes': 20}, 20),
    ({'max_entity_bytes': 3}, None),
    ({'max_response_bytes': 50, 'max_header_bytes': 50, 'max_entity_bytes': 50}, None),
])
def test_header_entity_and_combined_caps_apply_before_reading_excess(network, changes, read_bytes):
    raw = _header([b'Content-Length: 4', b'X-Test: raw'])
    assert len(raw) < 50 < len(raw) + 4
    network.responses = [raw + b'abcd']
    with pytest.raises(transport.CaptureError, match='byte limit'):
        _get(**changes)
    assert network.tls[0].received == (len(raw) if read_bytes is None else read_bytes)


@pytest.mark.parametrize('phase', ['connection', 'handshake', 'send', 'headers', 'entity'])
def test_elapsed_deadline_stops_nonblocking_wait_in_each_io_phase(network, phase):
    network.responses = [_header([b'Content-Length: 4']) + b'abcd']
    network.expire_on_wait = DEADLINE
    if phase == 'connection':
        network.connect_result = errno.EINPROGRESS
    else:
        network.pause = phase
    with pytest.raises(transport.CaptureError, match='elapsed deadline expired'):
        _get()
    assert len(network.raw) == 1 and network.raw[0].closed
    assert len(network.waits) == 1
    assert all(channel.closed for channel in network.tls)


def test_already_expired_deadline_cannot_open_socket(network):
    network.now = DEADLINE
    with pytest.raises(transport.CaptureError, match='elapsed deadline expired'):
        _get()
    assert not network.raw


def test_deadline_during_final_socket_cleanup_holds_completion(network):
    network.responses = [_header([b'Content-Length: 3']) + b'abc']
    network.expire_on_close = DEADLINE
    with pytest.raises(transport.CaptureError, match='elapsed deadline expired'):
        _get()
    assert network.raw[0].closed and network.tls[0].closed


def test_pending_connect_and_tls_handshake_can_progress_without_redial(network):
    network.responses = [_header([b'Content-Length: 3']) + b'abc']
    network.connect_result = errno.EINPROGRESS
    select = network.select

    def pause_after_connect(readable, writable, errors, timeout):
        ready = select(readable, writable, errors, timeout)
        if len(network.waits) == 1:
            network.pause = 'handshake'
        return ready

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(transport.select, 'select', pause_after_connect)
        assert _get()[1] == b'abc'
    assert network.waits == [(False, True), (True, False)]
    assert len(network.raw) == 1 and network.tls[0].sent.count(b'GET ') == 1


def test_certificate_failure_closes_connection_without_sending_get(network):
    network.responses = [b'']
    network.handshake_error = transport.ssl.SSLCertVerificationError('synthetic verification failure')
    with pytest.raises(transport.ssl.SSLCertVerificationError):
        _get()
    assert len(network.raw) == 1
    assert not network.tls[0].sent and network.tls[0].closed


def test_chunk_budget_and_cumulative_framing_cap(network, monkeypatch):
    header = _header([b'Transfer-Encoding: chunked'])
    network.responses = [header + b'4\r\nabcd\r\n0\r\n\r\n']
    with pytest.raises(transport.CaptureError, match='entity or combined byte limit'):
        _get(max_entity_bytes=3)
    assert network.tls[0].received == len(header) + len(b'4\r\n')

    monkeypatch.setattr(transport, '_MAX_CHUNK_FRAMING_BYTES', 9)
    network.responses = [header + b'1\r\na\r\n0\r\n\r\n']
    with pytest.raises(transport.CaptureError, match='chunk framing or trailers'):
        _get()
    assert network.tls[1].received == len(header) + len(b'1\r\na\r\n0\r\n')


def test_failed_dial_and_bad_alpn_do_not_send_or_retry(network):
    network.connect_result = errno.EINPROGRESS
    network.connect_error = errno.ECONNREFUSED
    with pytest.raises(transport.CaptureError, match='direct connection failed'):
        _get()
    assert len(network.raw) == 1
    assert not network.tls

    network.connect_error = 0
    network.alpn = 'h2'
    network.responses = [_header([b'Content-Length: 0'])]
    with pytest.raises(transport.CaptureError, match='unsupported protocol'):
        _get()
    assert len(network.raw) == 2 and len(network.tls) == 1
    assert not network.tls[0].sent


def test_context_requires_consumption_and_closes_the_unread_socket(network):
    network.responses = [_header([b'Content-Length: 4']) + b'abcd']
    with pytest.raises(transport.CaptureError, match='not completely consumed'):
        with transport.PublicCaptureTransport(SELECTED).open_get(FOR, **LIMITS):
            pass
    assert network.tls[0].closed


def test_tls_uses_compiled_trust_and_explicit_hostname_verification(monkeypatch):
    paths = SimpleNamespace(openssl_cafile='/compiled/roots', openssl_capath='/compiled/dir',
                            cafile='/environment/roots', capath='/environment/dir')
    events = []

    def context(protocol):
        events.append(protocol)
        return SimpleNamespace(verify_mode=transport.ssl.CERT_REQUIRED, check_hostname=True, keylog_filename=None,
                               load_verify_locations=lambda **paths: events.append(paths),
                               set_alpn_protocols=lambda protocols: events.append(protocols))

    monkeypatch.setattr(transport.ssl, 'get_default_verify_paths', lambda: paths)
    monkeypatch.setattr(transport.ssl, 'SSLContext', context)
    monkeypatch.setattr(transport.os.path, 'isfile', lambda path: path == paths.openssl_cafile)
    monkeypatch.setattr(transport.os.path, 'isdir', lambda path: path == paths.openssl_capath)
    tls = transport._verified_tls()
    assert tls.minimum_version == transport.ssl.TLSVersion.TLSv1_2
    assert events == [transport.ssl.PROTOCOL_TLS_CLIENT,
                      {'cafile': '/compiled/roots', 'capath': '/compiled/dir'}, ['http/1.1']]


def test_actual_capture_helper_compiles_31_attempts_through_synthetic_direct_io(network, owned):
    for _, response in owned.routes:
        entity = b''.join(response.entity)
        http1 = response.headers.replace(b'HTTP/2 ', b'HTTP/1.1 ')
        network.responses.append(http1[:-2] + f'Content-Length: {len(entity)}\r\n\r\n'.encode() + entity)

    socket = transport.socket.socket

    def verify_attempt_before_socket(*args):
        attempt, receipt = owned.ledger.read_attempts()[-1]
        assert attempt.sequence == len(network.raw) + 1 and receipt is None
        return socket(*args)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(transport.socket, 'socket', verify_attempt_before_socket)
        owned.transport = transport.PublicCaptureTransport(SELECTED)
        result = collect(owned)

    assert len(result.exchanges) == len(network.raw) == len(network.tls) == 31
    assert not network.responses
    assert all(channel.closed for channel in (*network.raw, *network.tls))
    assert result.exchanges[0].headers.startswith(b'HTTP/1.1 103\r\n')
    assert [entry.entity for entry in result.exchanges if entry.receipt.status == 308] == [b'non-followed alias body']
    assert all(response.sent.count(b'GET ') == 1 for response in network.tls)
