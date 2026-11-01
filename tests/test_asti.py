import unittest
from job_search_helper.asti import fetch_asti,SOURCE
from job_search_helper.ats import HTTPResponse
class Fake:
 def __init__(self,body): self.body=body.encode(); self.calls=0
 def get(self,url): self.calls+=1; return HTTPResponse(200,self.body,{'content-type':'text/html'})
BODY='''<div class="accordion-group"><a><h3>Project Engineer</h3></a><div><p>ASTi Project Engineer</p><p>'''+'x '*300+'''</p></div></div><div class="accordion-group"><a><h3>Software Engineer</h3></a><div><p>ASTi Software Engineer</p><p>'''+'x '*300+'''</p></div></div>'''
class Tests(unittest.TestCase):
 def test_roles_and_reread(self):
  f=Fake(BODY); r=fetch_asti(SOURCE,'COMP-0336','Advanced Simulation Technology inc. (ASTi)',f); self.assertEqual(r.status,'complete'); self.assertEqual(len(r.jobs),2); self.assertEqual(f.calls,2)
 def test_missing_role_partial(self):
  r=fetch_asti(SOURCE,'COMP-0336','Advanced Simulation Technology inc. (ASTi)',Fake(BODY.split('<div class="accordion-group">',2)[0])); self.assertEqual(r.status,'partial')
 def test_wrong_scope_rejected(self):
  self.assertEqual(fetch_asti(SOURCE,'COMP-0336','ASTi',Fake(BODY)).status,'unsupported')
if __name__=='__main__': unittest.main()
