import unittest
import builtins
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.browser_scraper import _extract_links, _listing_pages, jobs_from_json_payload, with_browser_fallback


class FakeLocator:
    def __init__(self, anchors):
        self.anchors = anchors

    def evaluate_all(self, _script):
        return self.anchors


class FakePage:
    def __init__(self, anchors):
        self.anchors = anchors

    def locator(self, _selector):
        return FakeLocator(self.anchors)


class BrowserFallbackTests(unittest.TestCase):
    def test_successful_direct_fetch_does_not_open_browser(self):
        direct = lambda *args: Inventory("complete", [{"title": "x"}], "ok")
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory") as browser:
            result = with_browser_fallback(direct)("ATS", "https://example.com/careers", "C", "Acme")
        self.assertEqual(result.status, "complete")
        browser.assert_not_called()

    def test_blocked_direct_fetch_can_return_browser_inventory(self):
        direct = lambda *args: Inventory("blocked", [], "HTTP 403", "https://example.com/careers", "Workday")
        browser_result = Inventory("complete", [{"title": "Field Engineer"}], "scraped", "https://example.com/careers", "Workday")
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser_result) as browser:
            result = with_browser_fallback(direct)("Workday", "https://example.com/careers", "C", "Acme")
        self.assertEqual(result.status, "complete")
        self.assertIn("Direct fetch returned blocked", result.reason)
        browser.assert_called_once()

    def test_partial_direct_fetch_runs_browser_and_keeps_better_inventory(self):
        direct_result = Inventory("partial", [{"title": "Direct A"}, {"title": "Direct B"}], "incomplete")
        direct = lambda *args: direct_result
        browser_result = Inventory("partial", [{"title": "Browser A", "posting_id": "browser-a"}], "also incomplete")
        direct_result.jobs[0]["posting_id"] = "direct-a"
        direct_result.jobs[1]["posting_id"] = "direct-b"
        with patch("job_search_helper.browser_scraper.fetch_browser_inventory", return_value=browser_result) as browser:
            result = with_browser_fallback(direct)("Taleo", "https://example.com/careers", "C", "Acme")
        self.assertIs(result, direct_result)
        self.assertEqual(len(result.jobs), 3)
        self.assertIn("Browser fallback returned partial", result.reason)
        browser.assert_called_once()

    def test_missing_playwright_is_manual_review_not_closure(self):
        from job_search_helper.browser_scraper import fetch_browser_inventory
        original_import = builtins.__import__

        def missing_playwright(name, *args, **kwargs):
            if name == "playwright.sync_api":
                raise ImportError("missing")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=missing_playwright):
            result = fetch_browser_inventory("Workday", "https://example.com/careers", "C", "Acme")
        self.assertEqual(result.status, "unsupported")
        self.assertIn("Playwright", result.reason)

    def test_frontend_json_payloads_normalize_to_inventory_jobs(self):
        payload = {
            "data": {
                "postings": [{
                    "jobTitle": "Field Service Program Manager",
                    "jobId": "123",
                    "jobDetailUrl": "/careers/jobs/123",
                    "jobLocation": {"name": "Remote US"},
                    "jobDescription": "<p>Lead deployments and customer troubleshooting.</p>",
                }]
            }
        }
        jobs = jobs_from_json_payload(payload, "https://example.com/careers", "C", "Acme", "Browser")
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["posting_id"], "123")
        self.assertEqual(jobs[0]["url"], "https://example.com/careers/jobs/123")
        self.assertIn("Lead deployments", jobs[0]["description"])

    def test_frontend_json_ignores_navigation_and_social_records(self):
        payload = {"items": [
            {"title": "Twitter", "id": "social-1", "url": "/Data/Navigation-Links/Footer/Twitter"},
            {"title": "Facebook", "id": "social-2", "url": "/Data/Navigation-Links/Footer/Facebook"},
            {"title": "Cloud Engineer", "id": "job-1", "url": "/careers/jobs/job-1"},
        ]}
        jobs = jobs_from_json_payload(payload, "https://www.example.com/careers", "C", "Acme", "Browser")
        self.assertEqual([job["title"] for job in jobs], ["Cloud Engineer"])

    def test_rendered_link_scraper_ignores_linkedin_actions_and_redirect_queries(self):
        links = _extract_links(FakePage([
            {"text": "See who Acme has hired for this role", "href": "https://www.linkedin.com/login?session_redirect=/jobs/view/123"},
            {"text": "Report this job", "href": "https://www.linkedin.com/uas/login?session_redirect=/jobs/view/123"},
            {"text": "Systems Engineer", "href": "https://www.linkedin.com/jobs/view/123"},
        ]), "https://www.linkedin.com/jobs/view/123")
        self.assertEqual(links, [])

    def test_rendered_link_scraper_rejects_listing_and_navigation_pages(self):
        links = _extract_links(FakePage([
            {"text": "Career Paths", "href": "https://example.com/careers/career-paths"},
            {"text": "Career Growth", "href": "https://example.com/careers/career-growth"},
            {"text": "Career Site Cookie Settings", "href": "https://example.com/careers/cookiesettings"},
            {"text": "Sign up for job alerts", "href": "https://example.com/jobs/talent-community"},
            {"text": "All Jobs", "href": "https://example.com/jobs/jobs"},
            {"text": "Cloud Engineer", "href": "https://example.com/careers/job/123/cloud-engineer"},
        ]), "https://example.com/careers")
        self.assertEqual(links, [{"url": "https://example.com/careers/job/123/cloud-engineer", "title": "Cloud Engineer"}])

    def test_rendered_link_scraper_accepts_job_id_query(self):
        links = _extract_links(FakePage([
            {"text": "Systems Engineer", "href": "https://example.com/careers/job-posting/?gh_jid=123"},
        ]), "https://example.com/careers")
        self.assertEqual(len(links), 1)

    def test_run_navigation_false_positives_are_not_postings(self):
        paths = ['employee-testimonials/', 'our-facility/', '_wp_link_placeholder',
                 'open-positions/', 'open-roles/', 'candidate-resources/application-faqs.html',
                 'product/dket-3421/', 'life-at-booz/professional-development.html',
                 'jobs/employment-scams/', 'programs-and-partnerships/']
        links = _extract_links(FakePage([
            {'text': '', 'href': 'https://example.com/careers/' + path} for path in paths
        ] + [
            {'text': 'Field Engineer', 'href': 'https://example.com/careers/open-positions/field-engineer'},
            {'text': 'Employee Relations Manager', 'href': 'https://example.com/jobs/employee-relations-manager'},
        ]), 'https://example.com/careers/')
        self.assertEqual(len(links), 2)
        self.assertTrue(all('engineer' in link['url'] or 'manager' in link['url'] for link in links))

    def test_rendered_link_scraper_accepts_avature_jobdetail_route(self):
        links = _extract_links(FakePage([
            {"text": "Senior IT Consultant", "href": "https://careers.example.com/en_US/careers/JobDetail/Senior-IT-Consultant/66475"},
        ]), "https://careers.example.com/en_US/careers/")
        self.assertEqual(len(links), 1)

    def test_rendered_link_scraper_rejects_avature_alert_and_apply_routes(self):
        links = _extract_links(FakePage([
            {"text": "Create Job Alert", "href": "https://careers.example.com/en_US/careers/JobAlertRegister"},
            {"text": "Apply", "href": "https://careers.example.com/en_US/careers/ApplicationMethods?jobId=66475"},
            {"text": "Senior IT Consultant", "href": "https://careers.example.com/en_US/careers/JobDetail/Senior-IT-Consultant/66475"},
        ]), "https://careers.example.com/en_US/careers/")
        self.assertEqual(links, [{"url": "https://careers.example.com/en_US/careers/JobDetail/Senior-IT-Consultant/66475", "title": "Senior IT Consultant"}])

    def test_mantech_search_and_remote_pages_are_not_jobs(self):
        source = 'https://careers.mantech.com/en_US/careers/'
        links = _extract_links(FakePage([
            {'text': 'Next', 'href': source + 'SearchJobs/?jobOffset=6'},
            {'text': 'Remote Jobs', 'href': source + 'RemoteJobs'},
            {'text': 'Senior CNO Developer', 'href': source + 'JobDetail/Senior-CNO-Developer/12345'},
        ]), source)
        self.assertEqual([link['title'] for link in links], ['Senior CNO Developer'])

    def test_rendered_link_scraper_ignores_self_careers_link(self):
        links = _extract_links(FakePage([
            {"text": "Career", "href": "https://www.foretellix.com/career/"},
            {"text": "Field Engineer", "href": "https://www.foretellix.com/career/field-engineer"},
        ]), "https://www.foretellix.com/career/")
        self.assertEqual(links, [{"url": "https://www.foretellix.com/career/field-engineer", "title": "Field Engineer"}])

    def test_listing_and_career_navigation_are_not_jobs_but_nested_postings_are(self):
        source = 'https://example.com/career'
        anchors = [{'text': text, 'href': source + '/' + path} for text, path in [
            ('Job Opportunities', 'job-opportunities'), ('Students', 'students'),
            ('Saab Life', 'saab-life'), ('Open Positions', 'open-positions'),
            ('Available Positions', 'positions.html'),
            ('Field Engineer', 'job-opportunities/field-engineer'),
            ('Student Support Engineer', 'student-support-engineer')]]
        links = _extract_links(FakePage(anchors), source)
        self.assertEqual({link['url'] for link in links}, {
            source + '/job-opportunities/field-engineer', source + '/student-support-engineer'})
        pages = _listing_pages(FakePage(anchors + [
            {'text': 'Jobs elsewhere', 'href': 'https://other.example.com/career/jobs'},
            {'text': 'Filtered board', 'href': source + '/jobs?country=Other'},
        ]), source)
        self.assertEqual(pages, [source + '/job-opportunities', source + '/open-positions', source + '/positions.html'])
        self.assertEqual(_listing_pages(FakePage([{'text': 'Jobs', 'href': source + '/jobs'}]),
                                        source + '?country=US'), [])

    def test_generic_listing_pages_only_follows_same_board_pagination(self):
        pages = _listing_pages(FakePage([
            {"text": "2", "href": "https://example.com/careers?page=2", "rel": "", "aria": "Go to page 2"},
            {"text": "Next", "href": "https://example.com/careers?page=3", "rel": "next", "aria": ""},
            {"text": "3", "href": "https://example.com/careers/SearchJobs/?jobRecordsPerPage=6&jobOffset=12", "rel": "", "aria": ""},
            {"text": "Engineering", "href": "https://example.com/careers/engineering", "rel": "", "aria": ""},
            {"text": "Next", "href": "https://other.example.com/careers?page=2", "rel": "next", "aria": ""},
        ]), "https://example.com/careers")
        self.assertEqual(pages, ["https://example.com/careers?page=2", "https://example.com/careers?page=3", "https://example.com/careers/SearchJobs/?jobOffset=12&jobRecordsPerPage=6"])


if __name__ == "__main__":
    unittest.main()
