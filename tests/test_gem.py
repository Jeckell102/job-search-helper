import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
from job_search_helper.gem import fetch_gem,LIST,DETAIL
from job_search_helper.ats import fetch_inventory,Inventory
from job_search_helper.browser_scraper import with_browser_fallback
D=json.loads((Path(__file__).parent/'fixtures/gem/detail.json').read_text())
class Fake:
 def __init__(self,detail=None,changed=False,duplicate=False):self.detail=copy.deepcopy(D if detail is None else detail);self.calls=0;self.changed=changed;self.duplicate=duplicate
 def query(self,q,v):
  if q==DETAIL:return {'oatsExternalJobPosting':self.detail}
  assert q==LIST;self.calls+=1
  rows=[{k:D[k] for k in ['id','extId','title']}]
  if self.duplicate:rows*=2
  if self.changed and self.calls>1:rows=[]
  return {'jobBoardExternal':{'id':'board','teamDisplayName':'Firestorm'},'oatsExternalJobPostings':{'jobPostings':rows}}
class GemTests(unittest.TestCase):
 def test_complete_and_routing(self):
  r=fetch_inventory('Gem','https://jobs.gem.com/firestorm','c','Firestorm Labs',Fake());self.assertEqual(r.status,'complete',r.reason);self.assertEqual(len(r.jobs),1);self.assertGreater(len(r.jobs[0]['description']),1000)
 def test_changed_inventory(self):self.assertEqual(fetch_gem('https://jobs.gem.com/firestorm','c','Firestorm',Fake(changed=True)).status,'partial')
 def test_duplicates(self):self.assertEqual(fetch_gem('https://jobs.gem.com/firestorm','c','Firestorm',Fake(duplicate=True)).status,'partial')
 def test_invalid_detail(self):
  for field,value in [('extId','wrong'),('descriptionHtml',''),('isUnlistedExternally',True)]:
   d=copy.deepcopy(D);d[field]=value;r=fetch_gem('https://jobs.gem.com/firestorm','c','Firestorm',Fake(d));self.assertEqual(r.status,'partial');self.assertEqual(r.jobs,[])
 def test_scope(self):
  for url in ['https://jobs.gem.com/firestorm/onejob','https://jobs.gem.com/firestorm?department=x','https://jobs.gem.com.evil.example/firestorm']:
   self.assertEqual(fetch_gem(url,'c','Firestorm',Fake()).status,'unsupported')
 def test_no_generic_fallback(self):
  with patch('job_search_helper.browser_scraper.fetch_browser_inventory') as f:
   r=with_browser_fallback(lambda *args:Inventory('partial',ats='Gem'))('Gem','https://jobs.gem.com/firestorm','c','Firestorm');f.assert_not_called();self.assertEqual(r.status,'partial')
