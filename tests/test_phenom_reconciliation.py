"""Inventory changes, detail failures, and durable resume behavior."""
from collections import Counter
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from test_phenom import BASE, SOURCE, APP, entry, listing, detail
from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.phenom import fetch_phenom
from job_search_helper.browser_progress import BrowserProgress
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.inbox import InventoryInbox


class Board:
    def __init__(self, snapshots, failures=None, size=2):
        self.snapshots = snapshots
        self.failures = failures or {}
        self.size = size
        self.round = -1
        self.calls = Counter()
        self.visits = []

    def get(self, url):
        self.visits.append(url)
        if '/job/' in url:
            ident = int(url.rsplit('/', 1)[1]); self.calls[ident] += 1
            action = self.failures.get(ident)
            if action:
                return action(self)
            current = self.snapshots[min(self.round, len(self.snapshots)-1)]
            item = next(e for e in current if e['jobId'] == str(ident))
            return detail(ident, title=item['title'], description='<p>Revision '+str(item.get('jobUpdatedDate','original'))+'</p>')
        offset = int(parse_qs(urlsplit(url).query).get('from', ['0'])[0])
        if offset == 0:
            self.round += 1
        items = self.snapshots[min(self.round, len(self.snapshots)-1)]
        return listing(items[offset:offset+self.size], len(items), offset)


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.output = StringIO()
        capture = redirect_stderr(self.output); capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def fetch(self, board, progress=None):
        return fetch_phenom('Phenom', SOURCE, 'C', 'Acme', board, progress=progress)

    def test_closed_middle_posting_does_not_stop_other_details(self):
        initial = [entry(i) for i in (1,2,3)]
        current = [initial[0], initial[2]]
        board = Board([initial,current,current], {2:lambda _:HTTPResponse(410,b'Gone')})
        r = self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual([j['posting_id'] for j in r.jobs],['1','3'])
        self.assertEqual(board.calls,Counter({1:1,2:1,3:1}))
        self.assertEqual(board.round,2)
        self.assertIn('posting_failed',self.output.getvalue())

    def test_edited_title_is_refetched_from_new_listing(self):
        revised = entry(2,title='Senior Engineer')
        board=Board([[entry(),entry(2)],[entry(),revised]],
                    {2:lambda _:detail(2,title='Senior Engineer')})
        r=self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(board.calls[2],2)
        self.assertEqual(r.jobs[1]['title'],'Senior Engineer')

    def test_same_title_revision_refreshes_description(self):
        board=Board([[entry()],[entry(jobUpdatedDate='updated')]])
        r=self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(board.calls[1],2)
        self.assertIn('updated',r.jobs[0]['description'])

    def test_changed_later_page_with_same_total_is_reconciled(self):
        before=[entry(i) for i in (1,2,3,4)]
        after=[entry(i) for i in (1,2,3,5)]
        board=Board([before,after,after])
        r=self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual({j['posting_id'] for j in r.jobs},{'1','2','3','5'})
        self.assertEqual(board.calls,Counter({i:1 for i in (1,2,3,4,5)}))
        self.assertEqual(board.round,2)

    def test_order_only_change_needs_no_refetch(self):
        board=Board([[entry(),entry(2)],[entry(2),entry()]])
        r=self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(board.calls,Counter({1:1,2:1}))
        self.assertEqual(board.round,1)

    def test_unresolved_detail_stays_partial_and_retries_are_bounded(self):
        board=Board([[entry(),entry(2),entry(3)]],{2:lambda _:HTTPResponse(404,b'Gone')})
        r=self.fetch(board)
        self.assertEqual(r.status,'partial',r.reason)
        self.assertEqual({j['posting_id'] for j in r.jobs},{'1','3'})
        self.assertEqual(board.calls,Counter({1:1,2:4,3:1}))
        self.assertIn('job detail 2',r.reason)

    def test_transient_detail_recovers_without_refetching_successes(self):
        board=Board([[entry(),entry(2)]],{1:lambda b:HTTPResponse(503,b'Unavailable') if b.calls[1]==1 else detail()})
        r=self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(board.calls,Counter({1:2,2:1}))

    def test_unstable_removal_does_not_discard_saved_successes(self):
        snapshots=[[entry(i)] for i in range(1,6)]
        board=Board(snapshots)
        r=self.fetch(board)
        self.assertEqual(r.status,'partial',r.reason)
        self.assertEqual({j['posting_id'] for j in r.jobs},{'1','2','3','4'})
        self.assertEqual(board.round,4)

    def test_zero_after_removal_requires_second_complete_empty_snapshot(self):
        board=Board([[entry()],[],[]])
        r=self.fetch(board)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(r.jobs,[])
        self.assertEqual(board.round,2)

    def test_repeated_later_page_keeps_partial_and_details(self):
        board=Board([[entry(),entry(2),entry(3)],[entry(),entry(2),entry()]])
        r=self.fetch(board)
        self.assertEqual(r.status,'partial',r.reason)
        self.assertEqual(len(r.jobs),3)
        self.assertIn('repeated',r.reason)

    def test_blocked_detail_stops_further_requests(self):
        board=Board([[entry(),entry(2),entry(3)]],{2:lambda _:HTTPResponse(403,b'Denied')})
        r=self.fetch(board)
        self.assertEqual(r.status,'blocked')
        self.assertEqual(board.calls,Counter({1:1,2:1}))
        self.assertEqual(len(r.jobs),1)

    def test_rate_limit_stops_instead_of_trying_the_entire_board(self):
        board=Board([[entry(),entry(2),entry(3)]],{2:lambda _:HTTPResponse(429,b'Too many requests')})
        r=self.fetch(board)
        self.assertEqual(r.status,'blocked')
        self.assertEqual(board.calls,Counter({1:1,2:1}))
        self.assertIn('rate limited',r.reason)

    def test_scope_change_during_final_check_is_not_reconciled_as_removal(self):
        class ScopeBoard(Board):
            def get(self,url):
                response=super().get(url)
                if '/job/' not in url and self.round>0:
                    response.body=response.body.replace(b'"allJobs"',b'"differentScope"')
                return response
        board=ScopeBoard([[entry()],[]])
        r=self.fetch(board)
        self.assertEqual(r.status,'partial',r.reason)
        self.assertEqual(len(r.jobs),1)
        self.assertIn('scope changed',r.reason)

    def test_bad_detail_does_not_stop_later_jobs(self):
        board=Board([[entry(),entry(2),entry(3)]],{2:lambda _:detail(2,description=None)})
        r=self.fetch(board)
        self.assertEqual(r.status,'partial',r.reason)
        self.assertEqual({j['posting_id'] for j in r.jobs},{'1','3'})
        self.assertEqual(board.calls[2],4)

    def test_durable_resume_after_interruption_and_source_isolation(self):
        def interrupt(_): raise KeyboardInterrupt()
        with TemporaryDirectory() as d:
            path=Path(d)/'inbox.sqlite3'
            inbox=InventoryInbox(path,'test')
            progress=BrowserProgress(inbox,'cycle','C',SOURCE)
            first=Board([[entry(),entry(2)]],{2:interrupt})
            with self.assertRaises(KeyboardInterrupt):self.fetch(first,progress)
            inbox.close()
            inbox=InventoryInbox(path,'test');self.addCleanup(inbox.close)
            board=Board([[entry(),entry(2)]])
            r=self.fetch(board,BrowserProgress(inbox,'cycle','C',SOURCE))
            self.assertEqual(r.status,'complete',r.reason)
            self.assertEqual(board.calls,Counter({2:1}))
            self.assertEqual(BrowserProgress(inbox,'cycle','C',SOURCE).entries(),{})
            other=Board([[entry(),entry(2)]])
            self.fetch(other,BrowserProgress(inbox,'other-cycle','C',SOURCE))
            self.assertEqual(other.calls,Counter({1:1,2:1}))

    def test_cached_revision_cannot_mask_an_edit_on_resume(self):
        progress=BrowserProgress()
        self.assertEqual(self.fetch(Board([[entry()]]),progress).status,'complete')
        board=Board([[entry(title='Revised')]])
        r=self.fetch(board,progress)
        self.assertEqual(r.status,'complete',r.reason)
        self.assertEqual(board.calls[1],1)
        self.assertEqual(r.jobs[0]['title'],'Revised')

    def test_reappearing_posting_requires_fresh_detail_after_confirmed_absence(self):
        progress=BrowserProgress()
        self.assertEqual(self.fetch(Board([[entry()]]),progress).status,'complete')
        removed=self.fetch(Board([[]]),progress)
        self.assertEqual(removed.status,'complete',removed.reason)
        self.assertTrue(progress._read('phenom_detail_v1')['1']['retired'])
        board=Board([[entry()]],{1:lambda _:detail(description='Newly reopened description')})
        result=self.fetch(board,progress)
        self.assertEqual(result.status,'complete',result.reason)
        self.assertEqual(board.calls[1],1)
        self.assertEqual(result.jobs[0]['description'].split('\n')[0],'Newly reopened description')

    def test_pipeline_wrapper_delivers_progress_to_adapter(self):
        progress=BrowserProgress()
        factory=lambda source:progress
        for expected in (Counter({1:1}),Counter()):
            board=Board([[entry()]])
            with patch('job_search_helper.phenom_session.PhenomSession',return_value=board):
                r=with_browser_fallback(fetch_inventory)('Phenom',SOURCE,'C','Acme',progress_factory=factory)
            self.assertEqual(r.status,'complete',r.reason)
            self.assertEqual(board.calls,expected)


if __name__=='__main__':unittest.main()
