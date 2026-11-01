import json
from urllib.parse import parse_qsl, urlsplit
from unittest.mock import patch

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.brightmove import SOURCE, fetch_brightmove, supports_brightmove


def listing(rows, total=None, start=1):
    total = len(rows) if total is None else total
    links = ''.join(f'<a href="/PortalViewRequirement.do?reqGK={rid}">{title}</a>' for rid, title in rows)
    end = start + len(rows) - 1
    return f'<html><body><div>Record (s) {start} - {end} of {total} record (s)</div>{links}</body></html>'.encode()


def detail(rid, title, *, employer='Mission Critical Partners', description=None, identifier=None, html_noise=True):
    description = description if description is not None else employer + ' Responsibilities and qualifications. ' * 40
    structured = {'@type': 'JobPosting', 'title': title, 'description': description,
                  'identifier': {'value': str(identifier or rid)}, 'hiringOrganization': {'name': employer},
                  'jobLocation': {'address': {'addressLocality': 'Remote, USA'}}, 'datePosted': '2026-09-23'}
    noise = '<script>FORM_SECRET();</script><form>Submit application</form>' if html_noise else ''
    body = f'<html><body><h1>Current Openings</h1><h1>{title}</h1>{noise}<div id="jobDescription">{description}</div>'
    body += '<script type="application/ld+json">' + json.dumps(structured) + '</script></body></html>'
    return HTTPResponse(200, body.encode(), {'Content-Type': 'text/html'})


class Transport:
    def __init__(self, rows=None):
        self.calls = []
        self.rows = rows or [('27785760', 'Manager of Court Technologies'), ('27785107', 'Systems Design Specialist'),
                             ('27785110', 'Technical Design Consultant'), ('27787491', 'Technology Specialist - Public Safety Applications')]

    def get(self, url):
        self.calls.append(url)
        p = urlsplit(url)
        if p.path == '/ax.do':
            q = dict(parse_qsl(p.query, keep_blank_values=True)); start = int(q.get('allOpenJobsStart', '1'))
            return HTTPResponse(200, listing(self.rows[start - 1:start + 24], len(self.rows), start), {'Content-Type': 'text/html'})
        q = dict(parse_qsl(p.query, keep_blank_values=True)); rid = q['reqGK']
        return detail(rid, dict(self.rows)[rid])


def test_scope_and_url_boundaries():
    assert supports_brightmove(SOURCE)
    for bad in (SOURCE.replace('39203', '1'), SOURCE.replace('https://j.brt.mv', 'https://user:j.brt.mv'),
                SOURCE.replace('https://j.brt.mv', 'https://j.brt.mv:444'), SOURCE + '&unexpected=1',
                SOURCE + '&allOpenJobsStart=abc'):
        assert not supports_brightmove(bad), bad


def test_normal_configured_source_uses_pinned_transport():
    transport = Transport()
    with patch('job_search_helper.brightmove.BrightMoveTransport.get', side_effect=transport.get):
        result = fetch_inventory('BrightMove', SOURCE, 'COMP-0475', 'Mission Critical Partners')
    assert result.status == 'complete', result.reason
    assert len(result.jobs) == 4


def test_full_inventory_and_recheck():
    transport = Transport(); result = fetch_brightmove(SOURCE, 'COMP-0475', 'Mission Critical Partners', transport)
    assert result.status == 'complete', result.reason
    assert {job['posting_id'] for job in result.jobs} == {row[0] for row in transport.rows}
    assert transport.calls[0] == SOURCE and transport.calls[-1] == SOURCE


def test_pagination_26_and_51_jobs():
    for count in (26, 51):
        rows = [(str(27785000 + i), f'Role {i}') for i in range(count)]
        result = fetch_brightmove(SOURCE, 'COMP-0475', 'Mission Critical Partners', Transport(rows))
        assert result.status == 'complete', (count, result.reason)
        assert len(result.jobs) == count


def test_count_mismatch_and_duplicate_ids_fail_closed():
    class BadCount(Transport):
        def get(self, url):
            if urlsplit(url).path == '/ax.do': return HTTPResponse(200, listing(self.rows, len(self.rows) + 1), {})
            return super().get(url)
    assert fetch_brightmove(SOURCE, 'COMP-0475', 'Mission Critical Partners', BadCount()).status == 'partial'
    class Duplicate(Transport):
        def get(self, url):
            if urlsplit(url).path == '/ax.do':
                rows = self.rows + [self.rows[0]]; return HTTPResponse(200, listing(rows, len(rows)), {})
            return super().get(url)
    assert fetch_brightmove(SOURCE, 'COMP-0475', 'Mission Critical Partners', Duplicate()).status == 'partial'


def test_jsonld_missing_wrong_id_wrong_employer_title_and_description_fail():
    for case in ('missing', 'wrong_id', 'wrong_employer', 'wrong_title', 'empty_description'):
        class Mutated(Transport):
            def get(self, url):
                if urlsplit(url).path == '/ax.do': return super().get(url)
                q = dict(parse_qsl(urlsplit(url).query)); rid = q['reqGK']; title = dict(self.rows)[rid]
                if case == 'missing': return HTTPResponse(200, b'<html><body><h1>no JobPosting</h1></body></html>', {})
                if case == 'wrong_id': return detail(rid, title, identifier='99999999')
                if case == 'wrong_employer': return detail(rid, title, employer='Other Employer')
                if case == 'wrong_title': return detail(rid, 'Different Title')
                return detail(rid, title, description='')
        result = fetch_brightmove(SOURCE, 'COMP-0475', 'Mission Critical Partners', Mutated())
        assert result.status == 'partial', (case, result.reason)


def test_final_nonfirst_page_count_and_title_drift_fail_closed():
    rows = [(str(27785000 + i), f'Role {i}') for i in range(51)]
    for drift in ('count', 'title'):
        class Drifting(Transport):
            def __init__(self): super().__init__(rows); self.page51_calls = 0
            def get(self, url):
                p = urlsplit(url); q = dict(parse_qsl(p.query))
                if p.path == '/ax.do' and q.get('allOpenJobsStart') == '51':
                    self.page51_calls += 1
                    if self.page51_calls >= 2 and drift == 'count': return HTTPResponse(200, listing(self.rows[50:], 52, 51), {})
                    if self.page51_calls >= 2 and drift == 'title': return HTTPResponse(200, listing([(self.rows[50][0], 'Changed')], 51, 51), {})
                return super().get(url)
        result = fetch_brightmove(SOURCE, 'COMP-0475', 'Mission Critical Partners', Drifting())
        assert result.status == 'partial', (drift, result.reason)


def test_description_uses_clean_jsonld_and_excludes_html_noise():
    from job_search_helper.brightmove import _Page, _detail
    page = _Page(); page.feed(detail('27785760', 'Manager of Court Technologies').body.decode()); page.close()
    row = _detail('https://j.brt.mv/PortalViewRequirement.do?reqGK=27785760', page,
                  'Manager of Court Technologies', 'COMP-0475', 'Mission Critical Partners')
    assert len(row['description']) > 1000
    assert 'FORM_SECRET' not in row['description'] and 'Submit application' not in row['description']
    assert row['created_at'] == '2026-09-23'
