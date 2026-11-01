"""Septentrio's public Trakstar RSS, reconciled against its full HTML board."""
from __future__ import annotations
from html.parser import HTMLParser
import re
from urllib.parse import parse_qsl, urljoin, urlsplit
from xml.etree import ElementTree
from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _base
from .core import plain_text
from .discovery import CareersTransport

HOST = 'jobsatseptentrio.hire.trakstar.com'
ROOT_URL = 'https://' + HOST + '/'
BOARD_URL = ROOT_URL + 'jobs'
RSS_PATH = '/jobfeeds/jobsatSeptentrio'
RSS_URL = 'https://' + HOST + RSS_PATH
MAX_JOBS, MAX_PAGES = 5000, 100
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}


def _public(url, *, http=False):
    p = urlsplit(url)
    if (p.scheme not in ({'https', 'http'} if http else {'https'}) or p.hostname != HOST
            or p.username or p.password or p.port not in (None, 443) or p.fragment):
        raise ValueError('Trakstar URL is outside the verified employer board.')
    return p


def _job(url):
    p = _public(url, http=True)
    match = re.fullmatch(r'/jobs/([A-Za-z0-9_-]{1,128})/?', p.path)
    if not match or p.query:
        raise ValueError('Trakstar posting identity is invalid.')
    return match[1], ROOT_URL + 'jobs/' + match[1]


def _get(client, url):
    r = client.get(url)
    if not isinstance(r, HTTPResponse):
        raise FetchError('failed', 'Invalid Trakstar transport response.')
    if r.status != 200:
        raise FetchError('blocked' if r.status in (401, 403, 429) else 'partial', f'Trakstar HTTP {r.status}; inventory unavailable.')
    return r.body


