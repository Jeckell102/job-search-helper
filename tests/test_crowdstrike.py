import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0663'
COMPANY = 'CrowdStrike'
SOURCE = 'https://www.crowdstrike.com/careers/'
BOARD = 'https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers'
ENDPOINT = 'https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers'


class FakeTransport:
    def post(self, url, payload):
        assert url == ENDPOINT + '/jobs'
        assert payload['offset'] == 0
        return HTTPResponse(200, b'{"total": 1, "jobPostings": [{"title": "Security Engineer", "externalPath": "/job/Remote/Security-Engineer_REQ-1", "bulletFields": ["REQ-1"]}], "facets": []}')

    def get(self, url):
        assert url == ENDPOINT + '/job/Remote/Security-Engineer_REQ-1'
        return HTTPResponse(200, b'{"jobPostingInfo": {"id": "crowdstrike-1", "jobPostingSiteId": "crowdstrikecareers", "jobReqId": "REQ-1", "title": "Security Engineer", "jobDescription": "<p>Protect customers.</p>", "location": "Remote, US", "additionalLocations": [], "posted": true}}')


class CrowdStrikeRouteTests(unittest.TestCase):
    def test_exact_source_repair_uses_unfiltered_employer_workday_board(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Workday', BOARD))
        self.assertTrue(note)
        subset = BOARD + '?Job_Family=1408861ee6e2017e954d08f7b000f40b'
        self.assertEqual(repair_source('Official careers', subset, COMPANY_ID, COMPANY), ('Official careers', subset, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, 'OTHER', COMPANY), ('Official careers', SOURCE, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'), ('Official careers', SOURCE, ''))

    def test_normal_dispatch_retrieves_full_workday_posting(self):
        result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY, FakeTransport())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.ats, 'Workday')
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['posting_id'], 'crowdstrike-1')
        self.assertIn('Protect customers.', result.jobs[0]['description'])


if __name__ == '__main__':
    unittest.main()
