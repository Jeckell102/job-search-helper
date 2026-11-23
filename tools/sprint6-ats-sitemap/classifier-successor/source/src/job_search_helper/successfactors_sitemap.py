"""Host-owned SuccessFactors inventory for a reviewed sitemap parser."""

from collections.abc import Callable
import re
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

from .ats import FetchError, Inventory, _base, text
from .successfactors import _Page, _get


MAX_SITEMAP_BYTES = 2 * 1024 * 1024
MAX_POSTINGS = 2500
SITEMAP_NAMESPACE = '{http://www.sitemaps.org/schemas/sitemap/0.9}'


def read_sitemap_membership(xml: str, host: str, classify_job_path: Callable[[str], str]) -> dict[str, str]:
    """Apply a path classifier only to jobs, retaining exact URLs and unique IDs."""
    if len(xml.encode()) > MAX_SITEMAP_BYTES or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.IGNORECASE):
        raise ValueError('Sitemap exceeds the XML boundary.')
    try:
        document = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError('Malformed sitemap XML.') from exc
    if document.tag != SITEMAP_NAMESPACE + 'urlset':
        raise ValueError('Unexpected sitemap root.')
    entries = {}
    for node in document.findall(SITEMAP_NAMESPACE + 'url'):
        locations = node.findall(SITEMAP_NAMESPACE + 'loc')
        if len(locations) != 1:
            raise ValueError('A sitemap entry must have exactly one location.')
        url = (locations[0].text or '').strip()
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != host:
            raise ValueError('Sitemap URL is outside the configured host.')
        if 'job' not in parts.path.split('/'):
            continue
        if parts.query or parts.fragment:
            raise ValueError('A job location must be canonical.')
        identity = classify_job_path(parts.path)
        if not isinstance(identity, str) or not re.fullmatch(r'[0-9]{4,24}', identity):
            raise ValueError('Invalid posting ID from job path.')
        if identity in entries or len(entries) >= MAX_POSTINGS:
            raise ValueError('Duplicate or excessive posting IDs.')
        entries[identity] = url
    if not entries:
        raise ValueError('Sitemap contains no jobs.')
    return entries


def fetch_from_sitemap(
    board: str,
    company_id: str,
    company: str,
    transport,
    *,
    job_prefixes: tuple[str, ...],
    parse: Callable[[str], dict[str, str]],
) -> Inventory:
    """Keep network, company identity and completion outside candidate code.

    The dispatcher selects the exact company, board, prefixes and parser
    together. The parser receives XML text and returns only ID-to-URL data.
    """
    if not job_prefixes or any(not prefix.startswith('/') or not prefix.endswith('/job/') for prefix in job_prefixes):
        raise ValueError('SuccessFactors sitemap requires reviewed job path prefixes.')
    source = urlsplit(board)
    host = source.netloc
    pattern = re.compile(
        '(?:' + '|'.join(map(re.escape, job_prefixes)) + r')[^/]+/(\d{4,24})/'
    )
    sitemap_url = urljoin(board, '/sitemap.xml')
    jobs = []

    def expected_path_id(path):
        match = pattern.fullmatch(path)
        if not match:
            raise ValueError('Unrecognized SuccessFactors job path.')
        return match.group(1)

    def posting_id(url):
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise FetchError('partial', 'SuccessFactors sitemap posting URL is malformed.') from exc
        match = pattern.fullmatch(parts.path)
        if parts.scheme == 'https' and parts.netloc == host and not parts.query and not parts.fragment and match:
            return match.group(1)
        raise FetchError('partial', 'SuccessFactors sitemap posting is outside the reviewed board scope.')

    def membership():
        xml = _get(transport, sitemap_url)
        try:
            official = read_sitemap_membership(xml, host, expected_path_id)
            entries = parse(xml)
        except (ValueError, ElementTree.ParseError) as exc:
            raise FetchError('partial', 'SuccessFactors sitemap parser rejected the response.') from exc
        if type(entries) is not dict or entries != official:
            raise FetchError('partial', 'SuccessFactors parser did not preserve exact official posting membership.')
        return entries

    try:
        first = _Page(_get(transport, board))
        visible = {}
        for href, title in first.links:
            url = urljoin(board, href)
            identity = posting_id(url)
            if not title or visible.setdefault(identity, (url, title)) != (url, title):
                raise FetchError('partial', 'SuccessFactors visible listing repeats a conflicting job identity.')
        entries = membership()
        if not visible or any(entries.get(i) != url for i, (url, _) in visible.items()):
            raise FetchError('partial', 'SuccessFactors sitemap does not cover the known visible listings.')
        for identity, url in entries.items():
            try:
                detail = _Page(_get(transport, url))
            except FetchError as error:
                if error.status == 'blocked':
                    raise
                continue
            title = text(''.join(detail.title))
            description = text(''.join(detail.description))
            if (detail.canonicals != [url] or len(detail.title) != 1 or detail.description_count != 1
                    or detail.depth or detail.title_depth or not title or not description
                    or (identity in visible and title != visible[identity][1])):
                continue
            row = _base({'id': identity}, 'SuccessFactors', company_id, company)
            row.update(title=title, url=url, description=description, req_id='')
            jobs.append(row)
        if len(jobs) != len(entries):
            raise FetchError('partial', f'SuccessFactors verified {len(jobs)} of {len(entries)} sitemap details.')
        if membership() != entries:
            raise FetchError('partial', 'SuccessFactors sitemap membership changed during the scan.')
        return Inventory('complete', jobs, 'SuccessFactors completed the stable reviewed sitemap.', board, 'SuccessFactors')
    except FetchError as error:
        return Inventory('partial' if jobs else error.status, jobs, error.reason, board, 'SuccessFactors')
