import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.aitech import SOURCE


def role_url(identifier):
    return f'https://aitechsystems.com/careers-3/co/locations/{identifier}/role/all/'


def listing(identifiers):
    return ''.join(f'<a href="{role_url(value)}">Role {value}</a>' for value in identifiers)


def detail(identifier, *, complete=True):
    description = ('Aitech Systems role description ' * 40) if complete else 'Short description'
    return (f'<div class="comeet-position-name">Role {identifier}</div>'
            '<div class="comeet-position-location">Chatsworth, CA</div>'
            f'<div class="comeet-user-text">{description}</div>')


class Transport:
    def __init__(self, responses): self.responses = {url: list(values) for url, values in responses.items()}
    def get(self, url): return HTTPResponse(200, self.responses[url].pop(0).encode(), {})


def responses(identifiers, *, final_identifiers=None, complete=True):
    final_identifiers = identifiers if final_identifiers is None else final_identifiers
    items = {SOURCE: [listing(identifiers), listing(final_identifiers)]}
    for value in identifiers: items[role_url(value)] = [detail(value, complete=complete)]
    return items


class AitechTests(unittest.TestCase):
    def test_normal_dispatch_accepts_inventory_counts_on_both_sides_of_stale_value(self):
        for total in (15, 18):
            identifiers = [f'id-{number}.aitech' for number in range(total)]
            with self.subTest(total=total):
                result = fetch_inventory('Browser', SOURCE, 'COMP-0428', 'Aitech Systems', transport=Transport(responses(identifiers)))
                self.assertEqual(result.status, 'complete', result.reason)
                self.assertEqual([job['posting_id'] for job in result.jobs], identifiers)

    def test_rejects_incomplete_detail_and_changed_membership(self):
        identifiers = ['one.aitech', 'two.aitech']
        for transport in (Transport(responses(identifiers, complete=False)),
                          Transport(responses(identifiers, final_identifiers=['one.aitech', 'three.aitech']))):
            with self.subTest(transport=transport):
                result = fetch_inventory('Browser', SOURCE, 'COMP-0428', 'Aitech Systems', transport=transport)
                self.assertEqual(result.status, 'partial')


if __name__ == '__main__': unittest.main()
