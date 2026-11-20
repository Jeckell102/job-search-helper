"""Guard Danfoss's exact official SuccessFactors source repair."""
import unittest

from job_search_helper.company_sources import repair_source
from job_search_helper.successfactors import DANFOSS_SOURCE, SITES


class DanfossSourceTests(unittest.TestCase):
    def test_official_source_routes_to_unfiltered_successfactors_search(self):
        for source in ('https://jobs.danfoss.com/', 'https://jobs.danfoss.com'):
            with self.subTest(source=source):
                ats, board, note = repair_source('', source, 'COMP-0570', 'Danfoss')
                self.assertEqual((ats, board), ('SuccessFactors', DANFOSS_SOURCE))
                self.assertTrue(note)
        self.assertEqual(SITES[DANFOSS_SOURCE], 'jobs.danfoss.com')

    def test_repair_requires_exact_company_and_original_source(self):
        changed = 'https://jobs.danfoss.com/?manual=1'
        self.assertEqual(repair_source('', changed, 'COMP-0570', 'Danfoss'), ('', changed, ''))
        self.assertEqual(repair_source('', 'https://jobs.danfoss.com/', 'OTHER', 'Danfoss'),
                         ('', 'https://jobs.danfoss.com/', ''))


if __name__ == '__main__':
    unittest.main()
