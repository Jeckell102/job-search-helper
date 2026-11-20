import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
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

    def test_eightfold_routes_to_dedicated_caci_adapter(self):
        with patch('job_search_helper.caci.fetch_caci', return_value=Inventory('complete', [], ats='CACI Eightfold')) as fetch:
            result = fetch_inventory('Eightfold', 'https://searchcareers.caci.com/careers', 'COMP-0001', 'CACI International')
        self.assertEqual(result.status, 'complete')
        self.assertEqual(fetch.call_args.args[:3], ('https://searchcareers.caci.com/careers', 'COMP-0001', 'CACI International'))

    def test_lockheed_route_requires_its_browser_adapter(self):
        result = fetch_inventory('Eightfold', 'https://lockheedmartin.eightfold.ai/careers', 'COMP-0074', 'Lockheed Martin')
        self.assertEqual(result.status, 'unsupported')
        self.assertIn('browser adapter', result.reason)

    def test_lockheed_landing_repairs_to_its_eightfold_browser_adapter(self):
        from job_search_helper.browser_scraper import with_browser_fallback
        landing = 'https://www.lockheedmartin.com/en-us/careers/'
        completed = Inventory('complete', [{'posting_id': '123'}], ats='Eightfold')
        with patch('job_search_helper.lockheed.fetch_lockheed', return_value=completed) as fetch:
            result = with_browser_fallback(fetch_inventory)('Browser', landing, 'COMP-0074', 'Lockheed Martin')
        self.assertIs(result, completed)
        self.assertEqual(fetch.call_args.args[:3], ('https://lockheedmartin.eightfold.ai/careers', 'COMP-0074', 'Lockheed Martin'))
        self.assertEqual(repair_source('Browser', landing, 'COMP-0074', 'Other Employer'), ('Browser', landing, ''))
        self.assertEqual(repair_source('Browser', landing + '?changed=1', 'COMP-0074', 'Lockheed Martin'), ('Browser', landing + '?changed=1', ''))

    def test_linquest_parent_board_is_repaired_to_scoped_query(self):
        with patch('job_search_helper.linquest.fetch_linquest', return_value=Inventory('partial', [], ats='Workday')) as fetch:
            result = fetch_inventory('Workday (shared parent board)', 'https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers', 'COMP-0016', 'LinQuest')
        self.assertEqual(result.status, 'partial')
        self.assertEqual(fetch.call_args.args[:3], ('https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers?q=LinQuest', 'COMP-0016', 'LinQuest'))


if __name__ == '__main__':
    unittest.main()
