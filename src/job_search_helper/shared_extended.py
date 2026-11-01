"""Shared public feeds for Dayforce, Comeet, ClearCompany and ApplicantPro."""
import json,re
from html.parser import HTMLParser
from urllib.parse import urlsplit,urljoin,parse_qsl,urlencode
from .shared_boards import checked,js,unique,Links,Scripts,board_link,schema_job
from .ats import FetchError,_base,text

class Elements(HTMLParser):
    def __init__(self,body,classes):
        super().__init__();self.classes=set(classes);self.depth=0;self.parts=[];self.values=[];self.feed(body)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if self.depth:self.depth+=tag not in {'br','hr','img','input','meta','link'};self.parts.append(self.get_starttag_text())
        elif self.classes.intersection(a.get('class','').split()) or 'itemprop:'+a.get('itemprop','') in self.classes or 'id:'+a.get('id','') in self.classes or 'title:'+a.get('title','') in self.classes:self.depth=1;self.parts=[]
    def handle_data(self,d):
        if self.depth:self.parts.append(d)
    def handle_endtag(self,tag):
        if tag in {'br','hr','img','input','meta','link'}:return
        if self.depth:
            self.depth-=1
            if not self.depth:self.values.append(text(''.join(self.parts)))
            else:self.parts.append('</'+tag+'>')

def assignment(body,name):
    matches=list(re.finditer(r'\b'+re.escape(name)+r'\s*=\s*(?=[{\[])',body))
    if len(matches)!=1:raise FetchError('partial','Public board bootstrap state missing or ambiguous.')
    return json.JSONDecoder().raw_decode(body[matches[0].end():])[0]

