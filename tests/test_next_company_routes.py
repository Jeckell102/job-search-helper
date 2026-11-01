"""Exact employer-scoped routes for the next integration batch."""
import unittest

from job_search_helper.company_sources import REPAIRS, repair_source


class NextCompanyRoutes(unittest.TestCase):
    def test_scout_ai_careers_row_reaches_verified_ashby_board(self):
        board = 'https://api.ashbyhq.com/posting-api/job-board/scout-ai'
        for source in ('https://job-boards.greenhouse.io/scoutai', 'https://www.scoutco.ai/careers', 'https://scoutco.ai/careers'):
            with self.subTest(source=source):
                ats, repaired, note = repair_source('Greenhouse', source, 'COMP-0496', 'Scout AI')
                self.assertEqual((ats, repaired), ('Ashby', board))
                self.assertTrue(note)
                self.assertEqual(repair_source('Greenhouse', source, 'OTHER', 'Scout AI'),
                                 ('Greenhouse', source, ''))
                self.assertEqual(repair_source('Greenhouse', source, 'COMP-0496', 'Other Employer'),
                                 ('Greenhouse', source, ''))
                self.assertEqual(repair_source('Greenhouse', source + '?changed=1', 'COMP-0496', 'Scout AI'),
                                 ('Greenhouse', source + '?changed=1', ''))

    def test_primer_row_reaches_exact_hibob_board(self):
        source = 'https://www.primer.ai/company/careers'
        ats, board, note = repair_source('Greenhouse', source, 'COMP-0456', 'Primer')
        self.assertEqual((ats, board), ('HiBob', 'https://primertechnology.careers.hibob.com/'))
        self.assertTrue(note)
        self.assertEqual(repair_source('Greenhouse', source, 'OTHER', 'Primer'),
                         ('Greenhouse', source, ''))
        self.assertEqual(repair_source('Greenhouse', source, 'COMP-0456', 'Other Employer'),
                         ('Greenhouse', source, ''))
        self.assertEqual(repair_source('Greenhouse', source + '?changed=1', 'COMP-0456', 'Primer'),
                         ('Greenhouse', source + '?changed=1', ''))

    def test_abaco_row_reaches_exact_scoped_successfactors_board(self):
        source = 'https://abaco.com/careers'
        ats, board, note = repair_source('Browser', source, 'COMP-0423', 'Abaco Systems')
        self.assertEqual((ats, board), (
            'SuccessFactors',
            'https://jobs.ametek.com/go/Abaco/8908500/?q=&sortColumn=referencedate&sortDirection=desc'))
        self.assertTrue(note)
        self.assertEqual(repair_source('Browser', source, 'OTHER', 'Abaco Systems'),
                         ('Browser', source, ''))
        self.assertEqual(repair_source('Browser', source, 'COMP-0423', 'Other Employer'),
                         ('Browser', source, ''))
        self.assertEqual(repair_source('Browser', source + '?changed=1', 'COMP-0423', 'Abaco Systems'),
                         ('Browser', source + '?changed=1', ''))

    def test_exail_row_reaches_verified_cegid_hr_api_board(self):
        source = 'https://www.exail.com/careers'
        ats, board, note = repair_source('Browser', source, 'COMP-0357', 'Exail')
        self.assertEqual((ats, board), ('Cegid HR', 'https://jobs.exail.com/en/annonces'))
        self.assertTrue(note)
        self.assertEqual(repair_source('Browser', source, 'OTHER', 'Exail'),
                         ('Browser', source, ''))
        self.assertEqual(repair_source('Browser', source, 'COMP-0357', 'Other'),
                         ('Browser', source, ''))

    def test_exail_careers_row_reaches_pinned_cegid_hr_board(self):
        source = 'https://www.exail.com/careers'
        ats, board, note = repair_source('Browser', source, 'COMP-0357', 'Exail')
        self.assertEqual((ats, board), ('Cegid HR', 'https://jobs.exail.com/en/annonces'))
        self.assertTrue(note)
        self.assertEqual(repair_source('Browser', source, 'OTHER', 'Exail'),
                         ('Browser', source, ''))
        self.assertEqual(repair_source('Browser', source, 'COMP-0357', 'Other Employer'),
                         ('Browser', source, ''))
        self.assertEqual(repair_source('Browser', source + '?changed=1', 'COMP-0357', 'Exail'),
                         ('Browser', source + '?changed=1', ''))

    def test_t2s_configured_hrmdirect_row_reaches_verified_clearcompany_api(self):
        from job_search_helper.company_sources import repair_source
        source = 'https://t2s-solutions.hrmdirect.com/employment/job-openings.php?frameborder=0&search=true'
        ats, board, note = repair_source('ClearCompany', source, 'COMP-0311', 'T2S Solutions')
        self.assertEqual(ats, 'ClearCompany')
        self.assertEqual(board, 'https://careers-api.clearcompany.com/v1/366df4d7-cb40-1096-8cdb-1f53109453cf')
        self.assertTrue(note)
        self.assertEqual(repair_source('ClearCompany', source, 'OTHER', 'T2S Solutions'),
                         ('ClearCompany', source, ''))
        self.assertEqual(repair_source('ClearCompany', source, 'COMP-0311', 'Other Employer'),
                         ('ClearCompany', source, ''))
    CASES = {
        "COMP-0082": ("Thales Defense & Security", "https://careers.thalesdsi.com/?locale=en_US", "SuccessFactors", "https://careers.thalesdsi.com/search/?q="),
        "COMP-0091": ("Saab Inc", "https://www.saab.com/markets/united-states/career", "Workday", "https://saabusa.wd1.myworkdayjobs.com/wday/cxs/saabusa/Saab_careers"),
        "COMP-0136": ("Ericsson", "https://jobs.ericsson.com/careers", "Browser", "https://jobs.ericsson.com/careers"),
        "COMP-0143": ("MultiTech", "", "Dayforce", "https://us231.dayforcehcm.com/CandidatePortal/en-US/multitech"),
        "COMP-0147": ("Moxa", "https://www.moxa.work/en", "Taleo", "https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en"),
        "COMP-0248": ("Dematic", "https://www.dematic.com/en-us/about/careers/", "Workday", "https://kiongroup.wd3.myworkdayjobs.com/wday/cxs/kiongroup/KION_SCS"),
    }

    def test_routes_are_exact_company_and_source_guarded(self):
        for cid, (company, source, provider, board) in self.CASES.items():
            with self.subTest(company=company):
                self.assertIn(cid, REPAIRS)
                ats, url, note = repair_source("Browser", source, cid, company)
                self.assertEqual((ats, url), (provider, board))
                self.assertTrue(note)
                self.assertEqual(repair_source("Browser", source, cid, "Other Employer"),
                                 ("Browser", source, ""))
                self.assertEqual(repair_source("Browser", source + "?changed=1", cid, company),
                                 ("Browser", source + "?changed=1", ""))

    def test_peplink_configured_row_reaches_dedicated_adapter(self):
        from unittest.mock import patch
        from job_search_helper.ats import Inventory, fetch_inventory
        source = "https://www.peplink.com/company/career/"
        with patch("job_search_helper.peplink.fetch_peplink", return_value=Inventory(
                "complete", [{"posting_id": "peplink-1"}], ats="Peplink")) as peplink:
            result = fetch_inventory("Peplink", source, "COMP-0149", "Peplink")
        self.assertEqual(result.status, "complete")
        self.assertEqual(peplink.call_args.args[:3], (source, "COMP-0149", "Peplink"))

    def test_carbon_robotics_careers_row_reaches_verified_ashby_board(self):
        from unittest.mock import patch
        import json
        from pathlib import Path
        from job_search_helper.ats import fetch_inventory
        from job_search_helper.company_sources import repair_source
        source = "https://carbonrobotics.com/careers"
        board = "https://api.ashbyhq.com/posting-api/job-board/carbon-robotics"
        ats, repaired, note = repair_source("Greenhouse", source, "COMP-0234", "Carbon Robotics")
        self.assertEqual((ats, repaired), ("Ashby", board))
        self.assertTrue(note)
        data = json.loads((Path(__file__).parent / "fixtures" / "carbon_ashby.json").read_text())
        with patch("job_search_helper.ats._json", return_value=data) as ashby:
            result = fetch_inventory(ats, repaired, "COMP-0234", "Carbon Robotics")
        self.assertEqual(result.status, "complete")
        self.assertEqual(len(result.jobs), 4)
        self.assertEqual(ashby.call_args.args[0], board + "?includeCompensation=true")
        self.assertEqual(repair_source("Greenhouse", source, "OTHER", "Carbon Robotics"),
                         ("Greenhouse", source, ""))
        self.assertEqual(repair_source("Greenhouse", source, "COMP-0234", "Other Employer"),
                         ("Greenhouse", source, ""))
        self.assertEqual(repair_source("Greenhouse", source + "?x=1", "COMP-0234", "Carbon Robotics"),
                         ("Greenhouse", source + "?x=1", ""))

    def test_airgain_careers_row_reaches_verified_cloud_adp_board(self):
        from unittest.mock import patch
        from job_search_helper.ats import HTTPResponse, Inventory, fetch_inventory
        source = "https://airgain.com/company/careers/"
        board = "https://workforcenow.cloud.adp.com/mascsr/default/mdf/recruitment/recruitment.html?ccId=19000101_000001&cid=a5bb880d-c347-4e46-9d87-7fa641c11036&lang=en_US&type=JS"
        class Pages:
            def __init__(self): self.urls = []
            def get(self, url):
                self.urls.append(url)
                return HTTPResponse(200, f'<a href="{board}">Jobs</a>'.encode(), {"Content-Type": "text/html"})
        pages = Pages()
        with patch("job_search_helper.adp.fetch_adp", return_value=Inventory(
                "complete", [{"posting_id": "airgain-1"}], ats="ADP")) as adp:
            result = fetch_inventory("ADP", source, "COMP-0144", "Airgain", discovery_transport=pages)
        self.assertEqual(result.status, "complete")
        self.assertEqual(adp.call_args.args[:2], (
            "cid=a5bb880d-c347-4e46-9d87-7fa641c11036&ccId=19000101_000001&lang=en_US",
            "https://workforcenow.cloud.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?"))
        self.assertEqual(pages.urls, [source])

    def test_saab_live_row_reaches_complete_official_workday_adapter(self):
        from unittest.mock import patch
        from job_search_helper.ats import Inventory, fetch_inventory
        from job_search_helper.browser_scraper import with_browser_fallback
        source = 'https://www.saab.com/career'
        with patch('job_search_helper.workday.fetch_workday', return_value=Inventory(
                'complete', [{'posting_id': 'one'}], ats='Workday')) as workday, patch(
                'job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
            result = with_browser_fallback(fetch_inventory)('Browser', source, 'COMP-0091', 'Saab, Inc.')
        self.assertEqual(result.status, 'complete')
        self.assertEqual(workday.call_args.args[:2], (
            'Saab_careers', 'https://saabusa.wd1.myworkdayjobs.com/wday/cxs/saabusa/'))
        browser.assert_not_called()
        for cid, company, url in [('OTHER', 'Saab, Inc.', source),
                                  ('COMP-0091', 'Another Saab Subsidiary', source),
                                  ('COMP-0091', 'Saab, Inc.', source + '?country=Sweden')]:
            self.assertEqual(repair_source('Browser', url, cid, company), ('Browser', url, ''))

    def test_thales_live_legal_name_reaches_complete_successfactors_adapter(self):
        from unittest.mock import patch
        from job_search_helper.ats import Inventory, fetch_inventory
        from job_search_helper.browser_scraper import with_browser_fallback
        source = 'https://careers.thalesdsi.com/?locale=en_US'
        with patch('job_search_helper.successfactors.fetch_successfactors', return_value=Inventory(
                'complete', [{'posting_id': 'thales-1'}], ats='SuccessFactors')) as successfactors, patch(
                'job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
            result = with_browser_fallback(fetch_inventory)(
                'Browser', source, 'COMP-0082', 'Thales Defense & Security, Inc.')
        self.assertEqual(result.status, 'complete')
        self.assertEqual(successfactors.call_args.args[:2], (
            'https://careers.thalesdsi.com/search/?q=', 'COMP-0082'))
        browser.assert_not_called()
        for cid, company, url in [
                ('OTHER', 'Thales Defense & Security, Inc.', source),
                ('COMP-0082', 'Other Thales Employer', source),
                ('COMP-0082', 'Thales Defense & Security, Inc.', source + '&country=US')]:
            self.assertEqual(repair_source('Browser', url, cid, company),
                             ('Browser', url, ''))

    def test_moxa_live_row_reaches_exact_taleo_board(self):
        from unittest.mock import patch
        from job_search_helper.ats import Inventory, fetch_inventory
        from job_search_helper.browser_scraper import with_browser_fallback
        source = 'https://tas-moxa.taleo.net/careersection/mx_ext/jobsearch.ftl?lang=en'
        with patch('job_search_helper.taleo.fetch_taleo', return_value=Inventory(
                'complete', [{'posting_id': 'moxa-1'}], ats='Taleo')) as taleo, patch(
                'job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
            result = with_browser_fallback(fetch_inventory)(
                'Oracle / Taleo', source, 'COMP-0147', 'Moxa')
        self.assertEqual(result.status, 'complete')
        self.assertEqual(taleo.call_args.args[:2], (
            'mx_ext/jobsearch.ftl', 'https://tas-moxa.taleo.net/careersection/'))
        browser.assert_not_called()
        for cid, company, url in [
                ('OTHER', 'Moxa', source),
                ('COMP-0147', 'Other Moxa Employer', source),
                ('COMP-0147', 'Moxa', source + '&country=US')]:
            self.assertEqual(repair_source('Browser', url, cid, company),
                             ('Browser', url, ''))

    def test_nuro_uses_verified_greenhouse_feed_without_generic_browser(self):
        from unittest.mock import patch
        from job_search_helper.ats import Inventory
        from job_search_helper.browser_scraper import with_browser_fallback
        source = 'https://www.nuro.ai/careers'
        calls = []
        def fetch(ats, url, cid, company):
            calls.append((ats, url, cid, company))
            return Inventory('complete', [{'posting_id': '5401358'}], ats='Greenhouse')
        with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
            result = with_browser_fallback(fetch)('Browser', source, 'COMP-0518', 'Nuro')
        self.assertEqual(calls, [('Greenhouse', 'https://boards-api.greenhouse.io/v1/boards/nuro', 'COMP-0518', 'Nuro')])
        self.assertEqual(result.status, 'complete')
        browser.assert_not_called()
        for cid, company, url in [('OTHER', 'Nuro', source),
                                  ('COMP-0518', 'Nuro Subsidiary', source),
                                  ('COMP-0518', 'Nuro', source + '?country=US')]:
            self.assertEqual(repair_source('Browser', url, cid, company), ('Browser', url, ''))

    def test_first_twenty_next_batch_routes_are_guarded(self):
        cases = {
            "COMP-0015": ("Fuse Integration", "https://www.fuseintegration.com/careers/"),
            "COMP-0039": ("Mission Solutions Group", "https://www.msgcorp.com/careers/"),
            "COMP-0040": ("Klas Government", "https://www.klasgov.com/careers/"),
            "COMP-0042": ("BlackTree Technology", "https://blacktree.com.au/careers/"),
            "COMP-0043": ("Digital Force Technologies", "https://www.digitalforcetech.com/company/careers/"),
            "COMP-0045": ("PAR Government", "https://pargovernment.com/careers/"),
            "COMP-0048": ("AMERGINT Technologies", "https://amergint.com/careers/"),
            "COMP-0061": ("Picogrid", "https://picogrid.com/careers"),
            "COMP-0062": ("Sempre", "https://sempre.ai/careers"),
            "COMP-0072": ("General Atomics Aeronautical Systems", "BrassRing (shared parent board)"),
            "COMP-0088": ("Textron Systems", "https://www.textronsystems.com/careers"),
            "COMP-0113": ("Rajant Corporation", "https://rajant.com/about/careers/"),
            "COMP-0114": ("Mobilicom", "https://mobilicom.com/careers/"),
            "COMP-0118": ("Hughes Network Systems", "https://www.hughes.com/careers"),
            "COMP-0123": ("Gilat Satellite Networks", "https://www.gilat.com/career/"),
            "COMP-0128": ("Aethercomm", "https://www.aethercomm.com/careers/"),
            "COMP-0137": ("Cambium Networks", "https://www.cambiumnetworks.com/about-cambium/careers/"),
            "COMP-0140": ("Cradlepoint", "https://cradlepoint.com/company/careers/"),
            "COMP-0141": ("Digi International", "https://www.digi.com/company/careers"),
            "COMP-0149": ("Peplink", "https://www.peplink.com/company/career/"),
        }
        for cid, (company, source) in cases.items():
            with self.subTest(company=company):
                self.assertIn(cid, REPAIRS)
                ats, board, note = repair_source("Browser", source, cid, company)
                self.assertTrue(note)
                self.assertEqual(board, REPAIRS[cid]["url"])
                self.assertEqual(repair_source("Browser", source, cid, "Other Employer"),
                                 ("Browser", source, ""))


if __name__ == "__main__":
    unittest.main()
