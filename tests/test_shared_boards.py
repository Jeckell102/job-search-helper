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
