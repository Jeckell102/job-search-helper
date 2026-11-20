import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0667'
COMPANY = 'Bentley Systems'
SOURCE = 'https://www.bentley.com/careers/'
BOARD = 'https://bentleysystems.wd5.myworkdayjobs.com/bentley'
ENDPOINT = 'https://bentleysystems.wd5.myworkdayjobs.com/wday/cxs/bentleysystems/bentley'


class FakeTransport:
    def post(self, url, payload):
        assert url == ENDPOINT + '/jobs'
        assert payload['offset'] == 0
        return HTTPResponse(200, b'{"total": 1, "jobPostings": [{"title": "Software Engineer", "externalPath": "/job/Remote/Software-Engineer_REQ-1", "bulletFields": ["REQ-1"]}], "facets": []}')

    def get(self, url):
        assert url == ENDPOINT + '/job/Remote/Software-Engineer_REQ-1'
        return HTTPResponse(200, b'{"jobPostingInfo": {"id": "bentley-1", "jobPostingSiteId": "bentley", "jobReqId": "REQ-1", "title": "Software Engineer", "jobDescription": "<p>Build infrastructure software.</p>", "location": "Remote, US", "additionalLocations": [], "posted": true}}')


class BentleyRouteTests(unittest.TestCase):
    def test_exact_source_repair_uses_unfiltered_employer_workday_board(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Workday', BOARD))
        self.assertTrue(note)
        keyword = BOARD + '?q=AI'
        self.assertEqual(repair_source('Official careers', keyword, COMPANY_ID, COMPANY), ('Official careers', keyword, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, 'OTHER', COMPANY), ('Official careers', SOURCE, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'), ('Official careers', SOURCE, ''))

    def test_normal_dispatch_retrieves_full_workday_posting(self):
        result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY, FakeTransport())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.ats, 'Workday')
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['posting_id'], 'bentley-1')
        self.assertIn('Build infrastructure software.', result.jobs[0]['description'])


if __name__ == '__main__':
    unittest.main()
