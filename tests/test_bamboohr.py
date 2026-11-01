from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from job_search_helper.ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.bamboohr import _discover, _listing, _posting, is_bamboohr_host
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.engine import _inventory_source
from test_ats import Transport, response


ROOT = 'https://acme.bamboohr.com'
BOARD = ROOT + '/careers'
EMPLOYER = 'https://www.acme.example/careers/'


def item(ident='1', **changes):
    return dict({'id': ident, 'jobOpeningName': 'Field Engineer ' + str(ident),
                 'departmentLabel': 'Engineering', 'location': {'city': 'Dayton', 'state': 'Ohio'},
                 'atsLocation': {}, 'locationType': '0'}, **changes)


def listing(items=None, **meta):
    items = [item()] if items is None else items
    return response({'meta': dict({'totalCount': len(items)}, **meta), 'result': items})


def detail(ident='1', **changes):
    data = dict({'jobOpeningShareUrl': ROOT + '/careers/' + ident, 'jobOpeningName': 'Field Engineer ' + ident,
                 'jobOpeningStatus': 'Open', 'description': '<p>Install and integrate mission systems.</p><p>Travel 20%.</p>',
                 'location': {'city': 'Dayton', 'state': 'Ohio', 'addressCountry': 'United States'},
                 'atsLocation': {'city': None, 'country': None}, 'departmentLabel': 'Engineering',
                 'compensation': '$140000 - $160000 per year', 'datePosted': '2026-10-01', 'locationType': '0'}, **changes)
    return response({'meta': {}, 'result': {'jobOpening': data, 'formFields': {'ignored': 'Not a description'}}})


def page(links=None, body=''):
    links = [BOARD] if links is None else links
    return HTTPResponse(200, (body + ''.join(f'<a href="{link}">Careers</a>' for link in links)).encode(), {'content-type': 'text/html'})


