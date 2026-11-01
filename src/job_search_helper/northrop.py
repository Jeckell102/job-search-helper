"""Northrop Grumman's official public Eightfold board (browser session).

The corporate /careers page links to jobs.northropgrumman.com; its Sitecore
navigation records are not jobs. Read only the observed public search/detail
routes on the jobs host, with count/ID checks and no account actions.
"""
from datetime import datetime, timezone
import json
import re
import sys
import time
from urllib.parse import parse_qsl, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, MAX_RESPONSE_BYTES, _base, _challenge, text

ROOT = 'https://jobs.northropgrumman.com'
BOARD = ROOT + '/careers'
MAX_JOBS = 10000
COMPANY_ID = 'COMP-0075'
COMPANY = 'Northrop Grumman'


def supports_northrop(url):
    try:
        return urlsplit(url).hostname in {'www.northropgrumman.com', 'northropgrumman.com', 'jobs.northropgrumman.com'}
    except ValueError:
        return False


def _source(url):
    p = urlsplit(url)
    if (not supports_northrop(url) or p.scheme != 'https' or p.username or p.password
            or p.port not in (None, 443) or p.path.rstrip('/') != '/careers' or p.fragment
            or '\\' in url or any(ord(c) <= 32 for c in url)
            or any(not k.startswith('utm_') for k,v in parse_qsl(p.query, keep_blank_values=True))):
        raise FetchError('unsupported', 'Northrop requires an unfiltered official careers board; configured filters are not discarded.')
    return BOARD


def _search_path(start):
    return f'/api/pcsx/search?domain=ngc.com&query=&location=&start={start}&'


def _detail_path(ident):
    return f'/api/pcsx/position_details?position_id={ident}&domain=ngc.com&hl=en'


