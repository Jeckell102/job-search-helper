import json,unittest
from job_search_helper.teamtailor import fetch_teamtailor
from job_search_helper.ats import HTTPResponse
U='https://careers.mildef.com/jobs'
D='https://careers.mildef.com/jobs/123-engineer'
B='<div>teamtailor</div><table id="jobs_list_container"><a href="'+D+'">Engineer</a></table><h2>1 jobs</h2><a href="/x/apply/general">General Application</a>'
J={'@type':'JobPosting','title':'Engineer','identifier':{'value':'123'},'description':'<p>Build complete hardware systems.</p>'}
class Fake:
 def __init__(self,listing=B,job=None):self.listing=listing;self.job=J if job is None else job
 def get(self,url):
  if url==U:s=self.listing
  elif url==D:s='<script type="application/ld+json">'+json.dumps(self.job)+'</script>'
  else:raise AssertionError(url)
  return HTTPResponse(200,s.encode())
class TeamtailorTests(unittest.TestCase):
 def test_full_description_and_excludes_application(self):
  r=fetch_teamtailor(U,'c','GMS',Fake());self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),1);self.assertEqual(r.jobs[0]['posting_id'],'123')
 def test_pagination_not_complete(self):self.assertEqual(fetch_teamtailor(U,'c','GMS',Fake(B.replace('1 jobs','2 jobs'))).status,'partial')
 def test_identity_or_description_failure(self):
  for k,v in [('identifier',{'value':'other'}),('description',''),('title','Other job')]:
   j=dict(J);j[k]=v;self.assertEqual(fetch_teamtailor(U,'c','GMS',Fake(job=j)).status,'partial')
 def test_filtered_and_foreign_sources_rejected(self):
  for u in [U+'?department=engineering',U.replace('mildef.com','mildef.com.evil.test'),D]:self.assertEqual(fetch_teamtailor(u,'c','GMS',Fake()).status,'unsupported')
