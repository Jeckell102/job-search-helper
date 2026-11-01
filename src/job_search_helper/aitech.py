"""Aitech Systems' first-party Comeet-rendered careers pages."""
from __future__ import annotations
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .ats import FetchError, HTTPTransport, Inventory, _base, text
from .discovery import CareersTransport
SOURCE='https://aitechsystems.com/careers/'
HOST='aitechsystems.com'
class _Page(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True); self.links=[]; self.parts={}; self.active=[]
 def handle_starttag(self,tag,attrs):
  a=dict(attrs); cls=set(a.get('class','').split())
  if tag=='a' and a.get('href'): self.links.append(a['href'])
  keys=[]
  for marker,key in [('comeet-position-name','title'),('comeet-position-location','location'),('comeet-position-employmenttype','employment'),('comeet-position-experiencelevel','experience'),('comeet-user-text','description')]:
   if marker in cls: keys.append(key)
  if keys: self.active.append((tag,tuple(keys))); self.parts.setdefault(tuple(keys),[])
 def handle_data(self,data):
  for _,keys in self.active: self.parts[keys].append(data)
 def handle_endtag(self,tag):
  if self.active and self.active[-1][0]==tag: self.active.pop()
 def value(self,key):
  for keys,parts in self.parts.items():
   if key in keys:
    value=text(' '.join(parts))
    if value:return value
  return ''
def _role_url(url):
 p=urlsplit(url); bits=[x for x in p.path.split('/') if x]
 return (p.scheme=='https' and p.hostname==HOST and not p.query and not p.fragment and len(bits)==6 and bits[:2]==['careers-3','co'] and bits[-1]=='all' and '.' in bits[3])
def _links(html):
 p=_Page(); p.feed(html); out=[]
 for href in p.links:
  u=urljoin(SOURCE,href)
  if _role_url(u):
   u=u.rstrip('/')+'/'
   if u not in out: out.append(u)
 return out
def _read(client,url):
 r=client.get(url)
 if r.status in (401,403,429): raise FetchError('blocked','Aitech public careers page was blocked.')
 if r.status!=200: raise FetchError('partial',f'Aitech public careers page HTTP {r.status}.')
 return r.body.decode('utf-8','replace')
def fetch_aitech(careers_url,company_id,company,transport=None):
 client=CareersTransport() if transport is None or isinstance(transport, HTTPTransport) else transport; jobs=[]
 try:
  first=_links(_read(client,SOURCE))
  if len(first)!=17: raise FetchError('partial',f'Aitech role inventory changed; found {len(first)} role links.')
  seen=set()
  for url in first:
   p=_Page(); p.feed(_read(client,url)); ident=urlsplit(url).path.split('/')[4]; title=p.value('title'); desc=p.value('description')
   if not title or len(desc)<500: raise FetchError('partial','Aitech role lacks a complete employer-scoped description.')
   if ident in seen: raise FetchError('partial','Aitech role inventory has duplicate IDs.')
   seen.add(ident); row=_base({'id':ident},'Aitech Comeet',company_id,company)
   row.update(title=title,description=desc,url=url,location=p.value('location'),work_arrangement=p.value('employment'),department=p.value('experience')); jobs.append(row)
  if _links(_read(client,SOURCE))!=first: raise FetchError('partial','Aitech role inventory changed during the scan.')
  return Inventory('complete',jobs,f'Aitech: retrieved {len(jobs)} complete postings and rechecked the public role inventory.',SOURCE,'Aitech Comeet')
 except FetchError as e: return Inventory(e.status,jobs,e.reason,SOURCE,'Aitech Comeet')
 except (AttributeError,TypeError,ValueError,IndexError): return Inventory('partial',jobs,'Aitech careers schema validation failed.',SOURCE,'Aitech Comeet')
