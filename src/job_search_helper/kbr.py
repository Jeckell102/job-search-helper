"""KBR's published Workday inventory plus its public Workable supplement."""
import json,re
from urllib.parse import urlsplit
from .ats import Inventory,FetchError,HTTPTransport,_json
from .discovery import CareersTransport
from .shared_boards import checked,fetch_shared
from .workday import _posting
SOURCE='https://jobs.kbr.com/'
FEED='https://jobs.kbr.com/data/kbr-jobs.json'
WIDGET='https://apply.workable.com/api/v1/widget/accounts/kbr'
HOST='kbr.wd5.myworkdayjobs.com'
SITE='KBR_Careers'

def feeds(public):
 d=json.loads(checked(public.get(FEED)));w=json.loads(checked(public.get(WIDGET)))
 rows=d['jobs']
 if d.get('source')!='workday_raas' or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',d.get('generated_at','')) or type(d.get('total_jobs')) is not int or len(rows)!=d['total_jobs'] or len(rows)>10000 or not isinstance(w.get('jobs'),list) or 'kbr' not in w.get('name','').casefold():raise FetchError('partial','KBR public feed scope or total unverified.')
 out={}
 for r in rows:
  ident=r['id']
  if not r.get('application_url'):
   if not re.fullmatch(r'R[0-9]+',ident) or ident in out or r.get('requisition_status')!='Open':raise FetchError('partial','KBR missing-link record identity unverified.')
   out[ident]=None;continue
  p=urlsplit(r['application_url'])
  if p.scheme!='https' or p.hostname!=HOST or p.username or p.password or p.port not in (None,443) or p.query or p.fragment or not p.path.startswith('/'+SITE+'/job/') or not re.fullmatch(r'R[0-9]+',ident) or ident in out or r.get('requisition_status')!='Open':raise FetchError('partial','KBR listed job identity or open state unverified.')
  out[ident]=p.path[len('/'+SITE):]
 return out,w['jobs']

def fetch_kbr(url,cid,company,public=None,transport=None):
 jobs=[]
 if url!=SOURCE:return Inventory('unsupported',reason='KBR requires its verified employer inventory.',source_url=url,ats='KBR')
 try:
  public=public or CareersTransport();transport=transport or HTTPTransport();entries,workable=feeds(public);failures=0
  for req,path in entries.items():
   try:
    if path is None:
     search=_json('https://'+HOST+'/wday/cxs/kbr/'+SITE+'/jobs',transport,{'appliedFacets':{},'limit':20,'offset':0,'searchText':req})
     found=search.get('jobPostings',[])
     if search.get('total')!=1 or len(found)!=1:raise ValueError('Exact requisition unavailable or ambiguous')
     path=found[0]['externalPath']
     from .workday import _job_path
     path=_job_path(path)
    d=_json('https://'+HOST+'/wday/cxs/kbr/'+SITE+path,transport)
    row=_posting(d,path,SITE,HOST,cid,company)
    if row['req_id']!=req:raise ValueError('KBR requisition mismatch')
    jobs.append(row)
   except FetchError as e:
    if e.status=='blocked':raise
    failures+=1
   except (ValueError,KeyError,TypeError):failures+=1
  if workable:
   result=fetch_shared('Workable','https://apply.workable.com/kbr/',cid,company)
   if result.status!='complete':raise FetchError('partial','KBR Workable supplement is incomplete.')
   expected={str(j.get('shortcode') or j.get('id')) for j in workable}
   if {str(j['posting_id']) for j in result.jobs}!=expected:raise FetchError('partial','KBR Workable listing identities disagree.')
   # Keep provider IDs distinct: similarly titled jobs can be separate vacancies.
   jobs.extend(result.jobs)
  check,supplement=feeds(public)
  if check!=entries or supplement!=workable:raise FetchError('partial','KBR source changed during scan.')
  return Inventory('partial' if failures else 'complete',jobs,f'KBR: verified {len(jobs)} full postings from published employer feeds; {failures} details unresolved.',url,'KBR')
 except FetchError as e:return Inventory(e.status,jobs,str(e),url,'KBR')
 except (KeyError,ValueError,TypeError,AttributeError):return Inventory('partial',jobs,'KBR public feed schema changed.',url,'KBR')
