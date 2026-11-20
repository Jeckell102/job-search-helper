import unittest

from job_search_helper.company_sources import repair_source
from job_search_helper.successfactors import FESTO_SOURCE, SITES


class FestoSourceTests(unittest.TestCase):
    def test_official_festo_source_routes_to_unfiltered_successfactors_board(self):
        for source in (FESTO_SOURCE, 'https://jobs.festo.com/viewalljobs'):
            with self.subTest(source=source):
                ats, board, note = repair_source('', source, 'COMP-0560', 'Festo')
                self.assertEqual((ats, board), ('SuccessFactors', FESTO_SOURCE))
                self.assertTrue(note)
        self.assertEqual(SITES[FESTO_SOURCE], 'jobs.festo.com')

    def test_repair_does_not_override_changed_source(self):
        changed = FESTO_SOURCE + '?manual=1'
        self.assertEqual(repair_source('', changed, 'COMP-0560', 'Festo'), ('', changed, ''))


if __name__ == '__main__':
    unittest.main()
