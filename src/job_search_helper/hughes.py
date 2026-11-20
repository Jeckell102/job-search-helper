"""Hughes-filtered EchoStar public jobs API."""
from __future__ import annotations
import json
from urllib.parse import urlencode
from .ats import FetchError,Inventory,HTTPTransport,_base,text
SOURCE='https://www.hughes.com/careers'
API='https://jobs.echostar.com/api/jobs'
MAX_PAGES=1000

def _page_url(page):
 if type(page) is not int or not 1<=page<=MAX_PAGES: raise FetchError('partial','Hughes pagination page is invalid.')
 return API+'?'+urlencode({'tags4':'Hughes','page':page})

def _page(t,page):
 u=_page_url(page)
 r=t.get(u)
 if r.status!=200: raise FetchError('blocked' if r.status in (401,403,429) else 'partial','Hughes filtered jobs API unavailable.')
 try:d=json.loads(r.body.decode())
 except Exception: raise FetchError('partial','Hughes jobs API returned invalid JSON.') from None
 rows=d.get('jobs'); total=d.get('totalCount')
 if not isinstance(rows,list) or type(total) is not int or total<0: raise FetchError('partial','Hughes jobs API schema invalid.')
 return d

def _rows(t):
 first=_page(t,1); total=first['totalCount']; first_rows=first['jobs']
 if total==0:
  if first_rows: raise FetchError('partial','Hughes empty inventory does not reconcile to its rows.')
  return []
 page_size=len(first_rows)
 if not page_size: raise FetchError('partial','Hughes inventory has a positive total but no first-page rows.')
 pages=(total+page_size-1)//page_size
 if pages>MAX_PAGES: raise FetchError('partial','Hughes inventory exceeds the bounded public pagination contract.')
 rows=list(first_rows)
 for page in range(2,pages+1):
  current=_page(t,page)
  if current['totalCount']!=total: raise FetchError('partial','Hughes inventory total changed during pagination.')
  rows.extend(current['jobs'])
 if len(rows)!=total: raise FetchError('partial','Hughes filtered pages do not reconcile to total.')
 return rows

def _ids(rows):
 ids=set()
 for raw in rows:
  e=raw.get('data') if isinstance(raw,dict) else None
  if not isinstance(e,dict) or e.get('tags4')!=['Hughes'] or not e.get('req_id') or not e.get('title') or not e.get('description'): raise FetchError('partial','Hughes record failed scope or full-description validation.')
  ident=str(e['req_id'])
  if ident in ids: raise FetchError('partial','Hughes filtered inventory has duplicate requisition IDs.')
  ids.add(ident)
 return ids

def fetch_hughes(url,cid,company,transport=None):
 if url not in {SOURCE,'https://www.hughes.com/careers/','https://www.hughes.com/who-we-are/life-at-hughes-echostar'}: return Inventory('unsupported',reason='Hughes adapter requires verified official careers URL.',source_url=url,ats='Hughes filtered EchoStar')
 t=transport or HTTPTransport(); jobs=[]
 try:
  allrows=_rows(t); seen=_ids(allrows)
  for raw in allrows:
   e=raw.get('data') if isinstance(raw,dict) else None
   ident=str(e['req_id'])
   row=_base({'id':ident},'Hughes filtered EchoStar',cid,company); row.update(title=text(e['title']),description=text(e['description'])+'\n\n'+text(e.get('qualifications'))+'\n\n'+text(e.get('responsibilities')),url='https://jobs.echostar.com/jobs/'+ident+'?lang=en-us',location=text(e.get('full_location') or e.get('location_name')),department=text(e.get('department')),created_at=text(e.get('posted_date'))); jobs.append(row)
  if _ids(_rows(t))!=seen: raise FetchError('partial','Hughes filtered membership changed during reread.')
  return Inventory('complete',jobs,f'Hughes: retrieved {len(jobs)} Hughes-filtered postings and rechecked the complete API inventory.',url,'Hughes filtered EchoStar')
 except FetchError as e:return Inventory(e.status,jobs,e.reason,url,'Hughes filtered EchoStar')
 except (AttributeError,TypeError,ValueError,KeyError):return Inventory('partial',jobs,'Hughes API validation failed.',url,'Hughes filtered EchoStar')
