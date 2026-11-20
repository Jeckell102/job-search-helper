"""KBR's published Workday inventory plus its optional Workable supplement."""
import json, os, re, time
from pathlib import Path
from urllib.parse import urlsplit
from .ats import Inventory,FetchError,HTTPTransport,_json
from .discovery import CareersTransport
from .shared_boards import checked,fetch_shared
from .workday import _job_path, _posting
from .detail_checkpoint import checkpoint_payload, reusable_details
SOURCE='https://jobs.kbr.com/'
FEED='https://jobs.kbr.com/data/kbr-jobs.json'
WIDGET='https://apply.workable.com/api/v1/widget/accounts/kbr'
HOST='kbr.wd5.myworkdayjobs.com'
SITE='KBR_Careers'
DETAIL_RETRIES=3
LISTING_PAGE_SIZE=20
MAX_LISTING_PAGES=100
DEFAULT_CHECKPOINT=Path('work/full-integrations-20261029/kbr/evidence/kbr-progress.json')

def _checkpoint_path(path=None):
 value=path or os.environ.get('KBR_CHECKPOINT')
 return Path(value) if value else DEFAULT_CHECKPOINT

def _write_checkpoint(path, *, phase, feed_ids, completed, missing, extras=None, feed_total=None, workday_total=None, error='', jobs=None, entries=None):
 if path is None:return
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 payload=checkpoint_payload({'company':'KBR','source':SOURCE,'phase':phase,'feed_total':feed_total,'workday_total':workday_total,'feed_ids':sorted(feed_ids),'completed_ids':sorted(completed),'missing_ids':sorted(missing),'extra_workday_ids':sorted(extras or set()),'jobs':jobs or [],'entries':entries or [],'error':error})
 temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n',encoding='utf-8');temp.replace(path)

def _read_checkpoint(path):
 if not path or not Path(path).is_file():return {}
 try:
  value=json.loads(Path(path).read_text(encoding='utf-8'));return value if isinstance(value,dict) else {}
 except (OSError,ValueError,TypeError):return {}

def _detail_json(url,transport,retries=DETAIL_RETRIES):
 last=None
 for attempt in range(retries):
  try:return _json(url,transport)
  except FetchError as exc:
   last=exc
   if not (exc.reason.startswith('HTTP 403') or exc.reason.startswith('HTTP 429')) or attempt+1>=retries:raise
   getattr(transport,'sleep',time.sleep)(min(8.0,0.5*(2**attempt)))
 raise last or FetchError('blocked','KBR detail access was denied.')

def feeds(public):
 d=json.loads(checked(public.get(FEED)))
 # KBR's current public site no longer exposes the historical Workable
 # supplement.  Treat an explicit 404 as an absent optional supplement; any
 # other response is still an inventory failure and must not be swallowed.
 widget=public.get(WIDGET)
 w={'jobs':[]}
 if widget.status != 404:
  w=json.loads(checked(widget))
 rows=d['jobs']
 if d.get('source')!='workday_raas' or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',d.get('generated_at','')) or type(d.get('total_jobs')) is not int or len(rows)!=d['total_jobs'] or len(rows)>10000 or not isinstance(w.get('jobs'),list) or (w.get('name') and 'kbr' not in w.get('name','').casefold()):raise FetchError('partial','KBR public feed scope or total unverified.')
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

def _workday_listing(transport,search_text='',offset=0):
 endpoint='https://'+HOST+'/wday/cxs/kbr/'+SITE+'/jobs'
 return _json(endpoint,transport,{'appliedFacets':{},'limit':LISTING_PAGE_SIZE,'offset':offset,'searchText':search_text})

def _resolve_missing(req,transport):
 data=_workday_listing(transport,req);found=data.get('jobPostings',[])
 if data.get('total')!=1 or len(found)!=1:raise ValueError('Exact requisition unavailable or ambiguous')
 return _job_path(found[0].get('externalPath'))

def _reconcile_extra_inventory(transport,feed_ids):
 first=_workday_listing(transport);total=first.get('total')
 if type(total) is not int or total<0 or not isinstance(first.get('jobPostings'),list):raise FetchError('partial','KBR Workday listing shell is invalid.')
 all_ids=set();offset=0
 while offset<total and offset<LISTING_PAGE_SIZE*MAX_LISTING_PAGES:
  page=first if offset==0 else _workday_listing(transport,offset=offset);postings=page.get('jobPostings')
  if not isinstance(postings,list) or not postings:raise FetchError('partial','KBR Workday listing ended before its advertised total.')
  for item in postings:
   path=_job_path(item.get('externalPath'));m=re.search(r'(?:^|_)(R[0-9]+)$',path)
   if m:all_ids.add(m.group(1))
  offset+=len(postings)
 if offset<total:raise FetchError('partial','KBR Workday listing exceeded its page cap.')
 return total,all_ids-set(feed_ids)

