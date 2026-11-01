import json,unittest
from urllib.parse import urlencode
from unittest.mock import patch
from test_shared_boards import Fake,fixture
from job_search_helper import shared_boards as s
from job_search_helper.shared_extended import listing_extended,posting_extended
from job_search_helper.eightfold import scan,identity
from job_search_helper.ats import Inventory
class ExtendedTests(unittest.TestCase):
 def test_t2s_captured_clearcompany_inventory_is_complete(self):
  b=s.Board('ClearCompany','https://careers-api.clearcompany.com','366df4d7-cb40-1096-8cdb-1f53109453cf','/v1/366df4d7-cb40-1096-8cdb-1f53109453cf')
  u=b.root+b.path+'?pageIndex=0&pageSize=25&source=CJB-0'
  payload=json.loads(fixture('t2s-clearcompany.json'))
  r=s._fetch(b,Fake({u:payload}),'COMP-0311','T2S Solutions',b.url)
  self.assertEqual(r.status,'complete',r.reason)
  self.assertEqual(len(r.jobs),15)
  self.assertEqual(len({j['posting_id'] for j in r.jobs}),15)
  self.assertTrue(all(len(j['description']) > 100 for j in r.jobs))
  self.assertTrue(all(j['company'] == 'T2S Solutions' for j in r.jobs))

 def test_t2s_missing_description_is_partial_not_empty_success(self):
  b=s.Board('ClearCompany','https://careers-api.clearcompany.com','366df4d7-cb40-1096-8cdb-1f53109453cf','/v1/366df4d7-cb40-1096-8cdb-1f53109453cf')
  u=b.root+b.path+'?pageIndex=0&pageSize=25&source=CJB-0'
  payload=json.loads(fixture('t2s-clearcompany.json'))
  payload['results'][0]['description']=''
  r=s._fetch(b,Fake({u:payload}),'COMP-0311','T2S Solutions',b.url)
  self.assertEqual(r.status,'partial')
  self.assertEqual(len(r.jobs),14)

 def test_complete_public_feeds(self):
  cases=[(s.board_link('https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE'),'https://jobs.dayforcehcm.com/api/geo/esa/jobposting/search','dayforce.json'),(s.board_link('https://www.comeet.com/jobs/Ceragon/D3.003'),'https://www.comeet.com/jobs/Ceragon/D3.003','comeet.html'),(s.Board('ClearCompany','https://careers-api.clearcompany.com','00ed92c3-5bfb-7bfb-456d-4d9d77fef9a5','/v1/00ed92c3-5bfb-7bfb-456d-4d9d77fef9a5'),'https://careers-api.clearcompany.com/v1/00ed92c3-5bfb-7bfb-456d-4d9d77fef9a5?pageIndex=0&pageSize=25&source=CJB-0','clearcompany.json'),(s.board_link('https://spa.jibeapply.com/jobs'),'https://spa.jibeapply.com/api/jobs?page=1&limit=100','jibe.json')]
  for b,u,f in cases:
   with self.subTest(provider=b.name):
    r=s._fetch(b,Fake({u:fixture(f)}),'c','SPA',b.url);self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),1);self.assertGreater(len(r.jobs[0]['description']),100)
 def test_jibe_parent_guard(self):
  b=s.board_link('https://spa.jibeapply.com/jobs');r=s._fetch(b,Fake({}),'c','Intrepid',b.url);self.assertNotEqual(r.status,'complete');self.assertFalse(r.jobs)
 def test_dayforce_wrong_tenant(self):
  b=s.board_link('https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE');d=json.loads(fixture('dayforce.json'));d['jobPostings'][0]['clientNamespace']='other';r=s._fetch(b,Fake({b.root+'/api/geo/esa/jobposting/search':d}),'c','C',b.url);self.assertEqual(r.status,'partial')
 def test_dayforce_truncation(self):
  b=s.board_link('https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE');d=json.loads(fixture('dayforce.json'));d['maxCount']=5;d['jobPostings']=[];d['count']=0
  with self.assertRaises(s.FetchError):listing_extended(b,Fake({b.root+'/api/geo/esa/jobposting/search':d}))
 def test_comeet_internal(self):
  b=s.board_link('https://www.comeet.com/jobs/Ceragon/D3.003');e=listing_extended(b,Fake({b.url:fixture('comeet.html')}))[0];e['is_internal']=True
  with self.assertRaises(s.FetchError):posting_extended(b,Fake({} ),e,'c','C')
 def test_applicantpro(self):
  b=s.board_link('https://davidsontech.applicantpro.com/jobs/');params={'cityUrl':'','countryAbbreviation':'','stateAbbreviation':'','isInternal':0};u=b.root+'/core/jobs/18222?'+urlencode({'getParams':json.dumps(params,separators=(',',':'))})
  t=Fake({b.url:'<script>var domain={"domain_id":18222}</script>',u:fixture('applicantpro.json'),b.root+'/jobs/4228192':fixture('applicantpro-detail.html')});r=s._fetch(b,t,'c','D',b.url);self.assertEqual(r.status,'complete',r.reason)
 def test_embedded_filters(self):
  body='<script>COMEET.init({"company-uid":"D5.00D","company-name":"bluewhite","department":"US"})</script>'
  self.assertEqual(s.embedded_boards(body,'https://example.com/careers'),[])
 def test_discovery_does_not_accept_comments(self):
  self.assertEqual(s.embedded_boards('<!-- <script src="https://app.jibecdn.com/main.js"></script> -->','https://example.com/careers'),[])
 def test_public_transport_scope(self):
  for u in ['https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE','https://davidsontech.applicantpro.com/jobs/','https://www.comeet.com/jobs/Ceragon/D3.003']:
   b=s.board_link(u);self.assertFalse(s.allowed(b,b.root+'/api/application',{}));self.assertFalse(s.allowed(b,'https://evil.test/jobs'))
 def test_eightfold_navigation_rejected(self):
  with self.assertRaises(s.FetchError):identity({'id':1,'name':'EEO','positionUrl':'/footer/eeo'})
 def test_eightfold_failure_retains_jobs(self):
  e={'id':1,'name':'Engineer','positionUrl':'/careers/job/1','displayJobId':'A'}
  class Client:
   root='https://careers.example.com'
   def data(self,kind,value):
    if kind=='position_details':return dict(e,publicUrl=self.root+e['positionUrl'],jobDescription='Full engineering role')
    if getattr(self,'read',False):raise TimeoutError()
    self.read=True;return {'count':1,'positions':[e],'appliedFilters':{}}
  r=scan(Client(),'c','C');self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
 def test_shared_fallback_never_generic_merges(self):
  from job_search_helper.browser_scraper import with_browser_fallback
  direct=Inventory('partial',[{'posting_id':'1'}],ats='Rippling');browser=Inventory('partial',[],ats='Rippling')
  with patch('job_search_helper.shared_boards.fetch_shared_browser',return_value=browser),patch('job_search_helper.browser_scraper.fetch_browser_inventory') as generic:
   r=with_browser_fallback(lambda *a:direct)('Rippling','https://ats.rippling.com/example/jobs','c','C');self.assertIs(r,direct);generic.assert_not_called()
