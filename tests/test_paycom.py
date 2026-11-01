import base64
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from job_search_helper.ats import HTTPResponse, FetchError, fetch_inventory, resolve_board, Inventory
from job_search_helper.paycom import SERVICE, SEARCH, PaycomTransport, _inventory, _posting
from job_search_helper.browser_scraper import with_browser_fallback
from test_ats import Transport, response

BOARD='https://www.paycomonline.net/v4/ats/web.php/portal/'+'A'*32+'/career-page'
def bootstrap(**changes):
    claims=dict(sub='0',system='ats',isInternalJobBoard='',clientcode='ABC')
    claims.update(changes)
    token='anon.'+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')+'.unsigned'
    config={'sessionJWT':token,'libConfig':json.dumps({'atsPortalMantleServiceUrl':SERVICE})}
    return HTTPResponse(200,('var configsFromHost = '+json.dumps(config)+';').encode())
def entry(i=1):return {'jobId':i,'jobTitle':f'Engineer {i}'}
def listing(items=None,total=None):
    items=[entry()] if items is None else items
    return response({'jobPostingPreviews':items,'jobPostingPreviewsCount':len(items) if total is None else total})
def detail(i=1,**changes):
    x=dict(jobId=i,clientCode='ABC',jobTitle=f'Engineer {i}',applyAvailable=True,description='<p>Full responsibilities</p>',qualifications='<p>Experience required</p>',location='Seattle',secondaryLocations=[],remoteType='Hybrid',salaryRange='$140,000')
    x.update(changes);return response({'jobPosting':x})
class API:
    def __init__(self,items):self.items=list(items);self.calls=[]
    def request(self,path,token,payload=None):
        self.calls.append((path,payload));return self.items.pop(0)
