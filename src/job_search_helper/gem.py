"""Read-only Gem public job board queries observed on the employer careers UI."""
import json,re,time
from datetime import datetime,timezone
from urllib.parse import urlsplit
from urllib.request import Request,build_opener
from urllib.error import HTTPError,URLError
from .ats import Inventory,FetchError,_NoRedirect,_base,text
ENDPOINT='https://jobs.gem.com/api/public/graphql/batch'
LIST='query JobBoardList($boardId: String!) { oatsExternalJobPostings(boardId: $boardId) { jobPostings { id extId title } } jobBoardExternal(vanityUrlPath: $boardId) { id teamDisplayName } }'
DETAIL='query ExternalJobPosting($boardId: String!, $extId: String!) { oatsExternalJobPosting(boardId: $boardId, extId: $extId) { id extId title descriptionHtml firstPublishedTsSec isUnlistedExternally locations { name } job { teamDisplayName locationType requisitionId department { name } } jobPostSectionHtml { introHtml outroHtml } compensationHtml } }'
class PublicTransport:
 def __init__(self):self.opener=build_opener(_NoRedirect());self.last=0
 def query(self,query,variables):
  if query not in (LIST,DETAIL):raise FetchError('unsupported','Only public listing and job detail queries are permitted.')
  body=json.dumps([{'query':query,'variables':variables}]).encode()
  for attempt in range(3):
   time.sleep(max(0,.4-(time.monotonic()-self.last)));self.last=time.monotonic()
   try:
    req=Request(ENDPOINT,data=body,headers={'Content-Type':'application/json','Accept':'application/json','User-Agent':'JobSearchHelper/1.0'},method='POST')
    with self.opener.open(req,timeout=25) as r:
     raw=r.read(16*1024*1024+1)
     if len(raw)>16*1024*1024:raise FetchError('partial','Gem response exceeds bounded size.')
     data=json.loads(raw)
    if not isinstance(data,list) or len(data)!=1 or data[0].get('errors') or not isinstance(data[0].get('data'),dict):raise FetchError('partial','Gem public query failed or changed shape.')
    return data[0]['data']
   except HTTPError as e:
    if e.code in (429,500,502,503,504) and attempt<2:time.sleep(2**attempt);continue
    raise FetchError('blocked' if e.code in (401,403,429) else 'failed','Gem public HTTP '+str(e.code)) from None
   except (URLError,TimeoutError):
    if attempt<2:time.sleep(2**attempt);continue
    raise FetchError('failed','Gem public request failed after retries.') from None

def listing(t,slug):
 d=t.query(LIST,{'boardId':slug});board=d['jobBoardExternal'];rows=d['oatsExternalJobPostings']['jobPostings']
 if not board or not board.get('id') or not board.get('teamDisplayName') or not isinstance(rows,list) or len(rows)>10000:raise FetchError('partial','Gem board identity or complete listing missing.')
 ids=set()
 for r in rows:
  if not isinstance(r,dict) or not r.get('id') or not text(r.get('title')) or not re.fullmatch('[A-Za-z0-9_-]+',r.get('extId','')) or r['extId'] in ids:raise FetchError('partial','Gem listing identities missing or duplicated.')
  ids.add(r['extId'])
 return board,rows

def fetch_gem(url,cid,company,transport=None):
 jobs=[]
 try:
  p=urlsplit(url)
  if p.scheme!='https' or p.hostname!='jobs.gem.com' or p.username or p.password or p.port not in (None,443) or p.query or p.fragment or not re.fullmatch('/[A-Za-z0-9_-]+/?',p.path):raise FetchError('unsupported','Gem requires an unfiltered public employer board URL.')
  slug=p.path.strip('/');t=transport or PublicTransport();board,entries=listing(t,slug)
  failures=0
  for e in entries:
   d=t.query(DETAIL,{'boardId':slug,'extId':e['extId']})['oatsExternalJobPosting']
   if not d or d.get('id')!=e['id'] or d.get('extId')!=e['extId'] or text(d.get('title'))!=text(e['title']) or d.get('isUnlistedExternally') is not False or d['job']['teamDisplayName']!=board['teamDisplayName']:raise FetchError('partial','Gem job identity, employer or listing state changed.')
   description=text(d.get('descriptionHtml'))
   if not description:failures+=1;continue
   section=d.get('jobPostSectionHtml') or {};row=_base({'id':e['extId']},'Gem',cid,company)
   row.update(title=text(d['title']),url='https://jobs.gem.com/'+slug+'/'+e['extId'],description='\n\n'.join(filter(None,[text(section.get('introHtml')),description,text(section.get('outroHtml'))])),location='; '.join(text(v.get('name')) for v in d.get('locations') or []),department=text((d['job'].get('department') or {}).get('name')),req_id=text(d['job'].get('requisitionId')),work_arrangement=text(d['job'].get('locationType')),compensation=text(d.get('compensationHtml')),created_at=datetime.fromtimestamp(d['firstPublishedTsSec'],timezone.utc).isoformat() if d.get('firstPublishedTsSec') else '')
   jobs.append(row)
  after,check=listing(t,slug)
  if after!=board or {e['extId']:e for e in check}!={e['extId']:e for e in entries}:raise FetchError('partial','Gem inventory changed during scan.')
  return Inventory('partial' if failures else 'complete',jobs,f'Gem: verified {len(jobs)} full postings; rechecked all {len(entries)} listing identities. {failures} empty descriptions.',url,'Gem')
 except FetchError as e:return Inventory(e.status,jobs,e.reason if hasattr(e,'reason') else str(e),url,'Gem')
 except (KeyError,ValueError,TypeError,AttributeError,OverflowError):return Inventory('partial',jobs,'Gem public response schema or field identity changed.',url,'Gem')
