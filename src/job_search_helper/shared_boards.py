"""Reusable public ATS board adapters and bounded employer-page discovery.

No profile, account, application submission, or authenticated recruiting API is
used. A partial/blocked adapter result cannot be replaced by generic link scraping.
"""
from __future__ import annotations
from dataclasses import dataclass
from html.parser import HTMLParser
import json,math,re,sys,time
from urllib.parse import urlsplit,urljoin,parse_qsl,urlencode
from urllib.request import Request,build_opener
from urllib.error import HTTPError,URLError
from http.client import IncompleteRead
from .ats import FetchError,HTTPResponse,Inventory,MAX_RESPONSE_BYTES,_NoRedirect,_challenge,_base,text,_delay,RETRY_STATUSES
from .discovery import CareersTransport,public_careers_url,_BoardLinks,_cta_candidates,_same_public_host

MAX_JOBS=10000
UUID=r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
SLUG=r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}'
FAMILIES={'Rippling','Pinpoint','Breezy HR','SmartRecruiters','Workable','JazzHR','Jobvite','Dayforce','Comeet','ClearCompany','ApplicantPro','Paycor Recruiting','isolved','Jibe','TalentBrew'}

@dataclass(frozen=True)
class Board:
    name:str
    root:str
    slug:str
    path:str
    ident:str=''
    @property
    def url(self):return self.root+self.path


# Employer-owned JazzHR custom domain, verified from its public board and job pages.
JAZZ_CUSTOM_HOSTS = {'jobs.nearearth.aero'}

def known_host(host):
    return bool(host in JAZZ_CUSTOM_HOSTS or host in {'ats.rippling.com','ats.us1.rippling.com','careers.smartrecruiters.com','jobs.smartrecruiters.com','apply.workable.com','jobs.jobvite.com','jobs.dayforcehcm.com','www.comeet.com','www.comeet.co','careers-content.clearcompany.com','careers-api.clearcompany.com','recruitingbypaycor.com'} or re.fullmatch(r'[a-z0-9-]+\.(?:breezy\.hr|pinpointhq\.com|applytojob\.com|hrmdirect\.com|applicantpro\.com|isolvedhire\.com|jibeapply\.com)',host or ''))


