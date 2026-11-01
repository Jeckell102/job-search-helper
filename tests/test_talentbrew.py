from collections import Counter
from contextlib import redirect_stderr
from io import StringIO
import json,math,unittest
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from job_search_helper.inbox import InventoryInbox
from unittest.mock import patch
from job_search_helper.shared_boards import Board
from job_search_helper.talentbrew import scan,page_entries,next_page
from job_search_helper.browser_progress import BrowserProgress
from job_search_helper.browser_scraper import with_browser_fallback
from job_search_helper.ats import Inventory,FetchError

ROOT='https://careers.l3harris.com'
BOARD=Board('TalentBrew',ROOT,'l3harris','/en/search-jobs')
COMPANY='L3Harris Technologies'
def entry(i,title=None):return dict(id=str(i),url=f'{ROOT}/en/job/city/engineer/1/{i}',title=title or f'Engineer {i}')

class Locator:
 def __init__(self,page,selector):self.page=page;self.selector=selector
 def count(self):return 1
 def evaluate(self,*args):
  p=self.page;c=p.context;n=len(c.current);size=c.size
  if c.listing_error:raise c.listing_error
  return dict({'data-total-job-results':str(n),'data-records-per-page':str(size),'data-current-page':str(p.number),'data-total-pages':str(max(1,math.ceil(n/size)))},**c.attrs)
 def locator(self,selector):return Locator(self.page,selector)
 def evaluate_all(self,*args):
  p=self.page;c=p.context
  return c.current[(p.number-1)*c.size:p.number*c.size]
 def click(self,**kwargs):self.page.number+=1

class Page:
 def __init__(self,context,detail=False):self.context=context;self.detail=detail;self.number=1;self.closed=False;self.url=''
 def goto(self,url,**kwargs):
  assert kwargs.get('wait_until')=='domcontentloaded'
  self.url=url;c=self.context
  if not self.detail:
   c.round+=1;self.number=1;c.current=c.snapshots[min(c.round,len(c.snapshots)-1)]
   return SimpleNamespace(status=200)
  self.ident=url.rsplit('/',1)[1];c.calls[self.ident]+=1
  if c.interrupt==self.ident:raise KeyboardInterrupt()
  return SimpleNamespace(status=c.status.get(self.ident,200))
 def locator(self,selector):return Locator(self,selector)
 def wait_for_selector(self,*a,**k):pass
 def wait_for_function(self,*a,**k):pass
 def content(self):
  c=self.context;ident=self.ident
  if ident in c.invalid:return '<script type="application/ld+json">{bad JSON}</script>'
  e=next(e for e in c.current if e['id']==ident)
  job={'@type':'JobPosting','url':e['url'],'title':c.titles.get(ident,e['title']),
       'description':'Full engineering description.','hiringOrganization':{'name':c.employer},'identifier':{'value':'REQ-'+ident}}
  return '<script type="application/ld+json">'+json.dumps(job)+'</script>'
 def close(self):self.closed=True

class Context:
 def __init__(self,snapshots,**options):
  self.snapshots=snapshots;self.round=-1;self.current=[];self.calls=Counter();self.pages=[];self.size=2
  self.attrs={};self.status={};self.invalid=set();self.titles={};self.employer=COMPANY;self.interrupt=None;self.listing_error=None
  self.__dict__.update(options)
 def new_page(self):
  p=Page(self,len(self.pages)==1);self.pages.append(p);return p

