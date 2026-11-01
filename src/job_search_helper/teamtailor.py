"""Teamtailor public counted job list and structured full job descriptions."""
import re
from urllib.parse import urlsplit,urljoin
from .ats import Inventory,FetchError,text
from .discovery import CareersTransport
from .shared_boards import checked,Links,Scripts,schema_job

def listing(t,url):
 body=checked(t.get(url),True)
 if 'teamtailor' not in body or not re.search(r'id=["\']jobs_list_container["\']',body):raise FetchError('partial','Teamtailor verified listing container missing.')
 totals=re.findall(r'<h2[^>]*>\s*(\d+)\s+(?:jobs?|offres?)\s*(?:<span[^>]*>\s*</span>)?\s*</h2>',body,re.S|re.I)
 if len(totals)!=1:raise FetchError('partial','Teamtailor listing total unavailable.')
 total=int(totals[0]);rows={};host=urlsplit(url).hostname
 for a,title in Links(body).links:
  u=urljoin(url,a.get('href',''));p=urlsplit(u);m=re.fullmatch('/jobs/([0-9]+)-[a-zA-Z0-9_-]+',p.path)
  if not m or p.scheme!='https' or p.hostname!=host or p.query or p.fragment:continue
  ident=m[1];title=text(title)
  if not title or (ident in rows and rows[ident]['title']!=title):raise FetchError('partial','Teamtailor title identity missing or conflicting.')
  rows[ident]={'id':ident,'url':u,'title':title}
 if total!=len(rows) or total>10000:raise FetchError('partial','Teamtailor listing is paginated or its total disagrees.')
 return rows

def fetch_teamtailor(url,cid,company,transport=None):
 jobs=[]
 try:
  p=urlsplit(url)
  allowed={'careers.mildef.com':{'','/jobs'},'leafspace.teamtailor.com':{'','/jobs','/en-GB','/en-GB/jobs'},'career.sbg-systems.com':{'','/jobs'}}
  if p.scheme!='https' or p.hostname not in allowed or p.username or p.password or p.port not in (None,443) or p.path.rstrip('/') not in allowed[p.hostname] or p.query or p.fragment:raise FetchError('unsupported','Teamtailor requires an unfiltered employer openings URL.')
  path=p.path.rstrip('/')
  if not path.endswith('/jobs'):
   path+='/jobs'
  url=p._replace(path=path).geturl()
  t=transport or CareersTransport();entries=listing(t,url)
  for ident,e in entries.items():
   body=checked(t.get(e['url']),True);records=Scripts(body).jobs()
   if len(records)!=1 or str((records[0].get('identifier') or {}).get('value'))!=ident or text(records[0].get('title'))!=e['title']:raise FetchError('partial','Teamtailor structured job identity mismatch.')
   jobs.append(schema_job(records[0],e['url'],ident,'Teamtailor',cid,company))
  if listing(t,url)!=entries:raise FetchError('partial','Teamtailor inventory changed during scan.')
  return Inventory('complete',jobs,f'Teamtailor: retrieved {len(jobs)} full postings and verified listing total twice.',url,'Teamtailor')
 except FetchError as e:return Inventory(e.status,jobs,str(e),url,'Teamtailor')
 except (ValueError,TypeError,KeyError,AttributeError):return Inventory('partial',jobs,'Teamtailor schema validation failed.',url,'Teamtailor')
