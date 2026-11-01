"""DCS public Taleo inventory: reconcile every HTML listing with its full RSS feed."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urlencode, urlsplit
from xml.etree import ElementTree

from .ats import FetchError, HTTPResponse, Inventory, _base
from .core import plain_text
from .discovery import CareersTransport

HOST = 'phh.tbe.taleo.net'
SEARCH_PATH = '/phh04/ats/careers/v2/jobSearch'
DETAIL_PATH = '/phh04/ats/careers/v2/viewRequisition'
RESULT_PATH = '/phh04/ats/careers/v2/searchResults'
RSS_PATH = '/phh04/ats/servlet/Rss'
RSS_SOURCE = 'https://' + HOST + RSS_PATH + '?org=DCSCORP2&cws=37&WebPage=SRCHR_V2&WebVersion=0&_rss_version=2'
MAX_JOBS, PAGE_SIZE, MAX_FEED_BYTES = 5000, 10, 16 * 1024 * 1024
NS = '{urn:TBERss}'


def _parts(url):
    p = urlsplit(url)
    pairs = parse_qsl(p.query, keep_blank_values=True, max_num_fields=12)
    q = dict(pairs)
    if (p.scheme != 'https' or p.hostname != HOST or p.port not in (None, 443)
            or p.username or p.password or p.fragment or len(q) != len(pairs)
            or q.get('org') != 'DCSCORP2' or q.get('cws') != '37'):
        raise ValueError('URL is outside the verified DCS board.')
    return p, q


def supports_tbe(url):
    try:
        p, q = _parts(url)
        if p.path == SEARCH_PATH:
            return set(q) <= {'org', 'cws', 'act'} and q.get('act', 'redirectCwsV2') == 'redirectCwsV2'
        return url == RSS_SOURCE
    except (ValueError, TypeError, AttributeError):
        return False


class TaleoTbeTransport:
    def __init__(self, base=None):
        self.base = base or CareersTransport(accept='*/*', max_bytes=MAX_FEED_BYTES)

    def get(self, url):
        try:
            p, q = _parts(url)
            if p.path == RSS_PATH:
                valid = url == RSS_SOURCE
            elif p.path == RESULT_PATH:
                valid = (set(q) <= {'org', 'cws', 'rowFrom', 'act', 'sortColumn', 'sortOrder'}
                         and q.get('rowFrom', '0').isdigit()
                         and int(q.get('rowFrom', '0')) <= MAX_JOBS
                         and q.get('act', 'search') == 'search'
                         and q.get('sortColumn', 'null') == 'null'
                         and q.get('sortOrder', 'null') == 'null')
            else:
                valid = False
            if not valid:
                raise ValueError('Unverified public listing endpoint.')
        except (ValueError, TypeError, AttributeError):
            raise FetchError('unsupported', 'Taleo TBE transport requires the verified DCS listing/feed.') from None
        return self.base.get(url)


def _get(url, transport):
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError('failed', 'Taleo TBE transport returned an invalid response.')
    if response.status in (401, 403, 429):
        raise FetchError('blocked', f'Taleo TBE HTTP {response.status}: public access denied.')
    if response.status != 200:
        raise FetchError('partial', f'Taleo TBE HTTP {response.status}; inventory unavailable.')
    limit = MAX_FEED_BYTES if url == RSS_SOURCE else 2 * 1024 * 1024
    if len(response.body) > limit:
        raise FetchError('partial', 'Taleo TBE response exceeded its verified size bound.')
    return response.body


def _job_link(url, *, listing=False):
    p, q = _parts(url)
    allowed = {DETAIL_PATH} if listing else {DETAIL_PATH, '/phh04/ats/careers/requisition.jsp'}
    if p.path not in allowed or set(q) != {'org', 'cws', 'rid'} or not re.fullmatch(r'[0-9]{1,20}', q['rid']):
        raise ValueError('Invalid DCS requisition link.')
    return q['rid']


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.entries = [], {}
        self.href, self.label, self.ignore = None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignore += 1
        if not self.ignore and tag == 'a':
            attrs = dict(attrs)
            self.href = attrs.get('href') if 'viewJobLink' in attrs.get('class', '').split() else None
            self.label = []

    def handle_data(self, data):
        if not self.ignore:
            self.text.append(data)
            if self.href:
                self.label.append(data)

    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.ignore:
            self.ignore -= 1
        if tag == 'a' and self.href:
            from urllib.parse import urljoin
            url = urljoin('https://' + HOST, self.href)
            if urlsplit(url).path == DETAIL_PATH:
                rid = _job_link(url, listing=True)
                title = plain_text(' '.join(self.label))
                if not title or rid in self.entries:
                    raise ValueError('Missing title or repeated DCS listing ID.')
                self.entries[rid] = (title, url)
            self.href = None


def _listing(transport):
    entries, total, start = {}, None, 0
    while total is None or start < total:
        url = 'https://' + HOST + RESULT_PATH + '?' + urlencode({
            'org': 'DCSCORP2', 'cws': '37', 'rowFrom': start,
            'act': 'search', 'sortColumn': 'null', 'sortOrder': 'null'})
        page = _HTML()
        page.feed(_get(url, transport).decode('utf-8'))
        page.close()
        counts = re.findall(r'Positions\s+Matched\s*[^0-9]{0,60}([0-9][0-9,]*)', ' '.join(page.text), re.I)
        if not counts or len(set(counts)) != 1:
            raise ValueError('DCS listing lacks one published total.')
        count = int(counts[0].replace(',', ''))
        if count > MAX_JOBS or (total is not None and total != count):
            raise ValueError('DCS inventory count changed or exceeded the page bound.')
        total = count
        if len(page.entries) != min(PAGE_SIZE, max(0, total - start)) or set(entries) & set(page.entries):
            raise ValueError('DCS pagination is incomplete or repeats requisitions.')
        entries.update(page.entries)
        start += PAGE_SIZE
    if len(entries) != total:
        raise ValueError('DCS listing membership does not match the advertised total.')
    return entries


def _rss(transport, company_id, company):
    body = _get(RSS_SOURCE, transport)
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('Unexpected XML declarations in DCS feed.')
    root = ElementTree.fromstring(body)
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None or plain_text(channel.findtext('title')) != 'DCS Corporation Job Feed':
        raise ValueError('RSS employer identity is missing or changed.')
    p, q = _parts(channel.findtext('link', ''))
    if p.path != '/dispatcher/servlet/DispatcherServlet' or set(q) - {'org', 'cws', 'act'}:
        raise ValueError('RSS employer scope is unverified.')
    jobs = {}
    for item in channel.findall('item'):
        rid = item.findtext(NS + 'reqId', '')
        title = plain_text(item.findtext('title'))
        link, guid = item.findtext('link', ''), item.findtext('guid', '')
        description = plain_text(item.findtext(NS + 'html-description'))
        if (not re.fullmatch(r'[0-9]{1,20}', rid) or rid in jobs
                or _job_link(link) != rid or _job_link(guid) != rid
                or not title or len(description) < 120 or len(jobs) >= MAX_JOBS):
            raise ValueError('RSS item has a missing/duplicate identity, scope, title, or full description.')
        row = _base({'id': rid}, 'Taleo TBE', company_id, company)
        row.update(req_id=rid, title=title, url=link, description=description,
                   location=plain_text(item.findtext(NS + 'location')),
                   department=plain_text(item.findtext(NS + 'department')), is_listed=True)
        jobs[rid] = row
    return jobs


def fetch_tbe(source, company_id, company, transport):
    if not supports_tbe(source):
        return Inventory('unsupported', reason='Taleo TBE requires the verified DCS employer board.', source_url=source, ats='Taleo TBE')
    jobs = {}
    try:
        listing = _listing(transport)
        jobs = _rss(transport, company_id, company)
        if set(jobs) != set(listing) or any(jobs[rid]['title'] != listing[rid][0] for rid in jobs):
            raise ValueError('DCS RSS membership/titles disagree with the full HTML inventory.')
        if _rss(transport, company_id, company) != jobs or _listing(transport) != listing:
            raise ValueError('DCS full feed or HTML inventory changed during retrieval.')
        return Inventory('complete', [jobs[rid] for rid in sorted(jobs)],
                         f'Taleo TBE: retrieved {len(jobs)} full postings; reconciled and rechecked all HTML pages and RSS membership/content.', source, 'Taleo TBE')
    except FetchError as exc:
        return Inventory('partial' if jobs else exc.status, list(jobs.values()), exc.reason, source, 'Taleo TBE')
    except (OSError, ValueError, TypeError, AttributeError, UnicodeError, ElementTree.ParseError) as exc:
        return Inventory('partial', list(jobs.values()), 'Taleo TBE incomplete inventory: ' + str(exc), source, 'Taleo TBE')