def board_link(url):
    p=urlsplit(url)
    if p.scheme!='https' or not known_host(p.hostname) or p.username or p.password or p.port not in (None,443) or p.fragment or '\\' in url or any(ord(c)<=32 for c in url):
        raise ValueError('A verified public HTTPS careers board is required.')
    host=p.hostname;path=p.path.rstrip('/');parts=path.strip('/').split('/') if path else []
    ident='';root='https://'+host
    if host=='careers-api.clearcompany.com':
        if not re.fullmatch('/v1/'+UUID,p.path) or p.query:raise ValueError('Invalid ClearCompany public board identity.')
        return Board('ClearCompany',root,p.path.split('/')[-1],p.path)
    if host.endswith('.jibeapply.com'):
        if p.path.rstrip('/')!='/jobs' or any(not k.startswith(('utm_','_gl')) for k,v in parse_qsl(p.query)):raise ValueError('Jibe requires the full unfiltered public board.')
        return Board('Jibe',root,host.split('.')[0],'/jobs')
    if host=='careers-content.clearcompany.com':
        q=dict(parse_qsl(p.query));slug=q.get('siteId','')
        if p.path!='/js/v1/career-site.js' or not re.fullmatch(UUID,slug):raise ValueError('Invalid ClearCompany public widget.')
        return Board('ClearCompany','https://careers-api.clearcompany.com',slug,'/v1/'+slug)
    if host=='recruitingbypaycor.com':
        q=dict(parse_qsl(p.query));slug=q.get('clientId','')
        if p.path not in ['/career/iframe.action','/career/CareerHome.action','/career/JobIntroduction.action'] or not re.fullmatch('[a-f0-9]{32}',slug):raise ValueError('Invalid Paycor employer board.')
        name='Paycor Recruiting';path='/career/CareerHome.action?clientId='+slug;ident=q.get('id','')
    elif host.endswith('.isolvedhire.com'):
        name,slug='isolved',host.split('.')[0]
        if re.fullmatch('/iframe/(?:[0-9]+|mobile)/?',p.path):path=p.path.rstrip('/')
        elif p.path.rstrip('/')=='/jobs':path='/jobs/'
        else:raise ValueError('Invalid isolved all-jobs board.')
    elif host=='jobs.dayforcehcm.com':
        if parts and re.fullmatch(r'[a-z]{2}-[A-Z]{2}',parts[0]):parts=parts[1:]
        if len(parts) not in (2,4) or not all(re.fullmatch(SLUG,v) for v in parts[:2]):raise ValueError('Invalid Dayforce board.')
        name,slug='Dayforce',parts[0]+'/'+parts[1];path='/en-US/'+slug
        if len(parts)==4:
            if parts[2]!='jobs' or not parts[3].isdigit():raise ValueError('Invalid Dayforce posting.')
            ident=parts[3]
    elif host in {'www.comeet.com','www.comeet.co'}:
        if len(parts) not in (3,5) or parts[0]!='jobs' or not re.fullmatch(SLUG,parts[1]) or not re.fullmatch(r'[A-Za-z0-9]+\.[A-Za-z0-9]+',parts[2]):raise ValueError('Invalid Comeet board.')
        name,slug='Comeet',parts[1]+'/'+parts[2];root='https://www.comeet.com';path='/jobs/'+slug
        if len(parts)==5:ident=parts[4]
    elif host.endswith('.hrmdirect.com'):
        name,slug='ClearCompany',host.split('.')[0];path='/employment/job-openings.php?search=true'
        if p.path not in ['/employment/job-openings.php','/employment/job-opening.php']:raise ValueError('Invalid ClearCompany board.')
        if p.path.endswith('/job-opening.php'):ident=dict(parse_qsl(p.query)).get('req','')
    elif host.endswith('.applicantpro.com'):
        name,slug='ApplicantPro',host.split('.')[0];path='/jobs/'
        if p.path.rstrip('/')!='/jobs':raise ValueError('ApplicantPro requires its public all-jobs board.')
    elif host in {'ats.rippling.com','ats.us1.rippling.com'}:
        if parts[:1]==['embed']:parts=parts[1:]
        if len(parts) not in (2,3) or parts[1]!='jobs' or not re.fullmatch(SLUG,parts[0]):raise ValueError('Invalid Rippling board.')
        name,slug='Rippling',parts[0];path='/'+slug+'/jobs';root='https://ats.rippling.com'
        if len(parts)==3:
            if not re.fullmatch(UUID,parts[2]):raise ValueError('Invalid Rippling posting.')
            ident=parts[2].lower()
    elif host.endswith('.pinpointhq.com'):
        name,slug='Pinpoint',host.split('.')[0];path='/jobs'
        m=re.fullmatch(r'/(?:[a-z]{2}/)?postings/('+UUID+')',p.path.rstrip('/'))
        if m:ident=m[1].lower()
        elif p.path.rstrip('/') not in ('','/jobs','/en','/en/jobs'):raise ValueError('Not a Pinpoint board.')
    elif host.endswith('.breezy.hr'):
        name,slug='Breezy HR',host.split('.')[0];path='/'
        if parts:
            if len(parts)!=2 or parts[0]!='p' or not re.fullmatch(r'[a-f0-9]{12}-.+',parts[1]):raise ValueError('Not a Breezy board.')
            ident=parts[1].split('-')[0]
    elif host in {'careers.smartrecruiters.com','jobs.smartrecruiters.com'}:
        if not parts or not re.fullmatch(SLUG,parts[0]) or parts[0] in {'my-applications','oneclick-ui'}:raise ValueError('Not a SmartRecruiters employer board.')
        name,slug='SmartRecruiters',parts[0];root='https://careers.smartrecruiters.com';path='/'+slug
        if len(parts)>1:
            if len(parts)!=2 or not re.fullmatch(r'[0-9]+(?:-.+)?',parts[1]):raise ValueError('Invalid SmartRecruiters scope.')
            ident=parts[1].split('-')[0]
    elif host=='apply.workable.com':
        if not parts or not re.fullmatch(SLUG,parts[0]) or parts[0]=='api':raise ValueError('Invalid Workable board.')
        name,slug='Workable',parts[0];path='/'+slug+'/'
        if len(parts)>1:
            if len(parts)!=3 or parts[1]!='j' or not re.fullmatch(r'[A-Z0-9]+',parts[2]):raise ValueError('Invalid Workable posting.')
            ident=parts[2]
    elif host.endswith('.applytojob.com') or host in JAZZ_CUSTOM_HOSTS:
        name,slug='JazzHR',host.split('.')[0];path='/apply'
        if parts and parts!=['apply']:
            if len(parts)!=3 or parts[0]!='apply' or not re.fullmatch(r'[A-Za-z0-9]+',parts[1]):raise ValueError('Invalid JazzHR scope.')
            ident=parts[1]
    else:
        if not parts or not re.fullmatch(SLUG,parts[0]):raise ValueError('Invalid Jobvite board.')
        name,slug='Jobvite',parts[0];path='/'+slug+'/jobs'
        if len(parts)==3 and parts[1]=='job':ident=parts[2]
        elif len(parts)>1 and parts[1:] not in (['jobs'],['search']):raise ValueError('Invalid Jobvite scope.')
    seen=set()
    for k,v in parse_qsl(p.query,keep_blank_values=True,max_num_fields=30):
        if k in seen:raise ValueError('Duplicate board scope parameter.')
        seen.add(k)
        if k.startswith('utm_') or k in {'source','src','st','gh_src'}:continue
        if name=='Rippling' and ((k=='page' and v=='0') or (k=='jobBoardSlug' and v==slug) or (k=='s' and p.path.startswith('/embed/'))):continue
        if name=='Paycor Recruiting' and ((k=='clientId' and v==slug) or (k=='id' and re.fullmatch('[a-f0-9]{32}',v)) or (k in {'source','lang','parentUrl','gns'})):continue
        if name=='ClearCompany' and ((k=='search' and v=='true') or (k=='frameborder' and v=='0') or (k in {'req','req_loc'} and v.isdigit())):continue
        if name=='Workable' and k=='lng' and v=='en':continue
        if name=='Jobvite' and k in {'c','l','q'} and not v:continue
        raise ValueError('Filtered board URL requires explicit company scope support.')
    return Board(name,root,slug,path,ident)


def resolve_shared(ats,url):
    b=board_link(url)
    if any(k in ats.casefold() for k in ('shared','parent')):raise ValueError('Shared parent board needs verified company scope.')
    return b.name,b.path,b.root


def discover(url,pages):
    origin=public_careers_url(url);queue=[origin];seen=set()
    while queue and len(seen)<5:
        u=queue.pop(0)
        if u in seen:continue
        seen.add(u);r=pages.get(u)
        if r.status in (301,302,303,307,308):
            target=public_careers_url(urljoin(u,next((v for k,v in r.headers.items() if k.lower()=='location'),'')))
            if known_host(urlsplit(target).hostname):
                b=board_link(target);return Board(b.name,b.root,b.slug,b.path),({b.ident} if b.ident else None)
            if not _same_public_host(u,target):raise FetchError('unsupported','Employer redirects to an unverified careers host; source verification required.')
            queue.insert(0,target);continue
        body=checked(r,html=True);p=_BoardLinks(u);p.feed(body)
        embedded=embedded_boards(body,u)
        if embedded:
            if len(embedded)!=1:raise FetchError('unsupported','Multiple embedded employer boards.')
            return embedded[0],None
        boards={}
        for link in p.links:
            v=urljoin(p.base_url,link)
            if not known_host(urlsplit(v).hostname):continue
            try:b=board_link(v)
            except ValueError:continue
            base=Board(b.name,b.root,b.slug,b.path);boards.setdefault(base,set())
            if b.ident:boards[base].add(b.ident)
        if len(boards)>1:raise FetchError('unsupported','Employer links multiple shared boards; select a company-specific source.')
        if boards:
            b,ids=next(iter(boards.items()));return b,ids or None
        queue.extend(v for v in _cta_candidates(p,origin) if v not in seen and v not in queue)
    raise FetchError('partial','No verified shared board found in bounded employer-page discovery.')


