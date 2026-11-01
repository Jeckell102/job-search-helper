import json,unittest
from job_search_helper.acquiretm import SOURCE,inventory,posting,fetch_acquiretm
from job_search_helper.ats import FetchError

def html(ident,total=2):
 return f'<div>{total} positions found.</div><a href="job_details_clean.aspx?ID={ident}">Engineer {ident}</a><a aria-label="Go to page {2 if ident==1 else 1} of job results">page</a>'
class Page:
 def __init__(self,repeat=False,total=2):self.number=1;self.repeat=repeat;self.total=total;self.url=SOURCE
 def goto(self,*a,**k):self.number=1
 def content(self):return html(1 if self.repeat else self.number,self.total)
 def wait_for_load_state(self,*a,**k):pass
 def get_by_role(self,*args,**kwargs):
  owner=self
  class Link:
   def click(self):owner.number=int(kwargs['name'].split()[3])
  return Link()
class AcquireTests(unittest.TestCase):
 def test_complete_two_pages(self):self.assertEqual(set(inventory(Page())),{'1','2'})
 def test_missing_and_repeated_pages(self):
  for p in [Page(repeat=True),Page(total=3)]:
   with self.assertRaises(FetchError):inventory(p)
 def test_schema_identity(self):
  e={'id':'1','title':'Engineer','url':SOURCE.replace('home.aspx','job_details_clean.aspx?ID=1')};j={'@type':'JobPosting','title':'Engineer','identifier':{'value':'1'},'url':e['url'],'description':'Full engineering responsibilities.'}
  def body():return '<script type="application/ld+json">'+json.dumps(j)+'</script>'
  self.assertEqual(posting(body(),e,'c','Amphenol')['posting_id'],'1')
  for k,v in [('title','Wrong'),('description',''),('url','https://other.example/job')]:
   old=j[k];j[k]=v
   with self.assertRaises(FetchError):posting(body(),e,'c','Amphenol')
   j[k]=old
 def test_scope(self):self.assertEqual(fetch_acquiretm(SOURCE+'?filter=1','c','Amphenol').status,'unsupported')

 def test_current_detail_json_ld_preserves_html_body(self):
  body = '<script type="application/ld+json">' + json.dumps({
   '@type': 'JobPosting', 'title': 'Engineer 2265',
   'identifier': {'value': '2265'},
   'url': SOURCE.replace('home.aspx', 'job_details_clean.aspx?ID=2265'),
   'description': '<p>Responsibilities and qualifications.</p>',
  }) + '</script>'
  e = {'id': '2265', 'title': 'Engineer 2265', 'url': SOURCE.replace('home.aspx', 'job_details_clean.aspx?ID=2265')}
  result = posting(body, e, 'COMP-0490', 'Amphenol Aerospace')
  self.assertIn('Responsibilities and qualifications.', result['description'])
