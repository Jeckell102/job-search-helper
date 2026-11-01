"""Paycom public career portals, verified against the official app 2026-10-08.

The portal supplies an anonymous, short-lived session for public listing reads.
Keep it in memory, send it only to the pinned careers service, never log it.
No account, application, analytics, or saved-search requests are made.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit
from urllib.request import Request, build_opener

from .ats import (FetchError, HTTPResponse, Inventory, MAX_RESPONSE_BYTES,
                  RETRY_STATUSES, _NoRedirect, _base, _challenge, _delay, text)
from .discovery import CareersTransport

HOST = 'www.paycomonline.net'
SERVICE = 'https://portal-applicant-tracking.us-cent.paycomonline.net/'
PREFIX = '/v4/ats/web.php/portal/'
SEARCH = 'api/ats/job-posting-previews/search'
MAX_JOBS = 10000
PAGE_SIZE = 50


def resolve_paycom(ats, url):
    p = urlsplit(url)
    match = re.fullmatch(PREFIX + r'([A-Fa-f0-9]{32})/career-page/?', p.path)
    if (p.scheme != 'https' or p.hostname != HOST or p.username or p.password
            or p.port not in (None, 443) or not match or p.fragment or '\\' in url
            or any(ord(c) <= 32 or ord(c) == 127 for c in url)):
        raise ValueError('Paycom requires a verified public HTTPS portal careers URL.')
    if any(not k.startswith('utm_') for k, v in parse_qsl(p.query, keep_blank_values=True)):
        raise ValueError('Paycom URL filters require explicit scope support; inventory not expanded.')
    label = ats.casefold()
    if any(x in label for x in ('shared', 'parent')):
        raise ValueError('Shared Paycom portals require a verified company-specific scope.')
    if 'paycom' not in label and any(x in label for x in ('workday', 'phenom', 'bamboohr', 'greenhouse', 'lever', 'ashby', 'icims', 'taleo', 'adp', 'paylocity')):
        raise ValueError('ATS / Source disagrees with the Paycom portal URL.')
    return 'Paycom', match[1].upper() + '/career-page', 'https://' + HOST + PREFIX


def _check(response, html=False):
    if not isinstance(response, HTTPResponse):
        raise FetchError('failed', 'Paycom transport returned an invalid response.')
    if response.status in (401, 403) or _challenge(response, expect_html=html):
        raise FetchError('blocked', 'Paycom denied the public careers request or requires human verification.')
    if not 200 <= response.status < 300:
        raise FetchError('failed', f'Paycom HTTP {response.status}; inventory incomplete.')
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise FetchError('partial', 'Paycom response exceeds the bounded size limit.')


def _session(source, pages):
    response = pages.get(source)
    _check(response, html=True)
    html = response.body.decode('utf-8')
    match = re.search(r'\bvar\s+configsFromHost\s*=\s*', html)
    if not match:
        raise FetchError('partial', 'Paycom public portal bootstrap is missing.')
    config = json.JSONDecoder().raw_decode(html[match.end():])[0]
    lib = json.loads(config['libConfig'])
    if lib.get('atsPortalMantleServiceUrl') != SERVICE:
        raise FetchError('unsupported', 'Paycom public careers service changed; verify its destination.')
    token = config['sessionJWT']
    if not isinstance(token, str) or len(token) > 32768 or not re.fullmatch(r'[\w-]+\.[\w-]+\.[\w-]+', token):
        raise FetchError('partial', 'Paycom anonymous portal session is malformed.')
    encoded = token.split('.')[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    # These claims constrain our use of the public bootstrap, not authentication
    # of server data; HTTPS establishes its provenance and the service validates JWT.
    if str(claims.get('sub')) != '0' or claims.get('system') != 'ats' or claims.get('isInternalJobBoard'):
        raise FetchError('unsupported', 'Paycom bootstrap is not an anonymous external careers session.')
    client = claims.get('clientcode')
    if not isinstance(client, str) or not re.fullmatch(r'[A-Za-z0-9]{1,20}', client):
        raise FetchError('partial', 'Paycom portal tenant identity is missing.')
    return token, client


class PaycomTransport:
    """Pinned, bounded public search/detail requests with no cookies or redirects."""
    def __init__(self, timeout=25, interval=.4):
        self.opener = build_opener(_NoRedirect())
        self.timeout, self.interval, self.last = timeout, interval, 0.

    def request(self, path, token, payload=None):
        if not ((path == SEARCH and payload is not None) or
                (re.fullmatch(r'api/ats/job-postings/[1-9][0-9]{0,15}', path) and payload is None)):
            raise FetchError('unsupported', 'Paycom transport permits only public inventory and detail reads.')
        for attempt in range(3):
            time.sleep(max(0., self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            req = Request(SERVICE + path, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={'Authorization': token, 'Locale': 'en-US', 'Accept': 'application/json',
                                   'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
                                   'User-Agent': 'JobSearchHelper/1.0 (public job-board inventory; read-only)'})
            try:
                with self.opener.open(req, timeout=self.timeout) as r:
                    response = HTTPResponse(r.status, r.read(MAX_RESPONSE_BYTES + 1), dict(r.headers))
            except HTTPError as e:
                response = HTTPResponse(e.code, e.read(8192), dict(e.headers))
                e.close()
            except (URLError, TimeoutError, ConnectionError):
                if attempt == 2:
                    raise FetchError('failed', 'Paycom network request failed after bounded retries.') from None
                time.sleep(2 ** attempt)
                continue
            if response.status in RETRY_STATUSES and attempt < 2:
                time.sleep(_delay(response.headers, attempt))
                continue
            return response
        raise FetchError('failed', 'Paycom request did not complete.')


def _read(transport, token, path, payload=None):
    response = transport.request(path, token, payload)
    _check(response)
    return json.loads(response.body)


def _page(transport, token, skip):
    filters = {k: [] for k in ('workEnvironments', 'positionTypes', 'educationLevels', 'categories',
                              'travelTypes', 'shiftTypes', 'otherFilters')}
    filters.update(distanceFrom=0, keywordSearchText='', location='', sortOption='')
    data = _read(transport, token, SEARCH, {'skip': skip, 'take': PAGE_SIZE, 'filtersForQuery': filters})
    total, entries = data.get('jobPostingPreviewsCount'), data.get('jobPostingPreviews')
    if type(total) is not int or not 0 <= total <= MAX_JOBS or not isinstance(entries, list):
        raise FetchError('partial', 'Paycom public list is missing a valid total or exceeds the inventory limit.')
    if len(entries) != min(PAGE_SIZE, max(0, total - skip)):
        raise FetchError('partial', 'Paycom page length disagrees with its advertised total.')
    for entry in entries:
        if (not isinstance(entry, dict) or type(entry.get('jobId')) is not int or not 0 < entry['jobId'] < 10**16
                or not isinstance(entry.get('jobTitle'), str) or not entry['jobTitle'].strip()):
            raise FetchError('partial', 'Paycom listing has invalid posting identity or title.')
    return entries, total


def _inventory(transport, token):
    entries, total = _page(transport, token, 0)
    for skip in range(PAGE_SIZE, total, PAGE_SIZE):
        page, count = _page(transport, token, skip)
        if count != total:
            raise FetchError('partial', 'Paycom inventory count changed during pagination.')
        entries.extend(page)
    if len({e['jobId'] for e in entries}) != total:
        raise FetchError('partial', 'Paycom pagination repeated posting IDs; inventory incomplete.')
    return entries


def _posting(transport, token, client, source, entry, company_id, company):
    ident = entry['jobId']
    job = _read(transport, token, 'api/ats/job-postings/' + str(ident)).get('jobPosting')
    if (not isinstance(job, dict) or type(job.get('jobId')) is not int or job['jobId'] != ident
            or job.get('clientCode') != client or text(job.get('jobTitle')) != text(entry['jobTitle'])
            or job.get('applyAvailable') is not True):
        raise FetchError('partial', 'Paycom detail identity, tenant, title, or open status disagrees with its listing.')
    if not isinstance(job.get('description'), str) or not text(job['description']).strip():
        raise FetchError('partial', 'Paycom full job description is missing.')
    if not isinstance(job.get('secondaryLocations', []), list):
        raise FetchError('partial', 'Paycom locations are malformed.')
    locations = [job.get('location', ''), *job.get('secondaryLocations', [])]
    if not all(isinstance(v, str) for v in locations):
        raise FetchError('partial', 'Paycom locations are malformed.')
    row = _base({'id': str(ident)}, 'Paycom', company_id, company)
    description = '\n\n'.join(text(job.get(k, '')) for k in ('description', 'qualifications') if job.get(k))
    row.update(title=text(job['jobTitle']), description=description,
               url=source.rsplit('/', 1)[0] + '/jobs/' + str(ident),
               location='; '.join(dict.fromkeys(v for v in locations if v)),
               work_arrangement=text(job.get('remoteType')), compensation=text(job.get('salaryRange')),
               department=text(job.get('jobCategory')), created_at=text(entry.get('postedOn')))
    return row


def fetch_paycom(ats, url, company_id, company, transport=None, pages=None):
    jobs, source = [], url
    try:
        _, board, root = resolve_paycom(ats, url)
        source = root + board
        token, client = _session(source, pages or CareersTransport())
        transport = transport or PaycomTransport()
        entries = _inventory(transport, token)
        for entry in entries:
            jobs.append(_posting(transport, token, client, source, entry, company_id, company))
            print(json.dumps({'event': 'inventory_page', 'provider': 'Paycom', 'company_id': company_id,
                              'postings_fetched': len(jobs), 'total': len(entries)}), file=sys.stderr)
        if _inventory(transport, token) != entries:
            raise FetchError('partial', 'Paycom public inventory changed during the scan; retry to establish completeness.')
        return Inventory('complete', jobs, f'Paycom: retrieved {len(jobs)} full postings and rechecked every inventory page.', source, 'Paycom')
    except FetchError as error:
        status = 'blocked' if error.status == 'blocked' else ('partial' if jobs else error.status)
        return Inventory(status, jobs, error.reason, source, 'Paycom')
    except (ValueError, TypeError, AttributeError, KeyError):
        return Inventory('partial' if jobs else 'unsupported', jobs,
                         'Paycom URL/configuration or public data is malformed; no complete inventory established.', source, 'Paycom')
    except OSError:
        return Inventory('partial' if jobs else 'failed', jobs, 'Paycom network failure; inventory incomplete.', source, 'Paycom')
