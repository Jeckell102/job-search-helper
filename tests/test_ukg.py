import copy
from contextlib import redirect_stderr
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from job_search_helper.ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _safe_api_url, fetch_inventory, resolve_board
from job_search_helper.ukg import SEARCH, _listing, _posting, _compensation, _criteria
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.engine import _inventory_source
from test_ats import Transport as ReadTransport,response

class Transport(ReadTransport):
 def __init__(self, responses):
  super().__init__(responses); self.payloads=[]
 def post(self,url,payload):
  self.payloads.append(payload); return self.get(url)

BID='07442cec-d18e-4589-ab15-8342edc29af7'
ROOT='https://recruiting.ultipro.com'
BOARD=ROOT+'/ACME1000/JobBoard/'+BID
FIX=Path(__file__).parent/'fixtures/ukg'
def ident(i=1):return f'00000000-0000-0000-0000-{i:012d}'
def item(i=1):return {'Id':ident(i),'Title':f'Engineer {i}','RequisitionNumber':f'ENG{i}','PostedDate':'2026-10-08T00:00:00Z'}
def listing(items=None,total=None):
 items=[item()] if items is None else items
 return response({'opportunities':items,'totalCount':len(items) if total is None else total,'locations':[]})
def board(**changes):
 x=dict(Id=BID,AllowExternal=True,AllowInternal=False,HasThirdPartyPostings=False,FilterCategory=None,FilterValues=None);x.update(changes)
 return HTTPResponse(200,('jobBoard: '+json.dumps(x)+', loadUrl: '+json.dumps(BOARD.removeprefix(ROOT)+SEARCH)+', isInternal: false, initialFeaturedOpportunities: []').encode())
def detail(i=1,**changes):
 x=dict(Id=ident(i),Title=f'Engineer {i}',RequisitionNumber=f'ENG{i}',OpportunityIsClosed=False,PublishingStatus=1,
        Description='<p>Deploy customer systems.</p>',Locations=[{'Address':{'City':'Seattle','State':{'Name':'Washington'},'Country':{'Name':'United States'}}}],
        JobBoardMemberships=[{'JobBoardId':BID,'PublishedExternal':True,'ExternalPostedDate':'2026-10-08T00:00:00Z'}],
        JobLocationType=1,Salaried=True,CompensationAnnualMinimum=120000,CompensationAnnualMaximum=160000,CompensationCurrencyCode='USD',
        WorkExperienceCriteria=[{'Required':True,'MinimumRequiredYears':3,'Description':'Field integration'}]);x.update(changes)
 return html_detail(x)
