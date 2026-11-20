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
 def test_one_bad_detail_does_not_stop_later_pages(self):
  first=copy.deepcopy(LIST);first['data']['count']=11
  extra=copy.deepcopy(first['data']['positions'][0]);extra.update(id=999,positionUrl='/careers/job/999',displayJobId='R999')
  second=copy.deepcopy(first);second['data']['positions']=[extra]
  bad=first['data']['positions'][1]['id'];calls=[]
  def posting(client,entry,*args):
   calls.append(entry['id'])
   if entry['id']==bad:raise FetchError('partial','Description unavailable')
   return {'posting_id':str(entry['id'])}
  with patch('job_search_helper.northrop._posting',side_effect=posting):
   result=_scan(Transport([response(first),response(second)]),'C','Northrop')
  self.assertEqual(result.status,'partial');self.assertEqual(len(result.jobs),10)
  self.assertEqual(calls[-1],999);self.assertIn(str(bad),result.reason)
 def test_access_denial_stops_further_detail_requests(self):
  calls=[]
  def posting(client,entry,*args):
   calls.append(entry['id']);raise FetchError('blocked','Access denied')
  with patch('job_search_helper.northrop._posting',side_effect=posting):
   result=_scan(Transport([response(LIST)]),'C','Northrop')
  self.assertEqual(result.status,'blocked');self.assertEqual(len(calls),1)
 def test_growing_total_collects_later_page_without_claiming_complete(self):
  first=copy.deepcopy(LIST);first['data']['count']=11
  second=copy.deepcopy(first);second['data']['count']=12
  extra=copy.deepcopy(first['data']['positions'][0]);extra.update(id=998,positionUrl='/careers/job/998',displayJobId='R998')
  last=copy.deepcopy(extra);last.update(id=999,positionUrl='/careers/job/999',displayJobId='R999')
  second['data']['positions']=[extra,last]
  with patch('job_search_helper.northrop._posting',side_effect=lambda c,e,*args:{'posting_id':str(e['id'])}):
   result=_scan(Transport([response(first),response(second)]),'C','Northrop')
  self.assertEqual(result.status,'partial');self.assertEqual(len(result.jobs),12)
  self.assertIn('total changed',result.reason)
 def test_caci_fallback_keeps_its_company_specific_listing_strategy(self):
  with patch('job_search_helper.caci.fetch_caci') as fetch:
   fetch_browser_inventory('Eightfold','https://searchcareers.caci.com/careers','COMP-0001','CACI International')
  fetch.assert_called_once_with('https://searchcareers.caci.com/careers','COMP-0001','CACI International')
 def test_caci_partial_is_not_immediately_downloaded_twice(self):
  from job_search_helper.ats import Inventory
  partial=Inventory('partial',reason='Changed membership',ats='Eightfold')
  fetch=with_browser_fallback(lambda *args:partial)
  with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as browser:
   result=fetch('Eightfold','https://searchcareers.caci.com/careers','COMP-0001','CACI International')
  self.assertIs(result,partial);browser.assert_not_called()
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

 def test_two_bounded_reconciliations_accept_stable_timestamp_tie_order(self):
  # The fixture's first several postings share a posted timestamp.  The
  # exact ordered ID sequence must remain stable across both passes.
  t=Transport([listing(),response(DETAIL),listing(),listing()])
  r=_scan(t,'C','Northrop',reconciliation_rounds=2)
  self.assertEqual(r.status,'complete',r.reason)
  self.assertIn('2 bounded inventory reconciliations',r.reason)

 def test_total_change_between_reconciliation_passes_is_rejected(self):
  changed=copy.deepcopy(LIST)
  changed['data']['count']=2
  changed['data']['positions']=changed['data']['positions'][:2]
  t=Transport([listing(),response(DETAIL),response(changed)])
  r=_scan(t,'C','Northrop',reconciliation_rounds=2)
  self.assertEqual(r.status,'partial')
  self.assertIn('count, pagination, or scope changed',r.reason)

 def test_addition_or_closure_at_page_boundary_is_rejected(self):
  first=copy.deepcopy(LIST); first['data']['count']=11
  initial_second=copy.deepcopy(first)
  initial_extra=copy.deepcopy(first['data']['positions'][0])
  initial_extra.update(id=998,positionUrl='/careers/job/998',displayJobId='R998',postedTs=1791417600)
  initial_second['data']['positions']=[initial_extra]
  changed_second=copy.deepcopy(initial_second)
  extra=copy.deepcopy(first['data']['positions'][0])
  extra.update(id=999,positionUrl='/careers/job/999',displayJobId='R999',postedTs=1791417600)
  changed_second['data']['positions']=[extra]
  t=Transport([response(first),response(initial_second),response(first),response(changed_second)])
  with patch('job_search_helper.northrop._posting',side_effect=lambda c,e,*a:{'posting_id':e['id']}):
   r=_scan(t,'C','Northrop',reconciliation_rounds=1)
  self.assertEqual(r.status,'partial')
  self.assertIn('inventory changed',r.reason)
