import html
from urllib.parse import parse_qsl, urlsplit

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.taleo_tbe import RSS_SOURCE, RESULT_PATH, fetch_tbe, supports_tbe

HOST = 'phh.tbe.taleo.net'
SOURCE = 'https://phh.tbe.taleo.net/phh04/ats/careers/v2/jobSearch?act=redirectCwsV2&cws=37&org=DCSCORP2'
DETAIL_PATH = '/phh04/ats/careers/v2/viewRequisition'
LEGACY_PATH = '/phh04/ats/careers/requisition.jsp'
RSS_NS = 'urn:TBERss'


def feed(items, *, channel_link=None, mutate=None):
    channel_link = channel_link or 'https://phh.tbe.taleo.net/dispatcher/servlet/DispatcherServlet?org=DCSCORP2&act=redirectCws&cws=37'
    rows = []
    for rid, title in items:
        path = LEGACY_PATH if str(rid).startswith('9') else DETAIL_PATH
        link = f'https://{HOST}{path}?org=DCSCORP2&cws=37&rid={rid}'
        desc = html.escape('DCS Corporation responsibilities and qualifications. ' * 30)
        rows.append(f'<item><title>{html.escape(title)}</title><link>{html.escape(link)}</link><guid>{html.escape(link)}</guid><tbe:reqId xmlns:tbe="{RSS_NS}">{rid}</tbe:reqId><tbe:html-description xmlns:tbe="{RSS_NS}">{desc}</tbe:html-description><tbe:location xmlns:tbe="{RSS_NS}">Remote</tbe:location></item>')
    text = f'<rss xmlns:tbe="{RSS_NS}"><channel><title>DCS Corporation Job Feed</title><link>{html.escape(channel_link)}</link>{"".join(rows)}</channel></rss>'
    return mutate(text) if mutate else text.encode()


def result_page(rows, total, start=0, next_start=None, duplicate_title=False):
    links = ''.join(f'<a class="viewJobLink" href="{DETAIL_PATH}?org=DCSCORP2&amp;cws=37&amp;rid={rid}">{title}</a><a class="btn btn-default fa fa-eye" href="{DETAIL_PATH}?org=DCSCORP2&amp;cws=37&amp;rid={rid}">View</a>' for rid, title in rows)
    if duplicate_title and rows:
        rid, title = rows[0]
        links += f'<a class="viewJobLink" href="{DETAIL_PATH}?org=DCSCORP2&amp;cws=37&amp;rid={rid}">{title}</a>'
    nxt = '' if next_start is None else f'<a href="{RESULT_PATH}?org=DCSCORP2&amp;cws=37&amp;rowFrom={next_start}">Next</a>'
    return f'<html><body>Positions Matched: {total}{links}{nxt}</body></html>'.encode()


def detail(rid, title, *, employer='DCS Corporation', description=None):
    description = description if description is not None else employer + ' responsibilities and qualifications. ' * 30
    return HTTPResponse(200, f'<html><body><strong>{title}</strong><div id="jobDescription"><p>{description}</p></div></body></html>'.encode(), {'Content-Type': 'text/html'})


class CombinedTransport:
    def __init__(self, items, *, rss_body=None, drift=False):
        self.items = items; self.rss_body = rss_body; self.calls = []; self.page_calls = {}; self.drift = drift
    def get(self, url):
        self.calls.append(url); p = urlsplit(url)
        if p.path.casefold() == '/phh04/ats/servlet/rss':
            return HTTPResponse(200, self.rss_body or feed(self.items), {'Content-Type': 'application/rss+xml'})
        if p.path.casefold() == RESULT_PATH.casefold():
            q = dict(parse_qsl(p.query)); start = int(q.get('rowFrom', '0')); self.page_calls[start] = self.page_calls.get(start, 0) + 1
            rows = self.items[start:start + 10]
            if self.drift and start and self.page_calls[start] > 1: rows = [(rows[0][0], 'Changed')] + rows[1:]
            return HTTPResponse(200, result_page(rows, len(self.items), start, start + 10 if start + 10 < len(self.items) else None), {})
        q = dict(parse_qsl(p.query)); rid = q.get('rid', ''); title = dict(self.items).get(rid, 'Unknown')
        return detail(rid, title)


