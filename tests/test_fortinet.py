"""Guard Fortinet's exact official-careers-to-Oracle source repair."""
import unittest

from job_search_helper.company_sources import repair_source


class FortinetSourceTests(unittest.TestCase):
    def test_official_careers_source_routes_to_fortinet_oracle_site(self):
        expected = 'https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001'
        for source in ('https://www.fortinet.com/corporate/careers',
                       'https://www.fortinet.com/corporate/careers/'):
            with self.subTest(source=source):
                ats, board, note = repair_source('', source, 'COMP-0660', 'Fortinet')
                self.assertEqual((ats, board), ('Oracle Fusion', expected))
                self.assertTrue(note)

    def test_repair_requires_exact_company_and_original_source(self):
        changed = 'https://www.fortinet.com/corporate/careers?manual=1'
        self.assertEqual(repair_source('', changed, 'COMP-0660', 'Fortinet'), ('', changed, ''))
        self.assertEqual(repair_source('', 'https://www.fortinet.com/corporate/careers', 'OTHER', 'Fortinet'),
                         ('', 'https://www.fortinet.com/corporate/careers', ''))
        self.assertEqual(repair_source('', 'https://www.fortinet.com/corporate/careers', 'COMP-0660', 'Other'),
                         ('', 'https://www.fortinet.com/corporate/careers', ''))


if __name__ == '__main__':
    unittest.main()
