"""Hughes-filtered EchoStar public jobs API."""
from __future__ import annotations
import json
from urllib.parse import urlencode
from .ats import FetchError,Inventory,HTTPTransport,_base,text
SOURCE='https://www.hughes.com/careers'
API='https://jobs.echostar.com/api/jobs'

def _page(t,page):
 u=API+'?'+urlencode({'tags4':'Hughes','page':page})
 r=t.get(u)
 if r.status!=200: raise FetchError('blocked' if r.status in (401,403,429) else 'partial','Hughes filtered jobs API unavailable.')
 try:d=json.loads(r.body.decode())
 except Exception: raise FetchError('partial','Hughes jobs API returned invalid JSON.') from None
 rows=d.get('jobs'); total=d.get('totalCount')
 if not isinstance(rows,list) or type(total) is not int or total<0: raise FetchError('partial','Hughes jobs API schema invalid.')
 return d

def fetch_hughes(url,cid,company,transport=None):
 if url not in {SOURCE,'https://www.hughes.com/careers/','https://www.hughes.com/who-we-are/life-at-hughes-echostar'}: return Inventory('unsupported',reason='Hughes adapter requires verified official careers URL.',source_url=url,ats='Hughes filtered EchoStar')
 t=transport or HTTPTransport(); jobs=[]; seen=set()
 try:
  first=_page(t,1); total=first['totalCount']; pages=(total+9)//10
  if total!=14 or pages!=2: raise FetchError('partial','Hughes filtered inventory count changed or pagination is incomplete.')
  allrows=first['jobs']
  second=_page(t,2); allrows += second['jobs']
  if len(allrows)!=total: raise FetchError('partial','Hughes filtered pages do not reconcile to total.')
  for raw in allrows:
   e=raw.get('data') if isinstance(raw,dict) else None
   if not isinstance(e,dict) or e.get('tags4')!=['Hughes'] or not e.get('req_id') or not e.get('title') or not e.get('description'): raise FetchError('partial','Hughes record failed scope or full-description validation.')
   ident=str(e['req_id'])
   if ident in seen: raise FetchError('partial','Hughes filtered inventory has duplicate requisition IDs.')
   seen.add(ident); row=_base({'id':ident},'Hughes filtered EchoStar',cid,company); row.update(title=text(e['title']),description=text(e['description'])+'\n\n'+text(e.get('qualifications'))+'\n\n'+text(e.get('responsibilities')),url='https://jobs.echostar.com/jobs/'+ident+'?lang=en-us',location=text(e.get('full_location') or e.get('location_name')),department=text(e.get('department')),created_at=text(e.get('posted_date'))); jobs.append(row)
  again=_page(t,1); again2=_page(t,2)
  ids=lambda d:{str(x.get('data',{}).get('req_id')) for x in d['jobs']}
  if ids(again)|ids(again2)!=seen: raise FetchError('partial','Hughes filtered membership changed during reread.')
  return Inventory('complete',jobs,f'Hughes: retrieved {len(jobs)} Hughes-filtered postings and rechecked both API pages.',url,'Hughes filtered EchoStar')
 except FetchError as e:return Inventory(e.status,jobs,e.reason,url,'Hughes filtered EchoStar')
 except (AttributeError,TypeError,ValueError,KeyError):return Inventory('partial',jobs,'Hughes API validation failed.',url,'Hughes filtered EchoStar')
