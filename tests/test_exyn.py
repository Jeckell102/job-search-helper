import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).parents[1];sys.path.insert(0,str(ROOT/'src'))
from job_search_helper.ats import HTTPResponse,_safe_api_url
from job_search_helper.exyn import SOURCE,fetch_exyn
E=pathlib.Path('/home/chris/.codex/.chatgpt-projects/g-p-6ab70f626df48191a04039506182677f/work/full-integrations-20261029/exyn/evidence/careers.html')
class T:
 def __init__(self):self.calls=0
 def get(self,url): self.calls+=1; return HTTPResponse(200,E.read_bytes(),{})
class Tests(unittest.TestCase):
 def test_two_embedded_roles_and_reread(self):
  t=T();r=fetch_exyn(SOURCE,'COMP-0328','Exyn Technologies',t);self.assertEqual(r.status,'complete');self.assertEqual(len(r.jobs),2);self.assertEqual(t.calls,2);self.assertTrue(all(len(j['description'])>500 for j in r.jobs))
 def test_scope(self): self.assertEqual(fetch_exyn(SOURCE,'COMP-0328','Other',T()).status,'unsupported')
 def test_safe(self): _safe_api_url(SOURCE)
