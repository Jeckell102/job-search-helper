"""AcquireTM public browser pagination and structured job details."""
import re,time
from urllib.parse import urlsplit,urljoin,parse_qs
from .ats import Inventory,FetchError,text,HTTPResponse
from .shared_boards import checked,Links,Scripts,schema_job
SOURCE='https://amphenol-aerospace.acquiretm.com/home.aspx'

def parse_listing(body):
 totals=re.findall(r'\b(\d+) positions found\.',text(body))
 if len(totals)!=1 or int(totals[0])>10000:raise FetchError('partial','AcquireTM listing total missing or ambiguous.')
 rows={};pages=set()
 for a,title in Links(body).links:
  u=urljoin(SOURCE,a.get('href',''));p=urlsplit(u);q=parse_qs(p.query)
  if p.scheme=='https' and p.hostname==urlsplit(SOURCE).hostname and p.path=='/job_details_clean.aspx' and set(q)=={'ID'} and len(q['ID'])==1 and q['ID'][0].isdigit():
   ident=q['ID'][0]
   if ident in rows or not text(title):raise FetchError('partial','AcquireTM duplicate job or missing title.')
   rows[ident]={'id':ident,'title':text(title),'url':u}
  m=re.fullmatch('Go to page ([0-9]+) of job results',a.get('aria-label',''))
  if m:pages.add(int(m[1]))
 return int(totals[0]),rows,pages

def inventory(page):
 page.goto(SOURCE,wait_until='domcontentloaded',timeout=30000)
 if page.url!=SOURCE:raise FetchError('partial','AcquireTM board redirected.')
 total,rows,pages=parse_listing(page.content());visited={1};pending=pages-{1}
 while pending:
  number=min(pending)
  if number>400:raise FetchError('partial','AcquireTM page bound exceeded.')
  page.get_by_role('link',name=f'Go to page {number} of job results',exact=True).click()
  # AcquireTM's ASP.NET UpdatePanel leaves analytics requests open forever.
  # The bounded settle is followed by strict listing-count and ID checks below.
  time.sleep(1)
  if page.url!=SOURCE:raise FetchError('partial','AcquireTM pagination left verified board.')
  n,part,links=parse_listing(page.content())
  if n!=total or rows.keys() & part.keys():raise FetchError('partial','AcquireTM total changed or pagination repeated.')
  rows.update(part);visited.add(number);pending=(pending|links)-visited
 if len(rows)!=total:raise FetchError('partial','AcquireTM retrieved count disagrees with public total.')
 return rows

def posting(body,e,cid,company):
 records=Scripts(body).jobs()
 if len(records)!=1:raise FetchError('partial','AcquireTM unique job schema missing.')
 j=records[0]
 if j.get('url')!=e['url'] or str((j.get('identifier') or {}).get('value'))!=e['id'] or text(j.get('title'))!=e['title']:raise FetchError('partial','AcquireTM job identity mismatch.')
 return schema_job(j,e['url'],e['id'],'AcquireTM',cid,company)

def fetch_acquiretm(url,cid,company):
 jobs=[]
 if url!=SOURCE:return Inventory('unsupported',reason='AcquireTM requires the verified unfiltered employer board.',source_url=url,ats='AcquireTM')
 try:
  from playwright.sync_api import sync_playwright
  with sync_playwright() as p:
   browser=p.chromium.launch(headless=True)
   try:
    context=browser.new_context();page=context.new_page();entries=inventory(page)
    for e in entries.values():
     time.sleep(.4);response=context.request.get(e['url'],max_redirects=0,timeout=30000)
     try:body=checked(HTTPResponse(response.status,response.body(),response.headers),True)
     finally:response.dispose()
     jobs.append(posting(body,e,cid,company))
    if inventory(page)!=entries:raise FetchError('partial','AcquireTM listing changed during scan.')
   finally:browser.close()
  return Inventory('complete',jobs,f'AcquireTM: verified all {len(jobs)} full postings and rechecked every listing page.',url,'AcquireTM')
 except FetchError as e:return Inventory(e.status,jobs,str(e),url,'AcquireTM')
 except Exception as e:return Inventory('partial',jobs,f'AcquireTM public scan failed ({type(e).__name__}).',url,'AcquireTM')
