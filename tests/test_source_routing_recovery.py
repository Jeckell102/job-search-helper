"""Source identity, scope preservation, localized boards and retry regressions."""
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.parse import urlsplit

from job_search_helper.ats import FetchError, HTTPResponse, Inventory, fetch_inventory
from job_search_helper.browser_progress import BrowserProgress
from job_search_helper.browser_scraper import (
    _exclude_saved_navigation, _looks_like_posting_url, _listing_pages,
    with_browser_fallback,
)
from job_search_helper.company_sources import repair_source
from job_search_helper.shared_boards import fetch_shared, fetch_shared_browser
from job_search_helper.teamtailor import fetch_teamtailor


class PublicBoard:
    def __init__(self, root, count='1 offre'):
        self.root, self.count, self.calls = root, count, []

    def get(self, url):
        self.calls.append(url)
        if url == self.root + '/jobs':
            body = ('<div>teamtailor</div><div id="jobs_list_container">'
                    '<a href="/jobs/123-field-engineer">Field Engineer</a></div>'
                    '<h2>' + self.count + '<span></span></h2>')
        elif url == 'https://' + urlsplit(self.root).hostname + '/jobs/123-field-engineer':
            body = '<script type="application/ld+json">' + json.dumps({
                '@type': 'JobPosting', 'identifier': {'value': '123'},
                'title': 'Field Engineer', 'description': 'Deploy and support navigation systems.',
            }) + '</script>'
        else:
            raise AssertionError(url)
        return HTTPResponse(200, body.encode())


class RoutingRecoveryTests(unittest.TestCase):
    CASES = [
        ('COMP-0143', 'MultiTech', 'https://us231.dayforcehcm.com/CandidatePortal/en-US/multitech', 'Dayforce'),
        ('COMP-0260', 'Advanced Navigation', 'https://www.advancednavigation.com/careers/', 'Rippling'),
        ('COMP-0274', 'Particle', 'https://www.particle.io/careers/', 'Rippling'),
        ('COMP-0284', 'OnLogic', 'https://www.onlogic.com/about/careers/', 'Workable'),
        ('COMP-0390', 'Vertech', 'https://www.vertech.com/open-positions', 'Paycor Recruiting'),
        ('COMP-0098', 'Blue Origin', 'https://www.blueorigin.com/careers', 'Workday'),
        ('COMP-0501', 'Reliable Robotics', 'https://reliable.co/careers', 'Ashby'),
        ('COMP-0296', 'Panasonic Connect', 'https://careers.na.panasonic.com/connect', 'Jibe'),
    ]

    def test_verified_routing_preserves_user_changes_and_other_employers(self):
        for cid, company, url, provider in self.CASES:
            with self.subTest(company=company):
                self.assertEqual(repair_source('Shared ATS', url, cid, company)[0], provider)
                for changed_url, changed_id, changed_name in (
                        (url + '?department=restricted', cid, company),
                        (url, 'OTHER', company), (url, cid, 'Other Employer')):
                    self.assertEqual(repair_source('Shared ATS', changed_url, changed_id, changed_name),
                                     ('Shared ATS', changed_url, ''))

    def test_unverified_and_real_parent_sources_stay_restricted(self):
        for cid, company, url in [
                ('COMP-0016', 'LinQuest', 'https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers')]:
            label = 'Workday (shared parent board)' if cid == 'COMP-0016' else 'Shared ATS'
            self.assertEqual(repair_source(label, url, cid, company), (label, url, ''))
        from job_search_helper.discovery import discover_board
        with self.assertRaises(FetchError):
            discover_board('Greenhouse (shared parent board)', 'https://example.com/careers', MagicMock())

    def test_browser_fallback_uses_the_same_verified_provider(self):
        cid, company, url, provider = self.CASES[3]
        with patch('job_search_helper.shared_boards.fetch_shared_browser',
                   return_value=Inventory('complete', ats=provider)) as browser:
            seen = []
            def direct(*args):
                seen.append(args)
                return Inventory('blocked', ats=provider)
            result = with_browser_fallback(direct)('Shared ATS', url, cid, company)
        self.assertEqual(seen[0][:2], (provider, 'https://apply.workable.com/onlogic-inc/'))
        self.assertEqual(browser.call_args.args[:2], seen[0][:2])
        self.assertEqual(result.status, 'complete')

    def test_unknown_discovery_does_not_invent_shared_provider(self):
        with patch('job_search_helper.shared_boards.discover',
                   side_effect=FetchError('partial', 'No verified board')):
            result = fetch_shared('', 'https://example.com/careers', 'C', 'Employer', pages=MagicMock())
        self.assertEqual(result.ats, '')
        self.assertEqual(result.status, 'partial')

    def test_unknown_browser_discovery_does_not_invent_shared_provider(self):
        with patch('playwright.sync_api.sync_playwright'), patch(
                'job_search_helper.shared_boards.discover', side_effect=FetchError('partial', 'No verified board')):
            result = fetch_shared_browser('', 'https://example.com/careers', 'C', 'Employer')
        self.assertEqual(result.ats, '')


