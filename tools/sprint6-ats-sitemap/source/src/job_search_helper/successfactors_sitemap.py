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
        if len(xml.encode()) > MAX_SITEMAP_BYTES or re.search(r'<!\s*(?:DOCTYPE|ENTITY)', xml, re.IGNORECASE):
            raise FetchError('partial', 'SuccessFactors sitemap response exceeds the reviewed XML boundary.')
        try:
            document = ElementTree.fromstring(xml)
            entries = parse(xml)
        except (ValueError, ElementTree.ParseError) as exc:
            raise FetchError('partial', 'SuccessFactors sitemap parser rejected the response.') from exc
        if type(entries) is not dict or not 1 <= len(entries) <= MAX_POSTINGS:
            raise FetchError('partial', 'SuccessFactors sitemap did not provide a bounded positive inventory.')
        for identity, url in entries.items():
            if not isinstance(url, str) or posting_id(url) != identity:
                raise FetchError('partial', 'SuccessFactors sitemap identity disagrees with its exact job URL.')
        if document.tag != SITEMAP_NAMESPACE + 'urlset':
            raise FetchError('partial', 'SuccessFactors sitemap has an unexpected root.')
        official_job_urls = set()
        for location in document.iterfind(f'{SITEMAP_NAMESPACE}url/{SITEMAP_NAMESPACE}loc'):
            url = (location.text or '').strip()
            try:
                parts = urlsplit(url)
            except ValueError as exc:
                raise FetchError('partial', 'SuccessFactors sitemap contains a malformed location.') from exc
            if parts.scheme != 'https' or parts.netloc != host:
                raise FetchError('partial', 'SuccessFactors sitemap contains a location outside the board.')
            if 'job' in parts.path.split('/'):
                posting_id(url)
                if url in official_job_urls:
                    raise FetchError('partial', 'SuccessFactors sitemap repeats a posting URL.')
                official_job_urls.add(url)
        if set(entries.values()) != official_job_urls:
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
