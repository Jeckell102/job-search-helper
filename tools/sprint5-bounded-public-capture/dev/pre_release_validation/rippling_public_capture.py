"""Collect exact Forterra and PDW replay evidence through owner-supplied capabilities."""

from dataclasses import asdict, dataclass
from email.utils import format_datetime, parsedate_to_datetime
from hashlib import sha256
import json
import re

import rippling_capture as oracle
import rippling_public_authority as authority
from validate_candidate import MAX_CAPTURE_BYTES, PUBLIC_CAPTURE_SCHEMA, ROW_FIELDS, SUPPORTED_SCOPE, digest


_HEADER_LIMIT = 65_536
_ENTITY_LIMIT = 6 * 1024 * 1024
_REQUEST_LIMIT = 128
_WINDOW_LIMIT_MS = 120_000
_DIGEST = re.compile(r'[0-9a-f]{64}')


@dataclass(frozen=True)
class Attempt:
    sequence: int
    method: str
    url: str
    started_unix_ms: int
    started_elapsed_ns: int


@dataclass(frozen=True)
class Receipt:
    final_url: str
    status: int
    completed_unix_ms: int
    completed_elapsed_ns: int
    headers_sha256: str
    headers_bytes: int
    entity_sha256: str
    entity_bytes: int
    date_unix_ms: int
    advertised_age_seconds: int | None


@dataclass(frozen=True)
class Exchange:
    attempt: Attempt
    receipt: Receipt
    headers: bytes
    entity: bytes


@dataclass(frozen=True)
class PublicCapture:
    candidate_capture: bytes
    manifest: bytes
    exchanges: tuple[Exchange, ...]


def _require(condition, reason):
    if not condition:
        raise oracle.CaptureError(reason)


def _positive(value, maximum):
    return type(value) is int and 0 < value <= maximum


def _canonical(value, limit):
    encoded = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    for part in encoder.iterencode(value):
        raw = part.encode('utf-8')
        _require(len(encoded) + len(raw) <= limit, 'Public capture exceeds its capsule byte limit')
        encoded.extend(raw)
    return bytes(encoded)


def _capture_inputs(binding, window, companies, policy):
    return json.dumps(
        {'binding': binding, 'window': asdict(window), 'companies': companies, 'policy': policy},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False,
    ).encode('utf-8')


def _response_freshness(headers, completed_ms, max_age_seconds, future_skew_seconds):
    fields = headers[:-4].split('\r\n\r\n')[-1].split('\r\n')[1:]
    dates, ages = [], []
    for line in fields:
        name, _, value = line.partition(':')
        if name.lower() == 'date':
            dates.append(value.strip(' \t'))
        elif name.lower() == 'age':
            ages.append(value.strip(' \t'))
    _require(len(dates) == 1 and len(ages) <= 1
             and (not ages or re.fullmatch(r'[0-9]{1,10}', ages[0])),
             'Public HTTP response freshness evidence is absent or ambiguous')
    try:
        parsed = parsedate_to_datetime(dates[0])
        _require(format_datetime(parsed, usegmt=True) == dates[0], 'Malformed public HTTP response Date')
        date_ms = int(parsed.timestamp()) * 1000
    except (TypeError, ValueError, OverflowError):
        raise oracle.CaptureError('Malformed public HTTP response Date') from None
    age = int(ages[0]) if ages else None
    _require(-future_skew_seconds * 1000 <= completed_ms - date_ms <= max_age_seconds * 1000
             and (age is None or age <= max_age_seconds), 'Public HTTP response is outside the approved cache age')
    return date_ms, age