class _Description(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth, self.ignored, self.count, self.parts = 0, 0, 0, []

    def handle_starttag(self, tag, attrs):
        if not self.depth and dict(attrs).get('id') == 'job_description':
            self.depth, self.count = 1, self.count + 1
        elif self.depth and tag not in VOID:
            if self.ignored:
                self.ignored += 1
            elif tag in {'script', 'style', 'form', 'template', 'noscript'}:
                self.ignored = 1
            else:
                self.depth += 1

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if self.ignored:
            self.ignored -= 1
        elif self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.ignored:
            self.parts.append(data)


def _read(transport):
    body = _get(transport, RSS_URL)
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('Unexpected Trakstar XML declaration.')
    root = ElementTree.fromstring(body)
    channel = root.find('channel')
    if root.tag != 'rss' or channel is None or plain_text(channel.findtext('title')) != 'Jobs at Septentrio':
        raise ValueError('Trakstar feed employer identity is missing or changed.')
    link = urlsplit(channel.findtext('link', ''))
    if (link.scheme not in {'http', 'https'} or link.hostname != 'recruiterbox.com'
            or link.path != RSS_PATH or link.query or link.fragment or link.username or link.password):
        raise ValueError('Trakstar feed scope is unverified.')
    out = {}
    for item in channel.findall('item'):
        ident, href = _job(item.findtext('link', '').strip())
        if _job(item.findtext('guid', '').strip())[0] != ident:
            raise ValueError('Trakstar feed link/guid identity mismatch.')
        title = plain_text(item.findtext('title'))
        desc = _Description()
        desc.feed(item.findtext('description', ''))
        desc.close()
        description = plain_text(' '.join(desc.parts))
        if ident in out or not title or not description or desc.count != 1 or desc.depth or len(out) >= MAX_JOBS:
            raise ValueError('Trakstar feed has a duplicate/missing posting, title, or full description.')
        ns = '{https://recruiterbox.com/rss/job/}'
        location = ', '.join(value for value in (
            plain_text(item.findtext(ns + 'locationCity')),
            plain_text(item.findtext(ns + 'locationState')),
            plain_text(item.findtext(ns + 'locationCountry'))) if value)
        out[ident] = {'id': ident, 'title': title, 'url': href, 'description': description,
                      'location': location, 'department': plain_text(item.findtext(ns + 'team'))}
    return out


class _Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ident, self.jobs = None, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a':
            href = urljoin(ROOT_URL, a.get('href', ''))
            self.ident = _job(href)[0] if urlsplit(href).path.startswith('/jobs/') else None
        if tag == 'h3' and 'js-job-list-opening-name' in a.get('class', '').split():
            title = plain_text(a.get('title', ''))
            if not self.ident or not title or self.ident in self.jobs:
                raise ValueError('Trakstar board has an invalid or repeated job card.')
            self.jobs[self.ident] = title

    def handle_endtag(self, tag):
        if tag == 'a':
            self.ident = None


def _board(client):
    url, visited, jobs, total = ROOT_URL, set(), {}, None
    while url:
        if url in visited or len(visited) >= MAX_PAGES:
            raise ValueError('Trakstar board pagination repeated or exceeded its bound.')
        visited.add(url)
        p = _public(url)
        pairs = parse_qsl(p.query, keep_blank_values=True)
        if p.path not in {'/', '/jobs', '/jobs/'} or len(dict(pairs)) != len(pairs) or any(k != 'page' or not v.isdigit() for k, v in pairs):
            raise ValueError('Trakstar board pagination changed its employer/filter scope.')
        html = _get(client, url).decode('utf-8')
        counts = re.findall(r'\btotal_jobs[\'"]?\s*:\s*(\d+)', html)
        if len(set(counts)) != 1:
            raise ValueError('Trakstar board lacks one published job count.')
        current = int(counts[0])
        if current > MAX_JOBS or total is not None and current != total:
            raise ValueError('Trakstar published inventory changed during pagination.')
        total = current
        page = _Cards(); page.feed(html); page.close()
        if set(page.jobs) & set(jobs):
            raise ValueError('Trakstar board pagination repeated job IDs.')
        jobs.update(page.jobs)
        next_links = re.findall(r'\bnext_page_url[\'"]?\s*:\s*(null|[\'"][^\'"]*[\'"])', html)
        if len(set(next_links)) != 1:
            raise ValueError('Trakstar board pagination metadata is missing or ambiguous.')
        url = None if next_links[0] == 'null' else urljoin(url, next_links[0][1:-1])
    if total != len(jobs):
        raise ValueError('Trakstar board membership does not match its advertised total.')
    return jobs


def fetch_trakstar(url, company_id, company, transport, discovery_transport=None):
    try:
        p = _public(url)
        if p.path.rstrip('/') != '/jobs' or p.query:
            raise FetchError('unsupported', 'Trakstar requires the verified employer jobs URL.')
    except (ValueError, FetchError) as e:
        return Inventory('unsupported', reason=str(e), source_url=BOARD_URL, ats='Trakstar Hire')
    jobs = {}
    try:
        page_client = discovery_transport or (CareersTransport() if isinstance(transport, HTTPTransport) else transport)
        board = _board(page_client)
        jobs = _read(transport)
        if {ident: row['title'] for ident, row in jobs.items()} != board:
            raise ValueError('Trakstar RSS membership or titles disagree with the full public board.')
        if _read(transport) != jobs or _board(page_client) != board:
            raise ValueError('Trakstar full board/feed changed during the scan.')
        rows = []
        for ident in sorted(jobs):
            e = jobs[ident]
            row = _base({'id': ident}, 'Trakstar Hire', company_id, company)
            row.update(title=e['title'], description=e['description'], url=e['url'],
                       location=e['location'], department=e['department'])
            rows.append(row)
        return Inventory('complete', rows, f'Trakstar Hire: retrieved {len(rows)} full postings and reconciled/rechecked the full public board and feed.', BOARD_URL, 'Trakstar Hire')
    except FetchError as e:
        return Inventory(e.status, reason=e.reason, source_url=BOARD_URL, ats='Trakstar Hire')
    except (ValueError, TypeError, AttributeError, UnicodeError, ElementTree.ParseError) as e:
        return Inventory('partial', reason='Trakstar incomplete inventory: ' + str(e), source_url=BOARD_URL, ats='Trakstar Hire')