def listing_extended(b,t):
    if b.name=='Jibe':
        out=[];total=None;client=None
        for page in range(1,101):
            d=js(t,b.root+'/api/jobs?page='+str(page)+'&limit=100');n=d['totalCount'];es=[v['data'] for v in d['jobs']]
            if type(n) is not int or not 0<=n<=10000 or d.get('count',0 if n==0 else None)!=n or (total is not None and total!=n) or len(es)!=min(100,n-len(out)):raise FetchError('partial','Jibe inventory counts or pagination changed.')
            total=n
            for e in es:
                if client is None:client=e['client_code']
                if client!=e['client_code'] or e.get('internal') is True or e.get('searchable') is not True:raise FetchError('partial','Jibe job employer or public scope mismatch.')
                out.append(dict(e,id=str(e['slug'])))
            if len(out)==n:return unique(out)
        raise FetchError('partial','Jibe page bound reached.')
    if b.name=='ClearCompany' and b.root=='https://careers-api.clearcompany.com':
        out=[];total=None
        for page in range(400):
            d=js(t,b.url+'?pageIndex='+str(page)+'&pageSize=25&source=CJB-0');n=d['totalCount'];entries=d['results']
            if type(n) is not int or not 0<=n<=10000 or (total is not None and n!=total) or d['currentPageIndex']!=page or d['currentPageCount']!=len(entries) or len(entries)!=min(25,n-page*25):raise FetchError('partial','ClearCompany pagination changed or is incomplete.')
            total=n;out.extend(entries)
            if len(out)==n:return unique(out)
        raise FetchError('partial','ClearCompany page bound reached.')
    if b.name=='Dayforce':
        tenant,code=b.slug.split('/');out=[];total=None;start=0
        for _ in range(500):
            d=js(t,b.root+'/api/geo/'+tenant+'/jobposting/search',{'clientNamespace':tenant,'jobBoardCode':code,'cultureCode':'en-US','distanceUnit':0,'paginationStart':start})
            n=d['maxCount'];entries=d['jobPostings']
            if type(n) is not int or not 0<=n<=10000 or (total is not None and n!=total) or d['offset']!=start or d['count']!=len(entries):raise FetchError('partial','Dayforce count or offset changed.')
            total=n
            for e in entries:
                if e['clientNamespace']!=tenant:raise FetchError('partial','Dayforce tenant mismatch.')
                out.append(dict(e,id=str(e['jobPostingId'])))
            start+=len(entries)
            if start==n:return unique(out)
            if not entries or start>n:raise FetchError('partial','Dayforce inventory is truncated.')
        raise FetchError('partial','Dayforce page bound reached.')
    body=checked(t.get(b.url),True)
    if b.name=='Comeet':
        company=assignment(body,'COMPANY_DATA');entries=assignment(body,'COMPANY_POSITIONS_DATA')
        if company['company_uid']!=b.slug.split('/')[1] or not isinstance(entries,list):raise FetchError('partial','Comeet employer identity mismatch.')
        return unique([dict(e,id=e['uid']) for e in entries])
    if b.name=='ApplicantPro':
        # Domain ID is published in the employer's own board bootstrap.
        ids=set(re.findall(r'["\']domain_id["\']\s*:\s*["\']?([0-9]+)',body))
        if len(ids)!=1:raise FetchError('partial','ApplicantPro public domain identity missing.')
        domain=ids.pop();params={'cityUrl':'','countryAbbreviation':'','stateAbbreviation':'','isInternal':0}
        d=js(t,b.root+'/core/jobs/'+domain+'?'+urlencode({'getParams':json.dumps(params,separators=(',',':'))}))
        if d.get('success') is not True:raise FetchError('partial','ApplicantPro listing rejected.')
        data=d['data'];entries=data['jobs']
        if type(data['jobCount']) is not int or len(entries)!=data['jobCount']:raise FetchError('partial','ApplicantPro inventory is paginated or incomplete.')
        # Field mapping is verified against live public cards before accepting jobs.
        return unique([dict(e,id=str(e['id'])) for e in entries])
    if b.name in {'Paycor Recruiting','isolved'}:
        marker='gnewtonCareerHome' if b.name=='Paycor Recruiting' else 'job-listings'
        if marker not in body:raise FetchError('partial','Public listing container missing.')
        entries={}
        for a,title in Links(body).links:
            u=urljoin(b.url,a.get('href',''));p=urlsplit(u);q=dict(parse_qsl(p.query))
            if p.hostname!=urlsplit(b.root).hostname:continue
            if b.name=='Paycor Recruiting':
                if p.path!='/career/JobIntroduction.action' or q.get('clientId')!=b.slug or not re.fullmatch('[a-f0-9]{32}',q.get('id','')):continue
                ident=q['id'];u=b.root+p.path+'?'+urlencode({'clientId':b.slug,'id':ident,'lang':'en'})
            else:
                m=re.fullmatch(re.escape(b.path.rstrip('/'))+r'/([0-9]+)\.html',p.path)
                if not m:continue
                ident=m[1]
            entries[ident]={'id':ident,'title':(next((v.strip() for v in title.splitlines() if v.strip()),'') if b.name=='isolved' else text(title)),'url':u}
        if not entries:
            if b.name == 'isolved' and re.search(r'no current job openings|no job openings', body, re.I):
                return []
            raise FetchError('partial','Empty HTML inventory requires explicit provider evidence.')
        return unique(list(entries.values()))
    # ClearCompany's legacy public table has no asynchronous/paged job results.
    if not re.search(r'<(?:table|div)[^>]+(?:reqResult|jobListings|jobListingsTable|reqSearch)',body,re.I):
        raise FetchError('partial','ClearCompany full listing container is missing.')
    links=Links(body);entries={}
    for a,title in links.links:
        p=urlsplit(urljoin(b.url,a.get('href','')));q=dict(parse_qsl(p.query))
        if p.hostname!=urlsplit(b.root).hostname or p.path!='/employment/job-opening.php' or not q.get('req','').isdigit():continue
        params={'req':q['req']}
        if q.get('req_loc','').isdigit():params['req_loc']=q['req_loc']
        ident=q['req']+(':'+q['req_loc'] if 'req_loc' in params else '')
        entries[ident]={'id':ident,'title':text(title),'url':b.root+p.path+'?'+urlencode(params)}
    if not entries and not re.search(r'id=["\']noOpeningsMsg',body):raise FetchError('partial','ClearCompany empty inventory is not established.')
    if any(a.get('rel')=='next' for a,_ in links.links):raise FetchError('partial','ClearCompany pagination needs verification.')
    return unique(list(entries.values()))

