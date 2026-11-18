"""Independent stdlib parsing; never imports the adapter's selectors/parsers."""
from html.parser import HTMLParser
from html import unescape
import json,re,hashlib
from urllib.parse import urljoin,urlsplit,parse_qsl
from urllib.request import Request,build_opener,HTTPRedirectHandler

from independent_samtec_detail import detail_evidence

BASE='https://jobs.jobvite.com/samtec/search'
class Page(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.anchor=None;self.scripts=[];self.script=None;self.words=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a':self.anchor=[a,'']
        if tag=='script' and a.get('type')=='application/ld+json':self.script=''
    def handle_data(self,data):
        self.words.append(data)
        if self.anchor is not None:self.anchor[1]+=data
        if self.script is not None:self.script+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor is not None:self.links.append(self.anchor);self.anchor=None
        if tag=='script' and self.script is not None:self.scripts.append(self.script);self.script=None

def normalized(value):
    # Compare complete description words, independent of presentation whitespace.
    return ' '.join(unescape(re.sub(r'<[^>]*>',' ',value)).split())

def listing_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.netloc!='jobs.jobvite.com' or p.path.rstrip('/')!='/samtec/search' or p.fragment:
        raise ValueError('Unapproved pagination URL')
    q=parse_qsl(p.query,keep_blank_values=True)
    if q and (len(q)!=1 or q[0][0]!='p' or not q[0][1].isdigit() or int(q[0][1])>20):
        raise ValueError('Filtered or unbounded pagination URL')
    return url

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args):raise ValueError('Independent listing redirected; review source')

def reconcile(output, report):
    opener=build_opener(NoRedirect()); queue=[BASE];seen=set();ids=set();declared=set();pages=[]
    while queue:
        url=listing_url(queue.pop(0))
        if url in seen:continue
        if len(seen)>=20:raise ValueError('Pagination exceeds independent bound')
        seen.add(url)
        with opener.open(Request(url,headers={'User-Agent':'WrapperValidation/1.0'}),timeout=25) as response:
            if response.status!=200:raise ValueError('Independent listing not HTTP200')
            body=response.read(2000001)
        if len(body)>2000000:raise ValueError('Oversized listing')
        path=output/f'independent-listing-{len(pages)+1}.html';path.write_bytes(body)
        p=Page();p.feed(body.decode('utf8'))
        text=' '.join(p.words)
        if 'Samtec' not in text:raise ValueError('Missing public company identity')
        totals=re.findall(r'\b\d+\s*[-–]\s*\d+\s+of\s+(\d+)\b',text)
        declared.update(map(int,totals))
        pageids=set()
        for a,title in p.links:
            target=urljoin(url,a.get('href',''));u=urlsplit(target)
            match=re.fullmatch(r'/samtec/job/([A-Za-z0-9]+)',u.path)
            if u.scheme=='https' and u.netloc=='jobs.jobvite.com' and match and not u.query:
                pageids.add(match[1])
            if 'jv-pagination-next' in a.get('class','').split() or a.get('rel')=='next':queue.append(listing_url(target))
        if not pageids:raise ValueError('No job identities on independently fetched search page')
        ids.update(pageids);pages.append({'url':url,'file':path.name,'jobs':len(pageids),'sha256':hashlib.sha256(body).hexdigest()})
    if len(declared)!=1 or next(iter(declared))!=len(ids):raise ValueError('Listing declared total and unique IDs disagree')
    details=[]
    for number in (1,2):
        inventory=json.loads((output/f'inventory-{number}.json').read_text());jobs=inventory['jobs']
        returned={str(j['posting_id']) for j in jobs}
        if returned!=ids:raise ValueError(f'Pass {number} differs from all public search pages')
        requests={r['url']:r for r in report['requests'] if r['pass']==number and r.get('status')==200}
        for job in jobs:
            request=requests.get(job['url'])
            if request is None:raise ValueError('No fresh detail HTTP200 receipt for returned job')
            body=(output/request['body_file']).read_bytes()
            if hashlib.sha256(body).hexdigest()!=request['body_sha256']:raise ValueError('Detail evidence hash changed')
            evidence=detail_evidence(body.decode('utf8'),job['url'])
            if ' '.join(evidence['description'].split())!=' '.join(job['description'].split()):raise ValueError('Full description differs from public HTML detail')
            if ' '.join(evidence['title'].split())!=' '.join(job['title'].split()):raise ValueError('Title differs from public HTML detail')
            if ' '.join(evidence['location'].split())!=' '.join(job.get('location','').split()):raise ValueError('Location differs from public HTML detail')
            if ' '.join(evidence['department'].split())!=' '.join(job.get('department','').split()):raise ValueError('Department differs from public HTML detail')
        details.append({'pass':number,'full_descriptions_matched':len(jobs),'public_ids_matched':True})
    return {'ok':True,'public_total':len(ids),'listing_pages':pages,'detail_checks':details,
            'scope':'All public Samtec postings, before candidate-specific filtering; no publication.'}
