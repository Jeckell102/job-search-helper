"""One direct HTTP/1.1 GET for the two reviewed public capture scopes."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import errno
from ipaddress import ip_address
import os
import re
import select
import socket
import ssl
import time
from typing import Iterator
from urllib.parse import urlsplit

from rippling_capture import CaptureError
from rippling_capture import _MAX_ITEMS, _PAGE_SIZE
import rippling_public_authority as authority
from validate_candidate import MAX_CAPTURE_BYTES


_FIXED = frozenset((authority.FORTERRA_CAREERS, authority.PDW_CAREERS, authority.PDW_ALIAS))
_BOARDS = (authority.FORTERRA_BOARD, authority.PDW_BOARD)
_ORIGINS = frozenset(urlsplit(url).hostname for url in (*_FIXED, *_BOARDS))
_UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
_BOARD_SUFFIX = re.compile(rf'(?:/{_UUID}|\?page=([1-9][0-9]{{0,2}}))?')
_MAX_HEADER_BYTES = 65_536
_MAX_ENTITY_BYTES = 6 * 1024 * 1024
_MAX_CHUNK_FRAMING_BYTES = 262_144
_READ_SIZE = 16_384
_CONNECT_PENDING = {errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EINTR}


def _require(condition, reason):
    if not condition:
        raise CaptureError(reason)


def _request_target(url):
    _require(type(url) is str, 'Public capture requires an exact URL')
    allowed = url in _FIXED
    for board in _BOARDS:
        if url.startswith(board):
            suffix = _BOARD_SUFFIX.fullmatch(url[len(board):])
            allowed = suffix is not None and (
                suffix[1] is None or int(suffix[1]) < _MAX_ITEMS // _PAGE_SIZE
            )
            break
    _require(allowed, 'Public capture URL is outside the reviewed routes')
    parsed = urlsplit(url)
    return parsed.hostname, parsed.path + (f'?{parsed.query}' if parsed.query else '')


def _endpoint(value):
    _require(type(value) is str, 'Public capture requires a selected numeric address')
    try:
        address = ip_address(value)
    except ValueError:
        raise CaptureError('Public capture requires a selected numeric address') from None
    _require(address.is_global and not address.is_multicast and not address.is_reserved
             and str(address) == value
             and getattr(address, 'scope_id', None) is None
             and getattr(address, 'ipv4_mapped', None) is None
             and getattr(address, 'sixtofour', None) is None
             and getattr(address, 'teredo', None) is None,
             'Public capture requires a canonical public address')
    if address.version == 4:
        return socket.AF_INET, (value, 443)
    return socket.AF_INET6, (value, 443, 0, 0)


def _verified_tls():
    # Match ordinary direct capture's compiled trust paths and avoid ambient key logging.
    paths = ssl.get_default_verify_paths()
    cafile = paths.openssl_cafile if os.path.isfile(paths.openssl_cafile) else None
    capath = paths.openssl_capath if os.path.isdir(paths.openssl_capath) else None
    _require(cafile is not None or capath is not None, 'Public capture has no compiled TLS trust roots')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=cafile, capath=capath)
    context.set_alpn_protocols(['http/1.1'])
    _require(context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
             and context.keylog_filename is None, 'Public capture TLS verification is unavailable')
    return context


class _Deadline:
    def __init__(self, end_ns):
        self.end_ns = end_ns

    def remaining(self):
        remaining = self.end_ns - time.clock_gettime_ns(time.CLOCK_BOOTTIME)
        _require(remaining > 0, 'Public capture elapsed deadline expired during I/O')
        return min(remaining, 100_000_000) / 1_000_000_000

    def wait(self, connection, *, reading):
        while True:
            # Recheck boot time frequently because select's relative wait may exclude suspend.
            delay = self.remaining()
            readable, writable, _ = select.select(
                [connection] if reading else [], [] if reading else [connection], [], delay,
            )
            self.remaining()
            if readable or writable:
                return

    def call(self, connection, operation):
        while True:
            self.remaining()
            try:
                result = operation()
            except ssl.SSLWantReadError:
                self.wait(connection, reading=True)
            except ssl.SSLWantWriteError:
                self.wait(connection, reading=False)
            else:
                self.remaining()
                return result


class _Reader:
    def __init__(self, connection, deadline):
        self.connection = connection
        self.deadline = deadline

    def receive(self, count):
        result = self.deadline.call(self.connection, lambda: self.connection.recv(count))
        _require(bool(result), 'Public capture response ended before its complete HTTP frame')
        return result

    def line(self, limit):
        raw = bytearray()
        # Stop exactly at the line delimiter so header/framing I/O does not consume entity budget.
        while len(raw) < limit:
            raw.extend(self.receive(1))
            if raw.endswith(b'\n'):
                _require(raw.endswith(b'\r\n'), 'Public capture requires exact HTTP line framing')
                return bytes(raw)
        raise CaptureError('Public capture exceeded its header or framing byte limit')

    def exact(self, size):
        while size:
            data = self.receive(min(size, _READ_SIZE))
            size -= len(data)
            yield data


def _headers(reader, limit, url):
    status_chain = []
    raw = bytearray()
    fields = {}
    while True:
        line = reader.line(limit - len(raw))
        raw.extend(line)
        match = authority.STATUS_LINE.fullmatch(line[:-2].decode('latin-1'))
        status = int(match[1]) if match and line.startswith(b'HTTP/1.1 ') else 0
        status_chain.append(status)
        expected = 308 if url == authority.PDW_ALIAS else 200
        _require(status == expected or (status_chain == [103] and url == authority.FORTERRA_CAREERS),
                 'Public capture response has an unexpected HTTP status or chain')
        fields.clear()
        while True:
            line = reader.line(limit - len(raw))
            raw.extend(line)
            if line == b'\r\n':
                break
            name, _, value = line[:-2].decode('latin-1').partition(':')
            fields.setdefault(name.lower(), []).append(value.strip(' \t'))
        if status == expected:
            break
        _require(not {'content-length', 'transfer-encoding'}.intersection(fields),
                 'Public capture informational status contains unexpected body framing')

    text = raw.decode('latin-1')
    is_alias = url == authority.PDW_ALIAS
    locations = authority.response_headers(text, {tuple(status_chain)},
                                          exact_refresh=f'0;url={authority.PDW_LOCATION}' if is_alias else None)
    _require(locations == ([authority.PDW_LOCATION] if is_alias else []),
             'Public capture response contains unexpected redirect evidence')
    return status, bytes(raw), fields


def _framing(fields):
    _require([value.lower() for value in fields.get('content-encoding', [])] in ([], ['identity']),
             'Public capture response must use identity content encoding')
    lengths = fields.get('content-length', [])
    transfers = fields.get('transfer-encoding', [])
    _require('trailer' not in fields, 'Public capture response has unsupported transfer framing')
    if transfers:
        _require(not lengths and [value.lower() for value in transfers] == ['chunked'],
                 'Public capture response has unsupported transfer framing')
        return None
    _require(len(lengths) == 1 and re.fullmatch(r'[0-9]{1,20}', lengths[0]) is not None,
             'Public capture response requires one explicit valid content length')
    return int(lengths[0])


def _chunked(reader, limit):
    framing = _MAX_CHUNK_FRAMING_BYTES
    while True:
        raw_size = reader.line(min(framing, 18))
        framing -= len(raw_size)
        _require(re.fullmatch(rb'[0-9A-Fa-f]{1,16}\r\n', raw_size) is not None,
                 'Public capture response has unsupported chunk framing')
        size = int(raw_size[:-2], 16)
        _require(size <= limit, 'Public capture exceeded its entity or combined byte limit')
        if size:
            yield from reader.exact(size)
            limit -= size
        _require(framing >= 2 and reader.line(2) == b'\r\n',
                 'Public capture response has invalid chunk framing or trailers')
        framing -= 2
        if not size:
            return


@dataclass(frozen=True)
class _Response:
    final_url: str
    status: int
    headers: bytes
    entity: Iterator[bytes]


class PublicCaptureTransport:
    """Open one request using an owner-selected public address per exact origin.

    Address selection and pin freshness belong to the measured owner. The
    adapter never resolves, redials, or follows redirects. TLS still verifies
    the URI hostname, independent of its selected numeric address. The
    collector remains responsible for listing membership and request sequence.
    """

    def __init__(self, selected_addresses):
        _require(type(selected_addresses) is dict and set(selected_addresses) == _ORIGINS,
                 'Public capture needs the exact approved origin address selection')
        self._endpoints = {host: _endpoint(address) for host, address in selected_addresses.items()}
        self._tls = _verified_tls()

    @contextmanager
    def open_get(self, url, *, deadline_elapsed_ns, max_response_bytes, max_header_bytes, max_entity_bytes):
        host, target = _request_target(url)
        _require(type(deadline_elapsed_ns) is int and type(max_response_bytes) is int
                 and type(max_header_bytes) is int and type(max_entity_bytes) is int
                 and 0 < max_response_bytes <= MAX_CAPTURE_BYTES
                 and 0 < max_header_bytes <= min(max_response_bytes, _MAX_HEADER_BYTES)
                 and 0 < max_entity_bytes <= min(max_response_bytes, _MAX_ENTITY_BYTES),
                 'Public capture has invalid I/O limits')
        deadline = _Deadline(deadline_elapsed_ns)
        deadline.remaining()
        family, endpoint = self._endpoints[host]
        with ExitStack() as connections:
            raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
            connections.callback(raw.close)
            raw.setblocking(False)
            deadline.remaining()
            outcome = raw.connect_ex(endpoint)
            if outcome in _CONNECT_PENDING:
                deadline.wait(raw, reading=False)
                outcome = raw.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            _require(outcome == 0, 'Public capture direct connection failed')
            deadline.remaining()

            secured = self._tls.wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False,
                                            suppress_ragged_eofs=False)
            connections.callback(secured.close)
            deadline.call(secured, secured.do_handshake)
            _require(secured.selected_alpn_protocol() in (None, 'http/1.1'),
                     'Public capture negotiated an unsupported protocol')

            request = memoryview((f'GET {target} HTTP/1.1\r\nHost: {host}\r\n'
                                  'User-Agent: JobSearchHelper/1.0\r\nAccept-Encoding: identity\r\n'
                                  'Connection: close\r\n\r\n').encode('ascii'))
            while request:
                sent = deadline.call(secured, lambda: secured.send(request))
                _require(sent > 0, 'Public capture could not complete its only GET')
                request = request[sent:]

            reader = _Reader(secured, deadline)
            status, headers, fields = _headers(reader, max_header_bytes, url)
            length = _framing(fields)
            limit = min(max_entity_bytes, max_response_bytes - len(headers))
            _require(length is None or length <= limit,
                     'Public capture exceeded its entity or combined byte limit')
            complete = False

            def entity():
                nonlocal complete
                if length is None:
                    yield from _chunked(reader, limit)
                else:
                    yield from reader.exact(length)
                complete = True

            stream = entity()
            connections.callback(stream.close)
            yield _Response(url, status, headers, stream)
            _require(complete, 'Public capture response entity was not completely consumed')
        deadline.remaining()
