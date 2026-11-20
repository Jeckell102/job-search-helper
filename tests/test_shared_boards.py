import unittest,json,copy
from pathlib import Path
from job_search_helper import shared_boards as s
from job_search_helper.ats import HTTPResponse,fetch_inventory,resolve_board
P=Path(__file__).parent/'fixtures/shared_boards'
class Fake:
 def __init__(self, mapping):self.mapping=mapping;self.calls=[]
 def get(self,url):
  self.calls.append(url);v=self.mapping[url]
  return HTTPResponse(200,v.encode() if isinstance(v,str) else json.dumps(v).encode())
 def post(self,url,payload):return self.get(url)
def fixture(n):return (P/n).read_text()

def rippling_state(*, page=0, total=1, items=None, query_key=None, board='pdwcareers', locale=None):
 state=copy.deepcopy(s.Scripts(fixture('rippling.html')).next())
 state['apiData']['jobBoardSlug']=board
 state['apiData']['jobBoard']['slug']=board
 query=state['dehydratedState']['queries'][0]
 query['queryKey']=query_key if query_key is not None else [
  'board',board,'job-posts',True,
  {'searchQuery':'','departments':[],'workplaceType':None,'country':'','state':'','city':'','page':page,'pageSize':20},
 ]
 if locale is not None:query['queryKey'].append(locale)
 data=query['state']['data']
 data.update(items=items if items is not None else data['items'],page=page,pageSize=20,totalItems=total,totalPages=(total+19)//20)
 return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps({'props':{'pageProps':state}})+'</script>'

class SharedTests(unittest.TestCase):
 def test_scope(self):
  for url in ['https://apply.workable.com/matternet/?department=x','https://ats.rippling.com/pdwcareers/jobs?page=1','https://jobs.jobvite.com/kymetacorp/search?c=Sales','https://a.breezy.hr/?location=NY','https://jobs.smartrecruiters.com/my-applications']:
   with self.assertRaises(ValueError):s.board_link(url)
 def test_single_posting_not_complete(self):
  r=s.fetch_shared('','https://ats.rippling.com/pdwcareers/jobs/ba5de22d-0c49-4d35-802e-230b4ee62792','c','C')
  self.assertEqual(r.status,'unsupported')
 def test_parent_scope(self):
  self.assertEqual(s.fetch_shared('Shared parent','https://a.breezy.hr','c','C').status,'unsupported')
 def test_pinned_transport(self):
  b=s.board_link('https://apply.workable.com/matternet/')
  for u in ['https://apply.workable.com/api/v3/accounts/other/jobs','https://evil.test/api/v3/accounts/matternet/jobs','https://apply.workable.com/api/v3/accounts/matternet/applications']:
   self.assertFalse(s.allowed(b,u,{}))
 def test_full_inventory(self):
  cases=[('https://ats.rippling.com/pdwcareers/jobs',{'https://ats.rippling.com/pdwcareers/jobs':fixture('rippling.html'),'https://ats.rippling.com/pdwcareers/jobs/ba5de22d-0c49-4d35-802e-230b4ee62792':fixture('rippling-detail.html')}),('https://astrolab.pinpointhq.com/jobs',{'https://astrolab.pinpointhq.com/postings.json':fixture('pinpoint-feed.json')}),('https://careers.smartrecruiters.com/GrantekSystemsIntegration',{'https://api.smartrecruiters.com/v1/companies/GrantekSystemsIntegration/postings?limit=100&offset=0':fixture('smartrecruiters-feed.json'),'https://api.smartrecruiters.com/v1/companies/GrantekSystemsIntegration/postings/744000153853089':fixture('smartrecruiters-detail.json')}),('https://apply.workable.com/matternet/',{'https://apply.workable.com/api/v3/accounts/matternet/jobs':fixture('workable-network-0.json'),'https://apply.workable.com/api/v2/accounts/matternet/jobs/4DA75B4F3F':fixture('workable-detail.json')})]
  for url,m in cases:
   with self.subTest(url=url):
    r=s.fetch_shared('',url,'c','C',Fake(m));self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),1);self.assertGreater(len(r.jobs[0]['description']),100)
 def test_rippling_trailing_locale_query_key_uses_normal_dispatch(self):
  url='https://ats.rippling.com/pdwcareers/jobs'
  state=rippling_state(locale='en-US')
  r=s.fetch_shared('',url,'c','C',Fake({url:state,url+'/ba5de22d-0c49-4d35-802e-230b4ee62792':fixture('rippling-detail.html')}))
  self.assertEqual(r.status,'complete',r.reason)
  self.assertEqual(len(r.jobs),1)
 def test_rippling_false_public_flag_is_valid_schema(self):
  b=s.board_link('https://ats.rippling.com/pdwcareers/jobs')
  key=['board','pdwcareers','job-posts',False,{'searchQuery':'','departments':[],'workplaceType':None,'country':'','state':'','city':'','page':0,'pageSize':20},'en-US']
  self.assertEqual(len(s.listing(b,Fake({b.url:rippling_state(query_key=key)}))),1)
 def test_rippling_query_key_rejects_invalid_scope_and_shape(self):
  b=s.board_link('https://ats.rippling.com/pdwcareers/jobs')
  valid=['board','pdwcareers','job-posts',True,{'searchQuery':'','departments':[],'workplaceType':None,'country':'','state':'','city':'','page':0,'pageSize':20}]
  cases={
   'missing filters':['board','pdwcareers','job-posts',True,'en-US'],
   'ambiguous filters':valid+[{}],
   'filtered search':['board','pdwcareers','job-posts',True,{**valid[4],'searchQuery':'engineer'}],
   'wrong locale':valid+['fr-FR'],
   'nonboolean flag':['board','pdwcareers','job-posts','public',valid[4]],
  }
  for label,key in cases.items():
   with self.subTest(label=label),self.assertRaises(s.FetchError):
    s.listing(b,Fake({b.url:rippling_state(query_key=key)}))
  bad=rippling_state();bad=bad.replace('"jobBoardSlug": "pdwcareers"','"jobBoardSlug": "other"')
  with self.assertRaises(s.FetchError):s.listing(b,Fake({b.url:bad}))
 def test_rippling_trailing_locale_query_key_paginates_all_pages(self):
  b=s.board_link('https://ats.rippling.com/pdwcareers/jobs')
  jobs=[{'id':f'job-{number}'} for number in range(21)]
  first=rippling_state(page=0,total=21,items=jobs[:20],locale='en-US')
  second=rippling_state(page=1,total=21,items=jobs[20:],locale='en-US')
  rows=s.listing(b,Fake({b.url:first,b.url+'?page=1':second}))
  self.assertEqual([row['id'] for row in rows],[row['id'] for row in jobs])
 def test_jazz_and_jobvite(self):
  for name,url,ident,title,detail in [('JazzHR','https://g2ops.applytojob.com/apply','AONmJi1N5j','Assistant Customer Technical Representative (ACTR)','https://g2ops.applytojob.com/apply/AONmJi1N5j/Assistant-Customer-Technical-Representative-ACTR'),('Jobvite','https://jobs.jobvite.com/kymetacorp/jobs','oCOKAfwu','Manager,\xa0Engineering Project Leader','https://jobs.jobvite.com/kymetacorp/job/oCOKAfwu')]:
   marker='jobs-list' if name=='JazzHR' else 'jv-job-list';t=Fake({url:f'<div class="{marker}"><a href="{detail}">{title}</a></div>',detail:fixture(name.lower()+'-detail.html')});r=s.fetch_shared(name,url,'c','C',t);self.assertEqual(r.status,'complete',r.reason)
 def test_duplicates(self):
  with self.assertRaises(s.FetchError):s.unique([{'id':'1'},{'id':'1'}])
 def test_html_empty_unproven(self):
  b=s.board_link('https://a.applytojob.com/apply')
  with self.assertRaises(s.FetchError):s.listing(b,Fake({b.url:'<h1>Careers</h1>'}))
 def test_isolved_verified_empty_inventory(self):
  url='https://igov.isolvedhire.com/iframe/mobile'
  body='<div class="job-listings"></div><p>Sorry, we have no current job openings.</p>'
  r=s.fetch_shared('isolved',url,'COMP-0307','iGov',Fake({url:body}))
  self.assertEqual(r.status,'complete',r.reason)
  self.assertEqual(r.jobs,[])
 def test_smart_total_mismatch(self):
  b=s.board_link('https://careers.smartrecruiters.com/Test');r=s._fetch(b,Fake({'https://api.smartrecruiters.com/v1/companies/Test/postings?limit=100&offset=0':{'offset':0,'limit':100,'totalFound':5,'content':[]}}),'c','C',b.url);self.assertEqual(r.status,'partial')
 def test_smart_scope_identifier_case_is_insensitive(self):
  feed=json.loads(fixture('smartrecruiters-feed.json'))
  detail=json.loads(fixture('smartrecruiters-detail.json'))
  feed['content'][0]['company']['identifier']='granteksystemsintegration'
  detail['company']['identifier']='granteksystemsintegration'
  detail['postingUrl']=detail['postingUrl'].replace('GrantekSystemsIntegration','granteksystemsintegration')
  u='https://careers.smartrecruiters.com/GrantekSystemsIntegration'
  api='https://api.smartrecruiters.com/v1/companies/GrantekSystemsIntegration/postings?limit=100&offset=0'
  detail_url='https://api.smartrecruiters.com/v1/companies/GrantekSystemsIntegration/postings/744000153853089'
  r=s.fetch_shared('',u,'c','C',Fake({api:feed,detail_url:detail}))
  self.assertEqual(r.status,'complete',r.reason)
  self.assertEqual(len(r.jobs),1)
 def test_routing(self):
  self.assertEqual(resolve_board('Browser','https://ats.rippling.com/pdwcareers/jobs')[0],'Rippling')
if __name__=='__main__':unittest.main()
