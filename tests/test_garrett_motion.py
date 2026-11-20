import json
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory, is_oracle_host
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0638'
COMPANY = 'Garrett Motion'
SOURCE = 'https://www.garrettmotion.com/careers/'
BOARD = 'https://ehth.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001'


def response(value): return HTTPResponse(200, json.dumps(value).encode())


class Page:
    def get(self, url): return HTTPResponse(200, b'<base href="?siteNumber=CX_2001">')


class API:
    def get(self, url):
        if 'recruitingCEJobRequisitionDetails' in url:
            return response({'items': [{'Id': '1', 'Title': 'Engineer', 'RequisitionId': 'G-1', 'ExternalDescriptionStr': '<p>Build mobility systems.</p>', 'ExternalResponsibilitiesStr': '', 'ExternalQualificationsStr': '', 'PrimaryLocation': 'Torrance, CA', 'otherWorkLocations': [], 'secondaryLocations': []}]})
        return response({'items': [{'TotalJobsCount': 1, 'requisitionList': [{'Id': '1'}]}]})


class GarrettMotionTests(unittest.TestCase):
    def test_em2_oracle_host_and_exact_official_route(self):
        self.assertTrue(is_oracle_host('ehth.fa.em2.oraclecloud.com'))
        self.assertFalse(is_oracle_host('ehth.fa.emx.oraclecloud.com'))
        self.assertEqual(repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)[:2], ('Oracle Fusion', BOARD))
        subset = BOARD + '/jobs?keyword=Sales'
        self.assertEqual(repair_source('Official careers', subset, COMPANY_ID, COMPANY), ('Official careers', subset, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, 'OTHER', COMPANY), ('Official careers', SOURCE, ''))

    def test_normal_dispatch_retrieves_full_oracle_posting_and_rereads_listing(self):
        result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY, API(), discovery_transport=Page())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertIn('Build mobility systems.', result.jobs[0]['description'])


if __name__ == '__main__': unittest.main()