class TeamtailorRoutingTests(unittest.TestCase):
    def test_verified_roots_and_localized_counts_reconcile(self):
        for root, count in [('https://career.sbg-systems.com', '1 offre'),
                            ('https://leafspace.teamtailor.com', '1 job'),
                            ('https://leafspace.teamtailor.com/en-GB', '1 jobs')]:
            transport = PublicBoard(root, count)
            result = fetch_teamtailor(root + '/', 'C', 'Employer', transport)
            self.assertEqual(result.status, 'complete', result.reason)
            self.assertEqual(result.source_url, root + '/jobs')
            self.assertEqual(len(result.jobs), 1)
            self.assertEqual(transport.calls.count(root + '/jobs'), 2)

    def test_count_mismatch_and_filtered_root_never_complete(self):
        root = 'https://career.sbg-systems.com'
        self.assertEqual(fetch_teamtailor(root, 'C', 'Employer', PublicBoard(root, '2 offres')).status, 'partial')
        for url in [root+'/?department=engineering', root+'/#filter',
                    root+'.evil.test/', root+'/jobs/123-engineer']:
            result = fetch_teamtailor(url, 'C', 'Employer', MagicMock())
            self.assertEqual(result.status, 'unsupported', url)


class ListingRetryTests(unittest.TestCase):
    LISTINGS = [
        'https://www.axon.com/careers/all',
        'https://www.axon.com/careers/all?greenhouse-jobs-index%5Bquery%5D=finland',
        'https://www.rohde-schwarz.com/au/career/jobs/career-jobboard_251573.html?change_c=NZ',
        'https://www.rohde-schwarz.com/cac-en/career/jobs/career-jobboard_251573.html?change_c=RU',
        'https://www.rohde-schwarz.com/career/jobs/career-jobboard_251573.html?change_c=HQ',
    ]

    def test_saved_listings_are_excluded_without_erasing_checkpoint(self):
        real = 'https://www.axon.com/careers/job/123-field-engineer'
        progress = BrowserProgress()
        progress.discover([{'url': u, 'title': 'Open roles'} for u in self.LISTINGS] +
                          [{'url': real, 'title': 'Field Engineer'}])
        _exclude_saved_navigation(progress, self.LISTINGS[0])
        self.assertEqual(list(progress.entries()), [real])
        self.assertEqual(len(progress._read('job')), len(self.LISTINGS) + 1)

    def test_job_queries_and_other_hosts_remain_eligible(self):
        for url in [self.LISTINGS[0]+'?gh_jid=123',
                    self.LISTINGS[2]+'&jobId=456',
                    'https://example.com/careers/all',
                    'https://www.rohde-schwarz.com/us/career/jobs/field-engineer_123.html']:
            self.assertTrue(_looks_like_posting_url(url), url)

    def test_listing_pagination_is_still_discoverable(self):
        page = MagicMock()
        url = self.LISTINGS[0] + '?page=2'
        page.locator.return_value.evaluate_all.return_value = [{'href': url, 'text': 'Next page'}]
        self.assertEqual(_listing_pages(page, self.LISTINGS[0]), [url])
