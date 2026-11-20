"""HX5's company-scoped Oracle Taleo TBE v2 board."""
from __future__ import annotations
import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit, parse_qs
from .ats import FetchError, HTTPTransport, Inventory, text
from .discovery import CareersTransport
from .shared_boards import Scripts, schema_job
SOURCE='https://phe.tbe.taleo.net/phe01/ats/careers/v2/jobSearch?cws=37&org=ACDY28'
HOST='phe.tbe.taleo.net'; PREFIX='/phe01/ats/careers/v2'; ORG='ACDY28'; CWS='37'
class _Page(HTMLParser):
 def __init__(self):
  super().__init__(convert_charrefs=True); self.links=[]; self.parts=[]; self.title=[]; self.meta_title=''; self._h=0; self._skip=0
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if tag in {'script','style'}: self._skip+=1
  if not self._skip and tag=='a' and a.get('href'): self.links.append((a['href'],text(' '.join(self._pending)))) if False else self.links.append((a['href'],''))
  if not self._skip and tag in {'h1','h2','h3'}: self._h+=1
  if not self._skip and tag in {'p','li','div','br','h1','h2','h3','td'}: self.parts.append('\n')
 def handle_endtag(self,tag):
  if tag in {'script','style'} and self._skip: self._skip-=1
  if tag in {'h1','h2','h3'} and self._h: self._h-=1
  if tag in {'p','li','div','td'}: self.parts.append('\n')
 def handle_data(self,data):
  if not self._skip:
   self.parts.append(data)
   if self._h: self.title.append(data)
def _read(client,url):
 r=client.get(url)
 if r.status in (401,403,429): raise FetchError('blocked','HX5 public Taleo board was blocked.')
 if r.status!=200: raise FetchError('partial',f'HX5 public Taleo board HTTP {r.status}.')
 return r.body.decode('utf-8','replace')
def _url(path,**q): return 'https://'+HOST+PREFIX+path+'?'+urlencode({'org':ORG,'cws':CWS,**q})
def _search(html):
 p=_Page(); p.feed(html); out=[]
 for href,_ in p.links:
  u='https://'+HOST+href if href.startswith('/') else href; z=urlsplit(u); qs=parse_qs(z.query)
  if z.scheme=='https' and z.hostname==HOST and z.path==PREFIX+'/viewRequisition' and set(qs)=={'org','cws','rid'} and qs['org']==[ORG] and qs['cws']==[CWS] and qs['rid'][0].isdigit() and u not in out: out.append(u)
 return out

def parse_posting(html, url, company_id, company):
 """Use the actual JobPosting fields, never Taleo's generic page heading."""
 parsed=urlsplit(url); query=parse_qs(parsed.query)
 if (parsed.scheme!='https' or parsed.hostname!=HOST or parsed.path!=PREFIX+'/viewRequisition'
     or set(query)!={'org','cws','rid'} or query['org']!=[ORG] or query['cws']!=[CWS]
     or len(query['rid'])!=1 or not query['rid'][0].isdigit()):
  raise FetchError('partial','HX5 detail URL is outside the verified employer scope.')
 rid=query['rid'][0]
 try:
  records=Scripts(html).jobs()
 except (ValueError,TypeError):
  raise FetchError('partial','HX5 structured job data is malformed.')
 if len(records)!=1:
  raise FetchError('partial','HX5 structured JobPosting is missing or ambiguous.')
 data=records[0]; employer=data.get('hiringOrganization') or {}; identifier=data.get('identifier') or {}
 if (not isinstance(employer,dict) or text(employer.get('name')).casefold().replace('.','') not in {'hx5','hx5 llc','hx5, llc'}
     or not isinstance(identifier,dict) or str(identifier.get('value',''))!=rid):
  raise FetchError('partial','HX5 structured employer or requisition identity does not match.')
 actual=urlsplit(str(data.get('url') or ''))
 if (actual.scheme,actual.hostname,actual.path,parse_qs(actual.query)) != (parsed.scheme,parsed.hostname,parsed.path,query):
  raise FetchError('partial','HX5 structured URL does not match the requested requisition.')
 title=text(data.get('title'))
 if not title or re.match(r'^position description\b',title,re.I):
  raise FetchError('partial','HX5 structured job title is missing or generic.')
 try:
  posting=schema_job(data,url,rid,'Taleo TBE v2',company_id,company)
 except (AttributeError,TypeError,ValueError):
  raise FetchError('partial','HX5 structured posting fields are malformed.')
 if len(posting['description'])<300 or 'HX5' not in posting['description'] or not posting['location']:
  raise FetchError('partial','HX5 detail lacks full description or location.')
 posting['location']=re.sub(r'\bUS-[A-Z]{2}-','',posting['location'])
 return posting

def fetch_hx5(careers_url,company_id,company,transport=None):
 client=CareersTransport() if transport is None or isinstance(transport,HTTPTransport) else transport; jobs=[]
 try:
  total=None; first=[]; row=0
  while row<500:
   html=_read(client,_url('/searchResults',act='search',rowFrom=row,sortColumn='null',sortOrder='null'))
   p=_Page(); p.feed(html); body=text(' '.join(p.parts));
   if 'Positions Matched' not in body: raise FetchError('partial','HX5 search results marker missing.')
   import re
   m=re.search(r'Positions Matched\s+(\d+)',body,re.I)
   if not m: raise FetchError('partial','HX5 published total missing.')
   n=int(m.group(1)); total=n if total is None else total
   if n!=total: raise FetchError('partial','HX5 published total changed during pagination.')
   links=_search(html)
   if not links:
    if row>=n: break
    raise FetchError('partial','HX5 search page has no requisitions.')
   if row==0:first=list(links)
   if len(links)>10 or row+len(links)>n: raise FetchError('partial','HX5 page length is inconsistent with published total.')
   for url in links:
    rid=parse_qs(urlsplit(url).query)['rid'][0]
    if any(j['posting_id']==rid for j in jobs): raise FetchError('partial','HX5 duplicate requisition ID.')
    jobs.append(parse_posting(_read(client,url),url,company_id,company))
   row+=len(links)
   if row>=total: break
  if total is None or len(jobs)!=total: raise FetchError('partial','HX5 inventory did not match published total.')
  if _search(_read(client,_url('/searchResults',act='search',rowFrom=0,sortColumn='null',sortOrder='null'))) != first: raise FetchError('partial','HX5 inventory changed during final reread.')
  return Inventory('complete',jobs,f'HX5: retrieved {len(jobs)} complete postings and rechecked the public inventory.',SOURCE,'Taleo TBE v2')
 except FetchError as e: return Inventory(e.status,jobs,e.reason,SOURCE,'Taleo TBE v2')
 except (ValueError,TypeError,AttributeError): return Inventory('partial',jobs,'HX5 Taleo schema validation failed.',SOURCE,'Taleo TBE v2')
