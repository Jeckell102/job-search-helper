"""Mobilicom's first-party WordPress careers RSS feed."""
from __future__ import annotations
import hashlib
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit
from .ats import FetchError, Inventory, HTTPTransport, _base, text
from .discovery import CareersTransport

SOURCE='https://mobilicom.com/careers/'
FEED='https://mobilicom.com/careers/feed/'
NS={'content':'http://purl.org/rss/1.0/modules/content/'}

def _read(t,url):
 r=t.get(url)
 if r.status!=200: raise FetchError('blocked' if r.status in (401,403,429) else 'partial','Mobilicom public careers source unavailable.')
 return r.body.decode('utf-8','replace')

def _parse(feed):
 try: root=ET.fromstring(feed)
 except ET.ParseError: raise FetchError('partial','Mobilicom careers RSS was malformed.') from None
 items=root.findall('./channel/item')
 if not items or len(items)>100: raise FetchError('partial','Mobilicom careers RSS inventory is empty or unbounded.')
 out=[]; seen=set()
 for item in items:
  title=text(item.findtext('title') or '')
  link=text(item.findtext('link') or '')
  desc=item.findtext('content:encoded',default='',namespaces=NS) or ''
  p=urlsplit(link)
  if p.scheme!='https' or p.hostname!='mobilicom.com' or not p.path.startswith('/careers/') or p.query or p.fragment or p.path.rstrip('/')=='/careers':
   raise FetchError('partial','Mobilicom RSS item escaped the verified careers scope.')
  if not title or len(text(desc))<200: raise FetchError('partial','Mobilicom RSS item lacks a full description.')
  ident=hashlib.sha256(link.encode()).hexdigest()[:24]
  if ident in seen: raise FetchError('partial','Mobilicom RSS has duplicate posting URLs.')
  seen.add(ident); out.append((ident,title,link,desc))
 return out

def fetch_mobilicom(careers_url, company_id, company, transport=None):
 if careers_url!=SOURCE: return Inventory('unsupported',reason='Mobilicom adapter requires its verified careers page.',source_url=careers_url,ats='Mobilicom careers')
 t=transport or CareersTransport(); jobs=[]
 try:
  first=_parse(_read(t,FEED))
  for ident,title,link,desc in first:
   detail=_read(t,link)
   if title.casefold() not in detail.casefold() or len(text(detail))<500: raise FetchError('partial','Mobilicom detail page lacks stable title or full content.')
   row=_base({'id':ident},'Mobilicom careers',company_id,company); row.update(title=title,description=text(desc),url=link)
   jobs.append(row)
  second=_parse(_read(t,FEED))
  if [(x[0],x[2]) for x in second] != [(x[0],x[2]) for x in first]: raise FetchError('partial','Mobilicom RSS membership changed during scan.')
  return Inventory('complete',jobs,f'Mobilicom: retrieved {len(jobs)} complete postings and rechecked the public RSS inventory.',careers_url,'Mobilicom careers')
 except FetchError as e: return Inventory(e.status,jobs,e.reason,careers_url,'Mobilicom careers')
 except (AttributeError,TypeError,ValueError,UnicodeError): return Inventory('partial',jobs,'Mobilicom careers schema validation failed.',careers_url,'Mobilicom careers')
