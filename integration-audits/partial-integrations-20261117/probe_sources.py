"""Bounded public GET evidence only. No login, scraper run, or database writes.

One request per selected source plus at most five public HTTPS redirects. No
retries/challenge handling. Saves metadata and candidate links, not job bodies.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import hashlib
import ipaddress
import json
import re
import socket
import sys
import traceback
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

OUT = Path(__file__).resolve().parent
ROOT = Path('/home/chris/job-search-helper_old')
sys.path.insert(0, str(ROOT/'src'))
from job_search_helper.ats import HTTPResponse, _safe_api_url
from job_search_helper.shared_boards import board_link, listing, Scripts, known_host

def validate(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('Non-public HTTPS destination rejected')
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)):
        raise ValueError('Non-public address rejected')

class Redirects(HTTPRedirectHandler):
    def __init__(self): self.chain=[]
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        self.chain.append({'status':code,'from':req.full_url,'to':newurl})
        if len(self.chain)>5: raise ValueError('Redirect budget exceeded')
        validate(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

class Links(HTMLParser):
    def __init__(self): super().__init__(); self.urls=[]; self.title=[]; self.in_title=False
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='title': self.in_title=True
        if tag in {'a','iframe','script'}:
            for k in ('href','src'):
                if attrs.get(k): self.urls.append(attrs[k])
    def handle_endtag(self,tag):
        if tag=='title': self.in_title=False
    def handle_data(self,data):
        if self.in_title: self.title.append(data)

PROVIDER = re.compile(r'greenhouse|lever\.co|ashbyhq|workday|myworkdayjobs|smartrecruiters|rippling|icims|oraclecloud|phenom|talentbrew|successfactors|jobvite|teamtailor|paylocity|bamboohr|workable|eightfold|avature|recruiting2\.ultipro|dayforce|adp\.com|brassring|taleo|jobscore|pinpoint|breezy|clearcompany|jibeapply|applytojob|applicantpro|isolvedhire|hrmdirect|comeet|recruitee|recruiterbox|trakstar|silkroad|jobboardhq|saashr',re.I)

SPECIAL = {
 'rippling-forterra':'https://ats.rippling.com/forterra/jobs',
 'rippling-droneup':'https://ats.rippling.com/droneup/jobs',
 'hughes-api':'https://jobs.echostar.com/api/jobs?tags4=Hughes&page=1',
 'asti-page':'https://www.asti-usa.com/jobs/positions.html',
 'massvirtual-feed':'https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/2df5ac23-47b5-4c64-b536-e7f04caf6ffe',
 'blackriver-page':'https://www.blackriversystems.com/job-opportunities/',
 'freefly-page':'https://freeflysystems.com/careers/open',
 'aitech-page':'https://aitechsystems.com/careers/',
 'jr-page':'https://careers.hitachi.com/jobs?filter%5Bbrand%5D%5B0%5D=JR%20Automation',
 'caterpillar-page':'https://www.caterpillar.com/en/careers.html',
 'samtec-page':'https://jobs.jobvite.com/samtec/jobs',
 'arm-page':'https://careers.arm.com/search-jobs',
}

def inspect(key,url):
    record={'key':key,'requested_url':url,'checked_at':datetime.now(timezone.utc).isoformat()}
    redirects=Redirects()
    try:
        validate(url)
        try: response=build_opener(redirects).open(Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; JobSourceAudit/1.0)','Accept':'text/html,application/json;q=0.9,*/*;q=0.5'}),timeout=18)
        except HTTPError as e: response=e
        with response:
            body=response.read(4_000_001)
            record.update(status=response.status,final_url=response.geturl(),content_type=response.headers.get('Content-Type',''),bytes=len(body),truncated=len(body)>4_000_000,sha256=hashlib.sha256(body).hexdigest())
        if len(body)>4_000_000: body=body[:4_000_000]
        raw=body.decode('utf-8','replace')
        parser=Links(); parser.feed(raw)
        urls={urljoin(record['final_url'],v) for v in parser.urls}
        urls={v for v in urls if v.startswith('https://')}
        # Inspect embedded plain public URLs too; these are candidates, not verified scopes.
        urls.update(re.findall(r'https://[^\s<>"\x27\\]+',raw))
        record['title']=' '.join(parser.title).strip()[:240]
        record['ats_candidates']=sorted(v for v in urls if PROVIDER.search(v))[:50]
        record['career_links']=sorted(v for v in urls if urlsplit(v).hostname==urlsplit(record['final_url']).hostname and re.search(r'career|job|vacanc|position|opportunit',urlsplit(v).path,re.I))[:30]
        record['provider_markers']=sorted(set(x.lower() for x in PROVIDER.findall(raw)))
        if 'json' in record['content_type']:
            try:
                data=json.loads(raw)
                record['json_shape']={'type':type(data).__name__,'keys':sorted(data)[:30] if isinstance(data,dict) else [],'counts':{k:len(v) for k,v in data.items() if isinstance(v,list)} if isinstance(data,dict) else {}}
                if isinstance(data,dict): record['json_totals']={k:v for k,v in data.items() if isinstance(v,(int,float)) or k in {'totalCount','total','totalItems'}}
            except ValueError: record['json_error']='invalid JSON'
        if key.startswith('rippling-') and record['status']==200:
            state=Scripts(raw).next()
            queries=[q for q in state['dehydratedState']['queries'] if q.get('queryKey',[])[:3]==['board',urlsplit(url).path.split('/')[1],'job-posts']]
            record['rippling_query_keys']=[q.get('queryKey') for q in queries]
            record['rippling_data_shape']=[{'type':type(q['state']['data']).__name__,'keys':list(q['state']['data']) if isinstance(q['state']['data'],dict) else []} for q in queries]
            class Replay:
                calls=0
                def get(self,u):
                    self.calls+=1
                    if self.calls>1: raise RuntimeError('Audit one-page replay budget reached')
                    return HTTPResponse(record['status'],body,{'Content-Type':record['content_type']})
            try: record['listing_replay_count']=len(listing(board_link(url),Replay()))
            except Exception: record['listing_replay_traceback']=traceback.format_exc()
        if key in {'hughes-api','asti-page','massvirtual-feed'}:
            try: _safe_api_url(url); record['production_api_guard']='accepted'
            except Exception as e: record['production_api_guard']=str(e)
    except Exception as e:
        record['error']=type(e).__name__+': '+str(e)
    record['redirects']=redirects.chain
    return record

def main():
    snapshot=json.loads((OUT/'snapshot.json').read_text())
    selected={c['company_id']:c['source_url'] or c['configured_url'] for c in snapshot['companies'] if c['category'].startswith(('C1','C2','C3'))}
    selected.update(SPECIAL)
    records=[]
    # Deduplicate shared exact sources; record aliases for company-level register.
    byurl={}
    for key,url in selected.items(): byurl.setdefault(url,[]).append(key)
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks={pool.submit(inspect,keys[0],url):keys for url,keys in byurl.items()}
        for future in as_completed(tasks):
            r=future.result(); r['aliases']=tasks[future]; records.append(r)
            (OUT/'public-source-probes.json').write_text(json.dumps(sorted(records,key=lambda v:v['key']),indent=2,ensure_ascii=False)+'\n')
            print(r['key'],r.get('status',r.get('error')),len(r.get('ats_candidates',[])),flush=True)
    print('Completed',len(records),'unique public sources',flush=True)

if __name__=='__main__': main()
