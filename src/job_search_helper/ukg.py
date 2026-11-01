"""UKG/UltiPro public JobBoard inventories, verified 2026-10-08.

Only anonymous board HTML, public listing-search POST, and posting detail GET
are used. Embedded JSON is parsed, never executed. No candidate/account API.
"""
from __future__ import annotations

import json
import re
import sys
from http.client import HTTPException
from urllib.parse import parse_qsl, urlsplit

from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, MAX_RESPONSE_BYTES, _base, _challenge, text

HOSTS = {'recruiting.ultipro.com', 'recruiting2.ultipro.com'}
UUID = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
BOARD = r'/[A-Za-z0-9]{1,40}/JobBoard/' + UUID
SEARCH = '/JobBoardView/LoadSearchResults'
PAGE_SIZE = 50
MAX_JOBS = 10000


def is_ukg_host(host):
    return host in HOSTS


def safe_api_path(p):
    if p.fragment or '\\' in p.path or '%' in p.path:
        return False
    if re.fullmatch(BOARD + '(?:' + SEARCH + ')?', p.path):
        return not p.query
    return bool(re.fullmatch(BOARD + '/OpportunityDetail', p.path)
                and re.fullmatch('opportunityId=' + UUID, p.query))


def resolve_ukg(ats, url):
    p = urlsplit(url)
    path = p.path.rstrip('/')
    if (p.scheme != 'https' or not is_ukg_host(p.hostname) or p.username or p.password
            or p.port not in (None,443) or not re.fullmatch(BOARD,path) or p.fragment
            or '\\' in url or any(ord(c)<=32 or ord(c)==127 for c in url)):
        raise ValueError('UKG requires a verified public HTTPS JobBoard URL, not an individual job link.')
    seen = set()
    for k,v in parse_qsl(p.query,keep_blank_values=True,max_num_fields=30):
        if k in seen:
            raise ValueError('Duplicate UKG URL parameter; verify company scope.')
        seen.add(k)
        if k.startswith('utm_') or (k=='o' and v in ('','postedDateDesc','postedDateAsc')):
            continue
        if k in {'q','w','wc','we','wpst'} and not v:
            continue
        raise ValueError('UKG URL filters are unsupported; configured company scope is not expanded.')
    label = ats.casefold()
    if any(x in label for x in ('shared','parent')):
        raise ValueError('Shared UKG boards require an explicit company-specific scope.')
    if not any(x in label for x in ('ukg','ultipro')) and any(x in label for x in ('greenhouse','lever','ashby','workday','icims','adp','paylocity','taleo','phenom','paycom','bamboohr')):
        raise ValueError('ATS / Source disagrees with the UKG board URL.')
    # Keep tenant capitalization (UKG routes use tenant identifiers), normalize GUID.
    tenant, board_id = path.split('/')[1], path.split('/')[-1].lower()
    return 'UKG', f'/{tenant}/JobBoard/{board_id}', 'https://' + p.hostname


def _response(response, html=False):
    if not isinstance(response,HTTPResponse):
        raise FetchError('failed','UKG transport did not return HTTPResponse.')
    if response.status in (401,403) or _challenge(response,expect_html=html):
        raise FetchError('blocked','UKG denied public access or requires human verification.')
    if not 200<=response.status<300:
        raise FetchError('failed',f'UKG HTTP {response.status}; inventory incomplete.')
    if len(response.body)>MAX_RESPONSE_BYTES:
        raise FetchError('partial','UKG response exceeds the bounded size limit.')
    return response.body.decode('utf-8')


def _embedded(html, marker):
    matches = list(re.finditer(marker,html))
    if len(matches)!=1:
        raise FetchError('partial','UKG public page has missing or ambiguous embedded job data.')
    return json.JSONDecoder().raw_decode(html[matches[0].end():])[0]


def _board(transport, source):
    html=_response(transport.get(source),True)
    data=_embedded(html,r'\bjobBoard\s*:\s*')
    if (not isinstance(data,dict) or data.get('Id','').lower()!=source.rsplit('/',1)[1]
            or data.get('AllowExternal') is not True or data.get('HasThirdPartyPostings') is not False
            or re.search(r'\bisInternal\s*:\s*false\b',html) is None):
        raise FetchError('unsupported','UKG page does not establish the configured external company board.')
    load=_embedded(html,r'\bloadUrl\s*:\s*')
    if load!=urlsplit(source).path+SEARCH:
        raise FetchError('unsupported','UKG listing endpoint does not match the configured company board.')
    # Board-level filters belong to this board; never switch to another board.
    return {k:data.get(k) for k in ('Id','AllowExternal','AllowInternal','FilterCategory','FilterValues','HasThirdPartyPostings')}


