"""Public Eightfold search/detail adapter; derives its tenant from observed search."""
import json,os,re,shutil,time
from urllib.parse import urlsplit,parse_qsl,urlencode,urljoin
from .ats import FetchError,HTTPResponse,Inventory,_base,text
from .shared_boards import checked,MAX_JOBS
from .discovery import public_careers_url

class Client:
    def __init__(self,context,root,domain,sort_by=None):
        if sort_by not in (None, 'hot', 'timestamp', 'relevance'):
            raise FetchError('unsupported','Unverified public Eightfold ordering.')
        self.context=context;self.root=root;self.domain=domain;self.sort_by=sort_by;self.last=0.
    def data(self,kind,value):
        if kind=='search':
            q={'domain':self.domain,'query':'','location':'','start':value}
            if self.sort_by:q['sort_by']=self.sort_by
        elif kind=='position_details' and re.fullmatch('[0-9]{1,16}',str(value)):q={'position_id':value,'domain':self.domain,'hl':'en'}
        else:raise FetchError('unsupported','Unverified public Eightfold route.')
        time.sleep(max(0,.4-(time.monotonic()-self.last)));self.last=time.monotonic()
        r=self.context.request.get(self.root+'/api/pcsx/'+kind+'?'+urlencode(q)+('&' if kind=='search' else ''),max_redirects=0,timeout=30000)
        try:d=json.loads(checked(HTTPResponse(r.status,r.body(),r.headers)))
        finally:r.dispose()
        if d.get('status')!=200 or (d.get('error') or {}).get('message'):raise FetchError('partial','Eightfold public response reports an error.')
        return d['data']

def identity(e):
    ident=str(e.get('id',''))
    if not re.fullmatch('[1-9][0-9]{0,15}',ident) or not text(e.get('name')) or e.get('positionUrl')!='/careers/job/'+ident:raise FetchError('partial','Eightfold record is not a verified job posting.')
    return ident

def scan(client,cid,company,max_jobs=MAX_JOBS,listing_first=False):
    jobs=[];seen=set();snapshots=[];total=None
    def listing(start):
        d=client.data('search',start);n=d['count'];es=d['positions']
        if type(n) is not int or not 0<=n<=MAX_JOBS or d.get('appliedFilters')!={} or len(es)!=min(10,max(0,n-start)) or (total is not None and n!=total):raise FetchError('partial','Eightfold pagination, total, or scope changed.')
        return es,n
    try:
        entries,total=listing(0)
        all_entries=[]
        def download(e):
            if len(jobs)>=max_jobs:raise FetchError('partial',f'Bounded validation stopped at {len(jobs)} of {total} jobs.')
            ident=identity(e);j=client.data('position_details',ident)
            if identity(j)!=ident or j['name']!=e['name'] or j.get('displayJobId')!=e.get('displayJobId') or j.get('publicUrl')!=client.root+e['positionUrl'] or not text(j.get('jobDescription')):raise FetchError('partial','Eightfold full detail identity mismatch.')
            row=_base({'id':ident},'Eightfold',cid,company);row.update(title=text(j['name']),description=text(j['jobDescription']),url=j['publicUrl'],req_id=str(j.get('displayJobId','')),location='; '.join(j.get('standardizedLocations') or j.get('locations') or []),department=text(j.get('department')),work_arrangement=text(j.get('workLocationOption')));jobs.append(row)
        for start in range(0,max(1,total),10):
            if start:entries,_=listing(start)
            ids=[identity(e) for e in entries]
            if len(set(ids))!=len(ids) or seen.intersection(ids):raise FetchError('partial','Eightfold pagination repeated job IDs.')
            seen.update(ids);snapshots.append(ids)
            if listing_first: all_entries.extend(entries)
            else:
                for e in entries: download(e)
        if listing_first:
            if len(all_entries) != total: raise FetchError('partial','Eightfold listing did not yield its published inventory.')
            for e in all_entries: download(e)
        for page,ids in enumerate(snapshots):
            if [identity(e) for e in listing(page*10)[0]]!=ids:raise FetchError('partial','Eightfold inventory changed during scan.')
        return Inventory('complete',jobs,f'Eightfold: retrieved {len(jobs)} full postings and rechecked every page.',client.root+'/careers','Eightfold')
    except FetchError as e:return Inventory(e.status,jobs,e.reason,client.root+'/careers','Eightfold')
    except Exception as e:return Inventory('partial',jobs,f'Eightfold response failed validation ({type(e).__name__}).',client.root+'/careers','Eightfold')

