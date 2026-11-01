"""Browser timeout recovery and durable retry tests, without network access."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

try:
    from playwright.sync_api import TimeoutError as BrowserTimeout
except ImportError:
    BrowserTimeout = None

from job_search_helper.ats import Inventory
from job_search_helper.browser_progress import BrowserProgress
from job_search_helper.browser_scraper import _fetch_detail, fetch_browser_inventory, with_browser_fallback
from job_search_helper.inbox import InventoryInbox


SOURCE = 'https://example.com/careers'
LINKS = [{'url': f'https://example.com/jobs/{i}', 'title': f'Field Engineer {i}'} for i in range(3)]
CONTENT = {'title': 'Field Engineer', 'description': 'Responsibilities include deploying and supporting equipment. ' * 8}


@unittest.skipIf(BrowserTimeout is None, 'Optional Playwright dependency unavailable')
class BrowserProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'inbox.db'
        self.inbox = InventoryInbox(self.path, 'fixture')
        self.addCleanup(self.inbox.close)

    def progress(self, cycle='cycle', source=SOURCE):
        return BrowserProgress(self.inbox, cycle, 'C', source)

    def browser_run(self, progress, fetch_detail, **options):
        stack = ExitStack()
        self.addCleanup(stack.close)
        playwright = stack.enter_context(patch('playwright.sync_api.sync_playwright'))
        browser = playwright.return_value.__enter__.return_value.chromium.launch.return_value
        browser.new_page.return_value.goto.return_value.status = 200
        stack.enter_context(patch('job_search_helper.browser_scraper._scoped_browser_inventory', return_value=None))
        stack.enter_context(patch('job_search_helper.browser_scraper._extract_links', return_value=LINKS))
        stack.enter_context(patch('job_search_helper.browser_scraper._listing_pages', return_value=[]))
        stack.enter_context(patch('job_search_helper.browser_scraper._page_text', return_value='Careers'))
        stack.enter_context(patch('job_search_helper.browser_scraper._fetch_detail', side_effect=fetch_detail))
        result = fetch_browser_inventory('Browser', SOURCE, 'C', 'Company', progress=progress, **options)
        stack.close()
        return result

    def seeded_progress(self, count=96):
        progress = self.progress()
        links = [{'url': f'https://example.com/jobs/{i}', 'title': f'Field Engineer {i}'} for i in range(count)]
        progress.discover(links)
        progress.save_listing({'queue': [], 'visited': [SOURCE], 'complete': True})
        return progress, links

    def test_repeated_detail_failures_stop_without_visiting_all_96_twice(self):
        from job_search_helper.browser_scraper import DetailUnavailable
        progress, links = self.seeded_progress()
        calls = []
        def fail(browser, link, timeout):
            calls.append((link['url'], timeout))
            raise DetailUnavailable('Job description not available yet')
        result = self.browser_run(progress, fail)
        self.assertEqual(len(calls), 10)
        self.assertEqual([timeout for _, timeout in calls], [15000] * 5 + [30000] * 5)
        self.assertEqual(len(result.browser_pending_urls), 96)
        self.assertEqual(result.status, 'partial')
        saved = self.progress().entries()
        self.assertEqual(sum(item['attempts'] == 2 for item in saved.values()), 5)
        self.assertEqual(sum(item['attempts'] == 0 for item in saved.values()), 91)
        self.assertEqual(saved[links[0]['url']]['error'], 'DetailUnavailable: Job description not available yet')
        self.assertIn('5 consecutive failures', result.reason)

    def test_failure_threshold_preserves_longer_retry_and_can_recover_every_job(self):
        progress, links = self.seeded_progress()
        calls = []
        def slow(browser, link, timeout):
            calls.append((link['url'], timeout))
            if timeout < 20000:
                raise BrowserTimeout('slow render')
            return CONTENT
        result = self.browser_run(progress, slow)
        self.assertEqual(len(result.jobs), 96)
        self.assertEqual(result.browser_pending_urls, [])
        self.assertEqual(len(calls), 101)
        self.assertEqual([timeout for _, timeout in calls[:5]], [15000] * 5)
        self.assertTrue(all(timeout == 30000 for _, timeout in calls[5:]))

    def test_company_deadline_preserves_successes_and_unattempted_urls(self):
        progress, links = self.seeded_progress()
        clock = [0.0]
        timeouts = []
        def fetch(browser, link, timeout):
            timeouts.append(timeout)
            clock[0] += 15
            return CONTENT
        with patch('job_search_helper.browser_scraper.MAX_BROWSER_SECONDS', 35), patch(
                'job_search_helper.browser_scraper.time.monotonic', side_effect=lambda: clock[0]):
            result = self.browser_run(progress, fetch)
        self.assertEqual(timeouts, [15000, 15000, 5000])
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(len(result.browser_pending_urls), 93)
        self.assertIn('Browser time limit reached (35 seconds)', result.reason)
        self.assertEqual(sum(bool(item['job']) for item in self.progress().entries().values()), 3)

    def test_successes_reset_failure_streak(self):
        progress, links = self.seeded_progress(15)
        calls = []
        def mixed(browser, link, timeout):
            calls.append(link['url'])
            if int(link['url'].rsplit('/', 1)[1]) % 5 != 4 and timeout == 15000:
                raise BrowserTimeout('slow render')
            return CONTENT
        result = self.browser_run(progress, mixed)
        self.assertEqual(len(result.jobs), 15)
        self.assertEqual(result.browser_pending_urls, [])
        self.assertEqual(len(calls), 27)

    def test_successes_survive_interruption_and_restart_skips_completed_details(self):
        calls = []
        def first(browser, link, timeout):
            calls.append(link['url'])
            if link == LINKS[1]:
                # Success is already visible to a separate read connection.
                other = InventoryInbox(self.path, 'fixture')
                try:
                    saved = BrowserProgress(other, 'cycle', 'C', SOURCE).entries()
                    self.assertEqual(saved[LINKS[0]['url']]['job']['description'], CONTENT['description'])
                    self.assertEqual(len(saved), 3)
                finally:
                    other.close()
                raise KeyboardInterrupt()
            return CONTENT
        with self.assertRaises(KeyboardInterrupt):
            self.browser_run(self.progress(), first)
        restarted_calls = []
        def resumed(browser, link, timeout):
            restarted_calls.append(link['url'])
            return CONTENT
        result = self.browser_run(self.progress(), resumed)
        self.assertEqual(restarted_calls, [x['url'] for x in LINKS[1:]])
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(result.browser_pending_urls, [])
        self.assertFalse(result.browser_discovery_incomplete)
        self.assertEqual(result.status, 'partial')  # Generic discovery never proves completeness.

    def test_failed_urls_retry_after_first_pass_and_remain_durable(self):
        calls = []
        timeouts = []
        def fetch(browser, link, timeout):
            calls.append(link['url'])
            timeouts.append(timeout)
            if link == LINKS[0]:
                raise BrowserTimeout('still loading')
            return CONTENT
        result = self.browser_run(self.progress(), fetch)
        self.assertEqual(calls, [x['url'] for x in LINKS] + [LINKS[0]['url']])
        self.assertEqual(timeouts, [15000, 15000, 15000, 30000])
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.browser_pending_urls, [LINKS[0]['url']])
        self.assertEqual(self.progress().entries()[LINKS[0]['url']]['attempts'], 2)
        self.assertTrue(all(j['description'] == CONTENT['description'] for j in result.jobs))

    def test_slow_job_succeeds_on_longer_retry_without_refetching_fast_jobs(self):
        calls = []
        def fetch(browser, link, timeout):
            calls.append((link['url'], timeout))
            if link == LINKS[0] and timeout < 20000:
                raise BrowserTimeout('description needs twenty seconds')
            return CONTENT
        result = self.browser_run(self.progress(), fetch)
        self.assertEqual(calls, [(link['url'], 15000) for link in LINKS] + [(LINKS[0]['url'], 30000)])
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(result.browser_pending_urls, [])
        self.assertEqual(self.progress().entries()[LINKS[0]['url']]['job']['description'], CONTENT['description'])

    def test_shorter_explicit_timeout_is_preserved_for_both_attempts(self):
        timeouts = []
        def fetch(browser, link, timeout):
            timeouts.append(timeout)
            raise BrowserTimeout('unresolved')
        result = self.browser_run(self.progress(), fetch, timeout_ms=5000)
        self.assertEqual(timeouts, [5000] * 6)
        self.assertEqual(set(result.browser_pending_urls), {link['url'] for link in LINKS})
        self.assertEqual(result.jobs, [])

    def test_checkpoint_scope_prevents_stale_results_in_new_cycle_or_board(self):
        saved = self.progress()
        saved.discover(LINKS)
        saved.save_job(LINKS[0]['url'], CONTENT)
        self.assertEqual(self.progress(cycle='next').entries(), {})
        self.assertEqual(self.progress(source='https://elsewhere.com/careers').entries(), {})
        self.inbox.acknowledge('cycle', 'C')
        self.assertEqual(self.progress().entries()[LINKS[0]['url']]['job'], CONTENT)

    def test_resume_repairs_mantech_titles_and_skips_cached_search_pages(self):
        source = 'https://careers.mantech.com/en_US/careers/'
        real = source + 'JobDetail/Senior-IT-Consultant/66475'
        pending = source + 'JobDetail/Field-Engineer/12345'
        search = source + 'SearchJobs/?jobOffset=6'
        remote = source + 'RemoteJobs'
        progress = self.progress(source=source)
        progress.discover([{'url': url, 'title': title} for url, title in (
            (real, 'Senior It Consultant'), (pending, 'Field Engineer'),
            (search, 'Searchjobs'), (remote, 'Remotejobs'))])
        progress.save_job(real, dict(CONTENT, title='MANTECH', url=real))
        progress.save_job(search, dict(CONTENT, title='MANTECH', url=search))
        progress.save_listing({'queue': [], 'visited': [source], 'complete': True})
        with patch('playwright.sync_api.sync_playwright'), patch(
                'job_search_helper.browser_scraper._fetch_detail', return_value=CONTENT) as detail:
            result = fetch_browser_inventory('Browser', source, 'C', 'ManTech', progress=progress)
        self.assertEqual(detail.call_count, 1)
        self.assertEqual(detail.call_args.args[1]['url'], pending)
        self.assertEqual(len(result.jobs), 2)
        self.assertEqual(result.jobs[0]['title'], 'Senior IT Consultant')
        self.assertEqual(result.jobs[0]['description'], CONTENT['description'])
        self.assertEqual(result.browser_pending_urls, [])
        self.assertEqual(self.progress(source=source).entries()[real]['job']['title'], 'Senior IT Consultant')
        # Keep the original non-job checkpoint as audit evidence on disk.
        self.assertIn(search, self.progress(source=source).entries())

    def test_resume_preserves_pending_listing_pages_and_saved_descriptions(self):
        saved = self.progress()
        saved.discover(LINKS[:1])
        saved.save_job(LINKS[0]['url'], dict(CONTENT, url=LINKS[0]['url']))
        next_page = SOURCE + '?page=2'
        saved.save_listing({'queue': [next_page], 'visited': [SOURCE], 'complete': False})
        with patch('playwright.sync_api.sync_playwright') as playwright:
            page = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_page.return_value
            page.goto.side_effect = BrowserTimeout('listing timed out')
            result = fetch_browser_inventory('Browser', SOURCE, 'C', 'Company', progress=self.progress())
        self.assertEqual(len(result.jobs), 1)
        self.assertTrue(result.browser_discovery_incomplete)
        self.assertEqual(self.progress().listing(SOURCE)['queue'], [next_page])
        self.assertEqual(page.goto.call_args.args[0], next_page)
        calls = []
        def detail(browser, link, timeout):
            calls.append(link['url'])
            return CONTENT
        result = self.browser_run(self.progress(), detail)
        self.assertEqual(calls, [x['url'] for x in LINKS[1:]])
        self.assertEqual(len(result.jobs), 3)
        self.assertFalse(result.browser_discovery_incomplete)

    def test_resume_ignores_confirmed_navigation_but_keeps_checkpoint_evidence(self):
        saved = self.progress()
        navigation = {'url': SOURCE.rstrip('/') + '/employee-testimonials/', 'title': 'Employee Testimonials'}
        saved.discover([navigation, LINKS[0]])
        saved.failed(navigation['url'], 'ValueError')
        saved.save_listing({'queue': [], 'visited': [SOURCE], 'complete': True})
        calls = []
        def detail(browser, link, timeout):
            calls.append(link['url'])
            return CONTENT
        result = self.browser_run(self.progress(), detail)
        self.assertEqual(calls, [LINKS[0]['url']])
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.browser_pending_urls, [])
        self.assertEqual(result.status, 'partial')
        self.assertIn(navigation['url'], self.progress().entries())

    def test_old_pending_listing_link_is_migrated_to_listing_discovery(self):
        saved = self.progress()
        board = SOURCE + '/job-opportunities'
        saved.discover([{'url': board, 'title': 'Job Opportunities'},
                        {'url': SOURCE + '/students', 'title': 'Students'}, LINKS[0]])
        saved.save_job(LINKS[0]['url'], dict(CONTENT, url=LINKS[0]['url']))
        saved.save_listing({'queue': [], 'visited': [SOURCE], 'complete': True})
        result = self.browser_run(self.progress(), lambda *args: CONTENT)
        self.assertEqual(len(result.jobs), 3)
        self.assertEqual(result.browser_pending_urls, [])
        self.assertFalse(result.browser_discovery_incomplete)
        listing = self.progress().listing(SOURCE)
        self.assertIn(board, listing['visited'])
        self.assertEqual(listing['queue'], [])
        self.assertIn(board, self.progress().entries())  # Old evidence is retained.

    def test_landing_page_without_jobs_can_lead_to_actual_job_list(self):
        board = SOURCE + '/open-positions'
        with ExitStack() as stack:
            playwright = stack.enter_context(patch('playwright.sync_api.sync_playwright'))
            page = playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_page.return_value
            page.goto.return_value.status = 200
            stack.enter_context(patch('job_search_helper.browser_scraper._scoped_browser_inventory', return_value=None))
            stack.enter_context(patch('job_search_helper.browser_scraper._extract_links', side_effect=[[], LINKS]))
            stack.enter_context(patch('job_search_helper.browser_scraper._listing_pages', side_effect=[[board], []]))
            stack.enter_context(patch('job_search_helper.browser_scraper._page_text', return_value='Careers'))
            detail = stack.enter_context(patch('job_search_helper.browser_scraper._fetch_detail', return_value=CONTENT))
            result = fetch_browser_inventory('Browser', SOURCE, 'C', 'Company', progress=self.progress())
        self.assertEqual([call.args[0] for call in page.goto.call_args_list], [SOURCE, board])
        self.assertEqual(detail.call_count, 3)
        self.assertEqual(len(result.jobs), 3)
        self.assertFalse(result.browser_discovery_incomplete)

    def test_failed_checkpoint_does_not_claim_job_was_saved(self):
        saved = self.progress()
        saved.discover(LINKS[:1])
        with patch.object(saved, '_write', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                saved.save_job(LINKS[0]['url'], CONTENT)
        self.assertIsNone(saved.entries()[LINKS[0]['url']]['job'])
        self.assertIsNone(self.progress().entries()[LINKS[0]['url']]['job'])

    def test_detail_uses_content_readiness_and_closes_page(self):
        browser = MagicMock()
        page = browser.new_page.return_value
        page.goto.return_value.status = 200
        page.wait_for_function.return_value.json_value.return_value = CONTENT
        self.assertEqual(_fetch_detail(browser, LINKS[0], 30000), CONTENT)
        self.assertEqual(page.goto.call_args.kwargs['wait_until'], 'commit')
        page.wait_for_function.assert_called_once()
        page.close.assert_called_once()

    def test_navigation_and_content_timeouts_recover_loaded_description(self):
        for failed_step in ('goto', 'wait_for_function'):
            with self.subTest(failed_step=failed_step):
                browser = MagicMock()
                page = browser.new_page.return_value
                page.goto.return_value.status = 200
                getattr(page, failed_step).side_effect = BrowserTimeout('timeout')
                page.evaluate.return_value = CONTENT
                self.assertEqual(_fetch_detail(browser, LINKS[0], 30000), CONTENT)
                page.close.assert_called_once()

    def test_no_description_never_substitutes_listing_text_and_closes_page(self):
        browser = MagicMock()
        page = browser.new_page.return_value
        page.goto.side_effect = BrowserTimeout('timeout')
        page.evaluate.return_value = False
        with self.assertRaisesRegex(ValueError, 'description not available'):
            _fetch_detail(browser, LINKS[0], 30000)
        page.close.assert_called_once()

    def test_interruption_also_closes_detail_page(self):
        browser = MagicMock()
        page = browser.new_page.return_value
        page.goto.side_effect = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            _fetch_detail(browser, LINKS[0], 30000)
        page.close.assert_called_once()

    def test_pending_browser_metadata_survives_direct_result_merge(self):
        direct = Inventory('partial', [{'posting_id': 'one'}, {'posting_id': 'two'}])
        result = Inventory('partial', browser_pending_urls=['https://example.com/jobs/3'])
        with patch('job_search_helper.browser_scraper.fetch_browser_inventory', return_value=result):
            merged = with_browser_fallback(lambda *args: direct)('Taleo', SOURCE, 'C', 'Company')
        self.assertEqual(merged.browser_pending_urls, result.browser_pending_urls)


if __name__ == '__main__':
    unittest.main()
