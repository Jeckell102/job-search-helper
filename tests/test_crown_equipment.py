import unittest
from job_search_helper.company_sources import repair_source
from job_search_helper.successfactors import CROWN_SOURCE

class CrownEquipmentTests(unittest.TestCase):
    def test_official_source_routes_to_unfiltered_board(self):
        for source in ('https://www.crown.com/en-us/careers.html', 'https://us-careers.crown.com/'):
            ats, board, note = repair_source('', source, 'COMP-0588', 'Crown Equipment')
            self.assertEqual((ats, board), ('SuccessFactors', CROWN_SOURCE)); self.assertTrue(note)