def html_detail(x):return HTTPResponse(200,('var opportunity = new US.Opportunity.CandidateOpportunityDetail('+json.dumps(x)+');').encode())
class UKGTests(unittest.TestCase):
 def setUp(self):
  ctx=redirect_stderr(StringIO());ctx.__enter__();self.addCleanup(ctx.__exit__,None,None,None)
 def fetch(self,items,url=BOARD,ats='UKG / UltiPro',pages=()):
  api=Transport(items);discovery=Transport(pages)
  return fetch_inventory(ats,url,'C','Acme',api,discovery_transport=discovery),api,discovery
 def test_complete_full_description_criteria_and_identity(self):
  r,t,_=self.fetch([board(),listing(),detail(),listing(),board()]);self.assertEqual(r.status,'complete',r.reason)
  j=r.jobs[0];self.assertEqual(j['posting_id'],ident());self.assertEqual(j['req_id'],'ENG1');self.assertEqual(j['ats'],'UKG')
  self.assertIn('Field integration',j['description']);self.assertIn('Required:',j['description']);self.assertEqual(j['location'],'Seattle, Washington, United States')
  self.assertEqual(j['compensation'],'USD 120000 - 160000 per year');self.assertEqual(j['work_arrangement'],'On-site')
  self.assertEqual(j['created_at'],'2026-10-08T00:00:00Z');self.assertEqual(r.source_url,BOARD)
 def test_complete_empty_inventory_requires_metadata_and_recheck(self):
  r,t,_=self.fetch([board(),listing([]),listing([]),board()]);self.assertEqual(r.status,'complete');self.assertFalse(r.jobs);self.assertEqual(len(t.urls),4)
 def test_pagination_and_featured_jobs_are_not_duplicated(self):
  first=[item(i) for i in range(1,51)];first[0]['Featured']=True
  t=Transport([listing(first,51),listing([item(51)],51)])
  jobs=_listing(t,BOARD);self.assertEqual(len(jobs),51);self.assertEqual(t.payloads[0]['opportunitySearch']['Skip'],0);self.assertEqual(t.payloads[1]['opportunitySearch']['Skip'],50)
 def test_repeat_or_missing_page_not_complete(self):
  for last in [listing([item(1)],51),listing([],51),listing([item(51),item(52)],52)]:
   t=Transport([listing([item(i) for i in range(1,51)],51),last])
   with self.assertRaises(FetchError):_listing(t,BOARD)
 def test_counts_and_identity_validation(self):
  for bad in [listing([],False),listing([],10001),listing([None]),listing([dict(item(),Id='../1')]),listing([dict(item(),Title='')]),listing([item(),item()]),response({})]:
   r,t,_=self.fetch([board(),bad]);self.assertNotEqual(r.status,'complete');self.assertFalse(r.jobs)
 def test_detail_must_belong_to_current_external_board(self):
  changes=[{'Id':ident(2)},{'Title':'Other'},{'RequisitionNumber':'OTHER'},{'PublishingStatus':2},{'OpportunityIsClosed':True},{'Description':''},
           {'JobBoardMemberships':[{'JobBoardId':BID,'PublishedExternal':False}]},{'JobBoardMemberships':[{'JobBoardId':ident(8),'PublishedExternal':True}]}]
  for change in changes:
   r,t,_=self.fetch([board(),listing(),detail(**change)]);self.assertEqual(r.status,'partial',change);self.assertFalse(r.jobs)
 def test_changed_posting_date_rejected(self):
  r,_,_=self.fetch([board(),listing(),detail(JobBoardMemberships=[{'JobBoardId':BID,'PublishedExternal':True,'ExternalPostedDate':'changed'}])]);self.assertEqual(r.status,'partial')
 def test_later_failure_keeps_full_jobs(self):
  r,_,_=self.fetch([board(),listing([item(),item(2)]),detail(),HTTPResponse(503,b'error')]);self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
 def test_blocked_not_overridden_by_browser(self):
  r,_,_=self.fetch([HTTPResponse(403,b'denied')]);self.assertEqual(r.status,'blocked')
  with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as b:
   self.assertIs(with_browser_fallback(lambda *a:r)('UKG',BOARD,'C','Acme'),r);b.assert_not_called()
 def test_redirects_not_followed(self):
  r,_,_=self.fetch([HTTPResponse(302,b'',{'Location':'https://evil.example'})]);self.assertNotEqual(r.status,'complete')
 def test_malformed_embedded_data_not_executed(self):
  for value in [b'jobBoard: alert(1)',b'jobBoard: {} jobBoard: {}',b'<h1>Contact Us</h1>']:
   r,_,_=self.fetch([HTTPResponse(200,value)]);self.assertNotEqual(r.status,'complete');self.assertFalse(r.jobs)
 def test_board_identity_external_and_endpoint_verification(self):
  for b in [board(Id=ident(8)),board(AllowExternal=False),board(HasThirdPartyPostings=True),HTTPResponse(200,board().body.replace(b'isInternal: false',b'isInternal: true')),HTTPResponse(200,board().body.replace(SEARCH.encode(),b'/Account/Login'))]:
   r,t,_=self.fetch([b]);self.assertEqual(r.status,'unsupported');self.assertEqual(len(t.urls),1)
 def test_final_inventory_and_scope_changes_remain_partial(self):
  for tail in [[listing([])],[listing(),board(FilterCategory='Department',FilterValues=['Other'])]]:
   r,_,_=self.fetch([board(),listing(),detail(),*tail]);self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
 def test_url_canonicalization_preserves_tenant_board(self):
  for suffix in ['', '/', '/?o=postedDateDesc&q=&w=&wc=&we=&wpst=', '?utm_source=company']:
   name,path,root=resolve_board('UKG / UltiPro',BOARD+suffix);self.assertEqual(root+path,BOARD);self.assertEqual(name,'UKG')
  self.assertEqual(_inventory_source(BOARD+'?o=postedDateDesc&q='),BOARD)
  self.assertNotEqual(_inventory_source(BOARD),_inventory_source(BOARD.replace(BID,ident(2))))
 def test_filters_mismatches_and_shared_sources_never_requested(self):
  for url,ats in [(BOARD+'?q=engineering','UKG'),(BOARD+'?w=Seattle','UKG'),(BOARD+'?f=division','UKG'),(BOARD+'?q=&q=','UKG'),(BOARD+'#filter','UKG'),(BOARD+'/OpportunityDetail?opportunityId='+ident(),'UKG'),(BOARD,'Workday'),(BOARD,'UKG shared parent')]:
   r,t,d=self.fetch([],url,ats);self.assertEqual(r.status,'unsupported',(url,ats));self.assertFalse(t.urls+d.urls)
 def test_only_pinned_safe_public_transport_paths(self):
  for url in [BOARD,BOARD+SEARCH,BOARD+'/OpportunityDetail?opportunityId='+ident()]:_safe_api_url(url)
  for url in [BOARD+'/Account/Login',BOARD+'/QuickApply?opportunityId='+ident(),BOARD+SEARCH+'?x=1',BOARD+'/OpportunityDetail?opportunityId='+ident()+'&internal=true',BOARD+'#x',BOARD.replace('https','http'),BOARD.replace('recruiting.ultipro.com','recruiting.ultipro.com.evil.test')]:
   with self.assertRaises(FetchError):_safe_api_url(url)
  with self.assertRaises(FetchError):HTTPTransport().post(BOARD,{})
 def test_http_transport_allows_only_listing_post(self):
  t=HTTPTransport()
  with patch.object(t,'_request',return_value=response({})) as request:
   t.post(BOARD+SEARCH,{'opportunitySearch':{}});request.assert_called_once()
 def test_wrapper_discovery(self):
  r,t,d=self.fetch([board(),listing(),detail(),listing(),board()],url='https://acme.example/careers',pages=[HTTPResponse(200,f'<iframe src="{BOARD}"></iframe>'.encode())]);self.assertEqual(r.status,'complete',r.reason);self.assertIn('Discovered UKG',r.reason)
 def test_work_location_labels_from_official_ui(self):
  for value,expected in [(0,'Hybrid'),(1,'On-site'),(2,'Remote'),(None,''),(-1,'')]:
   r,_,_=self.fetch([board(),listing(),detail(JobLocationType=value),listing(),board()]);self.assertEqual(r.jobs[0]['work_arrangement'],expected)
 def test_compensation_preserves_period(self):
  j={'Salaried':False,'CompensationHourlyMinimum':50,'CompensationHourlyMaximum':90,'CompensationCurrencyCode':'USD'}
  self.assertEqual(_compensation(j),'USD 50 - 90 per hour')
  self.assertEqual(_compensation({'PayRangeVisible':True,'PayRange':{'PayRangeMinimum':50,'PayRangeMaximum':90},'PayRangeCurrencyCode':'USD'}),'USD 50 - 90')
 def test_official_four_tenant_detail_fixtures(self):
  for stem,lst in [('','http-list'),('globalstar-','globalstar-list'),('cpi-','cpi-list'),('ezurio-','ezurio-list')]:
   entry=json.loads((FIX/(lst+'.json')).read_text())['opportunities'][0];job=json.loads((FIX/(stem+'detail.json')).read_text())
   membership=next(m for m in job['JobBoardMemberships'] if m['PublishedExternal'])
   source=BOARD.replace(BID,membership['JobBoardId']);row=_posting(Transport([html_detail(job)]),source,entry,'C','Acme')
   self.assertGreater(len(row['description']),200);self.assertEqual(row['req_id'],entry['RequisitionNumber'])
   if stem=='cpi-':self.assertIn('Cycle counting',row['description']);self.assertIn('Supply Chain Management',row['description'])