def checked(r,html=False):
    if not isinstance(r,HTTPResponse):raise FetchError('failed','Invalid public board response.')
    if r.status in (401,403) or _challenge(r,expect_html=html):raise FetchError('blocked','Public job board denied access or requires human verification.')
    if not 200<=r.status<300:raise FetchError('partial',f'Public job board HTTP {r.status}; inventory incomplete.')
    if len(r.body)>MAX_RESPONSE_BYTES:raise FetchError('partial','Public job response exceeds the bounded size limit.')
    return r.body.decode('utf-8')


def allowed(b,url,payload=None):
    p=urlsplit(url)
    if p.scheme!='https' or p.username or p.password or p.port not in (None,443) or p.fragment or '\\' in url or any(ord(c)<=32 for c in url):return False
    if b.name=='SmartRecruiters':
        return payload is None and p.hostname=='api.smartrecruiters.com' and bool(re.fullmatch('/v1/companies/'+re.escape(b.slug)+r'/postings(?:/[0-9]+)?',p.path)) and (not p.query or bool(re.fullmatch(r'limit=100&offset=[0-9]+',p.query)))
    if p.hostname!=urlsplit(b.root).hostname:return False
    if b.name=='Jibe':return payload is None and p.path=='/api/jobs' and bool(re.fullmatch(r'page=[1-9][0-9]*&limit=100',p.query))
    if b.name=='ClearCompany' and b.root=='https://careers-api.clearcompany.com':return payload is None and p.path==b.path and bool(re.fullmatch(r'pageIndex=[0-9]+&pageSize=25&source=CJB-0',p.query))
    if b.name=='Paycor Recruiting':
        q=dict(parse_qsl(p.query));return payload is None and q.get('clientId')==b.slug and set(q).issubset({'clientId','id','source','lang'}) and p.path in {'/career/CareerHome.action','/career/JobIntroduction.action'} and (p.path.endswith('CareerHome.action') or bool(re.fullmatch('[a-f0-9]{32}',q.get('id',''))))
    if b.name=='isolved':return payload is None and not p.query and (p.path==b.path or bool(re.fullmatch(re.escape(b.path.rstrip('/'))+r'/[0-9]+\.html',p.path)))
    if b.name=='Dayforce':return (payload is None and p.path==b.path and not p.query) or (payload is not None and p.path=='/api/geo/'+b.slug.split('/')[0]+'/jobposting/search' and not p.query)
    if b.name=='Comeet':return payload is None and p.path==b.path and not p.query
    if b.name=='ClearCompany':return payload is None and ((p.path=='/employment/job-openings.php' and p.query=='search=true') or (p.path=='/employment/job-opening.php' and bool(re.fullmatch(r'req=[0-9]+(?:&req_loc=[0-9]+)?',p.query))))
    if b.name=='ApplicantPro':return payload is None and ((p.path=='/jobs/' and not p.query) or (bool(re.fullmatch(r'/core/jobs/[0-9]+',p.path)) and p.query.startswith('getParams=')) or (bool(re.fullmatch(r'/jobs/[0-9]+(?:-[a-zA-Z0-9-]+)?(?:\.html)?',p.path)) and not p.query))
    if b.name=='Rippling':return payload is None and bool(re.fullmatch(re.escape(b.path)+'(?:/'+UUID+')?',p.path)) and (not p.query or bool(re.fullmatch(r'page=[0-9]+',p.query)))
    if b.name=='Pinpoint':return payload is None and p.path in {'/jobs','/postings.json'} and not p.query
    if b.name=='Breezy HR':return payload is None and (p.path in {'/','/json'} or bool(re.fullmatch(r'/p/[a-f0-9]{12}-[A-Za-z0-9-]+',p.path))) and not p.query
    if b.name=='Workable':
        return ((payload is not None and p.path=='/api/v3/accounts/'+b.slug+'/jobs') or (payload is None and (p.path in {b.path} or bool(re.fullmatch('/api/v2/accounts/'+re.escape(b.slug)+r'/jobs/[A-Z0-9]+',p.path))))) and not p.query
    if b.name=='JazzHR':return payload is None and (p.path in {'/','/apply','/apply/'} or bool(re.fullmatch(r'/apply/[A-Za-z0-9]+/[A-Za-z0-9_-]+',p.path))) and not p.query
    if b.name=='Jobvite':return payload is None and bool(re.fullmatch('/'+re.escape(b.slug)+r'/(?:jobs|job/[A-Za-z0-9]+)',p.path)) and not p.query
    return False


class Transport:
    def __init__(self,b):self.board=b;self.opener=build_opener(_NoRedirect());self.last=0.
    def request(self,url,payload=None):
        if not allowed(self.board,url,payload):raise FetchError('unsupported','Only this employer’s pinned public listing and job-detail endpoints are allowed.')
        for attempt in range(3):
            time.sleep(max(0,.4-(time.monotonic()-self.last)));self.last=time.monotonic()
            req=Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers={'User-Agent':'JobSearchHelper/1.0 (public job-board inventory; read-only)','Content-Type':'application/json','Accept-Encoding':'identity'})
            try:
                with self.opener.open(req,timeout=25) as r:result=HTTPResponse(r.status,r.read(MAX_RESPONSE_BYTES+1),dict(r.headers))
            except HTTPError as e:result=HTTPResponse(e.code,e.read(8192),dict(e.headers));e.close()
            except (URLError,TimeoutError,ConnectionError,IncompleteRead):
                if attempt==2:raise FetchError('partial','Public job request timed out after bounded retries.') from None
                time.sleep(2**attempt);continue
            if result.status in RETRY_STATUSES and attempt<2:time.sleep(_delay(result.headers,attempt));continue
            return result
        raise FetchError('partial','Public job request failed.')
    def get(self,url):return self.request(url)
    def post(self,url,payload):return self.request(url,payload)