def test_scope_boundaries():
    assert supports_tbe(SOURCE) and supports_tbe(RSS_SOURCE)
    for bad in (SOURCE.replace('DCSCORP2', 'OTHER'), SOURCE.replace('https://phh.tbe.taleo.net', 'https://user:pw@phh.tbe.taleo.net'), SOURCE.replace('https://phh.tbe.taleo.net', 'https://phh.tbe.taleo.net:444'), SOURCE + '#x', SOURCE + '&extra=1'):
        assert not supports_tbe(bad), bad


def test_rss_channel_and_item_scope_with_165_full_jobs():
    items = [(str(10000 + i), f'DCS Role {i}') for i in range(165)]
    for source in (SOURCE, RSS_SOURCE):
        transport = CombinedTransport(items)
        result = fetch_tbe(source, 'COMP-0447', 'DCS Corporation', transport)
        assert result.status == 'complete', result.reason
        assert len(result.jobs) == 165
        assert {job['posting_id'] for job in result.jobs} == {rid for rid, _ in items}
        assert all(job['company_id'] == 'COMP-0447' and job['company'] == 'DCS Corporation' for job in result.jobs)


def test_normal_configured_row_uses_rss_and_html_membership():
    items = [('10001', 'DCS Role')]
    transport = CombinedTransport(items)
    result = fetch_inventory('Taleo TBE', 'https://careers.dcscorp.com/', 'COMP-0447', 'DCS Corporation', transport=transport)
    assert result.status == 'complete', result.reason
    assert result.jobs[0]['posting_id'] == '10001'
    assert any(urlsplit(url).path.casefold() == '/phh04/ats/servlet/rss' for url in transport.calls)


def test_rss_truncation_and_channel_or_item_scope_fail_closed():
    items = [('10001', 'DCS Role'), ('10002', 'DCS Role 2')]
    for mutation in (
        lambda text: text.replace('</item></channel>', '</channel>'),
        lambda text: text.replace('DCS Corporation Job Feed', 'Other Employer Job Feed'),
        lambda text: text.replace('org=DCSCORP2', 'org=OTHER', 1),
        lambda text: text.replace('<guid>https://', '<guid>https://other.example/'),
        lambda text: text.replace('<tbe:html-description', '<tbe:wrongField'),
    ):
        transport = CombinedTransport(items, rss_body=feed(items, mutate=lambda text: mutation(text).encode()))
        result = fetch_tbe(RSS_SOURCE, 'COMP-0447', 'DCS Corporation', transport)
        assert result.status in {'partial', 'failed'}, result.reason


def test_malformed_rss_and_http_403_fail_closed():
    malformed = CombinedTransport([], rss_body=b'<rss><channel><item>')
    result = fetch_tbe(RSS_SOURCE, 'COMP-0447', 'DCS Corporation', malformed)
    assert result.status in {'partial', 'failed'}
    class Denied(CombinedTransport):
        def get(self, url): return HTTPResponse(403, b'denied', {})
    assert fetch_tbe(RSS_SOURCE, 'COMP-0447', 'DCS Corporation', Denied([])).status == 'blocked'


def test_html_pagination_26_and_51_and_final_title_drift():
    for count in (26, 51):
        items = [(str(20000 + i), f'HTML Role {i}') for i in range(count)]
        result = fetch_tbe(SOURCE, 'COMP-0447', 'DCS Corporation', CombinedTransport(items))
        assert result.status == 'complete', (count, result.reason)
        assert len(result.jobs) == count
    items = [(str(30000 + i), f'HTML Role {i}') for i in range(51)]
    assert fetch_tbe(SOURCE, 'COMP-0447', 'DCS Corporation', CombinedTransport(items, drift=True)).status == 'partial'


def test_view_control_does_not_duplicate_but_two_title_links_fail():
    items = [('40001', 'One'), ('40002', 'Two')]
    class DuplicateTitle(CombinedTransport):
        def get(self, url):
            p = urlsplit(url)
            if p.path.casefold() == RESULT_PATH.casefold():
                return HTTPResponse(200, result_page(self.items, len(self.items), 0, None, duplicate_title=True), {})
            return super().get(url)
    assert fetch_tbe(SOURCE, 'COMP-0447', 'DCS Corporation', CombinedTransport(items)).status == 'complete'
    assert fetch_tbe(SOURCE, 'COMP-0447', 'DCS Corporation', DuplicateTitle(items)).status == 'partial'
