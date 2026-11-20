import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.black_river import SOURCE


def listing(identifiers):
    return '<html>' + ''.join(f'<a href="/2027/01/role-{identifier}/">Role {identifier}</a>' for identifier in identifiers) + '</html>'


def detail(identifier, *, complete=True):
    body = ('Black River Systems Company ' * 40) if complete else 'Black River'
    return f'<html><h1>Role {identifier}</h1><p>{body}</p></html>'


class Transport:
    def __init__(self, responses):
        self.responses = {url: list(values) for url, values in responses.items()}

    def get(self, url):
        return HTTPResponse(200, self.responses[url].pop(0).encode(), {})


def responses(identifiers, *, final_identifiers=None, complete=True):
    final_identifiers = identifiers if final_identifiers is None else final_identifiers
    items = {SOURCE: [listing(identifiers), listing(final_identifiers)]}
    for identifier in identifiers:
        url = f'https://www.blackriversystems.com/2027/01/role-{identifier}/'
        items[url] = [detail(identifier, complete=complete)]
    return items


class BlackRiverTests(unittest.TestCase):
    def test_normal_dispatch_accepts_current_count_without_a_historical_cap(self):
        identifiers = [str(number) for number in range(1, 16)]
        result = fetch_inventory('Black River WordPress', SOURCE, 'COMP-0166', 'Black River Systems Company', transport=Transport(responses(identifiers)))
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual([job['posting_id'] for job in result.jobs], [f'/2027/01/role-{identifier}' for identifier in identifiers])

    def test_rejects_empty_unproven_listing_incomplete_details_and_changed_membership(self):
        cases = [
            Transport({SOURCE: [listing([])]}),
            Transport(responses(['1'], complete=False)),
            Transport(responses(['1', '2'], final_identifiers=['1', '3'])),
        ]
        for transport in cases:
            with self.subTest(transport=transport):
                result = fetch_inventory('Black River WordPress', SOURCE, 'COMP-0166', 'Black River Systems Company', transport=transport)
                self.assertEqual(result.status, 'partial')


if __name__ == '__main__':
    unittest.main()