class Scripts(HTMLParser):
    def __init__(self,body):super().__init__();self.scripts=[];self.current=None;self.feed(body)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='script' and a.get('type') in {'application/json','application/ld+json'}:self.current=[a,'']
    def handle_data(self,d):
        if self.current is not None:self.current[1]+=d
    def handle_endtag(self,tag):
        if tag=='script' and self.current is not None:self.scripts.append(self.current);self.current=None
    def next(self):
        xs=[json.loads(s) for a,s in self.scripts if a.get('id')=='__NEXT_DATA__']
        if len(xs)!=1:raise FetchError('partial','Public Next.js board state missing or ambiguous.')
        return xs[0]['props']['pageProps']
    def jobs(self):
        def walk(x):
            if isinstance(x,list):
                for y in x:yield from walk(y)
            elif isinstance(x,dict):
                if x.get('@type')=='JobPosting':yield x
                if '@graph' in x:yield from walk(x['@graph'])
        return [j for a,s in self.scripts if a.get('type')=='application/ld+json' for j in walk(json.loads(s))]


def js(t,url,payload=None):return json.loads(checked(t.get(url) if payload is None else t.post(url,payload)))
def unique(items):
    if any(e.get('id') is None or isinstance(e.get('id'),bool) for e in items):raise FetchError('partial','Public posting ID is missing or invalid.')
    ids=[str(e['id']) for e in items]
    if len(ids)>MAX_JOBS or len(ids)!=len(set(ids)) or any(not i for i in ids):raise FetchError('partial','Public inventory contains duplicate/missing IDs or exceeds its size limit.')
    return items

def rippling_locations(items):
    """Coalesce only repeated postings whose distinct locations explain each row.

    Reject ambiguous repeats; final reconciliation still compares the whole listing.
    """
    grouped = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
            raise FetchError('partial', 'Rippling posting ID is missing or invalid.')
        ident = item['id']
        if ident not in grouped:
            grouped[ident] = [item]
        else:
            grouped[ident].append(item)
    result = []
    for entries in grouped.values():
        if len(entries) == 1:
            result.append(entries[0]); continue
        base = {k:v for k,v in entries[0].items() if k != 'locations'}
        locations = []
        for entry in entries:
            if {k:v for k,v in entry.items() if k != 'locations'} != base:
                raise FetchError('partial', 'Rippling duplicate posting has conflicting metadata.')
            locs = entry.get('locations')
            if not isinstance(locs, list) or len(locs) != 1 or not isinstance(locs[0], dict) or not isinstance(locs[0].get('name'), str) or not locs[0]['name'].strip():
                raise FetchError('partial', 'Rippling duplicate posting location is ambiguous.')
            locations.append(locs[0])
        names = [v['name'].strip() for v in locations]
        if len(names) != len(set(names)):
            raise FetchError('partial', 'Rippling duplicate posting repeats a location.')
        merged = dict(base, locations=sorted(locations, key=lambda v:v['name']))
        merged['_rippling_duplicate_locations'] = sorted(names)
        result.append(merged)
    return unique(result)


def listing(b,t):
    if b.name in {'Dayforce','Comeet','ClearCompany','ApplicantPro','Paycor Recruiting','isolved','Jibe','TalentBrew'}:
        from .shared_extended import listing_extended
        return listing_extended(b,t)
    if b.name=='Rippling':
        out=[];total=None
        for page in range(500):
            state=Scripts(checked(t.get(b.url+('?page='+str(page) if page else '')),True)).next()
            if state['apiData']['jobBoardSlug']!=b.slug or state['apiData']['jobBoard']['slug']!=b.slug:raise FetchError('partial','Rippling board identity mismatch.')
            qs=[q for q in state['dehydratedState']['queries'] if q.get('queryKey',[])[:3]==['board',b.slug,'job-posts']]
            if len(qs)!=1:raise FetchError('partial','Rippling listing state is missing.')
            key=qs[0]['queryKey'][-1];d=qs[0]['state']['data'];n=d['totalItems']
            if type(n) is not int or not 0<=n<=MAX_JOBS or d['page']!=page or d['pageSize']!=20 or d['totalPages']!=math.ceil(n/20) or key.get('page')!=page or any(key.get(k) for k in ('searchQuery','departments','workplaceType','country','state','city')):raise FetchError('partial','Rippling pagination or scope cannot be verified.')
            if total is None:total=n
            if total!=n or len(d['items'])!=min(20,n-page*20):raise FetchError('partial','Rippling count changed during pagination.')
            out.extend(d['items'])
            if len(out)==n:return rippling_locations(out)
        raise FetchError('partial','Rippling page limit reached.')
    if b.name=='Pinpoint':
        data=js(t,b.root+'/postings.json')
        if set(data)!={'data'} or not isinstance(data['data'],list):raise FetchError('partial','Pinpoint public all-postings feed changed shape.')
        return unique(data['data'])
    if b.name=='Breezy HR':
        data=js(t,b.root+'/json')
        if not isinstance(data,list):raise FetchError('partial','Breezy public all-positions feed changed shape.')
        return unique(data)
    if b.name=='SmartRecruiters':
        out=[];total=None
        for offset in range(0,MAX_JOBS,100):
            d=js(t,'https://api.smartrecruiters.com/v1/companies/'+b.slug+'/postings?limit=100&offset='+str(offset));n=d['totalFound']
            if type(n) is not int or not 0<=n<=MAX_JOBS or d['offset']!=offset or d['limit']!=100:raise FetchError('partial','SmartRecruiters pagination metadata is invalid.')
            if total is None:total=n
            if total!=n or len(d['content'])!=min(100,n-offset):raise FetchError('partial','SmartRecruiters count or page changed.')
            out.extend(d['content'])
            if len(out)==n:return unique(out)
        raise FetchError('partial','SmartRecruiters inventory size limit reached.')
    if b.name=='Workable':
        out=[];total=None;token=None;tokens=set()
        for _ in range(500):
            payload={'query':'','department':[],'location':[],'workplace':[],'worktype':[]}
            if token:payload['token']=token
            d=js(t,b.root+'/api/v3/accounts/'+b.slug+'/jobs',payload);n=d['total']
            if type(n) is not int or not 0<=n<=MAX_JOBS or (total is not None and total!=n):raise FetchError('partial','Workable total is invalid or changed.')
            total=n;out.extend(d['results']);token=d.get('nextPage')
            if not token:
                if len(out)!=total:raise FetchError('partial','Workable listing did not reconcile with total.')
                return unique(out)
            if not isinstance(token,str) or token in tokens:raise FetchError('partial','Workable repeated pagination cursor.')
            tokens.add(token)
        raise FetchError('partial','Workable page limit reached.')
    return html_listing(b,t)