if __name__=='__main__':unittest.main()

class AdditionalValidationTests(unittest.TestCase):
 def test_jibe_explicit_zero_without_count(self):
  b=s.board_link('https://spa.jibeapply.com/jobs');r=s._fetch(b,Fake({b.root+'/api/jobs?page=1&limit=100':{'totalCount':0,'jobs':[]}}),'c','SPA',b.url);self.assertEqual(r.status,'complete');self.assertFalse(r.jobs)
 def test_pinpoint_uuid_company_subset(self):
  b=s.board_link('https://astrolab.pinpointhq.com/jobs');d=json.loads(fixture('pinpoint-feed.json'));ident=s.board_link(d['data'][0]['url']).ident;r=s._fetch(b,Fake({b.root+'/postings.json':d}),'c','C',b.url,{ident});self.assertEqual(r.status,'complete');self.assertEqual(len(r.jobs),1)
 def test_css_does_not_prove_empty_inventory(self):
  b=s.board_link('https://a.applytojob.com/apply')
  with self.assertRaises(s.FetchError):s.listing(b,Fake({b.url:'<style>.jobs-list{display:block}</style>'}))
 def test_removed_job_is_reconciled_after_stable_empty_recheck(self):
  b=s.board_link('https://astrolab.pinpointhq.com/jobs');d=json.loads(fixture('pinpoint-feed.json'))
  class Changing(Fake):
   def get(self,url):
    response=super().get(url)
    if len(self.calls)>1:response=s.HTTPResponse(200,b'{"data":[]}')
    return response
  transport=Changing({b.root+'/postings.json':d})
  r=s._fetch(b,transport,'c','C',b.url);self.assertEqual(r.status,'complete');self.assertEqual(len(r.jobs),0)
  self.assertEqual(len(transport.calls),3);self.assertIn('removed 1',r.reason)
 def test_talentbrew_division_is_not_parent(self):
  from job_search_helper.talentbrew import employer_key
  self.assertNotEqual(employer_key('Boeing'),employer_key('Boeing Defense, Space & Security'))
 def test_no_complete_null_identity(self):
  with self.assertRaises(s.FetchError):s.unique([{'id':None}])

