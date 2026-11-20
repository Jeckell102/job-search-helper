import json
import unittest

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0727'
COMPANY = 'Texas Instruments'
SOURCE = 'https://careers.ti.com/en/sites/CX/jobs'
BOARD = 'https://edbz.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX'


def response(value):
    return HTTPResponse(200, json.dumps(value).encode())


class Page:
    def get(self, url):
        assert url == BOARD
        return HTTPResponse(200, b'<base href="?siteNumber=CX">')


class API:
    def get(self, url):
        if 'recruitingCEJobRequisitionDetails' in url:
            return response({'items': [{'Id': '101', 'Title': 'Process Engineer', 'RequisitionId': 'TI-1',
                                        'ExternalDescriptionStr': '<p>Build semiconductor technology.</p>',
                                        'ExternalResponsibilitiesStr': '', 'ExternalQualificationsStr': '',
                                        'PrimaryLocation': 'Dallas, TX', 'otherWorkLocations': [], 'secondaryLocations': []}]})
        return response({'items': [{'TotalJobsCount': 1, 'requisitionList': [{'Id': '101'}]}]})


class TexasInstrumentsRouteTests(unittest.TestCase):
    def test_exact_custom_host_repair_uses_explicit_oracle_mapping(self):
        ats, url, note = repair_source('Oracle Recruiting', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Oracle Fusion', BOARD))
        self.assertTrue(note)
        changed = SOURCE + '?manual=1'
        self.assertEqual(repair_source('Oracle Recruiting', changed, COMPANY_ID, COMPANY), ('Oracle Recruiting', changed, ''))
        self.assertEqual(repair_source('Oracle Recruiting', SOURCE, 'OTHER', COMPANY), ('Oracle Recruiting', SOURCE, ''))
        self.assertEqual(repair_source('Oracle Recruiting', SOURCE, COMPANY_ID, 'Other employer'), ('Oracle Recruiting', SOURCE, ''))

    def test_normal_dispatch_retrieves_full_oracle_posting_and_rereads_listing(self):
        result = fetch_inventory('Oracle Recruiting', SOURCE, COMPANY_ID, COMPANY, API(), discovery_transport=Page())
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['posting_id'], '101')
        self.assertIn('Build semiconductor technology.', result.jobs[0]['description'])


if __name__ == '__main__':
    unittest.main()
