import pathlib, sys, unittest
from urllib.parse import urlsplit
ROOT=pathlib.Path(__file__).parents[1]; sys.path.insert(0,str(ROOT/'src'))
from job_search_helper.ats import HTTPResponse, _safe_api_url
from job_search_helper.radd import SITEMAP, fetch_radd
E=pathlib.Path('/home/chris/.codex/.chatgpt-projects/g-p-6ab70f626df48191a04039506182677f/work/full-integrations-20261029/radd/evidence')
class T:
 def __init__(self): self.calls=[]
 def get(self,u):
  self.calls.append(u); p=urlsplit(u)
  if p.path=='/sitemap.xml': b=(E/'sitemap.xml').read_bytes()
  else:
   slug=p.path.rsplit('/',1)[-1]
   name='ml-detail.html' if slug=='ml-engineer-01' else ('staff-robotics-engineer-01-retry.html' if slug=='staff-robotics-engineer-01' else slug+'.html')
   b=(E/name).read_bytes()
  return HTTPResponse(200,b,{})
class Tests(unittest.TestCase):
 def test_three_roles_and_reread(self):
  t=T(); r=fetch_radd('https://radd.tech/','COMP-0325','RADD',t)
  self.assertEqual(r.status,'complete'); self.assertEqual(len(r.jobs),2); self.assertEqual(len({x['posting_id'] for x in r.jobs}),2); self.assertEqual(t.calls.count(SITEMAP),2)
  self.assertTrue(all(len(x['description'])>500 for x in r.jobs))
 def test_scope(self): self.assertEqual(fetch_radd('https://radd-co.com/','COMP-0325','Other',T()).status,'unsupported')
 def test_safe(self):
  _safe_api_url(SITEMAP); _safe_api_url('https://radd-co.com/open-roles/ml-engineer-01')
  with self.assertRaises(Exception): _safe_api_url('https://radd-co.com/open-roles/../x')
