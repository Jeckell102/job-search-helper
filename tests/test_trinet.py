import unittest

from job_search_helper.ats import HTTPResponse
from job_search_helper.trinet import SOURCE, fetch_trinet


class Transport:
    def __init__(self, body):
        self.body = body

    def get(self, url):
        self.url = url
        return HTTPResponse(200, self.body.encode(), {})


class TriNetTests(unittest.TestCase):
    def test_verified_empty_board_is_complete(self):
        t = Transport('<h1>Our Current Job Openings</h1><p>Sorry, we have no current job openings.</p>')
        result = fetch_trinet(SOURCE, 'COMP-0269', 'Uhnder', t)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.jobs, [])

    def test_postings_fail_closed_until_detail_schema_is_verified(self):
        t = Transport('<h1>Our Current Job Openings</h1><a href="/companies/32235-uhnder-inc/jobs/1-role">Role</a>')
        result = fetch_trinet(SOURCE, 'COMP-0269', 'Uhnder', t)
        self.assertEqual(result.status, 'partial')

    def test_separator_only_table_is_verified_empty(self):
        t = Transport('''<h1>Our Current Job Openings</h1>
          <table class="table thire-tbl-content wrap job-list"><thead><tr><th>Role</th></tr></thead>
          <tbody class="sortable"><tr class="job separator" id="position_1"><td>Operations</td></tr></tbody></table>''')
        result = fetch_trinet(SOURCE, 'COMP-0269', 'Uhnder', t)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.jobs, [])


if __name__ == '__main__':
    unittest.main()