def _listing(transport, source):
    entries,seen,total=[],set(),None
    for skip in range(0,MAX_JOBS,PAGE_SIZE):
        payload={'opportunitySearch':{'Top':PAGE_SIZE,'Skip':skip,'QueryString':'','Filters':[]}}
        data=json.loads(_response(transport.post(source+SEARCH,payload)))
        count,page=data.get('totalCount'),data.get('opportunities')
        if type(count) is not int or not 0<=count<=MAX_JOBS or not isinstance(page,list):
            raise FetchError('partial','UKG listing lacks a valid count or exceeds the bounded inventory size.')
        if total is None:total=count
        if count!=total or len(page)!=min(PAGE_SIZE,max(0,total-skip)):
            raise FetchError('partial','UKG page size or total changed during pagination.')
        for item in page:
            if (not isinstance(item,dict) or not re.fullmatch(UUID,str(item.get('Id','')))
                    or not isinstance(item.get('Title'),str) or not item['Title'].strip()
                    or not isinstance(item.get('RequisitionNumber'),str) or not item['RequisitionNumber'].strip()):
                raise FetchError('partial','UKG listing has invalid job identity or title.')
            ident=item['Id'].lower()
            if ident in seen:
                raise FetchError('partial','UKG listing repeated job IDs; inventory incomplete.')
            seen.add(ident);entries.append(item)
        if len(entries)==total:
            return entries
    raise FetchError('partial','UKG page limit reached; inventory incomplete.')


def _locations(job):
    values=job.get('Locations')
    if not isinstance(values,list):
        raise FetchError('partial','UKG detail locations are malformed.')
    result=[]
    for loc in values:
        addr=loc.get('Address') or {}
        parts=[addr.get('City'),(addr.get('State') or {}).get('Name'),(addr.get('Country') or {}).get('Name')]
        value=', '.join(str(p) for p in parts if p)
        if not value:value=text(loc.get('LocalizedName') or loc.get('LocalizedDescription'))
        if value and value not in result:result.append(value)
    return '; '.join(result)


def _criteria(job):
    sections=[]
    for key,label in [('EducationCriteria','Education'),('WorkExperienceCriteria','Experience'),
                      ('LicenseAndCertificationCriteria','Licenses and certifications'),('SkillCriteria','Skills'),
                      ('BehaviorCriteria','Behaviors'),('MotivationCriteria','Motivations')]:
        items=job.get(key) or []
        if not isinstance(items,list):raise FetchError('partial','UKG qualification criteria are malformed.')
        lines=[]
        for item in items:
            if not isinstance(item,dict):raise FetchError('partial','UKG qualification criterion is malformed.')
            # Preserve the human-readable public fields and years, not internal GUIDs.
            parts=[f'{re.sub(r"(?<!^)(?=[A-Z])", " ", k)}: {text(v)}' for k,v in item.items()
                   if v is not None and v!='' and not k.endswith('Id') and k not in {'Required','Related'}]
            if not parts:raise FetchError('partial','UKG qualification criterion lacks readable fields.')
            prefix='Required: ' if item.get('Required') is True else ('Preferred: ' if item.get('Required') is False else '')
            lines.append(prefix+'; '.join(parts)+('; or related field' if item.get('Related') else ''))
        if lines:sections.append(label+'\n'+'\n'.join(lines))
    return sections


def _compensation(job):
    salaried=job.get('Salaried')
    period='per year' if salaried is True else ('per hour' if salaried is False else '')
    result=[]
    prefix='CompensationAnnual' if salaried is True else 'CompensationHourly'
    lo,hi=job.get(prefix+'Minimum'),job.get(prefix+'Maximum')
    if salaried is not None and lo is not None and hi is not None:
        result.append(f'{job.get("CompensationCurrencyCode") or ""} {lo} - {hi} {period}'.strip())
    amount=job.get('CompensationAmount') or {}
    if amount.get('Value') is not None:
        result.append(f'{amount.get("Code") or ""} {amount["Value"]} {period}'.strip())
    if job.get('PayRangeVisible') is True:
        bounds=job.get('PayRange') or {}
        lo,hi=bounds.get('PayRangeMinimum'),bounds.get('PayRangeMaximum')
        if lo is not None and hi is not None:
            # PayRange UI does not label a time period; do not infer annual/hourly.
            result.append(f'{job.get("PayRangeCurrencyCode") or ""} {lo} - {hi}'.strip())
    return '; '.join(dict.fromkeys(result))


