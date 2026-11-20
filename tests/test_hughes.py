import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from job_search_helper.ats import FetchError, HTTPResponse, _safe_api_url, fetch_inventory
from job_search_helper.hughes import API, SOURCE, _page_url


def payload(total, identifiers, *, tag='Hughes', include_jobs=True):
    jobs = []
    if include_jobs:
        jobs = [{'data': {
            'req_id': identifier, 'title': f'Role {identifier}',
            'description': f'<p>Description for {identifier}</p>',
            'tags4': [tag], 'location_name': 'Germantown, MD',
            'department': 'Engineering', 'posted_date': '2026-11-17',
        }} for identifier in identifiers]
    return HTTPResponse(200, json.dumps({'totalCount': total, 'jobs': jobs}).encode(), {})


class Transport:
    def __init__(self, responses):
        self.responses = {url: list(values) for url, values in responses.items()}
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return self.responses[url].pop(0)


def pages(total, identifiers, *, page_size=10, final_identifiers=None):
    final_identifiers = identifiers if final_identifiers is None else final_identifiers
    results = {}
    for current in (identifiers, final_identifiers):
        for page, start in enumerate(range(0, len(current), page_size), 1):
            results.setdefault(_page_url(page), []).append(payload(total, current[start:start + page_size]))
    if total == 0:
        results[_page_url(1)] = [payload(0, []), payload(0, [])]
    return results


class HughesTests(unittest.TestCase):
    def test_normal_dispatch_dynamically_paginates_above_and_below_historical_count(self):
        for identifiers, page_size in (([str(n) for n in range(1, 7)], 10),
                                       ([str(n) for n in range(1, 22)], 10)):
            with self.subTest(total=len(identifiers)):
                transport = Transport(pages(len(identifiers), identifiers, page_size=page_size))
                result = fetch_inventory('Browser', SOURCE, 'COMP-0118', 'Hughes Network Systems', transport=transport)
                self.assertEqual(result.status, 'complete', result.reason)
                self.assertEqual([job['posting_id'] for job in result.jobs], identifiers)
                self.assertEqual(len(transport.urls), 2 * ((len(identifiers) + page_size - 1) // page_size))

    def test_normal_dispatch_accepts_explicit_empty_inventory(self):
        transport = Transport(pages(0, []))
        result = fetch_inventory('Browser', SOURCE, 'COMP-0118', 'Hughes Network Systems', transport=transport)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.jobs, [])
        self.assertEqual(transport.urls, [_page_url(1), _page_url(1)])

    def test_rejects_missing_listing_duplicate_ids_and_changed_final_membership(self):
        cases = [
            Transport({_page_url(1): [HTTPResponse(200, b'{}', {})]}),
            Transport({_page_url(1): [payload(2, ['1', '1'])]}),
            Transport(pages(2, ['1', '2'], final_identifiers=['1', '3'])),
        ]
        for transport in cases:
            with self.subTest(transport=transport):
                result = fetch_inventory('Browser', SOURCE, 'COMP-0118', 'Hughes Network Systems', transport=transport)
                self.assertEqual(result.status, 'partial')

    def test_rejects_truncated_page_and_non_hughes_row(self):
        truncated = Transport({_page_url(1): [payload(3, ['1', '2'])], _page_url(2): [payload(3, [])]})
        wrong_scope = Transport({_page_url(1): [payload(1, ['1'], tag='EchoStar')]})
        for transport in (truncated, wrong_scope):
            with self.subTest(transport=transport):
                result = fetch_inventory('Browser', SOURCE, 'COMP-0118', 'Hughes Network Systems', transport=transport)
                self.assertEqual(result.status, 'partial')

    def test_real_transport_allows_only_scoped_hughes_public_api(self):
        _safe_api_url(_page_url(1))
        for url in (API, API + '?tags4=Hughes&page=0', API + '?tags4=Other&page=1',
                    API + '?tags4=Hughes&page=1&location=MD',
                    'https://jobs.echostar.com/api/admin?tags4=Hughes&page=1'):
            with self.subTest(url=url):
                with self.assertRaises(FetchError):
                    _safe_api_url(url)


if __name__ == '__main__':
    unittest.main()
