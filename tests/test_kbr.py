import copy,json,unittest
from job_search_helper.kbr import fetch_kbr,SOURCE,FEED,WIDGET,HOST,SITE
from job_search_helper.ats import HTTPResponse
ROW={'id':'R123','requisition_status':'Open','application_url':'https://'+HOST+'/'+SITE+'/job/City/Engineer_R123'}
class Public:
 def __init__(self,row=None,changed=False):self.row=copy.deepcopy(ROW if row is None else row);self.calls=0;self.changed=changed
 def get(self,url):
  if url==WIDGET:d={'name':'KBR','jobs':[]}
  else:
   assert url==FEED;self.calls+=1;rs=[self.row] if not(self.changed and self.calls>1) else [];d={'source':'workday_raas','generated_at':'2026-10-08','total_jobs':len(rs),'jobs':rs}
  return HTTPResponse(200,json.dumps(d).encode())
class Workday:
 def __init__(self,req='R123',found=1):self.req=req;self.found=found
 def get(self,url):return HTTPResponse(200,json.dumps({'jobPostingInfo':{'id':'opaque','jobPostingSiteId':SITE,'posted':True,'title':'Updated title','jobDescription':'Full responsibilities','jobReqId':self.req}}).encode())
 def post(self,url,payload):
  assert payload['searchText']=='R123'
  return HTTPResponse(200,json.dumps({'total':self.found,'jobPostings':[{'externalPath':'/job/City/Engineer_R123'}] if self.found else []}).encode())
class KBRTests(unittest.TestCase):
 def test_linked_and_missing_link_records(self):
  for link in [ROW['application_url'],None]:
   row=dict(ROW,application_url=link);r=fetch_kbr(SOURCE,'c','KBR',Public(row),Workday());self.assertEqual(r.status,'complete',r.reason);self.assertEqual(r.jobs[0]['title'],'Updated title')
 def test_wrong_requisition_and_unavailable_lookup(self):
  r=fetch_kbr(SOURCE,'c','KBR',Public(),Workday(req='R456'));self.assertEqual(r.status,'partial');self.assertEqual(r.jobs,[])
  r=fetch_kbr(SOURCE,'c','KBR',Public(dict(ROW,application_url=None)),Workday(found=0));self.assertEqual(r.status,'partial')
 def test_changed_feed(self):self.assertEqual(fetch_kbr(SOURCE,'c','KBR',Public(changed=True),Workday()).status,'partial')
 def test_foreign_link(self):
  row=dict(ROW,application_url=ROW['application_url'].replace(HOST,'other.wd5.myworkdayjobs.com'));self.assertEqual(fetch_kbr(SOURCE,'c','KBR',Public(row),Workday()).status,'partial')