def posting_extended(b,t,e,cid,company):
    row=_base({'id':e['id']},b.name,cid,company)
    if b.name=='Jibe':
        row.update(title=text(e['title']),description='\n\n'.join(text(e.get(k)) for k in ['description','responsibilities','qualifications'] if e.get(k)),url=b.root+'/jobs/'+e['id'],req_id=text(e.get('req_id')),location=text(e.get('full_location')),department=text(e.get('department')),created_at=e.get('posted_date',''),compensation=' '.join(str(e.get(k) or '') for k in ['salary_value','salary_min_value','salary_max_value']).strip())
    elif b.name=='ClearCompany' and b.root=='https://careers-api.clearcompany.com':
        url=e['applyLink'];p=urlsplit(url)
        if p.scheme!='https' or not ((p.hostname=='apply.hrmdirect.com' and p.path=='/resumedirect/ApplyOnline/Apply.aspx') or (re.fullmatch(r'[a-z0-9-]+\.clearcompany\.com',p.hostname or '') and p.path=='/careers/jobs/'+e['id']+'/apply')):raise FetchError('partial','ClearCompany public posting identity changed.')
        row.update(title=text(e['positionTitle']),description=text(e['description']),url=url,req_id=text(e.get('userDefinedId')),location=text(e.get('location')),department=text(e.get('departmentName')),created_at=e.get('postedDate',''),compensation=' '.join(str(e.get(k) or '') for k in ['salaryRangeLow','salaryRangeHigh','salaryType']).strip())
    elif b.name=='Dayforce':
        row.update(title=text(e['jobTitle']),description=text(e['jobDescription']),url=b.url+'/jobs/'+e['id'],req_id=str(e['jobReqId']),location='; '.join(v['formattedAddress'] for v in e['postingLocations']),created_at=e.get('postingStartTimestampUTC',''))
    elif b.name=='Comeet':
        if e.get('is_internal') is not False:raise FetchError('partial','Comeet returned an internal posting.')
        linked=board_link(e['url_comeet_hosted_page'])
        if linked.slug.casefold()!=b.slug.casefold() or linked.ident!=e['id']:raise FetchError('partial','Comeet posting scope mismatch.')
        details=e['custom_fields']['details']
        row.update(title=text(e['name']),description='\n\n'.join(text(d['name'])+'\n'+text(d['value']) for d in details if d.get('value')),url=e['url_comeet_hosted_page'],req_id=text(e.get('internal_use_custom_id')),location=text(e['location']['name']),department=text(e.get('department')),updated_at=e.get('time_updated',''),work_arrangement=text(e.get('workplace_type')))
    elif b.name=='ClearCompany':
        body=checked(t.get(e['url']),True);descs=Elements(body,{'jobDesc'}).values
        if len(descs)!=1 or not descs[0] or e['title'] not in text(body):raise FetchError('partial','ClearCompany detail identity or description missing.')
        row.update(title=e['title'],description=descs[0],url=e['url'],req_id=e['id'].split(':')[0])
    elif b.name in {'ApplicantPro','isolved'}:
        url=e.get('jobUrl') or e['url'];p=urlsplit(url)
        if p.hostname!=urlsplit(b.root).hostname or not re.search(r'/'+re.escape(str(e['id']))+r'(?:\.html)?$',p.path):raise FetchError('partial','ApplicantPro employer or job identity mismatch.')
        body=checked(t.get(url),True);jobs=Scripts(body).jobs()
        if b.name=='isolved' and not jobs:
            descs=Elements(body,{'itemprop:description'}).values
            if len(descs)!=1 or not descs[0] or 'schema.org/JobPosting' not in body:raise FetchError('partial','isolved public full job description missing.')
            row.update(title=e['title'],url=url,description=descs[0]);return row
        if len(jobs)!=1 or not text(jobs[0].get('title')) or (b.name=='ApplicantPro' and text(jobs[0]['title'])!=text(e['title'])):raise FetchError('partial','ApplicantPro structured job details missing or mismatched.')
        if urlsplit(jobs[0].get('url','')).hostname!=p.hostname or not re.search(r'/'+re.escape(str(e['id']))+r'(?:\.html)?$',urlsplit(jobs[0].get('url','')).path):raise FetchError('partial','ApplicantPro detail ID mismatch.')
        return schema_job(jobs[0],url,e['id'],b.name,cid,company)
    else:
        body=checked(t.get(e['url']),True);jobs=Scripts(body).jobs()
        if len(jobs)==1 and text(jobs[0].get('title'))==e['title']:return schema_job(jobs[0],e['url'],e['id'],b.name,cid,company)
        descs=Elements(body,{'id:gnewtonJobDescriptionText'}).values
        if len(descs)!=1 or e['title'] not in text(body):raise FetchError('partial','Paycor full job description or title missing.')
        row.update(title=e['title'],url=e['url'],description=descs[0])
    if not row['title'] or not row['description']:raise FetchError('partial','Full title and description are required.')
    return row