class _Acquisition:
    def __init__(self, binding, window, policy, read_clock, transport, ledger, verify_inputs):
        self.window = window
        self.wall_deadline = binding['deadline_unix_ms']
        self.read_clock = read_clock
        self.transport = transport
        self.ledger = ledger
        self.verify_inputs = verify_inputs
        self.request_limit = binding['live_request_limit']
        self.remaining = binding['capsule_bytes_limit']
        self.entity_limit = policy['entity_bytes_limit']
        self.max_age = policy['max_age_seconds']
        self.future_skew = policy['future_skew_seconds']
        self.previous_clock = (window['started_unix_ms'], window['started_elapsed_ns'])
        self.exchanges = []

    def now(self):
        boot, wall, elapsed = self.read_clock()
        self.verify_inputs()
        last_wall, last_elapsed = self.previous_clock
        _require(type(wall) is int and type(elapsed) is int and boot == self.window['boot_id']
                 and last_wall <= wall < self.wall_deadline
                 and last_elapsed <= elapsed < self.window['deadline_elapsed_ns'],
                 'Public acquisition clock changed or its deadline expired')
        self.previous_clock = wall, elapsed
        return wall, elapsed

    def get(self, url, *, alias=False, forterra_employer=False):
        _require(len(self.exchanges) < self.request_limit, 'Public acquisition request budget exhausted')
        _require(self.remaining > 0, 'Public capture exceeds its capsule byte limit')
        attempt = Attempt(len(self.exchanges) + 1, 'GET', url, *self.now())
        _require(self.ledger.begin_attempt(attempt) == attempt, 'Public request attempt did not durably read back')
        self.now()
        expected_status = 308 if alias else 200
        complete = False
        with self.transport.open_get(url, deadline_elapsed_ns=self.window['deadline_elapsed_ns'],
                                     max_response_bytes=self.remaining,
                                     max_header_bytes=min(_HEADER_LIMIT, self.remaining),
                                     max_entity_bytes=min(self.entity_limit, self.remaining)) as response:
            self.now()
            _require(response.final_url == url and type(response.status) is int and response.status == expected_status,
                     'Public response URL or status differs from the exact request')
            raw_headers = response.headers
            _require(type(raw_headers) is bytes and 0 < len(raw_headers) <= min(_HEADER_LIMIT, self.remaining),
                     'Public response exceeds its header or capsule byte limit')
            headers = raw_headers.decode('latin-1')
            statuses = {(200,), (103, 200)} if forterra_employer else {(expected_status,)}
            location = authority.response_headers(headers, statuses,
                                                  exact_refresh=f'0;url={authority.PDW_LOCATION}' if alias else None)
            _require(location == ([authority.PDW_LOCATION] if alias else []),
                     'Public response contains a missing or unexpected redirect target')
            entity_limit = min(self.entity_limit, self.remaining - len(raw_headers))
            entity = bytearray()
            for chunk in response.entity:
                self.now()
                _require(type(chunk) is bytes and 0 < len(chunk) <= entity_limit - len(entity),
                         'Public response exceeds its entity or capsule byte limit')
                entity.extend(chunk)
            complete = True
        _require(complete, 'Public response ended without a complete entity')
        wall, elapsed = self.now()
        date, age = _response_freshness(headers, wall, self.max_age, self.future_skew)
        raw_entity = bytes(entity)
        receipt = Receipt(url, expected_status, wall, elapsed, sha256(raw_headers).hexdigest(), len(raw_headers),
                          sha256(raw_entity).hexdigest(), len(raw_entity), date, age)
        _require(self.ledger.finish_attempt(attempt, receipt) == receipt,
                 'Public response receipt did not durably read back')
        self.verify_inputs()
        self.remaining -= len(raw_headers) + len(raw_entity)
        self.exchanges.append(Exchange(attempt, receipt, raw_headers, raw_entity))
        return headers, raw_entity.decode('utf-8') if not alias else None

    def case(self, scope, company):
        role, company_id, _, board = scope
        url = company['Official Careers URL']
        headers, body = self.get(url, forterra_employer=company_id == 'COMP-0066')
        redirect = None
        if company_id == 'COMP-0178':
            alias_headers, _ = self.get(authority.PDW_ALIAS, alias=True)
            redirect = {'url': authority.PDW_ALIAS, 'headers': alias_headers}
        employer = {'url': url, 'headers': headers, 'body': body, 'redirect': redirect}
        authority.check_public_authority(company_id, board, employer)
        responses = {}

        def board_get(url):
            _, body = self.get(url)
            responses.setdefault(url, []).append({'status': 200, 'body': body})
            return body

        initial = self.listing(board, board_get)
        for item in initial:
            body = board_get(f"{board}/{item['id']}")
            oracle.read_detail(board, item, body)
            self.now()
        _require(self.listing(board, board_get) == initial, 'Public board inventory changed on its complete reread')
        return {'role': role, 'company': company, 'authority': employer, 'board_url': board, 'responses': responses}

    def listing(self, board, board_get):
        seen = {}
        total = None
        page = 0
        while total is None or len(seen) < total:
            body = board_get(f'{board}?page={page}' if page else board)
            count, entries = oracle.read_listing(board, page, body)
            _require(count > 0, 'A verified empty inventory requires separate collection approval')
            _require(total is None or count == total, 'Public board listing total changed between pages')
            total = count
            for entry in entries:
                _require(entry['id'] not in seen, 'Public board listing repeats a posting ID')
                seen[entry['id']] = entry
            page += 1
            self.now()
        return list(seen.values())