class BambooHRTests(unittest.TestCase):
    def setUp(self):
        capture = redirect_stderr(StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, responses, url=BOARD, pages=(), ats='BambooHR'):
        api, discovery = Transport(responses), Transport(pages)
        return fetch_inventory(ats, url, 'C-1', 'Acme', api, discovery_transport=discovery), api, discovery

    def test_complete_public_feed_and_full_job_description(self):
        result, api, pages = self.fetch([listing([item('2'), item()]), detail(), detail('2'), listing([item(), item('2')])])
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(api.urls, [ROOT + '/careers/list', ROOT + '/careers/1/detail', ROOT + '/careers/2/detail', ROOT + '/careers/list'])
        self.assertEqual(pages.urls, [])
        self.assertEqual(result.source_url, BOARD)
        job = result.jobs[0]
        self.assertEqual(job['posting_id'], '1')
        self.assertEqual(job['ats'], 'BambooHR')
        self.assertEqual(job['url'], BOARD + '/1')
        self.assertIn('Travel 20%', job['description'])
        self.assertNotIn('Not a description', job['description'])
        self.assertEqual(job['location'], 'Dayton, Ohio, United States')
        self.assertEqual(job['work_arrangement'], 'On-site')
        self.assertEqual(job['compensation'], '$140000 - $160000 per year')
        self.assertEqual(job['created_at'], '2026-10-01')

    def test_public_careers_aliases_and_discovery_normalize(self):
        for path in ('/careers/', '/jobs/', '/jobs/embed.php', '/js/jobs2.php', '/js/embed.js', '/careers/12', '/jobs/view.php?id=12'):
            self.assertEqual(resolve_board('BambooHR', ROOT + path), ('BambooHR', '/careers', ROOT))
        self.assertEqual(_inventory_source(BOARD + '?utm_source=company'), BOARD)
        self.assertNotEqual(_inventory_source(BOARD), _inventory_source('https://other.bamboohr.com/careers'))
        result, _, _ = self.fetch([listing(), detail(), listing()], ROOT + '/jobs/?utm_source=employer', ats='Browser')
        self.assertEqual(result.status, 'complete', result.reason)

    def test_safe_transport_allows_only_public_read_endpoints(self):
        for url in (ROOT + '/careers/list', ROOT + '/careers/42/detail'):
            _safe_api_url(url)
        for url in (ROOT + '/api/v1/employees', ROOT + '/careers/1/apply', BOARD, ROOT + '/careers/list?departmentId=5',
                    ROOT + '/careers/../1/detail', ROOT + '/careers/list#filter', 'https://acme.bamboohr.com.evil.test/careers/list',
                    'http://acme.bamboohr.com/careers/list', 'https://api.bamboohr.com/careers/list'):
            with self.assertRaises(FetchError, msg=url):
                _safe_api_url(url)
        with self.assertRaises(FetchError):
            HTTPTransport().post(ROOT + '/careers/list', {})

    def test_bad_configuration_never_makes_requests(self):
        for url, ats in ((BOARD + '?departmentId=5', 'BambooHR'), (BOARD + '#filter', 'BambooHR'),
                         (BOARD + '/1', 'BambooHR'), (BOARD, 'BambooHR shared parent'), (BOARD, 'Greenhouse'),
                         ('https://localhost/careers', 'BambooHR'), ('https://user:pass@acme.bamboohr.com/careers', 'BambooHR')):
            result, api, pages = self.fetch([], url, ats=ats)
            self.assertEqual(result.status, 'unsupported', (url, result.reason))
            self.assertEqual(api.urls + pages.urls, [])

    def test_zero_jobs_requires_valid_metadata_and_final_recheck(self):
        result, api, _ = self.fetch([listing([]), listing([])])
        self.assertEqual(result.status, 'complete')
        self.assertEqual(result.jobs, [])
        self.assertEqual(len(api.urls), 2)
        for bad in (response([]), response({'result': []}), listing([], totalCount=None), listing([], totalCount=False),
                    listing([], totalCount=1), listing([], nextCursor='more'), listing([], hasMore=True)):
            result, _, _ = self.fetch([bad])
            self.assertEqual(result.status, 'partial')

    def test_duplicates_bad_ids_and_counts_never_reach_details(self):
        for bad in (listing([item(), item()]), listing([item(id='../2')]), listing([item(id=1)]),
                    listing([item(jobOpeningName='')]), listing([None]), listing(totalCount=2)):
            result, api, _ = self.fetch([bad])
            self.assertEqual(result.status, 'partial')
            self.assertEqual(len(api.urls), 1)

    def test_detail_requires_matching_open_job_and_full_description(self):
        for change in ({'jobOpeningShareUrl': ROOT + '/careers/2'}, {'jobOpeningShareUrl': 'https://other.bamboohr.com/careers/1'},
                       {'jobOpeningStatus': 'Closed'}, {'jobOpeningName': 'Changed'}, {'description': ''}, {'description': None},
                       {'location': []}, {'locationType': '9'}):
            # An empty location collection is treated as unknown, so use a nonempty invalid shape.
            if change == {'location': []}:
                change = {'location': ['bad']}
            result, _, _ = self.fetch([listing(), detail(**change)])
            self.assertEqual(result.status, 'partial', change)
            self.assertEqual(result.jobs, [])

    def test_remote_hybrid_and_compensation_are_not_inferred(self):
        for location_type, expected in (('1', 'Remote'), ('2', 'Hybrid'), (None, '')):
            result, _, _ = self.fetch([listing(), detail(locationType=location_type, location={}, compensation='$80 hourly'), listing()])
            self.assertEqual(result.status, 'complete', result.reason)
            self.assertEqual(result.jobs[0]['work_arrangement'], expected)
            self.assertEqual(result.jobs[0]['compensation'], '$80 hourly')
            self.assertEqual(result.jobs[0]['location'], '')

    def test_later_detail_failure_retains_successful_jobs(self):
        result, _, _ = self.fetch([listing([item(), item('2')]), detail(), HTTPResponse(503, b'Unavailable')])
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 1)
        self.assertIn('job detail 2', result.reason)

    def test_challenges_and_redirects_never_establish_closure(self):
        for failed, expected in ((HTTPResponse(403, b'Denied'), 'blocked'),
                                 (HTTPResponse(200, b'<title>Just a moment</title>cf-chl-'), 'blocked'),
                                 (HTTPResponse(302, b'', {'Location': 'https://elsewhere.example'}), 'failed'),
                                 (HTTPResponse(200, b'not JSON'), 'partial')):
            result, api, _ = self.fetch([failed])
            self.assertEqual(result.status, expected)
            self.assertEqual(len(api.urls), 1)

    def test_final_changed_feed_including_empty_becoming_nonempty_is_partial(self):
        for responses in ([listing(), detail(), listing([])], [listing([]), listing()],
                          [listing(), detail(), listing([item(jobOpeningName='Changed')])]):
            result, _, _ = self.fetch(responses)
            self.assertEqual(result.status, 'partial')
            self.assertIn('changed', result.reason)

    def test_embedded_board_discovered_and_scope_rechecked(self):
        embed = page([], f'<iframe src="{BOARD}"></iframe>')
        result, _, pages = self.fetch([listing(), detail(), listing()], EMPLOYER, [embed, embed])
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.source_url, BOARD)
        self.assertEqual(pages.urls, [EMPLOYER, EMPLOYER])

    def test_job_links_discover_all_listed_jobs_without_guessing_tenant(self):
        employer = page([BOARD + '/1', BOARD + '/2'])
        result, _, _ = self.fetch([listing([item(), item('2')]), detail(), detail('2'), listing([item(), item('2')])], EMPLOYER, [employer, employer])
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.source_url, EMPLOYER)
        self.assertNotEqual(_inventory_source(result.source_url), _inventory_source(BOARD))

    def test_parent_board_is_limited_to_employer_links_and_remains_incomplete(self):
        employer = page([BOARD, BOARD + '/1'])
        result, api, _ = self.fetch([listing([item(), item('2')]), detail(), listing([item(), item('2')])], EMPLOYER, [employer, employer])
        self.assertEqual(result.status, 'partial')
        self.assertEqual([j['posting_id'] for j in result.jobs], ['1'])
        self.assertNotIn(ROOT + '/careers/2/detail', api.urls)
        self.assertIn('subset', result.reason)

    def test_stale_employer_links_do_not_become_zero_company_inventory(self):
        employer = page([BOARD + '/1'])
        result, _, _ = self.fetch([listing([]), listing([])], EMPLOYER, [employer, employer])
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.jobs, [])

    def test_changed_employer_scope_during_scan_is_partial(self):
        result, _, _ = self.fetch([listing(), detail(), listing()], EMPLOYER, [page([BOARD + '/1']), page([BOARD + '/2'])])
        self.assertEqual(result.status, 'partial')
        self.assertIn('scope changed', result.reason)

    def test_ambiguous_filtered_or_empty_discovery_does_not_fetch_parent_board(self):
        for employer in (page([BOARD, 'https://other.bamboohr.com/careers']), page([BOARD + '?departmentId=9']), page([])):
            result, api, _ = self.fetch([], EMPLOYER, [employer])
            self.assertIn(result.status, {'partial', 'unsupported'})
            self.assertEqual(api.urls, [])

    def test_same_site_discovery_and_bamboo_redirect(self):
        for pages in ([page(['openings']), page()], [HTTPResponse(302, b'', {'location': BOARD})]):
            repeated = pages + pages
            result, _, _ = self.fetch([listing(), detail(), listing()], EMPLOYER, repeated)
            self.assertEqual(result.status, 'complete', result.reason)
        result, api, _ = self.fetch([], EMPLOYER, [HTTPResponse(302, b'', {'location': 'https://other.example/careers'})])
        self.assertEqual(result.status, 'unsupported')
        self.assertEqual(api.urls, [])

    def test_unlabelled_employer_uses_generic_discovery_and_preserves_subset(self):
        employer = page([BOARD + '/1'])
        result, _, _ = self.fetch([listing([item(), item('2')]), detail(), listing([item(), item('2')])], EMPLOYER, [employer] * 3, ats='Browser')
        self.assertEqual(result.ats, 'BambooHR')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 1)

    def test_generic_browser_fallback_cannot_replace_or_merge_scoped_results(self):
        for status in ('partial', 'unsupported', 'blocked'):
            expected = Inventory(status, ats='BambooHR')
            with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
                self.assertIs(with_browser_fallback(lambda *a: expected)('BambooHR', BOARD, 'C-1', 'Acme'), expected)
                browser.assert_not_called()

    def test_public_live_fixtures_validate_all_seven_feed_formats(self):
        fixtures = Path(__file__).parent / 'fixtures' / 'bamboohr'
        samples = sorted(fixtures.glob('*-list.json'))
        self.assertEqual(len(samples), 7)
        for path in samples:
            data = json.loads(path.read_text())
            entries = _listing(ROOT, Transport([response(data)]))
            self.assertEqual(len(entries), data['meta']['totalCount'])
        entry = json.loads((fixtures / 'plusone-list.json').read_text())['result'][0]
        job = _posting('https://plusonerobotics.bamboohr.com', entry,
                       Transport([response(json.loads((fixtures / 'plusone-detail.json').read_text()))]), 'C', 'Plus One Robotics')
        self.assertGreater(len(job['description']), 3000)
        self.assertEqual(job['compensation'], '$140,000-155,000')


if __name__ == '__main__':
    unittest.main()
