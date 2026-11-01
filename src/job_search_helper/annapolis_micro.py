"""Annapolis Micro Systems' bounded first-party static careers inventory."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit
from .ats import FetchError,Inventory,_base,text
from .discovery import CareersTransport
SOURCE='https://www.annapmicro.com/careers-at-annapolis-micro-systems/'
HOST='www.annapmicro.com'; PREFIX='/careers-at-annapolis-micro-systems/'
class _Page(HTMLParser):
 def __init__(self): super().__init__(convert_charrefs=True); self.links=[];self.parts=[];self.main=0;self.form=0;self.head=[];self._h=None
 def handle_starttag(self,t,attrs):
  a=dict(attrs);ident=a.get('id','')
  if t=='main' or ident in {'content','primary'}: self.main+=1
  if t=='form':self.form+=1
  if t=='a' and a.get('href'):self.links.append(a['href'])
  if self.main and not self.form and t in {'h1','h2'}:self._h=[]
 def handle_data(self,d):
  if self.main and not self.form:
   self.parts.append(d)
   if self._h is not None:self._h.append(d)
 def handle_endtag(self,t):
  if self._h is not None and t in {'h1','h2'}:
   h=text(' '.join(self._h));
   if h:self.head.append(h)
   self._h=None
  if t=='form' and self.form:self.form-=1
  if t=='main' and self.main:self.main-=1
def _read(c,u):
 r=c.get(u)
 if r.status in (401,403,429):raise FetchError('blocked',f'Annapolis Micro careers page blocked (HTTP {r.status}).')
 if r.status!=200:raise FetchError('partial',f'Annapolis Micro careers page HTTP {r.status}.')
 return r.body.decode('utf-8','replace')
def _listing(html):
 p=_Page();p.feed(html);out=[]
 for h in p.links:
  u=urljoin(SOURCE,h);q=urlsplit(u)
  if q.scheme=='https' and q.hostname==HOST and q.path.startswith(PREFIX) and q.path.rstrip('/') not in {PREFIX.rstrip('/'),PREFIX+'engineering-careers',PREFIX+'manufacturing-careers',PREFIX+'quality-careers',PREFIX+'procurement-careers',PREFIX+'information-technology-careers',PREFIX+'executive-careers',PREFIX+'co-op-program', PREFIX+'feed'} and not q.query and not q.fragment and u not in out:out.append(u)
 if len(out)!=23:raise FetchError('partial',f'Annapolis Micro role link set changed; found {len(out)} instead of 23.')
 return out
def fetch_annapolis_micro(url,company_id,company,transport=None):
 c=transport
 if c is None or c.__class__.__name__=='HTTPTransport':c=CareersTransport()
 jobs=[]
 try:
  urls=_listing(_read(c,SOURCE))
  for u in urls:
   p=_Page();p.feed(_read(c,u)); title=next((h for h in p.head if 'careers' not in h.casefold()),'');desc=text(' '.join(p.parts));slug=urlsplit(u).path.rstrip('/').split('/')[-1]
   if not title or len(desc)<500 or 'Annapolis Micro' not in desc:raise FetchError('partial','Annapolis Micro detail identity or full description failed.')
   jobs.append(_base({'id':slug},'Annapolis Micro careers',company_id,company)|{'posting_id':slug,'req_id':slug,'title':title,'description':desc,'url':u})
  if _listing(_read(c,SOURCE))!=urls:raise FetchError('partial','Annapolis Micro role link set changed during reread.')
  return Inventory('complete',jobs,f'Annapolis Micro: retrieved {len(jobs)} full postings and rechecked the role links.',SOURCE,'Annapolis Micro careers')
 except FetchError as e:return Inventory(e.status,jobs,e.reason,SOURCE,'Annapolis Micro careers')
 except (ValueError,TypeError,AttributeError):return Inventory('partial',jobs,'Annapolis Micro careers validation failed.',SOURCE,'Annapolis Micro careers')
