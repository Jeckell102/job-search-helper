"""HX5 Taleo pages have a generic H2; JobPosting contains the role title."""
import json
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from job_search_helper.ats import FetchError
from job_search_helper.hx5 import SOURCE, _url, fetch_hx5, parse_posting


def data(rid='5515', title='Acquisition Manager'):
    return {'@type': 'JobPosting', '@context': 'http://schema.org', 'title': title,
            'url': _url('/viewRequisition', rid=rid), 'identifier': {'value': rid},
            'hiringOrganization': {'name': 'HX5, LLC'}, 'jobLocation': {'address': {
                'addressLocality': 'US-OK-Oklahoma City', 'addressRegion': 'Oklahoma',
                'addressCountry': {'name': 'US'}}},
            'description': '<p>HX5 is seeking qualified candidates to deploy customer hardware. '
                           + 'Perform technical integration and support customer operations. ' * 8 + '</p>'}


def page(record=None, headings='Position Description'):
    if record is None:
        record = data()
    return '<h2>' + headings + '</h2><script type="application/ld+json">' + json.dumps(record) + '</script>'


class DetailTests(unittest.TestCase):
    def parse(self, record=None, **kwargs):
        return parse_posting(page(record, **kwargs), data()['url'], 'COMP-0448', 'HX5')

    def test_actual_title_location_and_description_are_not_page_heading(self):
        row = self.parse(headings='Position Description</h2><h3>Technical Skills')
        self.assertEqual(row['title'], 'Acquisition Manager')
        self.assertEqual(row['location'], 'Oklahoma City, Oklahoma, US')
        self.assertEqual(row['posting_id'], '5515')
        self.assertEqual(row['req_id'], '5515')
        self.assertNotIn('Position Description', row['description'])
        self.assertIn('customer hardware', row['description'])

    def test_same_titled_requisitions_keep_distinct_identities(self):
        for rid in ('5515', '5536'):
            d = data(rid)
            row = parse_posting(page(d), d['url'], 'COMP-0448', 'HX5')
            self.assertEqual(row['posting_id'], rid)
            self.assertEqual(row['url'], d['url'])
            self.assertEqual(row['title'], 'Acquisition Manager')

    def test_missing_or_generic_structured_title_fails_closed(self):
        for title in ('', 'Position Description', 'Position Description\nTechnical Skills'):
            d = data(title=title)
            with self.subTest(title=title), self.assertRaises(FetchError):
                self.parse(d)
        with self.assertRaises(FetchError):
            parse_posting('<h2>Position Description</h2>', data()['url'], 'COMP-0448', 'HX5')

    def test_employer_requisition_url_and_location_must_match(self):
        changes = [{'hiringOrganization': {'name': 'Other employer'}}, {'identifier': {'value': '9999'}},
                   {'url': _url('/viewRequisition', rid='9999')}, {'jobLocation': {}},
                   {'jobLocation': 'invalid'}, {'description': 'Too short'}]
        for changeset in changes:
            with self.subTest(changes=changeset), self.assertRaises(FetchError):
                self.parse({**data(), **changeset})

    def test_ambiguous_or_malformed_schema_is_not_replaced_with_generic_heading(self):
        for html in (page([data(), data()]), '<h2>Position Description</h2><script type="application/ld+json">{bad}</script>'):
            with self.subTest(html=html[:50]), self.assertRaises(FetchError):
                parse_posting(html, data()['url'], 'COMP-0448', 'HX5')


class InventoryTests(unittest.TestCase):
    def fetch(self, *, invalid_second=False):
        class Transport:
            def get(self, url):
                if urlsplit(url).path.endswith('/searchResults'):
                    body = '<h3>Positions Matched</h3>2' + ''.join(
                        '<a href="' + data(rid)['url'] + '">' + data(rid)['title'] + '</a>'
                        for rid in ('5515', '5536'))
                else:
                    rid = parse_qs(urlsplit(url).query)['rid'][0]
                    d = data(rid)
                    if invalid_second and rid == '5536':
                        d['title'] = 'Position Description'
                    body = page(d)
                return SimpleNamespace(status=200, body=body.encode())
        return fetch_hx5(SOURCE, 'COMP-0448', 'HX5', Transport())

    def test_complete_inventory_contains_real_titles_and_locations(self):
        result = self.fetch()
        self.assertEqual(result.status, 'complete')
        self.assertEqual(len(result.jobs), 2)
        self.assertTrue(all(j['title'] == 'Acquisition Manager' for j in result.jobs))
        self.assertTrue(all(j['location'] for j in result.jobs))

    def test_bad_detail_keeps_partial_inventory_without_false_completeness(self):
        result = self.fetch(invalid_second=True)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 1)
        self.assertIn('title', result.reason)


if __name__ == '__main__':
    unittest.main()