class SearchFormTests(unittest.TestCase):
 def test_public_form_board(self):
  bs=s.embedded_boards('<form action="https://spa.jibeapply.com/jobs" method="get"><input name="keywords"></form>','https://spa.com/careers/');self.assertEqual(bs[0].name,'Jibe')
 def test_filtered_form_not_expanded(self):
  bs=s.embedded_boards('<form action="https://spa.jibeapply.com/jobs"><input type="hidden" name="brand" value="other"></form>','https://spa.com/careers/');self.assertEqual(bs,[])

class JazzMarkupTests(unittest.TestCase):
 def test_full_public_markup_without_jsonld(self):
  b=s.board_link('https://a.applytojob.com/apply');u=b.root+'/apply/ABC123/Engineer';e={'id':'ABC123','url':u,'title':'Engineer'}
  body='<link rel="canonical" href="'+u+'"><div class="job-header"><h2>Engineer</h2><div title="Location">Boston, MA</div></div><div id="job-description"><p>Build and validate engineering systems.</p></div><form>Application form must not become description.</form>'
  j=s.html_posting(b,Fake({u:body}),e,'c','C');self.assertEqual(j['description'],'Build and validate engineering systems.');self.assertEqual(j['location'],'Boston, MA')
 def test_markup_wrong_identity_rejected(self):
  b=s.board_link('https://a.applytojob.com/apply');u=b.root+'/apply/ABC123/Engineer'
  with self.assertRaises(s.FetchError):s.html_posting(b,Fake({u:'<h2>Engineer</h2><div id="job-description">Full job details</div>'}),{'id':'ABC123','url':u,'title':'Engineer'},'c','C')

class DispatchTests(unittest.TestCase):
 def test_jibe_widget_over_legacy_login_link(self):
  from job_search_helper.ats import fetch_inventory
  url='https://careers.example.com/';api=url.rstrip('/')+'/api/jobs?page=1&limit=100'
  pages=Fake({url:'<script src="https://app.jibecdn.com/prod/search/main.js"></script><a href="https://careers-example.icims.com/jobs/1/login">Login</a>'})
  r=fetch_inventory('iCIMS',url,'c','Example',Fake({api:fixture('jibe.json')}),discovery_transport=pages);self.assertEqual(r.status,'complete',r.reason);self.assertEqual(r.ats,'Jibe')
 def test_description_void_tags_do_not_truncate(self):
  from job_search_helper.shared_extended import Elements
  p=Elements('<div id="job-description">First<br/>Second<br>Third</div>',{'id:job-description'});self.assertEqual(p.values,['First\nSecond\nThird'])