def _join_locations(values):
    return '; '.join(dict.fromkeys(text(v.get('name') or ', '.join(str(v[k]) for k in ('city','region','country') if v.get(k))) for v in values))


def posting(b,t,e,cid,company):
    if b.name in {'Dayforce','Comeet','ClearCompany','ApplicantPro','Paycor Recruiting','isolved','Jibe','TalentBrew'}:
        from .shared_extended import posting_extended
        return posting_extended(b,t,e,cid,company)
    ident=str(e['id']);row=_base({'id':ident},b.name,cid,company)
    if b.name=='Rippling':
        url=b.url+'/'+ident;d=Scripts(checked(t.get(url),True)).next()['apiData'];j=d['jobPost']
        if j['uuid']!=ident or j['name']!=e['name'] or j.get('unlistedFromSearch') is not False or d['jobBoard']['slug']!=b.slug or j['url']!=url:raise FetchError('partial','Rippling detail identity or listing state mismatch.')
        if '_rippling_duplicate_locations' in e:
            actual=d.get('workLocations')
            if not isinstance(actual,list) or any(not isinstance(v,str) or not v.strip() for v in actual) or sorted(set(v.strip() for v in actual)) != e['_rippling_duplicate_locations']:
                raise FetchError('partial','Rippling listing locations do not match posting detail.')
        row.update(title=text(j['name']),url=url,description='\n\n'.join(text(j['description'].get(k)) for k in ('company','role') if j['description'].get(k)),location='; '.join(d['workLocations']),department=text((j.get('department') or {}).get('name')),created_at=j.get('createdOn',''),work_arrangement='; '.join(dict.fromkeys(v.get('workplaceType','') for v in e.get('locations',[]))),compensation='; '.join(f"{r.get('currency','')} {r.get('rangeStart','')} - {r.get('rangeEnd','')} {r.get('frequency','')} ({r.get('location','')})" for r in d.get('payRangeDetails') or []))
    elif b.name=='Pinpoint':
        j=e;linked=board_link(j['url'])
        if linked.root!=b.root or not linked.ident:raise FetchError('partial','Pinpoint posting belongs to a different board.')
        row.update(title=text(j['title']),url=j['url'],req_id=text(j.get('job',{}).get('requisition_id')),description='\n\n'.join(text(j.get(k)) for k in ('description','key_responsibilities','skills_knowledge_expertise','benefits') if j.get(k)),location=text((j.get('location') or {}).get('name')),department=text((j.get('job',{}).get('department') or {}).get('name')),work_arrangement=text(j.get('workplace_type_text')),compensation=text(j.get('compensation')) if j.get('compensation_visible') else '')
    elif b.name=='Breezy HR':
        url=e['url'];linked=board_link(url)
        if linked.root!=b.root or linked.ident!=ident or e['company']['friendly_id']!=b.slug:raise FetchError('partial','Breezy posting identity mismatch.')
        body=checked(t.get(url),True);jobs=Scripts(body).jobs()
        if not jobs:
            from .shared_extended import Elements
            descriptions=Elements(body,{'description'}).values
            headings=[text(v) for v in re.findall(r'<h1(?:\s[^>]*)?>(.*?)</h1>',body,re.S|re.I)]
            meta=PublicMetadata();meta.feed(body)
            if len(descriptions)!=1 or not descriptions[0] or headings!=[text(e['name'])] or meta.urls!=[url]:
                raise FetchError('partial','Breezy visible detail identity or description missing.')
            description=descriptions[0]
        else:
            if len(jobs)!=1 or board_link(jobs[0]['url'])!=linked or text(jobs[0]['title'])!=text(e['name']):raise FetchError('partial','Breezy job detail identity mismatch.')
            description=text(jobs[0]['description'])
        row.update(title=text(e['name']),url=url,description=description,location='; '.join(text(v.get('name')) for v in e.get('locations') or [e.get('location',{})]),department=text(e.get('department')),created_at=e.get('published_date',''),compensation=text(e.get('salary')),work_arrangement='Remote' if e.get('location',{}).get('is_remote') is True else '')
    elif b.name=='SmartRecruiters':
        if str(e.get('company',{}).get('identifier','')).casefold()!=b.slug.casefold() or e.get('visibility')!='PUBLIC':raise FetchError('partial','SmartRecruiters employer scope mismatch.')
        j=js(t,'https://api.smartrecruiters.com/v1/companies/'+b.slug+'/postings/'+ident)
        if str(j['id'])!=ident or j['name']!=e['name'] or str(j['company']['identifier']).casefold()!=b.slug.casefold() or j.get('active') is not True or j.get('visibility')!='PUBLIC':raise FetchError('partial','SmartRecruiters detail is closed or mismatched.')
        linked=board_link(j['postingUrl'])
        if linked.slug.casefold()!=b.slug.casefold() or linked.ident!=ident:raise FetchError('partial','SmartRecruiters public posting URL mismatch.')
        sections=j['jobAd']['sections']
        if not text(sections.get('jobDescription',{}).get('text')):raise FetchError('partial','SmartRecruiters full description missing.')
        row.update(title=text(j['name']),url=j['postingUrl'],req_id=text(j.get('refNumber')),description='\n\n'.join(text(s.get('title'))+'\n'+text(s.get('text')) for s in sections.values() if s.get('text')),location=text(j.get('location',{}).get('fullLocation')),department=text(j.get('department',{}).get('label')),created_at=j.get('releasedDate',''),work_arrangement='Remote' if j.get('location',{}).get('remote') else ('Hybrid' if j.get('location',{}).get('hybrid') else ''))
    elif b.name=='Workable':
        if e.get('state')!='published' or e.get('isInternal') is not False:raise FetchError('partial','Workable returned an internal or unpublished job.')
        j=js(t,b.root+'/api/v2/accounts/'+b.slug+'/jobs/'+e['shortcode'])
        if str(j['id'])!=ident or j['shortcode']!=e['shortcode'] or j['title']!=e['title']:raise FetchError('partial','Workable detail identity mismatch.')
        row.update(title=text(j['title']),url=b.url+'j/'+e['shortcode']+'/',req_id=text(e.get('code')),description='\n\n'.join(text(j.get(k)) for k in ('description','requirements','benefits') if j.get(k)),location=_join_locations(e.get('locations') or [e.get('location',{})]),department='; '.join(e.get('department',[])),created_at=e.get('published',''),work_arrangement=text(e.get('workplace')))
    else:return html_posting(b,t,e,cid,company)
    if not row['title'] or not row['description']:raise FetchError('partial','Public posting lacks title or full description.')
    return row


