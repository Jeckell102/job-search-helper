"""WOLF Advanced Technology's first-party Scouterecruit inventory."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urlsplit
from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE='https://wolfadvancedtechnology.scouterecruit.net'
LISTING=SOURCE+'/'
HOST='wolfadvancedtechnology.scouterecruit.net'
class _Listing(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True); self.jobs=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag=='div' and 'jobblock' in a.get('class','').split() and a.get('data-url'): self.jobs.append({'url':a['data-url'],'id':a.get('data-reference',''),'title':a.get('data-title','')})
class _Detail(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True); self.parts=[]; self.title=''; self.ref=''; self.loc=''; self.in_desc=0; self.in_title=0; self.in_ref=0
 def handle_starttag(self,tag,attrs):
  a=dict(attrs); ident=a.get('id','')
  if ident=='description': self.in_desc+=1
  if a.get('class','')=='job-title': self.in_title=1
  if ident=='job_reference': self.in_ref=1
 def handle_data(self,d):
  if self.in_title:self.title+=d
  if self.in_ref:self.ref+=d
  if self.in_desc:self.parts.append(d)
 def handle_endtag(self,tag):
  if tag=='h1': self.in_title=0
  if tag=='div' and self.in_ref:self.in_ref=0
  if tag=='div' and self.in_desc:self.in_desc-=1

def _read(c,u):
 r=c.get(u)
 if r.status in (401,403,429): raise FetchError('blocked',f'WOLF Scouterecruit page blocked (HTTP {r.status}).')
 if r.status!=200: raise FetchError('partial',f'WOLF Scouterecruit page HTTP {r.status}.')
 return r.body.decode('utf-8','replace')
def _listing(html):
 p=_Listing();p.feed(html)
 if not p.jobs or len(p.jobs)>1000: raise FetchError('partial','WOLF listing missing or exceeds supported bound.')
 out=[]; ids=set()
 for j in p.jobs:
  q=urlsplit(j['url'])
  if q.scheme!='https' or q.hostname!=HOST or not q.path.startswith('/jobs/') or q.query or q.fragment or not j['id'] or j['id'] in ids: raise FetchError('partial','WOLF listing has invalid or duplicate posting identity.')
  ids.add(j['id']); out.append(j)
 return out

def fetch_wolf(url,company_id,company,transport=None):
 c=transport
 if c is None or c.__class__.__name__ == 'HTTPTransport': c=CareersTransport()
 jobs=[]
 try:
  entries=_listing(_read(c,LISTING))
  for e in entries:
   p=_Detail();p.feed(_read(c,e['url'])); title=text(p.title); ref=text(p.ref); desc=text(' '.join(p.parts))
   if title!=text(e['title']) or ref.find(e['id'])<0 or len(desc)<500 or 'WOLF' not in desc.upper(): raise FetchError('partial','WOLF detail identity or full description failed.')
   slug=urlsplit(e['url']).path.strip('/'); jobs.append(_base({'id':e['id']},'WOLF Scouterecruit',company_id,company)|{'posting_id':e['id'],'req_id':e['id'],'title':title,'description':desc,'url':e['url']})
  if [x['id'] for x in _listing(_read(c,LISTING))] != [x['id'] for x in entries]: raise FetchError('partial','WOLF listing changed during reread.')
  return Inventory('complete',jobs,f'WOLF Scouterecruit: retrieved {len(jobs)} full postings and rechecked the listing.','https://wolfadvancedtechnology.scouterecruit.net','WOLF Scouterecruit')
 except FetchError as e:return Inventory(e.status,jobs,e.reason,LISTING,'WOLF Scouterecruit')
 except (ValueError,TypeError,AttributeError):return Inventory('partial',jobs,'WOLF Scouterecruit validation failed.',LISTING,'WOLF Scouterecruit')
