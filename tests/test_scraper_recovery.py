import unittest
from contextlib import redirect_stderr
from http.client import IncompleteRead, RemoteDisconnected
from io import StringIO
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from job_search_helper.ats import FetchError, HTTPTransport, fetch_inventory
from job_search_helper.company_sources import repair_source
from test_kbr import Public, Workday
from test_ukg import BOARD, Transport, board, listing, detail, item
from job_search_helper.ukg import fetch_ukg


class ScraperRecoveryTests(unittest.TestCase):
    def response(self, body=b'{}'):
        response = Mock(status=200, headers={})
        response.read.return_value = body
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_truncated_response_is_retried_from_the_start(self):
        broken = self.response()
        broken.read.side_effect = IncompleteRead(b'{"partial":', 10)
        transport = HTTPTransport(sleep=lambda _: None)
        transport.opener = Mock()
        transport.opener.open.side_effect = [broken, self.response(b'{"complete":true}')]
        result = transport.get('https://api.lever.co/v0/postings/acme')
        self.assertEqual(result.body, b'{"complete":true}')
        self.assertEqual(transport.opener.open.call_count, 2)
        broken.__exit__.assert_called_once()

    def test_http_stream_failures_are_bounded_and_safe(self):
        for error in [IncompleteRead(b'private partial response', 1), RemoteDisconnected()]:
            transport = HTTPTransport(sleep=lambda _: None)
            transport.opener = Mock()
            transport.opener.open.side_effect = error
            with self.assertRaises(FetchError) as ctx:
                transport.get('https://api.lever.co/v0/postings/acme')
            self.assertEqual(transport.opener.open.call_count, 3)
            self.assertNotIn('private partial', str(ctx.exception))

    def test_truncated_denial_body_does_not_retry_permission_failure(self):
        body = Mock()
        body.read.side_effect = IncompleteRead(b'', 1)
        transport = HTTPTransport(sleep=lambda _: None)
        transport.opener = Mock()
        transport.opener.open.side_effect = HTTPError('https://api.lever.co/v0/postings/acme', 403, 'Forbidden', {}, body)
        self.assertEqual(transport.get('https://api.lever.co/v0/postings/acme').status, 403)
        self.assertEqual(transport.opener.open.call_count, 1)

    def test_ukg_retains_finished_jobs_on_late_incomplete_read(self):
        with redirect_stderr(StringIO()):
            result = fetch_ukg('UKG', BOARD, 'C', 'Acme', Transport([
                board(), listing([item(), item(2)]), detail(), IncompleteRead(b'', 10)]))
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(result.jobs), 1)

    def test_kbr_dispatch_from_actual_company_configuration_and_old_alias(self):
        for url in ['https://careers.kbr.com/us/en', 'https://jobs.kbr.com/', 'https://jobs.kbr.com/jobs.html']:
            result = fetch_inventory('Phenom (career site)', url, 'COMP-0008', 'KBR', Workday(), discovery_transport=Public())
            self.assertEqual(result.status, 'complete', result.reason)
            self.assertEqual(len(result.jobs), 1)
            self.assertEqual(result.ats, 'KBR')

    def test_verified_source_aliases_preserve_user_changes(self):
        for cid, company, url, target in [
            ('COMP-0027', 'Two Six Technologies', 'https://twosixtech.com/careers/current-opportunities/', 'https://job-boards.greenhouse.io/twosixtechnologies'),
            ('COMP-0279', 'Tulip Interfaces', 'https://tulip.co/careers/', 'https://boards.greenhouse.io/tulip'),
        ]:
            self.assertEqual(repair_source('Browser', url, cid, company)[1], target)
            self.assertEqual(repair_source('Browser', 'https://new.example/jobs', cid, company)[1], 'https://new.example/jobs')
            self.assertEqual(repair_source('Browser', url, cid, 'Another Company')[1], url)

class BrowserIdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from job_search_helper.engine import State
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name) / 'state.db')
        self.addCleanup(self.state.close)

    def engine(self, old_id=None, duplicate=False):
        from job_search_helper.browser_scraper import _posting_id
        from job_search_helper.core import job_key, pack_snapshot, material_hash
        from job_search_helper.engine import Engine
        from job_search_helper.repository import MemoryRepository
        from test_engine import company, posting
        current = posting(title='Director of Field Operations')
        prior = dict(current, ats='Browser', posting_id=old_id or _posting_id(current['url']), req_id='')
        old_key = job_key('C-1', prior['ats'], prior['posting_id'], prior['url'])
        row = {'Company':'Acme', 'Job Key':old_key, 'Official Job URL':prior['url'],
               'Current Snapshot':pack_snapshot({'v':1,'evaluated':prior,'pending':None,'evaluations':[]}),
               'Review Status':'Reviewed','Reconsideration Count':0,'Added to Opportunities?':'Yes',
               'Description Hash':material_hash(prior), 'Source Hash':material_hash(prior),
               'First Seen':'2026-09-01', 'Review Notes':'Keep this review'}
        history=[row,dict(row,**{'Job Key':'duplicate'})] if duplicate else [row]
        repo=MemoryRepository({'Companies':[company()], 'Job History':history,
             'Opportunities':[{'Company':'Acme','Job URL':prior['url'],'Application Status':'Applied','Notes':'User notes'}]})
        engine=Engine(repo,self.state)
        return engine,current,company(),old_key

    def test_migrates_in_place_and_preserves_user_decisions_on_replay(self):
        from job_search_helper.core import job_key
        engine,current,company,old_key=self.engine()
        with patch('job_search_helper.engine.classify_title',return_value='review'):
            engine._stage_posting({},company,current)
            engine._stage_posting({},company,current)
        rows=engine.repo.read('Job History')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['Prior Job Key'],old_key)
        self.assertEqual(rows[0]['Job Key'],job_key('C-1',current['ats'],current['posting_id'],current['url']))
        self.assertEqual(rows[0]['First Seen'],'2026-09-01')
        self.assertEqual(rows[0]['Review Notes'],'Keep this review')
        self.assertEqual(rows[0]['Added to Opportunities?'],'Yes')
        opportunities=engine.repo.read('Opportunities')
        self.assertEqual(len(opportunities),1)
        self.assertEqual(opportunities[0]['Application Status'],'Applied')
        self.assertEqual(opportunities[0]['Notes'],'User notes')

    def test_real_id_or_unrelated_hash_still_requires_disambiguation(self):
        from job_search_helper.browser_scraper import _posting_id
        for ident in ['REAL-OLD-ID',_posting_id('https://other.example/jobs/1')]:
            engine,current,company,_=self.engine(ident)
            before=engine.repo.read('Job History')
            with self.assertRaisesRegex(ValueError,'disambiguation'):
                engine._history(current,company)
            self.assertEqual(engine.repo.read('Job History'),before)

    def test_duplicate_url_still_requires_reconciliation(self):
        engine,current,company,_=self.engine(duplicate=True)
        with self.assertRaisesRegex(ValueError,'Ambiguous history identity'):
            engine._history(current,company)

    def test_new_synthetic_id_does_not_replace_real_identity(self):
        from job_search_helper.browser_scraper import _posting_id
        engine,current,company,_=self.engine('REAL-OLD-ID')
        current['posting_id']=_posting_id(current['url'])
        with self.assertRaisesRegex(ValueError,'disambiguation'):
            engine._history(current,company)

