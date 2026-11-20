import unittest
from pathlib import Path

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0789'
COMPANY = 'Aerotech'
SOURCE = 'https://www.aerotech.com/careers/search-all/'
BOARD = 'https://aerotech.applytojob.com/apply/'


class FakeTransport:
    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url):
        return HTTPResponse(200, self.mapping[url].encode())


class AerotechRouteTests(unittest.TestCase):
    def test_exact_source_repair_reaches_employer_jazzhr_board(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('JazzHR', BOARD))
        self.assertTrue(note)
        self.assertEqual(
            repair_source('Official careers', SOURCE + '?team=engineering', COMPANY_ID, COMPANY),
            ('Official careers', SOURCE + '?team=engineering', ''),
        )
        self.assertEqual(
            repair_source('Official careers', SOURCE, 'OTHER', COMPANY),
            ('Official careers', SOURCE, ''),
        )
        self.assertEqual(
            repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'),
            ('Official careers', SOURCE, ''),
        )

    def test_normal_dispatch_retrieves_full_employer_posting(self):
        detail = (Path(__file__).parent / 'fixtures/shared_boards/jazzhr-detail.html').read_text()
        board_url = BOARD.rstrip('/')
        job_url = board_url + '/AONmJi1N5j/Assistant-Customer-Technical-Representative-ACTR'
        listing = '<div class="jobs-list"><a href="' + job_url + '">Assistant Customer Technical Representative (ACTR)</a></div>'
        result = fetch_inventory(
            'Official careers', SOURCE, COMPANY_ID, COMPANY,
            FakeTransport({board_url: listing, job_url: detail}),
        )
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.ats, 'JazzHR')
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['url'], job_url)
        self.assertGreater(len(result.jobs[0]['description']), 100)


if __name__ == '__main__':
    unittest.main()