def _posting(transport,source,entry,company_id,company):
    ident=entry['Id'].lower()
    url=source+'/OpportunityDetail?opportunityId='+ident
    html=_response(transport.get(url),True)
    job=_embedded(html,r'\bvar\s+opportunity\s*=\s*new\s+US\.Opportunity\.CandidateOpportunityDetail\(\s*')
    if (not isinstance(job,dict) or str(job.get('Id','')).lower()!=ident or text(job.get('Title'))!=text(entry['Title'])
            or job.get('RequisitionNumber')!=entry['RequisitionNumber'] or job.get('OpportunityIsClosed') is not False
            or job.get('PublishingStatus')!=1 or not isinstance(job.get('Description'),str) or not text(job['Description']).strip()):
        raise FetchError('partial','UKG detail identity, title, open status, or full description disagrees with its listing.')
    memberships=job.get('JobBoardMemberships')
    if not isinstance(memberships,list):raise FetchError('partial','UKG detail board membership is missing.')
    matching=[m for m in memberships if str(m.get('JobBoardId','')).lower()==source.rsplit('/',1)[1] and m.get('PublishedExternal') is True]
    if len(matching)!=1:raise FetchError('partial','UKG job is not externally published on the configured board.')
    if matching[0].get('ExternalPostedDate')!=entry.get('PostedDate'):
        raise FetchError('partial','UKG public posting date changed during the scan.')
    location_type=job.get('JobLocationType')
    if location_type not in (None,-1,0,1,2) or isinstance(location_type,bool):
        raise FetchError('partial','UKG work-location type is unrecognized.')
    sections=[text(job['Description']),*_criteria(job)]
    for field in ('TravelDescription','EqualOpportunityEmployerDescription','PayTransparencyPolicyStatement'):
        if job.get(field):sections.append(text(job[field]))
    row=_base({'id':ident},'UKG',company_id,company)
    row.update(req_id=job['RequisitionNumber'],title=text(job['Title']),url=url,description='\n\n'.join(sections),
               location=_locations(job),work_arrangement={0:'Hybrid',1:'On-site',2:'Remote'}.get(location_type,''),
               compensation=_compensation(job),department=text(job.get('JobCategoryName')),
               created_at=matching[0].get('ExternalPostedDate') or '',updated_at=job.get('UpdatedDate') or '')
    return row


def fetch_ukg(ats,url,company_id,company,transport=None):
    jobs,source,context=[],url,'UKG board'
    try:
        _,board,root=resolve_ukg(ats,url);source=root+board
        transport=transport or HTTPTransport()
        scope=_board(transport,source)
        context='UKG public inventory';entries=_listing(transport,source)
        for entry in entries:
            context='UKG detail '+entry['Id']
            jobs.append(_posting(transport,source,entry,company_id,company))
            print(json.dumps({'event':'inventory_page','provider':'UKG','company_id':company_id,
                              'postings_fetched':len(jobs),'total':len(entries)}),file=sys.stderr)
        context='UKG final inventory check'
        if _listing(transport,source)!=entries or _board(transport,source)!=scope:
            raise FetchError('partial','UKG inventory or board scope changed during the scan.')
        return Inventory('complete',jobs,f'UKG: retrieved {len(jobs)} full postings and rechecked every listing page and board scope.',source,'UKG')
    except FetchError as e:
        return Inventory('blocked' if e.status=='blocked' else ('partial' if jobs else e.status),jobs,context+': '+e.reason,source,'UKG')
    except (ValueError,TypeError,KeyError,AttributeError):
        return Inventory('partial' if jobs else 'unsupported',jobs,context+': malformed public data or unsupported URL/configuration; inventory incomplete.',source,'UKG')
    except (OSError, HTTPException):
        return Inventory('partial' if jobs else 'failed',jobs,context+': network failure; inventory incomplete.',source,'UKG')
