import json,unittest
from job_search_helper.applicantstack import fetch_applicantstack
from job_search_helper.ats import HTTPResponse
U='https://gms4sbc.applicantstack.com/x/openings'
D='https://gms4sbc.applicantstack.com/x/detail/abc123'
B='<table id="data-table"><a href="'+D+'">Engineer</a></table><div>Showing 1 - 1 of 1</div><a href="/x/apply/general">General Application</a>'
J={'@type':'JobPosting','title':'Engineer','identifier':{'value':'abc123'},'description':'<p>Build complete hardware systems.</p>'}
class Fake:
 def __init__(self,listing=B,job=None):self.listing=listing;self.job=J if job is None else job
 def get(self,url):
  if url==U:s=self.listing
  elif url==D:s='<script type="application/ld+json">'+json.dumps(self.job)+'</script>'
  else:raise AssertionError(url)
  return HTTPResponse(200,s.encode())
class ApplicantStackTests(unittest.TestCase):
 def test_full_description_and_excludes_application(self):
  r=fetch_applicantstack(U,'c','GMS',Fake());self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),1);self.assertEqual(r.jobs[0]['posting_id'],'abc123')
 def test_pagination_not_complete(self):self.assertEqual(fetch_applicantstack(U,'c','GMS',Fake(B.replace('of 1','of 2'))).status,'partial')
 def test_identity_or_description_failure(self):
  for k,v in [('identifier',{'value':'other'}),('description',''),('title','Other job')]:
   j=dict(J);j[k]=v;self.assertEqual(fetch_applicantstack(U,'c','GMS',Fake(job=j)).status,'partial')
 def test_filtered_and_foreign_sources_rejected(self):
  for u in [U+'?department=engineering',U.replace('applicantstack.com','applicantstack.com.evil.test'),D]:self.assertEqual(fetch_applicantstack(u,'c','GMS',Fake()).status,'unsupported')