def fetch_eightfold(url,cid,company,ats='',max_jobs=MAX_JOBS,sort_by=None,listing_first=False):
    try:
        if sort_by not in (None, 'hot', 'timestamp', 'relevance'):
            raise FetchError('unsupported','Unverified public Eightfold ordering.')
        public_careers_url(url)
        if any(k in ats.casefold() for k in ['parent','shared']):raise FetchError('unsupported','Eightfold parent-company scope needs a company-specific source.')
        for k,v in parse_qsl(urlsplit(url).query):
            if k.startswith('utm_') or (k=='pid' and v.isdigit()) or (k=='start' and v=='0') or (k=='sort_by' and v in {'hot','timestamp','relevance'}):continue
            raise FetchError('unsupported','Eightfold filtered source cannot be expanded to the employer board.')
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            # CI and desktop deployments can provide a system Chrome without
            # Playwright's separately downloaded Chromium bundle.  Prefer an
            # explicitly configured binary, then the system Chrome, while
            # retaining Playwright's default launch when neither is present.
            executable = os.environ.get('JOB_SCRAPER_CHROMIUM_EXECUTABLE') or shutil.which('google-chrome')
            options = {'headless': True}
            if executable:
                options['executable_path'] = executable
            browser=p.chromium.launch(**options)
            try:
                context=browser.new_context();page=context.new_page();searches=[]
                def capture(request):
                    q=urlsplit(request.url)
                    if q.path=='/api/pcsx/search':searches.append(request.url)
                page.on('request',capture)
                r=page.goto(url,wait_until='domcontentloaded',timeout=30000)
                try:page.wait_for_load_state('networkidle',timeout=5000)
                except Exception:pass
                if not r or r.status!=200:raise FetchError('blocked','Eightfold public careers page did not grant access.')
                if not searches:
                    links=page.locator('a[href]').evaluate_all('(els)=>els.map(e=>e.href)')
                    candidates=[]
                    origin=urlsplit(page.url).hostname
                    for link in links:
                        q=urlsplit(link)
                        if q.scheme=='https' and q.path.rstrip('/')=='/careers' and not q.query and (q.hostname.endswith('.eightfold.ai') or (q.hostname.endswith('.'+origin.removeprefix('www.').removeprefix('careers.')) and q.hostname.startswith(('searchcareers.','talent.')))):candidates.append(link)
                    if len(set(candidates))!=1:raise FetchError('unsupported','No unique verified Eightfold board linked from employer page.')
                    r=page.goto(candidates[0],wait_until='networkidle',timeout=30000)
                root='https://'+urlsplit(page.url).hostname
                domains=set()
                for u in searches:
                    q=urlsplit(u);params=dict(parse_qsl(q.query,keep_blank_values=True))
                    if q.scheme=='https' and 'https://'+q.hostname==root and re.fullmatch('[a-zA-Z0-9.-]+',params.get('domain','')) and not any(params.get(k) for k in ['query','location']):domains.add(params['domain'])
                if len(domains)!=1:raise FetchError('partial','Public Eightfold tenant/search scope not established.')
                return scan(Client(context,root,domains.pop(),sort_by),cid,company,max_jobs,listing_first)
            finally:browser.close()
    except FetchError as e:return Inventory(e.status,reason=e.reason,source_url=url,ats='Eightfold')
    except Exception as e:return Inventory('partial',reason=f'Eightfold browser failed ({type(e).__name__}).',source_url=url,ats='Eightfold')
