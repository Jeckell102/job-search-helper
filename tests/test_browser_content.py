"""Opt-in Chromium checks using intercepted pages; no external network."""
import os
import time
import unittest

from job_search_helper.browser_scraper import _fetch_detail


@unittest.skipUnless(os.environ.get('JSH_BROWSER_TESTS') == '1', 'Opt-in local Chromium test')
class BrowserContentTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(headless=True)
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context()
        self.addCleanup(self.context.close)
        self.link = {'url': 'https://fixture.invalid/jobs/1', 'title': 'Field Engineer'}

    def serve(self, markup):
        def route(request):
            if request.request.resource_type == 'document':
                request.fulfill(status=200, content_type='text/html', body=markup)
            else:
                request.fulfill(status=200, body='ok')
        self.context.route('**/*', route)

    def test_extracts_dynamic_description_while_background_requests_continue(self):
        text = 'Responsibilities include deploying customer systems. Qualifications include field support experience. ' * 4
        self.serve('<h1>Field Engineer</h1><main><div class="job-description"></div></main>'
                   '<script>setInterval(()=>fetch("/analytics?t="+Date.now()),100);'
                   'setTimeout(()=>document.querySelector(".job-description").textContent=' + repr(text) + ',200);</script>')
        start = time.monotonic()
        result = _fetch_detail(self.context, self.link, 5000)
        elapsed = time.monotonic() - start
        self.assertIn('field support experience', result['description'])
        self.assertLess(elapsed, 3.5)
        self.assertEqual(self.context.pages, [])
        print(f'Browser readiness with ongoing analytics: {elapsed:.2f}s')

    def test_reads_structured_job_description(self):
        self.serve('<script type="application/ld+json">{"@type":"JobPosting","title":"Field Engineer",'
                   '"description":"<p>Deploy and support equipment at customer locations, train operators, '
                   'troubleshoot technical issues and coordinate field service schedules for the customer.</p>"}</script>')
        result = _fetch_detail(self.context, self.link, 3000)
        self.assertIn('train operators', result['description'])
        self.assertEqual(self.context.pages, [])

    def test_loading_placeholder_is_unresolved_and_page_is_closed(self):
        self.serve('<h1>Field Engineer</h1><main>Loading...</main>')
        with self.assertRaises(ValueError):
            _fetch_detail(self.context, self.link, 700)
        self.assertEqual(self.context.pages, [])

    def test_mantech_uses_job_banner_not_hidden_company_heading(self):
        self.link = {'url': 'https://careers.mantech.com/en_US/careers/JobDetail/Senior-IT-Consultant/66475',
                     'title': 'Senior It Consultant'}
        self.serve('<h1 class="visibility--hidden--visually">MANTECH</h1>'
                   '<h2 class="banner__text__title title title--banner">Senior IT Consultant</h2>'
                   '<main>Responsibilities and requirements. ' + 'Technical consulting. ' * 20 + '</main>')
        result = _fetch_detail(self.context, self.link, 3000)
        self.assertEqual(result['title'], 'Senior IT Consultant')

    def test_mantech_missing_banner_preserves_discovered_title(self):
        self.link = {'url': 'https://careers.mantech.com/en_US/careers/JobDetail/Field-Engineer/12345',
                     'title': 'Field Engineer'}
        self.serve('<h1>MANTECH</h1><main>Responsibilities and requirements. '
                   + 'Field engineering. ' * 20 + '</main>')
        self.assertEqual(_fetch_detail(self.context, self.link, 3000)['title'], 'Field Engineer')


if __name__ == '__main__':
    unittest.main()
