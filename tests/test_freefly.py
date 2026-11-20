import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.freefly import HOST, SOURCE


def identifier(number):
    return f'c{number:020d}'


def listing(identifiers):
    rows = [{'id': value, 'title': f'Role {value}'} for value in identifiers]
    return f'<script>{json.dumps(rows)}</script>'


def detail(identifier, *, complete=True):
    body = ('Freefly Systems ' * 50) if complete else 'Freefly'
    return f'<html><p>{body}</p></html>'


class Transport:
    def __init__(self, responses):
        self.responses = {url: list(values) for url, values in responses.items()}

    def get(self, url):
        return HTTPResponse(200, self.responses[url].pop(0).encode(), {})


def responses(identifiers, *, final_identifiers=None, complete=True):
    final_identifiers = identifiers if final_identifiers is None else final_identifiers
    items = {SOURCE: [listing(identifiers), listing(final_identifiers)]}
    for value in identifiers:
        items[f'https://{HOST}/careers/{value}'] = [detail(value, complete=complete)]
    return items


class FreeflyTests(unittest.TestCase):
    def test_normal_dispatch_accepts_inventories_above_and_below_historical_count(self):
        for total in (14, 16):
            identifiers = [identifier(number) for number in range(total)]
            with self.subTest(total=total):
                result = fetch_inventory('Freefly Careers', SOURCE, 'COMP-0171', 'Freefly Systems', transport=Transport(responses(identifiers)))
                self.assertEqual(result.status, 'complete', result.reason)
                self.assertEqual([job['posting_id'] for job in result.jobs], identifiers)

    def test_rejects_incomplete_detail_invalid_listing_and_changed_final_membership(self):
        identifiers = [identifier(1), identifier(2)]
        cases = [
            Transport(responses(identifiers, complete=False)),
            Transport({SOURCE: ['<script>[]</script>']}),
            Transport(responses(identifiers, final_identifiers=[identifier(1), identifier(3)])),
        ]
        for transport in cases:
            with self.subTest(transport=transport):
                result = fetch_inventory('Freefly Careers', SOURCE, 'COMP-0171', 'Freefly Systems', transport=transport)
                self.assertEqual(result.status, 'partial')


if __name__ == '__main__':
    unittest.main()
