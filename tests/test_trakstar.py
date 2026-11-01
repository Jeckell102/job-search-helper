import html
import json
from urllib.parse import urlsplit

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.trakstar import BOARD_URL, RSS_URL, fetch_trakstar

ROOT_URL = 'https://jobsatseptentrio.hire.trakstar.com/'


def rss(items, *, mutate=''):
    rows = []
    for ident, title, desc in items:
        link = f'http://jobsatSeptentrio.hire.trakstar.com/jobs/{ident}'
        body = desc if 'id="job_description"' in desc else f'<div id="job_description"><p>{desc}</p></div>'
        rows.append(f'<item><title>{html.escape(title)}</title><link>{link}</link><description>{html.escape(body)}</description><guid>{link}</guid></item>')
    text = f'<rss version="2.0"><channel><title>Jobs at Septentrio</title><link>http://recruiterbox.com/jobfeeds/jobsatSeptentrio</link><description>Current open positions at Septentrio</description>{"".join(rows)}</channel></rss>'
    return text.replace(*mutate).encode() if mutate else text.encode()


def board(items, *, total=None, start=1, end=None, next_url='null'):
    total = len(items) if total is None else total
    end = end if end is not None else start + len(items) - 1
    cards = ''.join(f'<div class="js-card"><a href="/jobs/{ident}/"><h3 class="js-job-list-opening-name" title="{html.escape(title)}">{html.escape(title)}</h3></a></div>' for ident, title, _ in items)
    init = {'total_jobs': total, 'paginator': {'start_index': str(start), 'end_index': str(end), 'total_results': str(total), 'next_page_url': None if next_url == 'null' else next_url}}
    return f'<html><body>{cards}<script>RB = {{ init_data: {json.dumps(init)} }};</script></body></html>'.encode()


def detail(ident, title, desc):
    return HTTPResponse(200, f'<html><body><div id="job_meta"><p>Location: Leuven</p></div><div id="job_description"><p>{html.escape(desc)}</p><script>SECRET_JS</script></div></body></html>'.encode(), {})


class Transport:
    def __init__(self, items, *, second_rss=None, html_items=None, html_drift=False, rss_body=None):
        self.items = items; self.second_rss = second_rss; self.html_items = html_items or items; self.html_drift = html_drift; self.rss_calls = 0; self.board_calls = 0; self.rss_body = rss_body
    def get(self, url):
        p = urlsplit(url)
        if p.path.endswith('/jobfeeds/jobsatSeptentrio'):
            self.rss_calls += 1; rows = self.second_rss if self.rss_calls > 1 and self.second_rss is not None else self.items
            return HTTPResponse(200, self.rss_body if self.rss_body is not None else rss(rows), {})
        if p.path == '/' or p.path == '/jobs':
            self.board_calls += 1; rows = self.html_items
            if self.html_drift and self.board_calls > 1: rows = rows[:-1]
            return HTTPResponse(200, board(rows, total=len(self.html_items)), {})
        ident = p.path.rstrip('/').rsplit('/', 1)[-1]
        title = dict((row[0], row[1]) for row in self.items).get(ident, 'Unknown')
        desc = dict((row[0], row[2]) for row in self.items).get(ident, '')
        return detail(ident, title, desc)


def test_complete_rss_and_html_membership_scope():
    items = [('fk01', 'Engineer', 'Septentrio responsibilities and qualifications.')]
    result = fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport(items))
    assert result.status == 'complete', result.reason
    assert len(result.jobs) == 1 and result.jobs[0]['posting_id'] == 'fk01'
    assert result.jobs[0]['company_id'] == 'COMP-0253'
    assert urlsplit(result.jobs[0]['url']).hostname == 'jobsatseptentrio.hire.trakstar.com'


def test_normal_root_row_uses_rss_and_board():
    items = [('fk01', 'Engineer', 'Septentrio responsibilities and qualifications.')]
    t = Transport(items)
    result = fetch_inventory('Trakstar Hire', ROOT_URL, 'COMP-0253', 'Septentrio', transport=t)
    assert result.status == 'complete', result.reason
    assert t.rss_calls >= 2 and t.board_calls >= 2


def test_exact_source_guards():
    for ats, url, cid, company in (('Trakstar Hire', ROOT_URL, 'OTHER', 'Septentrio'), ('Trakstar Hire', ROOT_URL, 'COMP-0253', 'Other'), ('Trakstar Hire', ROOT_URL + '?x=1', 'COMP-0253', 'Septentrio')):
        assert fetch_inventory(ats, url, cid, company, transport=Transport([])).status == 'unsupported'


def test_rss_truncated_total_and_id_title_mismatch_fail():
    items = [('fk01', 'Engineer', 'Septentrio responsibilities and qualifications.'), ('fk02', 'Analyst', 'Septentrio responsibilities and qualifications.')]
    for body in (rss(items[:-1]), rss(items, mutate=('fk02', 'wrong'))):
        assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport(items, rss_body=body)).status == 'partial'
    t = Transport(items, html_items=items[:-1])
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', t).status == 'partial'


def test_duplicates_missing_description_and_wrong_link_fail():
    items = [('fk01', 'Engineer', 'Septentrio responsibilities and qualifications.')]
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport(items + items)).status == 'partial'
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport([('fk01', 'Engineer', '')])).status == 'partial'
    bad = rss(items).replace(b'jobsatSeptentrio.hire.trakstar.com/jobs/fk01', b'other.example/jobs/fk01')
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport(items, rss_body=bad)).status == 'partial'


def test_description_script_removed_and_mutation_rechecked():
    first = [('fk01', 'Engineer', 'Septentrio responsibilities and qualifications.')]
    changed = [('fk01', 'Engineer', 'Changed description for stable ID.')]
    good = fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport(first))
    assert good.status == 'complete' and 'SECRET_JS' not in good.jobs[0]['description']
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport(first, second_rss=changed)).status == 'partial'


def test_malformed_and_http_failure_fail_closed():
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Transport([], rss_body=b'<rss><channel>')).status == 'partial'
    class Denied(Transport):
        def get(self, url): return HTTPResponse(403, b'denied', {})
    assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', Denied([])).status == 'blocked'


def test_multipage_board_visits_every_published_page_and_rejects_missing_or_duplicate_records():
    items = [(f'fk{i:02d}', f'Role {i}', 'Septentrio responsibilities and qualifications.') for i in range(20)]

    class MultiPage(Transport):
        def __init__(self, mode=None):
            super().__init__(items); self.mode = mode; self.pages = []
        def get(self, url):
            p = urlsplit(url)
            if p.path in {'/', '/jobs'}:
                page = int(dict(__import__('urllib.parse', fromlist=['parse_qsl']).parse_qsl(p.query)).get('page', '1'))
                self.pages.append(page)
                if page == 1:
                    return HTTPResponse(200, board(items[:10], total=20, start=1, end=10, next_url=ROOT_URL + '?page=2'), {})
                second = items[10:]
                if self.mode == 'missing': second = second[:-1]
                if self.mode == 'duplicate': second = [items[0]] + second[1:]
                return HTTPResponse(200, board(second, total=20, start=11, end=20, next_url='null'), {})
            return super().get(url)

    good = MultiPage()
    result = fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', good)
    assert result.status == 'complete', result.reason
    assert good.pages.count(1) >= 2 and good.pages.count(2) >= 2
    assert len(result.jobs) == 20
    for mode in ('missing', 'duplicate'):
        bad = MultiPage(mode)
        assert fetch_trakstar(BOARD_URL, 'COMP-0253', 'Septentrio', bad).status == 'partial'