class Links(HTMLParser):
    def __init__(self,body):
        super().__init__();self.links=[];self.canonical=[];self.containers=set();self.cur=None;self.feed(body)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        self.containers.update(a.get('class','').split())
        if tag=='a':self.cur=[a,'']
        if tag=='link' and a.get('rel')=='canonical':self.canonical.append(a.get('href',''))
    def handle_data(self,data):
        if self.cur is not None:self.cur[1]+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.cur is not None:self.links.append(self.cur);self.cur=None


class PublicMetadata(HTMLParser):
    def __init__(self):
        super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta' and a.get('property')=='og:url':self.urls.append(a.get('content',''))


def html_listing(b,t):
    body=checked(t.get(b.url),True);p=Links(body)
    marker='jobs-list' if b.name=='JazzHR' else 'jv-job-list'
    if marker not in p.containers:
        raise FetchError('partial','Public HTML board has no verified job-list container; empty inventory unproven.')
    entries={}
    for attrs,title in p.links:
        url=urljoin(b.url,attrs.get('href',''))
        try:link=board_link(url)
        except ValueError:continue
        if link.name!=b.name or link.slug!=b.slug or not link.ident:continue
        if not text(title):raise FetchError('partial','Public job link has no title.')
        entries[link.ident]={'id':link.ident,'title':text(title),'url':url}
    if any(a.get('rel')=='next' or re.search(r'\bnext\b',a.get('aria-label',''),re.I) for a,_ in p.links):
        raise FetchError('partial','Public HTML board advertises additional pages; inventory incomplete.')
    if not entries and not re.search(r'no (?:current |open )?(?:jobs|positions|openings)',body,re.I):raise FetchError('partial','Empty HTML job inventory is not explicitly established.')
    return unique(list(entries.values()))


def schema_job(data,url,ident,name,cid,company):
    if not isinstance(data.get('description'),str) or not text(data['description']).strip():raise FetchError('partial','Structured full description missing.')
    row=_base({'id':ident},name,cid,company)
    locs=data.get('jobLocation') or []
    if isinstance(locs,dict):locs=[locs]
    locations=[]
    for loc in locs:
        a=loc.get('address') or {};country=a.get('addressCountry') or ''
        if isinstance(country,dict):country=country.get('name','')
        locations.append(', '.join(str(v) for v in [a.get('addressLocality'),a.get('addressRegion'),country] if v))
    salary=data.get('baseSalary') or {};salary=salary[0] if isinstance(salary,list) and salary else salary
    pay=''
    if isinstance(salary,dict):
        value=salary.get('value') or {}
        if isinstance(value,dict):pay=' '.join(str(v) for v in [salary.get('currency'),value.get('value') or value.get('minValue'),'-' if value.get('maxValue') else None,value.get('maxValue'),value.get('unitText')] if v is not None)
    identifier=data.get('identifier') or {}
    row.update(title=text(data.get('title')),url=url,description=text(data['description']),req_id=text(identifier.get('value')) if isinstance(identifier,dict) else text(identifier),location='; '.join(locations),compensation=pay,created_at=text(data.get('datePosted')),work_arrangement='Remote' if data.get('jobLocationType')=='TELECOMMUTE' else '')
    return row


def html_posting(b,t,e,cid,company):
    body=checked(t.get(e['url']),True);p=Links(body);jobs=Scripts(body).jobs()
    if not jobs and b.name=='JazzHR':
        from .shared_extended import Elements
        descriptions=Elements(body,{'id:job-description'}).values
        headings=[text(v) for v in re.findall(r'<h2(?:\s[^>]*)?>(.*?)</h2>',body,re.S|re.I)]
        matches=any(urlsplit(u).scheme=='https' and urlsplit(u).path.rstrip('/')==urlsplit(e['url']).path.rstrip('/') for u in p.canonical)
        if len(descriptions)!=1 or not descriptions[0] or e['title'] not in headings or not matches:raise FetchError('partial','JazzHR public description, title, or canonical identity missing.')
        row=_base({'id':e['id']},b.name,cid,company)
        row.update(title=e['title'],url=e['url'],description=descriptions[0])
        for field,label in [('location','Location'),('department','Department')]:
            values=Elements(body,{'title:'+label}).values
            if len(values)==1:row[field]=values[0]
        return row
    if len(jobs)!=1:raise FetchError('partial','Job page lacks a unique structured full job description.')
    j=jobs[0]
    if text(j.get('title'))!=text(e['title']):raise FetchError('partial','Structured job title disagrees with its listing.')
    targets=[j.get('url')] if j.get('url') else p.canonical
    matching = any(urlsplit(u).scheme=='https' and urlsplit(u).path.rstrip('/')==urlsplit(e['url']).path.rstrip('/') for u in targets)
    if b.name=='Jobvite' and j.get('identifier')==e['id']:matching=True
    if not matching:raise FetchError('partial','Structured posting URL does not establish matching identity.')
    return schema_job(j,e['url'],e['id'],b.name,cid,company)


def _inventory_changes(before, after):
    """Compare stable listing identities/content, ignoring presentation order."""
    def index(entries):
        result = {}
        for entry in entries:
            if entry.get('id') is None or isinstance(entry.get('id'), bool):
                raise FetchError('partial', 'Inventory recheck has an invalid job ID.')
            ident = str(entry.get('id', ''))
            if not ident or ident in result:
                raise FetchError('partial', 'Inventory recheck has missing or duplicate job IDs.')
            result[ident] = entry
        return result
    old, new = index(before), index(after)
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    edited = sorted(k for k in old.keys() & new.keys() if old[k] != new[k])
    if not (added or removed or edited):
        return ''
    return '; '.join(f'{label} {len(values)}' + (f' (IDs: {", ".join(values[:5])})' if values else '')
                     for label, values in [('added', added), ('removed', removed), ('edited', edited)])


MAX_INVENTORY_RECONCILIATIONS = 3


