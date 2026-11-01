from contextlib import redirect_stderr
from io import StringIO
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from job_search_helper.ats import HTTPResponse, FetchError, fetch_inventory
from job_search_helper.northrop import BOARD, BrowserClient, _source, _scan, _posting
from job_search_helper.browser_scraper import jobs_from_json_payload, _extract_links, fetch_browser_inventory, with_browser_fallback
from test_browser_scraper import FakePage
from test_ats import Transport, response
FIX=Path(__file__).parent/'fixtures/northrop'
LIST=json.loads((FIX/'list.json').read_text())
DETAIL=json.loads((FIX/'detail.json').read_text())
def listing(entries=None):
 x=copy.deepcopy(LIST);x['data']['positions']=[x['data']['positions'][0]] if entries is None else entries;x['data']['count']=len(x['data']['positions']);return response(x)
class NorthropTests(unittest.TestCase):
 def setUp(self):
  ctx=redirect_stderr(StringIO());ctx.__enter__();self.addCleanup(ctx.__exit__,None,None,None)
 def test_complete_fixture(self):
  t=Transport([listing(),response(DETAIL),listing()]);r=_scan(t,'C','Northrop');self.assertEqual(r.status,'complete',r.reason)
  j=r.jobs[0];self.assertEqual(j['req_id'],'R10255003');self.assertGreater(len(j['description']),5000);self.assertEqual(j['title'],DETAIL['data']['name']);self.assertEqual(j['url'],DETAIL['data']['publicUrl'])
 def test_corporate_navigation_json_is_not_jobs(self):
  payload=[{'name':s,'id':'nav-'+str(i),'url':f'/careers/{s.lower().replace(" ","-" )}'} for i,s in enumerate(['EEO','E-Verify','Contact Us','Privacy','Engineering'])]
  self.assertEqual(jobs_from_json_payload(payload,'https://www.northropgrumman.com/careers','C','Northrop','Browser'),[])
 def test_exact_reported_links_are_excluded_generically(self):
  anchors=[{'text':s,'href':'https://example.com/careers/'+s.lower().replace(' ','-')} for s in ['EEO','E-Verify','Contact Us']]
  self.assertEqual(_extract_links(FakePage(anchors),'https://example.com/careers'),[])
 def test_cms_navigation_cannot_enter_structured_inventory(self):
  x=copy.deepcopy(LIST);x['data']['positions']=[{'id':1,'name':'EEO','positionUrl':'/careers/eeo'}];x['data']['count']=1
  r=_scan(Transport([response(x)]),'C','Northrop');self.assertEqual(r.status,'partial');self.assertEqual(r.jobs,[])
 def test_full_detail_identity_required(self):
  for key,value in [('id',1),('displayJobId','R999'),('publicUrl','https://evil.example/jobs/1'),('jobDescription',''),('name','Contact Us')]:
   x=copy.deepcopy(DETAIL);x['data'][key]=value
   r=_scan(Transport([listing(),response(x)]),'C','Northrop');self.assertEqual(r.status,'partial');self.assertFalse(r.jobs)
 def test_no_expansion_of_filtered_sources(self):
  for url in [BOARD+'?query=engineer',BOARD+'?pid=123',BOARD+'#filters',BOARD+'/job/123','https://jobs.northropgrumman.com.evil.test/careers','http://www.northropgrumman.com/careers']:
   with self.assertRaises(FetchError):_source(url)
  self.assertEqual(_source('https://www.northropgrumman.com/careers'),BOARD)
 def test_browser_routing_uses_specialized_adapter(self):
  with patch('job_search_helper.northrop.fetch_northrop') as f:
   fetch_browser_inventory('Browser','https://www.northropgrumman.com/careers','C','Northrop');f.assert_called_once()
 def test_direct_path_never_scrapes_corporate_cms(self):
  with patch('job_search_helper.discovery.discover_board') as d:
   r=fetch_inventory('Browser','https://www.northropgrumman.com/careers','C','Northrop');self.assertEqual(r.status,'unsupported');d.assert_not_called()
 def test_partial_validation_is_not_complete(self):
  r=_scan(Transport([listing()]),'C','Northrop',max_jobs=0);self.assertEqual(r.status,'partial');self.assertIn('bounded',r.reason)
 def test_failure_retains_full_jobs(self):
  r=_scan(Transport([listing(),response(DETAIL),HTTPResponse(500,b'error')]),'C','Northrop');self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
 def test_final_page_changes_rejected(self):
  r=_scan(Transport([listing(),response(DETAIL),listing([])]),'C','Northrop');self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
 def test_blocked_data_not_an_empty_complete_inventory(self):
  r=_scan(Transport([HTTPResponse(403,b'denied')]),'C','Northrop');self.assertEqual(r.status,'blocked');self.assertFalse(r.jobs)
 def test_safe_get_endpoints_only(self):
  t=BrowserClient(None)
  for path in ['/api/pcsx/apply','https://evil.example','/api/pcsx/search?domain=other.com&query=&location=&start=0&']:
   with self.assertRaises(FetchError):t.get(path)
 def test_zero_requires_explicit_total_and_recheck(self):
  r=_scan(Transport([listing([]),listing([])]),'C','Northrop');self.assertEqual(r.status,'complete');self.assertFalse(r.jobs)
 def test_multiple_pages(self):
  entries=copy.deepcopy(LIST['data']['positions']);extra=copy.deepcopy(entries[0]);extra.update(id=999,positionUrl='/careers/job/999',displayJobId='R999')
  first=copy.deepcopy(LIST);first['data']['count']=11
  second=copy.deepcopy(first);second['data']['positions']=[extra]
  t=Transport([response(first),response(second),response(first),response(second)])
  with patch('job_search_helper.northrop._posting',side_effect=lambda c,e,*a:{'posting_id':e['id']}):
   r=_scan(t,'C','Northrop')
  self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),11);self.assertIn('start=10',t.urls[1])

 def test_repeated_pagination_retains_jobs_without_completeness(self):
  first=copy.deepcopy(LIST);first['data']['count']=11
  second=copy.deepcopy(first);second['data']['positions']=first['data']['positions'][:1]
  t=Transport([response(first),response(second)])
  with patch('job_search_helper.northrop._posting',side_effect=lambda c,e,*a:{'posting_id':e['id']}):
   r=_scan(t,'C','Northrop')
  self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),10);self.assertIn('repeated',r.reason)
 def test_browser_timeout_preserves_valid_jobs(self):
  t=Transport([listing(),response(DETAIL)])
  r=_scan(t,'C','Northrop');self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