class ListingRecheckTests(unittest.TestCase):
    def reconcile(self, snapshots, detail=None, ids=None):
        from job_search_helper import shared_boards as s
        b=s.board_link('https://jobs.jobvite.com/acme/jobs')
        details=detail or (lambda b,t,e,cid,co:dict(e))
        with patch.object(s,'listing',side_effect=snapshots) as lists, patch.object(s,'posting',side_effect=details) as postings, redirect_stderr(StringIO()):
            result=s._fetch(b,None,'C','Acme',b.url,ids)
        return result,lists,postings

    def scan(self, before, after):
        from job_search_helper import shared_boards as s
        b=s.board_link('https://jobs.jobvite.com/acme/jobs')
        with patch.object(s,'listing',side_effect=[before,after,after]), patch.object(s,'posting',side_effect=lambda b,t,e,cid,co:dict(e)), redirect_stderr(StringIO()):
            return s._fetch(b,None,'C','Acme',b.url)

    def test_reordering_jobs_does_not_make_inventory_partial(self):
        jobs=[{'id':'a','title':'Engineer','url':'https://jobs.jobvite.com/acme/job/a'},
              {'id':'b','title':'Manager','url':'https://jobs.jobvite.com/acme/job/b'}]
        result=self.scan(jobs,list(reversed(jobs)))
        self.assertEqual(result.status,'complete',result.reason)
        self.assertEqual(len(result.jobs),2)

    def test_real_changes_report_added_removed_and_edited_ids(self):
        result=self.scan([{'id':'a','title':'Before'},{'id':'b','title':'Gone'}],
                         [{'id':'a','title':'After'},{'id':'c','title':'New'}])
        self.assertEqual(result.status,'complete',result.reason)
        self.assertEqual(len(result.jobs),2)
        self.assertEqual({e['id']:e['title'] for e in result.jobs},{'a':'After','c':'New'})
        for expected in ['added 1 (IDs: c)','removed 1 (IDs: b)','edited 1 (IDs: a)']:
            self.assertIn(expected,result.reason)

    def test_repeated_identity_cannot_be_hidden_by_dictionary_comparison(self):
        result=self.scan([{'id':'a'}],[{'id':'a'},{'id':'a'}])
        self.assertEqual(result.status,'partial')
        self.assertIn('duplicate',result.reason)

    def test_addition_fetches_only_new_job_then_checks_again(self):
        a={'id':'a'};b={'id':'b'}
        result,lists,details=self.reconcile([[a],[a,b],[b,a]])
        self.assertEqual(result.status,'complete',result.reason)
        self.assertEqual([call.args[2]['id'] for call in details.call_args_list],['a','b'])
        self.assertEqual(lists.call_count,3)

    def test_edited_job_refetched_but_unchanged_job_reused(self):
        a={'id':'a','title':'old'};new={'id':'a','title':'new'};b={'id':'b'}
        result,lists,details=self.reconcile([[a,b],[new,b],[new,b]])
        self.assertEqual(result.status,'complete',result.reason)
        self.assertEqual([call.args[2] for call in details.call_args_list],[a,b,new])
        self.assertIn(new,result.jobs)
        self.assertNotIn(a,result.jobs)

    def test_closed_detail_then_removed_listing_finishes_successfully(self):
        from job_search_helper.ats import FetchError
        result,lists,_=self.reconcile([[{'id':'a'}],[],[]],detail=FetchError('partial','Job closed'))
        self.assertEqual(result.status,'complete',result.reason)
        self.assertFalse(result.jobs)
        self.assertEqual(lists.call_count,3)

    def test_unavailable_new_detail_remains_partial(self):
        from job_search_helper.ats import FetchError
        def detail(b,t,e,cid,co):
            if e['id']=='b':raise FetchError('partial','Description unavailable')
            return dict(e)
        a={'id':'a'};b={'id':'b'}
        result,_,_=self.reconcile([[a],[a,b],[a,b]],detail=detail)
        self.assertEqual(result.status,'partial')
        self.assertEqual(result.jobs,[a])

    def test_continuous_churn_stops_without_claiming_success(self):
        snapshots=[[{'id':str(i)}] for i in range(5)]
        result,lists,details=self.reconcile(snapshots)
        self.assertEqual(result.status,'partial')
        self.assertIn('3 reconciliation rounds',result.reason)
        self.assertEqual(lists.call_count,5)
        self.assertEqual(details.call_count,4)
        self.assertFalse(result.jobs)  # Every fetched job has since disappeared.

    def test_reconciliation_never_expands_company_scope(self):
        a={'id':'a'};b={'id':'b'}
        result,_,details=self.reconcile([[a],[a,b],[a,b]],ids={'a'})
        self.assertEqual(result.status,'partial')
        self.assertEqual(result.jobs,[a])
        self.assertEqual(details.call_count,1)


if __name__ == '__main__':
    unittest.main()