def _fetch(b,t,cid,company,source,ids=None,max_jobs=MAX_JOBS):
    jobs=[]; completed={}; revisions=[]
    try:
        if b.name=='Jibe' and urlsplit(b.root).hostname.endswith('.jibeapply.com'):
            words=re.findall('[a-z0-9]+',company.casefold());initials=''.join(w[0] for w in words if w not in {'and','inc','group','the'})
            if b.slug.casefold() not in ''.join(words) and b.slug.casefold()!=initials:raise FetchError('unsupported','Shared Jibe tenant does not establish this company scope.')
        entries=listing(b,t)
        _inventory_changes(entries, entries)  # Validate IDs before fetching details.
        for attempt in range(MAX_INVENTORY_RECONCILIATIONS + 1):
            selected=entries if ids is None else [e for e in entries if str(e['id']) in ids or str(e.get('shortcode','')) in ids or any(i in e.get('url','').split('/') for i in ids)]
            partial=ids is not None and (len(selected)!=len(entries) or not ids.issubset({str(e['id']) for e in selected}|{str(e.get('shortcode','')) for e in selected}|{i for e in selected for i in e.get('url','').split('/')}))
            failures=[]
            for e in selected:
                ident=str(e['id'])
                if ident in completed:
                    continue
                if len(jobs)>=max_jobs:raise FetchError('partial',f'Bounded validation stopped at {len(jobs)} of {len(selected)} postings.')
                try:
                    completed[ident]=(e, posting(b,t,e,cid,company))
                    jobs=[record[1] for record in completed.values()]
                except FetchError as error:
                    if error.status=='blocked':raise
                    failures.append(ident+': '+error.reason)
                except (ValueError,TypeError,KeyError,AttributeError,IndexError):
                    failures.append(ident+': malformed posting data')
                print(json.dumps({'event':'inventory_page','provider':b.name,'company_id':cid,'postings_fetched':len(jobs),'total':len(selected)}),file=sys.stderr)
            current=listing(b,t)
            changes=_inventory_changes(entries,current)
            if not changes:
                reason=f'{b.name}: retrieved {len(jobs)} full postings and rechecked the public inventory.'
                if revisions:reason+=' Reconciled inventory changes: '+' | '.join(revisions)+'.'
                if failures:reason+=' '+str(len(failures))+' postings failed validation: '+'; '.join(failures[:3])+'.'
                if partial:reason+=' Employer links only a subset of its board; company scope remains partial.'
                return Inventory('partial' if partial or failures else 'complete',jobs,reason,source,b.name)
            revisions.append(changes)
            print(json.dumps({'event':'inventory_changed','provider':b.name,'company_id':cid,
                              'reconciliation':attempt+1,'changes':changes}),file=sys.stderr)
            # Keep only full details that still match the latest listing. Deleted
            # entries leave this inventory; edited/new entries need fresh details.
            current_by_id={str(e['id']):e for e in current}
            completed={ident:record for ident,record in completed.items()
                       if current_by_id.get(ident)==record[0]}
            jobs=[record[1] for record in completed.values()]
            entries=current
            if attempt==MAX_INVENTORY_RECONCILIATIONS:
                raise FetchError('partial',f'Public inventory kept changing after {MAX_INVENTORY_RECONCILIATIONS} reconciliation rounds; inventory incomplete.')
    except FetchError as e:
        reason=e.reason+(' Observed inventory changes: '+' | '.join(revisions)+'.' if revisions else '')
        return Inventory('blocked' if e.status=='blocked' else 'partial',jobs,reason,source,b.name)
    except Exception as e:return Inventory('partial',jobs,f'Public board data/transport failed validation ({type(e).__name__}); inventory incomplete.',source,b.name)


def fetch_shared(ats,url,cid,company,transport=None,pages=None,max_jobs=MAX_JOBS):
    # Unknown discovery is not a provider and says nothing about parent scope.
    # Persisting "Shared ATS" here makes subsequent runs treat it as a scope
    # restriction. Report an ATS only once a board has actually been resolved.
    name=''
    try:
        direct=known_host(urlsplit(url).hostname)
        if direct:
            b=board_link(url);name=b.name
            if b.ident:raise FetchError('unsupported','A single job link cannot establish the full employer inventory.')
            ids=None
        else:b,ids=discover(url,pages or CareersTransport());name=b.name
        if any(k in ats.casefold() for k in ('shared','parent')) and ids is None:raise FetchError('unsupported','Parent board requires a company-specific job scope.')
        if b.name=='TalentBrew':return Inventory('blocked',reason='TalentBrew public inventory requires its browser pagination adapter.',source_url=url,ats=b.name)
        result=_fetch(b,transport or Transport(b),cid,company,url if ids is not None else b.url,ids,max_jobs)
        if not direct and result.status=='complete' and discover(url,pages or CareersTransport())!=(b,ids):
            result.status='partial';result.reason+=' Employer board links changed during the scan.'
        return result
    except FetchError as e:return Inventory(e.status,reason=e.reason,source_url=url,ats=name)
    except (ValueError,TypeError,KeyError,AttributeError,OSError):return Inventory('unsupported',reason='Unsupported shared-board URL or employer scope.',source_url=url,ats=name)