class BrowserClient:
    def __init__(self, context):
        self.context, self.last = context, 0.

    def get(self, path):
        if not (re.fullmatch(r'/api/pcsx/search\?domain=ngc\.com&query=&location=&start=[0-9]+&',path)
                or re.fullmatch(r'/api/pcsx/position_details\?position_id=[1-9][0-9]{0,15}&domain=ngc\.com&hl=en',path)):
            raise FetchError('unsupported', 'Northrop transport allows only public inventory and detail routes.')
        time.sleep(max(0., .4 - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        response = self.context.request.get(ROOT + path, timeout=30000, max_redirects=0)
        try:
            return HTTPResponse(response.status, response.body(), response.headers)
        finally:
            response.dispose()


def _data(client, path):
    r = client.get(path)
    if r.status in (401,403) or _challenge(r):
        raise FetchError('blocked', 'Northrop jobs board denied access or requires human verification.')
    if r.status != 200 or len(r.body) > MAX_RESPONSE_BYTES:
        raise FetchError('partial', f'Northrop public response was incomplete (HTTP {r.status}).')
    x = json.loads(r.body)
    if x.get('status') != 200 or not isinstance(x.get('data'),dict) or (x.get('error') or {}).get('message'):
        raise FetchError('partial', 'Northrop public job response has missing data or reports an error.')
    return x['data']


def _identity(entry):
    if (not isinstance(entry,dict) or type(entry.get('id')) is not int or not 0 < entry['id'] < 10**16
            or not isinstance(entry.get('name'),str) or not entry['name'].strip()
            or not re.fullmatch(r'R[0-9]+',str(entry.get('displayJobId','')))
            or entry.get('positionUrl') != f"/careers/job/{entry['id']}"):
        raise FetchError('partial','Northrop record lacks a verified job identity; navigation records are excluded.')
    return str(entry['id'])


def _page(client, start, expected=None):
    data = _data(client, _search_path(start))
    entries, count = data.get('positions'), data.get('count')
    if (type(count) is not int or not 0 <= count <= MAX_JOBS or not isinstance(entries,list)
            or len(entries) != min(10,max(0,count-start)) or data.get('appliedFilters') != {}
            or data.get('sortBy') != 'timestamp' or (expected is not None and count != expected)):
        raise FetchError('partial', 'Northrop listing count, pagination, or scope changed; inventory incomplete.')
    for entry in entries:
        _identity(entry)
    return entries, count


def _timestamp(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat() if type(value) in (int,float) else ''


def _posting(client, entry, company_id, company):
    ident = _identity(entry)
    job = _data(client, _detail_path(ident))
    if (_identity(job) != ident or job.get('displayJobId') != entry['displayJobId']
            or job.get('name') != entry['name'] or job.get('publicUrl') != ROOT + entry['positionUrl']
            or not isinstance(job.get('jobDescription'),str) or not text(job['jobDescription']).strip()):
        raise FetchError('partial', 'Northrop full detail is missing or disagrees with its listing.')
    locations = job.get('standardizedLocations') or job.get('locations') or []
    if not isinstance(locations,list) or not all(isinstance(v,str) for v in locations):
        raise FetchError('partial','Northrop location data is malformed.')
    row = _base({'id':ident},'Eightfold',company_id,company)
    row.update(req_id=job['displayJobId'],title=text(job['name']),url=job['publicUrl'],
               description=text(job['jobDescription']),location='; '.join(locations),
               department=text(job.get('department')),work_arrangement=text(job.get('workLocationOption')),
               created_at=_timestamp(job.get('creationTs')),updated_at=_timestamp(job.get('postedTs')))
    return row


def _scan(client, company_id, company, max_jobs=MAX_JOBS):
    jobs, seen, snapshots = [], set(), []
    try:
        entries,total = _page(client,0)
        for start in range(0,max(1,total),10):
            if start and len(jobs) >= max_jobs:
                raise FetchError('partial',f'Northrop bounded validation stopped after {len(jobs)} of {total} postings.')
            if start:
                entries,_ = _page(client,start,total)
            ids = [_identity(e) for e in entries]
            if len(set(ids)) != len(ids) or seen.intersection(ids):
                raise FetchError('partial','Northrop pagination repeated posting identities.')
            seen.update(ids);snapshots.append(ids)
            for entry in entries:
                if len(jobs) >= max_jobs:
                    raise FetchError('partial',f'Northrop bounded validation stopped after {len(jobs)} of {total} postings.')
                jobs.append(_posting(client,entry,company_id,company))
            print(json.dumps({'event':'inventory_page','provider':'Northrop Grumman','company_id':company_id,
                              'postings_fetched':len(jobs),'total':total}),file=sys.stderr)
        # Re-read all listing pages; detail reads can take time on this large board.
        for page_number, ids in enumerate(snapshots):
            check,_ = _page(client,page_number*10,total)
            if [_identity(e) for e in check] != ids:
                raise FetchError('partial','Northrop inventory changed during the scan; no closure inference.')
        return Inventory('complete',jobs,f'Northrop: retrieved {len(jobs)} full postings and rechecked every inventory page.',BOARD,'Eightfold')
    except FetchError as e:
        return Inventory('blocked' if e.status=='blocked' else 'partial',jobs,e.reason,BOARD,'Eightfold')
    except Exception as e:
        # Browser timeouts must preserve already verified full postings too.
        return Inventory('partial',jobs,f'Northrop data or transport failed validation ({type(e).__name__}); inventory incomplete.',BOARD,'Eightfold')


def fetch_northrop(url, company_id, company, *, headless=True, timeout_ms=30000, max_jobs=MAX_JOBS):
    try:
        if (company_id != COMPANY_ID
                or not isinstance(company, str)
                or company.strip().casefold() != COMPANY.casefold()):
            raise FetchError('unsupported', 'Northrop public board is verified only for the Northrop Grumman company record.')
        _source(url)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                context = browser.new_context()
                page = context.new_page()
                response = page.goto(BOARD,wait_until='networkidle',timeout=timeout_ms)
                if not response or response.status in (401,403) or response.status != 200:
                    raise FetchError('blocked','Northrop public jobs page did not grant access in the browser.')
                if urlsplit(page.url).hostname != urlsplit(BOARD).hostname:
                    raise FetchError('unsupported','Northrop jobs page redirected to an unverified host.')
                return _scan(BrowserClient(context),company_id,company,max_jobs)
            finally:
                browser.close()
    except FetchError as e:
        return Inventory(e.status,reason=e.reason,source_url=BOARD,ats='Eightfold')
    except ImportError:
        return Inventory('unsupported',reason='Northrop public board requires the optional Playwright browser dependency.',source_url=BOARD,ats='Eightfold')
    except Exception as e:
        return Inventory('partial',reason=f'Northrop browser could not complete the inventory ({type(e).__name__}).',source_url=BOARD,ats='Eightfold')