def collect_public_capture(binding, window, companies, *, ledger, transport, read_clock, response_policy):
    """Collect once under the caller's existing spent reservation and approved response policy.

    The owner supplies the slot binding/window and the read-only Company projections.
    Capture provenance and limits always come from their initial canonical snapshot.
    A change observed in the caller's inputs after a callback holds the capture.
    Its ledger is exclusive to that reservation. begin_attempt must durably append
    a previously unseen sequence, without idempotent reuse. finish_attempt must
    durably complete that exact record once. read_attempts returns ordered
    (Attempt, Receipt or None) pairs including interrupted work.

    The reviewed transport opens one GET without redirects, retries or decompression
    that loses the original entity. It supplies final_url, status, raw ordered
    headers, and an iterable of entity bytes with the transfer framing removed.
    It enforces separate header and entity caps, their combined response cap, and
    the elapsed deadline during I/O, with no suppression of failed or partial reads.
    read_clock supplies the current boot ID, UNIX milliseconds, and boot elapsed ns.
    The return value is evidence for replay, with no verdict or release authority.
    """
    try:
        _require(type(binding) is dict and type(response_policy) is dict,
                 'Public capture requires an exact slot binding and response policy')
        _require(type(companies) is tuple and len(companies) == len(SUPPORTED_SCOPE)
                 and all(type(company) is dict for company in companies),
                 'Public capture requires the exact Forterra and PDW scope')
        original_inputs = _capture_inputs(binding, window, companies, response_policy)
        snapshot = json.loads(original_inputs)
        frozen_binding, frozen_window = snapshot['binding'], snapshot['window']
        frozen_companies, policy = snapshot['companies'], snapshot['policy']

        def verify_inputs():
            try:
                unchanged = _capture_inputs(binding, window, companies, response_policy) == original_inputs
            except (TypeError, ValueError, RecursionError, RuntimeError):
                unchanged = False
            _require(unchanged, 'The enrolled public capture inputs changed during acquisition')

        _require(set(policy) == {'entity_bytes_limit', 'max_age_seconds', 'future_skew_seconds',
                                 'transport_policy_sha256'}
                 and digest(policy) == frozen_binding['collector_policy_sha256']
                 and _DIGEST.fullmatch(policy['transport_policy_sha256']),
                 'Public response policy differs from the enrolled policy')
        entity_bytes_limit = policy['entity_bytes_limit']
        max_age_seconds = policy['max_age_seconds']
        future_skew_seconds = policy['future_skew_seconds']
        deadline = frozen_binding['deadline_unix_ms']
        duration = deadline - frozen_window['started_unix_ms']
        _require(type(deadline) is int and 0 < duration <= _WINDOW_LIMIT_MS
                 and type(frozen_window['started_unix_ms']) is int and frozen_window['started_unix_ms'] > 0
                 and type(frozen_window['started_elapsed_ns']) is int and frozen_window['started_elapsed_ns'] >= 0
                 and type(frozen_window['deadline_elapsed_ns']) is int
                 and type(frozen_window['boot_id']) is str and bool(frozen_window['boot_id'])
                 and frozen_window['deadline_elapsed_ns'] == frozen_window['started_elapsed_ns'] + duration * 1_000_000
                 and _positive(frozen_binding['live_request_limit'], _REQUEST_LIMIT)
                 and _positive(frozen_binding['capsule_bytes_limit'], MAX_CAPTURE_BYTES)
                 and _positive(entity_bytes_limit, _ENTITY_LIMIT)
                 and _positive(max_age_seconds, (1 << 31) - 1)
                 and type(future_skew_seconds) is int and 0 <= future_skew_seconds <= max_age_seconds
                 and all(_DIGEST.fullmatch(frozen_binding[key]) for key in ('dispatch_sha256', 'collector_policy_sha256')),
                 'Public acquisition window, policy or budget differs from the allowed shape')
        scope_keys = ('company_projection_sha256', 'control_projection_sha256')
        employer_urls = (authority.FORTERRA_CAREERS, authority.PDW_CAREERS)
        for (_, company_id, names, _), company, employer, pin in zip(SUPPORTED_SCOPE, frozen_companies, employer_urls,
                                                                     scope_keys, strict=True):
            _require(set(company) == ROW_FIELDS and company['Company ID'] == company_id
                     and company['Company'] in names and company['Official Careers URL'] == employer
                     and company['Company Status'] == 'Active' and company['ATS / Source'] == 'Rippling'
                     and digest(company) == frozen_binding[pin],
                     'Public capture Company differs from its enrolled projection')

        acquisition = _Acquisition(frozen_binding, frozen_window, policy, read_clock, transport, ledger, verify_inputs)
        acquisition.now()
        _require(tuple(ledger.read_attempts()) == (), 'Public acquisition was already attempted')
        verify_inputs()
        cases = [acquisition.case(scope, company)
                 for scope, company in zip(SUPPORTED_SCOPE, frozen_companies, strict=True)]
        capture = _canonical({'schema': PUBLIC_CAPTURE_SCHEMA, 'cases': cases}, acquisition.remaining)
        receipts = tuple((exchange.attempt, exchange.receipt) for exchange in acquisition.exchanges)
        manifest = _canonical({
            'schema': 'rippling-bounded-public-evidence-v1', 'binding_sha256': digest(frozen_binding),
            'dispatch_sha256': frozen_binding['dispatch_sha256'], 'window': frozen_window,
            'response_policy': policy,
            'candidate_capture_sha256': sha256(capture).hexdigest(),
            'candidate_capture_bytes': len(capture),
            'exchanges': [{'attempt': asdict(attempt), 'receipt': asdict(receipt)} for attempt, receipt in receipts],
        }, acquisition.remaining - len(capture))
        _require(tuple(ledger.read_attempts()) == receipts, 'Public acquisition ledger changed before handoff')
        acquisition.now()
        return PublicCapture(capture, manifest, tuple(acquisition.exchanges))
    except (OSError, ValueError, TypeError, KeyError, RecursionError, AttributeError) as error:
        if isinstance(error, oracle.CaptureError):
            raise
        raise oracle.CaptureError('Public acquisition did not complete with exact owned evidence') from None
