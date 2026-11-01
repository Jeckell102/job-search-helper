import unittest,json
from job_search_helper.massvirtual import fetch_massvirtual,SOURCE
from job_search_helper.ats import HTTPResponse
class Fake:
 def __init__(self,b): self.body=json.dumps({'jobs':b}).encode(); self.calls=0
 def get(self,url): self.calls+=1; return HTTPResponse(200,self.body,{'content-type':'application/json'})
ROW={'jobId':1,'companyName':'Mass Virtual, Inc.','title':'Engineer','description':'x '*300,'displayUrl':'https://recruiting.paylocity.com/recruiting/jobs/Details/1/Mass-Virtual-Inc/Engineer','jobLocation':'Orlando, FL','publishedDate':'2026-10-01'}
class Tests(unittest.TestCase):
 def test_feed_complete_reread(self):
  f=Fake([ROW]);r=fetch_massvirtual(SOURCE,'COMP-0344','Mass Virtual',f);self.assertEqual(r.status,'complete');self.assertEqual(len(r.jobs),1);self.assertEqual(f.calls,2)
 def test_foreign_rejected(self):
  x=dict(ROW,companyName='Other');self.assertEqual(fetch_massvirtual(SOURCE,'COMP-0344','Mass Virtual',Fake([x])).status,'partial')
 def test_wrong_scope(self): self.assertEqual(fetch_massvirtual(SOURCE,'COMP-0344','Other',Fake([ROW])).status,'unsupported')
if __name__=='__main__':unittest.main()