def fetch_kbr(url,cid,company,public=None,transport=None,checkpoint_path=None):
 jobs=[]
 if url!=SOURCE:return Inventory('unsupported',reason='KBR requires its verified employer inventory.',source_url=url,ats='KBR')
 try:
  public=public or CareersTransport();transport=transport or HTTPTransport();entries,workable=feeds(public);checkpoint_path=_checkpoint_path(checkpoint_path);feed_ids=set(entries);saved=_read_checkpoint(checkpoint_path)
  checkpoint_entries=[{'req_id':req,'path':path} for req,path in entries.items()]
  cached=reusable_details(saved,checkpoint_entries,entry_id=lambda entry:entry['req_id'],job_id=lambda job:job['req_id'])
  completed=set(cached);missing=feed_ids-completed;jobs=list(cached.values())
  _write_checkpoint(checkpoint_path,phase='details',feed_ids=feed_ids,completed=completed,missing=missing,feed_total=len(entries),jobs=jobs,entries=checkpoint_entries)
  failures=[]
  for req,path in entries.items():
   if req in completed:continue
   try:
    if path is None:path=_resolve_missing(req,transport)
    d=_detail_json('https://'+HOST+'/wday/cxs/kbr/'+SITE+path,transport)
    row=_posting(d,path,SITE,HOST,cid,company)
    if row['req_id']!=req:raise ValueError('KBR requisition mismatch')
    jobs.append(row);completed.add(req);missing.discard(req)
   except FetchError as e:
    if e.status=='blocked':
     _write_checkpoint(checkpoint_path,phase='blocked',feed_ids=feed_ids,completed=completed,missing=missing,feed_total=len(entries),error=e.reason,jobs=jobs,entries=checkpoint_entries)
     return Inventory('blocked',jobs,e.reason,url,'KBR')
    failures.append(req)
   except (ValueError,KeyError,TypeError):failures.append(req)
   _write_checkpoint(checkpoint_path,phase='details',feed_ids=feed_ids,completed=completed,missing=missing,feed_total=len(entries),error='unresolved: '+','.join(sorted(failures)) if failures else '',jobs=jobs,entries=checkpoint_entries)
  extra_total,extras=_reconcile_extra_inventory(transport,feed_ids)
  if extras:
   _write_checkpoint(checkpoint_path,phase='partial',feed_ids=feed_ids,completed=completed,missing=feed_ids-completed,extras=extras,feed_total=len(entries),workday_total=extra_total,error='extra Workday inventory requires reconciliation',jobs=jobs,entries=checkpoint_entries)
   return Inventory('partial',jobs,f'KBR: {len(extras)} extra Workday postings require reconciliation; feed bodies are not sufficient for completion.',url,'KBR')
  if workable:
   result=fetch_shared('Workable','https://apply.workable.com/kbr/',cid,company)
   if result.status!='complete':raise FetchError('partial','KBR Workable supplement is incomplete.')
   expected={str(j.get('shortcode') or j.get('id')) for j in workable}
   if {str(j['posting_id']) for j in result.jobs}!=expected:raise FetchError('partial','KBR Workable listing identities disagree.')
   # Keep provider IDs distinct: similarly titled jobs can be separate vacancies.
   jobs.extend(result.jobs)
  check,supplement=feeds(public)
  if check!=entries or supplement!=workable:raise FetchError('partial','KBR source changed during scan.')
  if failures:
   _write_checkpoint(checkpoint_path,phase='partial',feed_ids=feed_ids,completed=completed,missing=feed_ids-completed,extras=extras,feed_total=len(entries),workday_total=extra_total,error='unresolved: '+','.join(sorted(failures)),jobs=jobs,entries=checkpoint_entries)
   return Inventory('partial',jobs,f'KBR: {len(failures)} details unresolved; Workday extra inventory {len(extras)} recorded.',url,'KBR')
  _write_checkpoint(checkpoint_path,phase='complete',feed_ids=feed_ids,completed=completed,missing=set(),extras=extras,feed_total=len(entries),workday_total=extra_total,jobs=jobs,entries=checkpoint_entries)
  return Inventory('complete',jobs,f'KBR: verified {len(jobs)} full postings; feed {len(entries)}, Workday {extra_total}, extras {len(extras)}.',url,'KBR')
 except FetchError as e:return Inventory(e.status,jobs,str(e),url,'KBR')
 except (KeyError,ValueError,TypeError,AttributeError):return Inventory('partial',jobs,'KBR public feed schema changed.',url,'KBR')
