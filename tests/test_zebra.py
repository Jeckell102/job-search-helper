import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0538'
COMPANY = 'Zebra Technologies'
SOURCE = 'https://www.zebra.com/us/en/about-zebra/careers.html'
BOARD = 'https://zebra.wd501.myworkdayjobs.com/Zebra_careers'
ENDPOINT = 'https://zebra.wd501.myworkdayjobs.com/wday/cxs/zebra/Zebra_careers'


class FakeTransport:
    def post(self, url, payload):
        assert url == ENDPOINT + '/jobs'
        assert payload['offset'] == 0
        return HTTPResponse(200, b'{"total": 1, "jobPostings": [{"title": "Systems Engineer", "externalPath": "/job/Remote/Systems-Engineer_REQ-1", "bulletFields": ["REQ-1"]}], "facets": []}')

    def get(self, url):
        assert url == ENDPOINT + '/job/Remote/Systems-Engineer_REQ-1'
        return HTTPResponse(200, b'{"jobPostingInfo": {"id": "zebra-1", "jobPostingSiteId": "Zebra_careers", "jobReqId": "REQ-1", "title": "Systems Engineer", "jobDescription": "<p>Build Zebra products.</p>", "location": "Remote, US", "additionalLocations": [], "posted": true}}')


class ZebraRouteTests(unittest.TestCase):
    def test_exact_source_repair_uses_unfiltered_employer_workday_board(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Workday', BOARD))
        self.assertTrue(note)
        highlighted = BOARD + '?jobFamilyGroup=281a47809d0e100122c06ac3b01a0000'
        self.assertEqual(repair_source('Official careers', highlighted, COMPANY_ID, COMPANY), ('Official careers', highlighted, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, 'OTHER', COMPANY), ('Official careers', SOURCE, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'), ('Official careers', SOURCE, ''))

    def test_normal_dispatch_retrieves_full_workday_posting(self):
        result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY, FakeTransport())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.ats, 'Workday')
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['posting_id'], 'zebra-1')
        self.assertIn('Build Zebra products.', result.jobs[0]['description'])


if __name__ == '__main__':
    unittest.main()