class BrowserTransport:
    """Use a normal anonymous browser only for the same pinned public routes."""
    def __init__(self,b,context):
        self.board=b;self.context=context;self.page=context.new_page();self.last=0.;self.public_headers={}
        if b.name=='Dayforce':
            def observe(request):
                if request.url==b.root+'/api/geo/'+b.slug.split('/')[0]+'/jobposting/search':
                    value=request.headers.get('x-csrf-token')
                    if value:self.public_headers={'x-csrf-token':value}
            self.page.on('request',observe)
        if b.name in {'Dayforce','Workable'}:
            r=self.page.goto(b.url,wait_until='networkidle',timeout=30000)
            if not r or r.status!=200:raise FetchError('blocked','Public board did not grant normal browser access.')
    def request(self,url,payload=None):
        if not allowed(self.board,url,payload):raise FetchError('unsupported','Browser request is outside the pinned public board.')
        time.sleep(max(0,.4-(time.monotonic()-self.last)));self.last=time.monotonic()
        if self.board.name=='Paycor Recruiting':
            from html import escape
            self.page.set_content('<iframe src="'+escape(url,quote=True)+'"></iframe>')
            frame=self.page.locator('iframe').element_handle().content_frame()
            frame.wait_for_load_state('networkidle',timeout=30000)
            if urlsplit(frame.url).hostname!=urlsplit(url).hostname:return HTTPResponse(302,b'')
            return HTTPResponse(200,frame.content().encode())
        is_json=('/core/jobs/' in url or '/api/' in url or url.endswith(('/json','/postings.json')))
        if is_json:
            r=self.context.request.post(url,data=payload,headers=self.public_headers,timeout=30000,max_redirects=0) if payload is not None else self.context.request.get(url,timeout=30000,max_redirects=0)
            try:return HTTPResponse(r.status,r.body(),r.headers)
            finally:r.dispose()
        r=self.page.goto(url,wait_until='domcontentloaded',timeout=30000)
        if not r:return HTTPResponse(503,b'')
        if urlsplit(self.page.url).hostname!=urlsplit(url).hostname:return HTTPResponse(302,b'')
        return HTTPResponse(r.status,self.page.content().encode(),r.headers)
    def get(self,url):return self.request(url)
    def post(self,url,payload):return self.request(url,payload)


class RenderedPages:
    """Read an employer's rendered public links; never operate account controls."""
    def __init__(self,context):self.context=context
    def get(self,url):
        from html import escape
        public_careers_url(url)
        page=self.context.new_page()
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=30000)
            try:page.wait_for_load_state('networkidle',timeout=5000)
            except Exception:pass
            if not response:return HTTPResponse(503,b'')
            final=page.url
            if not _same_public_host(url,final):return HTTPResponse(302,b'',{'Location':final})
            body=page.content()
            # Browser-created frames are actual embedded boards, unlike unused
            # script strings or commented-out provider integrations.
            for frame in page.frames[1:]:
                p=urlsplit(frame.url)
                if known_host(p.hostname):
                    target=frame.url
                    if p.hostname in {'www.comeet.com','www.comeet.co'}:
                        q=dict(parse_qsl(p.query))
                        if not any(k in q for k in ('department','location','position-uid','position-slug')):target=p._replace(query='',fragment='').geturl()
                    body+='<a href="'+escape(target,quote=True)+'"></a>'
            return HTTPResponse(response.status,body.encode(),response.headers)
        finally:page.close()


def fetch_shared_browser(ats,url,cid,company,max_jobs=MAX_JOBS,*,progress_factory=None):
    name=''
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True)
            try:
                context=browser.new_context();pages=RenderedPages(context)
                if known_host(urlsplit(url).hostname):
                    b=board_link(url);ids=None
                    if b.ident:raise FetchError('unsupported','Individual job source cannot establish full inventory.')
                else:b,ids=discover(url,pages)
                name=b.name
                if any(v in ats.casefold() for v in ('parent','shared')) and ids is None:raise FetchError('unsupported','Parent scope is not verified.')
                if b.name=='TalentBrew':
                    from .talentbrew import scan
                    return scan(b,context,cid,company,max_jobs,progress=progress_factory(b.url) if progress_factory is not None else None)
                result=_fetch(b,BrowserTransport(b,context),cid,company,url if ids else b.url,ids,max_jobs)
                if not known_host(urlsplit(url).hostname) and result.status=='complete' and discover(url,pages)!=(b,ids):result.status='partial';result.reason+=' Employer scope changed.'
                return result
            finally:browser.close()
    except FetchError as e:return Inventory(e.status,reason=e.reason,source_url=url,ats=name)
    except Exception as e:return Inventory('partial',reason=f'Public browser inventory failed ({type(e).__name__}).',source_url=url,ats=name)


def embedded_boards(body,url):
    body=re.sub(r'<!--.*?-->','',body,flags=re.S)
    p=_BoardLinks(url);p.feed(body)
    if any(urlsplit(urljoin(url,v)).hostname=='tbcdn.talentbrew.com' for v in p.links):
        source=urlsplit(url);paths={urlsplit(urljoin(url,v)).path for v in p.links if urlsplit(urljoin(url,v)).hostname==source.hostname and re.fullmatch(r'/(?:[a-z]{2}/)?search-jobs',urlsplit(urljoin(url,v)).path) and not urlsplit(urljoin(url,v)).query}
        if re.fullmatch(r'/(?:[a-z]{2}/)?search-jobs',source.path) and not source.query:paths={source.path}
        if len(paths)==1 and not source.query:return [Board('TalentBrew','https://'+source.hostname,source.hostname,paths.pop())]
    if any(urlsplit(urljoin(url,v)).hostname=='app.jibecdn.com' for v in p.links):
        source=urlsplit(url)
        if source.query:raise FetchError('unsupported','Filtered Jibe employer source cannot be expanded.')
        return [Board('Jibe','https://'+source.hostname,source.hostname,'/jobs')]
    boards=[]
    for target in PublicSearchForms(body).links:
        try:
            b=board_link(urljoin(url,target))
            if not b.ident:boards.append(b)
        except ValueError:pass
    for match in re.finditer(r'COMEET\.init\s*\(\s*(\{[^}]+\})',body):
        config=match[1]
        uid=re.search(r'["\']company-uid["\']\s*:\s*["\']([A-Za-z0-9.]+)',config)
        slug=re.search(r'["\']company-name["\']\s*:\s*["\']([A-Za-z0-9_-]+)',config)
        if uid and slug and not re.search(r'["\'](?:position-uid|department|location)["\']\s*:',config):boards.append(board_link('https://www.comeet.com/jobs/'+slug[1]+'/'+uid[1]))
    return list(dict.fromkeys(boards))

class PublicSearchForms(HTMLParser):
    """Only unfiltered search forms establish a whole public employer board."""
    def __init__(self,body):super().__init__();self.current=None;self.links=[];self.feed(body)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.current=[a.get('action',''),a.get('method','get').lower()!='get']
        elif self.current is not None:
            if tag=='input' and a.get('value','') and a.get('type','text') not in {'submit','button','reset'}:self.current[1]=True
            if tag=='option' and 'selected' in a and a.get('value',''):self.current[1]=True
    def handle_endtag(self,tag):
        if tag=='form' and self.current is not None:
            if not self.current[1]:self.links.append(self.current[0])
            self.current=None