class TalentBrewTests(unittest.TestCase):
 def setUp(self):
  self.logs=StringIO();capture=redirect_stderr(self.logs);capture.__enter__();self.addCleanup(capture.__exit__,None,None,None)
 def fetch(self,c,progress=None,max_jobs=10000):return scan(BOARD,c,'C',COMPANY,max_jobs,progress=progress)
 def test_full_inventory_reads_all_pages_before_details_and_rechecks(self):
  c=Context([[entry(i) for i in range(1,6)]])
  r=self.fetch(c);self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),5)
  self.assertEqual(c.round,1);self.assertTrue(all(p.closed for p in c.pages))
 def test_full_recheck_accepts_order_changes(self):
  c=Context([[entry(1),entry(2)],[entry(2),entry(1)]])
  r=self.fetch(c);self.assertEqual(r.status,'complete',r.reason);self.assertEqual(c.calls,Counter({'1':1,'2':1}))
 def test_later_page_same_count_replacement_is_reconciled(self):
  c=Context([[entry(i) for i in (1,2,3)],[entry(i) for i in (1,2,4)]])
  r=self.fetch(c);self.assertEqual(r.status,'complete',r.reason);self.assertEqual({j['posting_id'] for j in r.jobs},{'1','2','4'});self.assertEqual(c.round,2)
 def test_bad_json_keeps_later_details_and_specific_diagnostics(self):
  c=Context([[entry(i) for i in (1,2,3)]],invalid={'2'})
  r=self.fetch(c);self.assertEqual(r.status,'partial');self.assertEqual({j['posting_id'] for j in r.jobs},{'1','3'})
  self.assertIn('Invalid JSON-LD',r.reason);self.assertIn('posting=2',r.reason);self.assertIn('advertised=3',r.reason);self.assertEqual(c.calls['2'],4)
 def test_closed_posting_requires_stable_absence(self):
  c=Context([[entry(1),entry(2),entry(3)],[entry(1),entry(3)]],status={'2':410})
  r=self.fetch(c);self.assertEqual(r.status,'complete',r.reason);self.assertEqual(c.calls,Counter({'1':1,'2':1,'3':1}));self.assertEqual(c.round,2)
 def test_missing_still_listed_is_not_complete(self):
  c=Context([[entry(1),entry(2)]],status={'2':404})
  r=self.fetch(c);self.assertEqual(r.status,'partial');self.assertEqual(c.calls['2'],4)
 def test_edited_title_is_refetched(self):
  c=Context([[entry(1)],[entry(1,'Updated Engineer')]],titles={'1':'Updated Engineer'})
  r=self.fetch(c);self.assertEqual(r.status,'complete',r.reason);self.assertEqual(c.calls['1'],2)
 def test_access_denial_stops_requests(self):
  for status in (401,403,429):
   c=Context([[entry(1),entry(2),entry(3)]],status={'2':status})
   r=self.fetch(c);self.assertEqual(r.status,'blocked');self.assertEqual(c.calls,Counter({'1':1,'2':1}));self.assertIn(str(status),r.reason)
 def test_wrong_employer_is_not_assigned_to_company(self):
  c=Context([[entry(1)]],employer='Different Corporation')
  r=self.fetch(c);self.assertEqual(r.status,'unsupported');self.assertEqual(r.jobs,[])
 def test_boeing_division_rejected_before_parent_scan(self):
  c=Context([[entry(1)]]);b=Board('TalentBrew','https://jobs.boeing.com','boeing','/search-jobs')
  r=scan(b,c,'B','Boeing Defense, Space & Security');self.assertEqual(r.status,'unsupported');self.assertEqual(c.pages,[]);self.assertIn('division',r.reason)
 def test_missing_numeric_attribute_explains_field(self):
  c=Context([[entry(1)]],attrs={'data-total-pages':''})
  r=self.fetch(c);self.assertEqual(r.status,'partial');self.assertIn('data-total-pages',r.reason);self.assertEqual(c.calls,Counter())
 def test_filter_scope_never_silently_expands(self):
  c=Context([[entry(1)]],attrs={'data-organization-ids':'[123]'})
  r=self.fetch(c);self.assertEqual(r.status,'unsupported');self.assertEqual(c.calls,Counter())
 def test_duplicate_page_keeps_partial(self):
  c=Context([[entry(1),entry(2),entry(1)]])
  r=self.fetch(c);self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),2);self.assertIn('repeated',r.reason)
 def test_resume_preserves_successes_after_interrupt(self):
  with TemporaryDirectory() as directory:
   path=Path(directory)/'progress.sqlite3';inbox=InventoryInbox(path,'test')
   progress=BrowserProgress(inbox,'cycle','C',BOARD.url)
   c=Context([[entry(1),entry(2)]],interrupt='2')
   try:
    with self.assertRaises(KeyboardInterrupt):self.fetch(c,progress)
    self.assertTrue(all(p.closed for p in c.pages))
   finally:inbox.close()
   inbox=InventoryInbox(path,'test')
   try:
    progress=BrowserProgress(inbox,'cycle','C',BOARD.url)
    c=Context([[entry(1),entry(2)]]);r=self.fetch(c,progress)
    self.assertEqual(r.status,'complete',r.reason);self.assertEqual(c.calls,Counter({'2':1}));self.assertEqual(progress.entries(),{})
   finally:inbox.close()
 def test_removed_then_reappearing_job_refetches(self):
  p=BrowserProgress();self.fetch(Context([[entry(1)]]),p);self.fetch(Context([[]]),p)
  c=Context([[entry(1)]]);r=self.fetch(c,p);self.assertEqual(r.status,'complete');self.assertEqual(c.calls['1'],1)
 def test_bound_keeps_validated_details(self):
  r=self.fetch(Context([[entry(1),entry(2)]]),max_jobs=1);self.assertEqual(r.status,'partial');self.assertEqual(len(r.jobs),1)
 def test_public_http_detail_path_validates_and_disposes_responses(self):
  c=Context([[entry(1),entry(2)]])
  responses=[]
  def get(url,**kwargs):
   self.assertEqual(kwargs['max_redirects'],0)
   page=c.pages[1];status=page.goto(url,wait_until='domcontentloaded').status
   response=SimpleNamespace(status=status,url=url,body=lambda:page.content().encode(),disposed=False)
   response.dispose=lambda:setattr(response,'disposed',True)
   responses.append(response);return response
  c.request=SimpleNamespace(get=get)
  with patch('job_search_helper.talentbrew.time.sleep'):
   r=self.fetch(c)
  self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(responses),2);self.assertTrue(all(x.disposed for x in responses))
 def test_http_200_challenge_stops_without_trying_later_postings(self):
  c=Context([[entry(1),entry(2)]])
  def get(url,**kwargs):return SimpleNamespace(status=200,url=url,body=lambda:b'<title>Just a moment</title>',dispose=lambda:None)
  c.request=SimpleNamespace(get=get)
  r=self.fetch(c);self.assertEqual(r.status,'blocked');self.assertIn('human verification',r.reason)
 def test_l3harris_detail_value_error_is_actionable_and_response_is_released(self):
  c=Context([[entry(1)]])
  released=[]
  def get(url,**kwargs):
   response=SimpleNamespace(status=200,url=url,body=lambda:(_ for _ in ()).throw(ValueError('compressed detail payload is malformed')))
   response.dispose=lambda:released.append(url)
   return response
  c.request=SimpleNamespace(get=get)
  r=self.fetch(c)
  self.assertEqual(r.status,'partial')
  self.assertIn('job detail; page=1; posting=1',r.reason)
  self.assertIn('ValueError: compressed detail payload is malformed',r.reason)
  self.assertEqual(len(released),4)
 def test_l3harris_missing_request_response_is_not_masked_by_cleanup(self):
  c=Context([[entry(1)]],request=SimpleNamespace(get=lambda *args,**kwargs:None))
  r=self.fetch(c)
  self.assertEqual(r.status,'partial')
  self.assertIn('TalentBrew page returned no navigation response',r.reason)
  self.assertNotIn('AttributeError',r.reason)
 def test_l3harris_cleanup_failure_has_its_own_diagnostic(self):
  c=Context([[entry(1)]])
  def get(url,**kwargs):
   response=SimpleNamespace(status=200,url=url,body=lambda:b'<script type="application/ld+json">{}</script>')
   response.dispose=lambda:(_ for _ in ()).throw(ValueError('connection already closed'))
   return response
  c.request=SimpleNamespace(get=get)
  r=self.fetch(c)
  self.assertEqual(r.status,'partial')
  self.assertIn('response cleanup failed (ValueError: connection already closed)',r.reason)
 def test_listing_value_error_keeps_stage_and_cause(self):
  c=Context([[entry(1)]],listing_error=ValueError('search results attributes are incomplete'))
  r=self.fetch(c)
  self.assertEqual(r.status,'partial')
  self.assertIn('listing counts; page=1; posting=-',r.reason)
  self.assertIn('ValueError: search results attributes are incomplete',r.reason)
 def test_checkpoint_for_another_company_is_not_reused(self):
  p=BrowserProgress();self.fetch(Context([[entry(1)]]),p)
  c=Context([[entry(1)]],employer='Different Employer')
  r=scan(BOARD,c,'OTHER','Different Employer',progress=p)
  self.assertEqual(r.status,'complete',r.reason);self.assertEqual(c.calls['1'],1);self.assertEqual(r.jobs[0]['company_id'],'OTHER')
 def test_waits_for_pagination_controller_before_clicking(self):
  c=Context([[entry(1),entry(2),entry(3)]]);page=c.new_page();page.goto(BOARD.url,wait_until='domcontentloaded')
  calls=[]
  def wait(script,**kwargs):
   calls.append(script)
   if 'elasticSearch' in script:raise TimeoutError()
  page.wait_for_function=wait
  with self.assertRaisesRegex(FetchError,'controller not ready'):next_page(page,2)
  self.assertEqual(page.number,1);self.assertEqual(len(calls),1)
 def test_full_recheck_uses_a_fresh_listing_page(self):
  c=Context([[entry(1),entry(2),entry(3)]])
  r=self.fetch(c);self.assertEqual(r.status,'complete',r.reason)
  self.assertEqual(len(c.pages),3);self.assertTrue(c.pages[0].closed);self.assertFalse(c.pages[2].detail)
 def test_progress_factory_passes_through_browser_wrapper(self):
  factory=lambda source:BrowserProgress();expected=Inventory('partial',ats='TalentBrew')
  with patch('job_search_helper.shared_boards.fetch_shared_browser',return_value=expected) as browser:
   result=with_browser_fallback(lambda *args:Inventory('blocked',ats='TalentBrew'))('TalentBrew',BOARD.url,'C',COMPANY,progress_factory=factory)
  self.assertIs(result,expected);self.assertIs(browser.call_args.kwargs['progress_factory'],factory)

if __name__=='__main__':unittest.main()
