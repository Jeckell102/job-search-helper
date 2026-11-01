import unittest

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source


class NextBatchSourceTests(unittest.TestCase):
    def test_exact_company_repairs(self):
        cases = [
            ('COMP-0001', 'CACI International', 'https://careers.caci.com/', 'Eightfold',
             'https://searchcareers.caci.com/careers'),
            ('COMP-0041', 'DataPath', 'https://datapath.com/company-overview/careers/', 'Paycom',
             'https://www.paycomonline.net/v4/ats/web.php/portal/13086EB95BB41A9B5ADD096D9EC0EF88/career-page'),
            ('COMP-0068', 'Kratos Defense & Security Solutions', 'https://www.kratosdefense.com/careers', 'Kratos careers',
             'https://kratosdefense.submit4jobs.com/'),
            ('COMP-0074', 'Lockheed Martin', '', 'Eightfold', 'https://lockheedmartin.eightfold.ai/careers'),
        ]
        for cid, company, old_url, provider, target in cases:
            with self.subTest(cid=cid):
                self.assertEqual(repair_source('Shared ATS', old_url, cid, company)[:2], (provider, target))
                self.assertEqual(repair_source('Shared ATS', old_url + '?changed=1', cid, company),
                                 ('Shared ATS', old_url + '?changed=1', ''))
                self.assertEqual(repair_source('Shared ATS', old_url, cid, 'Other Employer'),
                                 ('Shared ATS', old_url, ''))

    def test_eightfold_dispatch_is_browser_only(self):
        for cid, company, url in [
            ('COMP-0001', 'CACI International', 'https://searchcareers.caci.com/careers'),
            ('COMP-0074', 'Lockheed Martin', 'https://lockheedmartin.eightfold.ai/careers'),
        ]:
            with self.subTest(cid=cid):
                result = fetch_inventory('Eightfold', url, cid, company)
                self.assertEqual(result.status, 'unsupported')
                self.assertEqual(result.ats, 'Eightfold')
                self.assertIn('browser adapter', result.reason)

    def test_linquest_parent_board_stays_scoped(self):
        result = fetch_inventory('Workday (shared parent board)',
                                 'https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers',
                                 'COMP-0016', 'LinQuest')
        self.assertEqual(result.status, 'unsupported')
        self.assertIn('explicit company search or filter', result.reason)


if __name__ == '__main__':
    unittest.main()
