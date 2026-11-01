"""ApplicantStack public openings table and structured full job descriptions."""
import re
from urllib.parse import urlsplit,urljoin
from .ats import Inventory,FetchError,text
from .discovery import CareersTransport
from .shared_boards import checked,Links,Scripts,schema_job

def listing(t,url):
 body=checked(t.get(url),True)
 if not re.search(r'id=["\']data-table["\']',body):raise FetchError('partial','ApplicantStack openings table missing.')
 totals=re.findall(r'Showing\s+(\d+)\s*-\s*(\d+)\s+of\s+(\d+)',text(body))
 if len(totals)!=1:raise FetchError('partial','ApplicantStack total unavailable; completeness unproven.')
 start,end,total=map(int,totals[0]);rows={};host=urlsplit(url).hostname
 for a,title in Links(body).links:
  u=urljoin(url,a.get('href',''));p=urlsplit(u);m=re.fullmatch('/x/detail/([a-z0-9]+)',p.path)
  if not m or p.scheme!='https' or p.hostname!=host or p.query or p.fragment:continue
  ident=m[1];title=text(title)
  if not title or (ident in rows and rows[ident]['title']!=title):raise FetchError('partial','ApplicantStack title identity missing or conflicting.')
  rows[ident]={'id':ident,'url':u,'title':title}
 if start!=1 or end!=total or total!=len(rows) or total>10000:raise FetchError('partial','ApplicantStack listing is paginated or its total disagrees.')
 return rows

def fetch_applicantstack(url,cid,company,transport=None):
 jobs=[]
 try:
  p=urlsplit(url)
  if p.scheme!='https' or not re.fullmatch('[a-z0-9-]+\\.applicantstack\\.com',p.hostname or '') or p.username or p.password or p.port not in (None,443) or p.path.rstrip('/')!='/x/openings' or p.query or p.fragment:raise FetchError('unsupported','ApplicantStack requires an unfiltered employer openings URL.')
  t=transport or CareersTransport();entries=listing(t,url)
  for ident,e in entries.items():
   body=checked(t.get(e['url']),True);records=Scripts(body).jobs()
   if len(records)!=1 or str((records[0].get('identifier') or {}).get('value'))!=ident or text(records[0].get('title'))!=e['title']:raise FetchError('partial','ApplicantStack structured job identity mismatch.')
   jobs.append(schema_job(records[0],e['url'],ident,'ApplicantStack',cid,company))
  if listing(t,url)!=entries:raise FetchError('partial','ApplicantStack inventory changed during scan.')
  return Inventory('complete',jobs,f'ApplicantStack: retrieved {len(jobs)} full postings and verified listing total twice.',url,'ApplicantStack')
 except FetchError as e:return Inventory(e.status,jobs,str(e),url,'ApplicantStack')
 except (ValueError,TypeError,KeyError,AttributeError):return Inventory('partial',jobs,'ApplicantStack schema validation failed.',url,'ApplicantStack')