class PaycomTests(unittest.TestCase):
    def setUp(self):
        ctx=redirect_stderr(StringIO());ctx.__enter__();self.addCleanup(ctx.__exit__,None,None,None)
    def fetch(self,items,url=BOARD,ats='Paycom',page=None):
        api=API(items);pages=Transport([page or bootstrap()])
        return fetch_inventory(ats,url,'C','Acme',api,discovery_transport=pages),api,pages
    def test_complete_full_details_and_identity(self):
        r,a,p=self.fetch([listing(),detail(),listing()]);self.assertEqual(r.status,'complete',r.reason)
        j=r.jobs[0];self.assertEqual(j['posting_id'],'1');self.assertEqual(j['url'],BOARD.replace('/career-page','/jobs/1'))
        self.assertIn('Experience required',j['description']);self.assertEqual(j['compensation'],'$140,000');self.assertEqual(j['work_arrangement'],'Hybrid')
        self.assertEqual([c[0] for c in a.calls],[SEARCH,'api/ats/job-postings/1',SEARCH])
    def test_empty_requires_recheck(self):
        r,a,_=self.fetch([listing([]),listing([])]);self.assertEqual(r.status,'complete');self.assertEqual(len(a.calls),2)
    def test_pagination_offsets(self):
        api=API([listing([entry(i) for i in range(1,51)],51),listing([entry(51)],51)])
        self.assertEqual(len(_inventory(api,'anonymous')),51)
        self.assertEqual([c[1]['skip'] for c in api.calls],[0,50])
    def test_pagination_repeats_rejected(self):
        api=API([listing([entry(i) for i in range(1,51)],51),listing([entry(1)],51)])
        with self.assertRaises(FetchError):_inventory(api,'anonymous')
    def test_changed_count_rejected(self):
        api=API([listing([entry(i) for i in range(1,51)],51),listing([entry(51),entry(52)],52)])
        with self.assertRaises(FetchError):_inventory(api,'anonymous')
    def test_bad_counts_and_shapes(self):
        for item in [listing([],1),listing([],False),listing([],10001),response({}),listing([None]),listing([entry(0)]),listing([entry(),entry()])]:
            r,_,_=self.fetch([item]);self.assertNotEqual(r.status,'complete');self.assertFalse(r.jobs)
    def test_wrong_detail_tenant_identity_or_closed(self):
        for changes in [{'clientCode':'OTHER'},{'jobId':2},{'jobTitle':'Other'},{'applyAvailable':False},{'description':''},{'secondaryLocations':[{}]}]:
            r,_,_=self.fetch([listing(),detail(**changes)]);self.assertEqual(r.status,'partial',changes);self.assertFalse(r.jobs)
    def test_later_failure_retains_jobs(self):
        r,_,_=self.fetch([listing([entry(),entry(2)]),detail(),HTTPResponse(503,b'failed')]);self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
    def test_final_inventory_change_is_partial(self):
        r,_,_=self.fetch([listing(),detail(),listing([])]);self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
    def test_blocks_and_redirects_not_complete(self):
        for status in [301,401,403,429,500]:
            r,_,_=self.fetch([HTTPResponse(status,b'no')]);self.assertNotEqual(r.status,'complete');self.assertFalse(r.jobs)
    def test_only_anonymous_external_session(self):
        for changes in [{'sub':'123'},{'system':'hr'},{'isInternalJobBoard':'Y'},{'clientcode':''}]:
            r,a,_=self.fetch([],page=bootstrap(**changes));self.assertNotEqual(r.status,'complete');self.assertEqual(a.calls,[])
    def test_service_destination_is_pinned(self):
        page=bootstrap();page.body=page.body.replace(SERVICE.encode(),b'https://evil.example/')
        r,a,_=self.fetch([],page=page);self.assertEqual(r.status,'unsupported');self.assertFalse(a.calls)
    def test_filtered_boards_and_mismatches_never_requested(self):
        for suffix in ['?jobSearchSettingsId=3','#filter','?query=engineer','?x=']:
            r,a,p=self.fetch([],url=BOARD+suffix);self.assertEqual(r.status,'unsupported');self.assertFalse(a.calls+p.urls)
        for label in ['Workday','Paycom shared parent']:
            r,a,p=self.fetch([],ats=label);self.assertEqual(r.status,'unsupported');self.assertFalse(a.calls+p.urls)
    def test_canonical_source(self):
        self.assertEqual(resolve_board('Browser',BOARD+'?utm_source=company')[1],'A'*32+'/career-page')
        for url in [BOARD.replace('https:','http:'),BOARD.replace('www.paycomonline.net','www.paycomonline.net.evil.test'),BOARD.replace('/career-page','/jobs/1')]:
            with self.assertRaises(ValueError):resolve_board('Paycom',url)
    def test_wrapper_discovery(self):
        pages=Transport([HTTPResponse(200,f'<a href="{BOARD}">Jobs</a>'.encode()),bootstrap()]);api=API([listing(),detail(),listing()])
        r=fetch_inventory('Paycom','https://example.com/careers','C','Acme',api,discovery_transport=pages)
        self.assertEqual(r.status,'complete',r.reason)
    def test_transport_rejects_non_read_routes(self):
        t=PaycomTransport()
        for path,payload in [('api/ats/session',{}),('https://evil.example',None),('api/ats/job-postings/1',{}),(SEARCH,None),('api/ats/job-postings/../account',None)]:
            with self.assertRaises(FetchError):t.request(path,'anonymous',payload)
    def test_browser_cannot_override_partial_paycom(self):
        result=Inventory('partial',reason='changed',ats='Paycom')
        with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
            self.assertIs(with_browser_fallback(lambda *a:result)('Paycom',BOARD,'C','Acme'),result);browser.assert_not_called()
    def test_official_detail_fixture(self):
        root=Path(__file__).parent/'fixtures/paycom'
        entries=json.loads((root/'list.json').read_text())['jobPostingPreviews']
        d=json.loads((root/'detail.json').read_text())
        api=API([response(d)])
        job=_posting(api,'anonymous',d['jobPosting']['clientCode'],BOARD,entries[0],'C','AeroTEC')
        self.assertEqual(job['posting_id'],'221994');self.assertIn('Qualifications',d['jobPosting']['qualificationsTitle']);self.assertGreater(len(job['description']),1000)
