import json
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0731'
COMPANY = 'onsemi'
SOURCE = 'https://www.onsemi.com/careers/professionals/career-opportunities'
BOARD = 'https://hctz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001'


def response(value):
    return HTTPResponse(200, json.dumps(value).encode())


class Page:
    def get(self, url):
        assert url == BOARD
        return HTTPResponse(200, b'<base href="?siteNumber=CX_1001">')


class API:
    def get(self, url):
        if 'recruitingCEJobRequisitionDetails' in url:
            return response({'items': [{'Id': '2500775', 'Title': 'Design Engineer', 'RequisitionId': 'REQ-1',
                                        'ExternalDescriptionStr': '<p>Design semiconductors.</p>',
                                        'ExternalResponsibilitiesStr': '', 'ExternalQualificationsStr': '',
                                        'PrimaryLocation': 'Phoenix, AZ', 'otherWorkLocations': [], 'secondaryLocations': []}]})
        return response({'items': [{'TotalJobsCount': 1, 'requisitionList': [{'Id': '2500775'}]}]})


class OnsemiRouteTests(unittest.TestCase):
    def test_exact_source_repair_uses_unfiltered_oracle_site(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Oracle Fusion', BOARD))
        self.assertTrue(note)
        subset = BOARD + '/requisitions?selectedCategoriesFacet=300000006382320'
        self.assertEqual(repair_source('Official careers', subset, COMPANY_ID, COMPANY), ('Official careers', subset, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, 'OTHER', COMPANY), ('Official careers', SOURCE, ''))
        self.assertEqual(repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'), ('Official careers', SOURCE, ''))

    def test_normal_dispatch_retrieves_full_oracle_posting_and_rereads_listing(self):
        result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY, API(), discovery_transport=Page())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['posting_id'], '2500775')
        self.assertIn('Design semiconductors.', result.jobs[0]['description'])


if __name__ == '__main__':
    unittest.main()
