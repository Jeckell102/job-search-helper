import copy
import json
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from job_search_helper.ats import HTTPResponse, fetch_inventory, resolve_board
from job_search_helper.browser_scraper import with_browser_fallback, fetch_browser_inventory
from job_search_helper.discovery import discover_board
from job_search_helper.engine import _inventory_source

URL = 'https://jobs.lever.co/zoox?location=Foster+City%2C+CA'
class Transport:
    def __init__(self, replies): self.replies, self.urls = iter(replies), []
    def get(self, url):
        self.urls.append(url)
        return HTTPResponse(200, json.dumps(next(self.replies)).encode())

def posting():
    item = json.loads((Path(__file__).parent / 'fixtures/lever.json').read_text())[0]
    item['categories']['location'] = 'Seattle, WA'
    item['categories']['allLocations'] = ['Seattle, WA', 'Foster City, CA']
    return item

class Sources(unittest.TestCase):
    def test_existing_greenhouse_boards(self):
        for token in ('figureai', 'archer56'):
            self.assertEqual(resolve_board('Greenhouse', 'https://job-boards.greenhouse.io/' + token)[1], token)

    def test_zoox_location_persists_in_all_requests_and_identity(self):
        t = Transport([[posting()], []])
        result = fetch_inventory('Lever', URL, 'id', 'Zoox', t)
        self.assertEqual(result.status, 'complete')
        self.assertEqual(len(result.jobs), 1)
        self.assertTrue(all(parse_qs(urlsplit(u).query)['location'] == ['Foster City, CA'] for u in t.urls))
        self.assertEqual([parse_qs(urlsplit(u).query)['skip'][0] for u in t.urls], ['0', '1'])
        self.assertEqual(_inventory_source(result.source_url), _inventory_source(URL))
        self.assertNotEqual(_inventory_source(URL), _inventory_source('https://jobs.lever.co/zoox'))
        self.assertNotEqual(_inventory_source(URL), _inventory_source('https://jobs.lever.co/zoox?location=Seattle'))

    def test_unverified_location_is_not_complete(self):
        item = posting()
        item['categories']['allLocations'] = ['Seattle, WA']
        result = fetch_inventory('Lever', URL, 'id', 'Zoox', Transport([[item], []]))
        self.assertEqual(result.status, 'partial')
        self.assertFalse(result.jobs)

    def test_scoped_failure_never_falls_back_to_browser(self):
        item = posting()
        item['categories']['allLocations'] = []
        t = Transport([[item], []])
        with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
            result = with_browser_fallback(lambda *a: fetch_inventory(*a, transport=t))('Lever', URL, 'id', 'Zoox')
            self.assertEqual(result.status, 'partial')
            browser.assert_not_called()
        self.assertEqual(fetch_browser_inventory('Lever', URL, 'id', 'Zoox').status, 'unsupported')

    def test_unsupported_and_ambiguous_filters_are_rejected(self):
        for query in ('location=One&location=Two', 'location=', 'location=One&team=Product', 'level=Senior'):
            self.assertEqual(fetch_inventory('Lever', 'https://jobs.lever.co/zoox?' + query, 'id', 'Zoox').status, 'unsupported')

    def test_sri_careers_discovery(self):
        class T:
            def get(self, url):
                return HTTPResponse(200, b'<a href="https://careers-sri.icims.com/jobs/intro?hashed=-625949242">Search jobs</a>', {})
        board, _ = discover_board('', 'https://www.sri.com/careers/', T())
        self.assertEqual(board, ('iCIMS', 'search', 'https://careers-sri.icims.com/jobs/'))
