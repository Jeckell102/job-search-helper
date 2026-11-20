"""Bounded, company-scoped retrieval for ManTech's public Avature board."""
from html.parser import HTMLParser
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = 'https://careers.mantech.com/en_US/careers/'
SEARCH_PATH = '/en_US/careers/SearchJobs/'
PAGE_SIZE, MAX_PAGES, DETAIL_WORKERS = 6, 200, 1
RETRIES = 3
SITE_INTERVAL = 0.4
COOLDOWN = 2.0
_TOTAL = re.compile(r'\bof\s+([0-9][0-9,]*)\s+results\b', re.I)
_DETAIL_PATH = re.compile(r'^/en_US/careers/JobDetail/[^/?#]+/([0-9]+)/?$')


class _ListingPage(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True); self.links=[]; self._anchor=None; self.feed(body); self.close()
    def handle_starttag(self, tag, attrs):
        if tag == 'a' and self._anchor is None:
            href=dict(attrs).get('href','')
            if _DETAIL_PATH.fullmatch(urlsplit(href).path): self._anchor=[href,[]]
    def handle_data(self, data):
        if self._anchor is not None: self._anchor[1].append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self._anchor is not None:
            self.links.append((self._anchor[0],text(''.join(self._anchor[1])))); self._anchor=None


class _DetailPage(HTMLParser):
    _VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self, body):
        super().__init__(convert_charrefs=True); self.depth=0; self.title=[]; self._banner_depth=None; self._article=None; self._heading_depth=None; self._label_depth=None; self._value_depth=None; self.sections=[]; self.feed(body); self.close()
    def handle_starttag(self, tag, attrs):
        if tag in self._VOID: return
        self.depth+=1; classes=set(dict(attrs).get('class','').split())
        if tag in {'h1','h2'} and 'banner__text__title' in classes: self._banner_depth=self.depth
        if tag == 'article' and self._article is None and 'article--details' in classes:
            self._article={'depth':self.depth,'heading':[],'label':[],'pending_label':'','values':[]}; return
        if self._article is None: return
        if tag == 'h3' and 'article__header__text__title' in classes: self._heading_depth=self.depth
        elif tag == 'div' and 'article__content__view__field__label' in classes: self._label_depth=self.depth
        elif tag == 'div' and 'article__content__view__field__value' in classes:
            self._value_depth=self.depth; self._article['values'].append([self._article['pending_label'],[]]); self._article['pending_label']=''
    def handle_data(self, data):
        if self._banner_depth is not None: self.title.append(data)
        if self._article is None: return
        if self._heading_depth is not None: self._article['heading'].append(data)
        if self._label_depth is not None: self._article['label'].append(data)
        if self._value_depth is not None and self._article['values']: self._article['values'][-1][1].append(data)
    def handle_endtag(self, tag):
        if tag in self._VOID: return
        if self._banner_depth == self.depth: self._banner_depth=None
        if self._article is not None:
            if self._heading_depth == self.depth: self._heading_depth=None
            if self._label_depth == self.depth:
                self._article['pending_label']=text(''.join(self._article['label'])); self._article['label']=[]; self._label_depth=None
            if self._value_depth == self.depth: self._value_depth=None
            if self._article['depth'] == self.depth:
                heading=text(''.join(self._article['heading']))
                values=[(text(label),text(''.join(value))) for label,value in self._article['values']]
                self.sections.append((heading,values)); self._article=None
        self.depth-=1
    def values_for(self, heading):
        found=[(label,value) for actual,values in self.sections if actual.casefold()==heading.casefold() for label,value in values]
        if not found: raise ValueError('Missing required Avature detail section.')
        return found


class _SiteClient:
    """Serialize all Avature requests and apply one board-wide pacing budget."""
    def __init__(self, client, interval=SITE_INTERVAL, cooldown=COOLDOWN):
        self.client = client
        self.interval = interval
        self.cooldown = cooldown
        self._lock = threading.Lock()
        self._next_request = 0.0

    def get(self, url):
        with self._lock:
            wait = max(0.0, self._next_request - time.monotonic())
            if wait:
                time.sleep(wait)
            self._next_request = time.monotonic() + self.interval
            response = self.client.get(url)
            if isinstance(response, HTTPResponse) and response.status in {406, 429}:
                self._next_request = max(self._next_request, time.monotonic() + self.cooldown)
            return response


def _get(client, url):
    for attempt in range(RETRIES):
        try:
            response = client.get(url)
        except FetchError as error:
            transient = error.status == 'failed' and error.reason == 'Careers page network/timeout failure; board discovery did not complete.'
            if not transient or attempt == 2:
                raise
        else:
            if not isinstance(response, HTTPResponse):
                raise FetchError('partial', 'Avature transport returned an invalid response.')
            if response.status == 200:
                return response.body.decode('utf-8', 'replace')
            # Avature intermittently returns 406 to the same public request;
            # treat it like a bounded access cooldown, not as proof the board
            # is unavailable.  Persistent 406/429 responses remain blocked.
            if response.status in (406, 429):
                if attempt == RETRIES - 1:
                    raise FetchError('blocked', f'Avature public page returned HTTP {response.status} after cooldown retries.')
            elif response.status in (401, 403):
                raise FetchError('blocked', f'Avature public page returned HTTP {response.status}.')
            elif response.status not in (500, 502, 503, 504) or attempt == RETRIES - 1:
                raise FetchError('partial', f'Avature public page returned HTTP {response.status}.')
        time.sleep(COOLDOWN * (2 ** attempt) if 'response' in locals() and response.status in {406, 429} else 0.5 * (2 ** attempt))

def _search_url(offset):
    if offset < 0 or offset % PAGE_SIZE: raise ValueError('Avature page offset must be a non-negative page boundary.')
    return urlunsplit(('https','careers.mantech.com',SEARCH_PATH,urlencode((('jobOffset',str(offset)),('jobRecordsPerPage',str(PAGE_SIZE)))),''))

def _detail_url(href):
    parsed=urlsplit(urljoin(SOURCE,href)); match=_DETAIL_PATH.fullmatch(parsed.path)
    if (parsed.scheme != 'https' or parsed.hostname != 'careers.mantech.com' or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.query or parsed.fragment or not match): raise FetchError('partial','Avature listing had an invalid job link.')
    return match.group(1),urlunsplit(('https','careers.mantech.com',parsed.path,'',''))

def _listing(client, offset):
    body=_get(client,_search_url(offset)); totals={value.replace(',','') for value in _TOTAL.findall(body)}
    if len(totals) != 1: raise FetchError('partial','Avature page did not expose one published result total.')
    total=int(totals.pop())
    if total > PAGE_SIZE*MAX_PAGES: raise FetchError('partial','Avature inventory exceeds the safe page limit.')
    entries=[]; seen=set()
    for href,title in _ListingPage(body).links:
        ident,detail=_detail_url(href)
        if not title or ident in seen: raise FetchError('partial','Avature listing had a missing title or duplicate posting ID.')
        seen.add(ident); entries.append((ident,title,detail))
    if len(entries) != min(PAGE_SIZE,max(0,total-offset)): raise FetchError('partial','Avature page size disagrees with its published total.')
    return total,entries

def _detail(client,item,company_id,company):
    ident,listing_title,detail_url=item; page=_DetailPage(_get(client,detail_url))
    fields={label.casefold():value for label,value in page.values_for('General information') if label and value}
    title=text(''.join(page.title)); description='\n'.join(value for _,value in page.values_for('Description & Requirements') if value); req_id=fields.get('requisition #','')
    if not title or title != listing_title or not description or not req_id: raise FetchError('partial','Avature detail lacks a matching title, requisition, or full description.')
    row=_base({'id':ident},'Avature',company_id,company)
    row.update(title=title,url=detail_url,description=description,req_id=req_id,location=fields.get('locations',''),work_arrangement=fields.get('remote type',''),created_at=fields.get('posting date',''))
    return row

def _checkpoint_read(path, source=SOURCE, company_id='COMP-0010'):
    if path is None:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if (not isinstance(value, dict) or value.get('source_url') != source
            or value.get('company_id') != company_id
            or type(value.get('total')) is not int
            or not isinstance(value.get('entries'), list)
            or not isinstance(value.get('ids'), list)
            or not isinstance(value.get('jobs'), dict)):
        return None
    return value


def _checkpoint_write(path, *, total, entries, jobs, phase, company_id='COMP-0010'):
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    ids = [item[0] for item in entries]
    payload = {'source_url': SOURCE, 'company_id': company_id,
               'total': total, 'entries': entries, 'ids': ids,
               'jobs': jobs, 'phase': phase}
    with NamedTemporaryFile('w', encoding='utf-8', dir=target.parent,
                            prefix=target.name + '.', delete=False) as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, target)


def fetch_avature(url,company_id,company,transport=None,checkpoint_path=None):
    if url != SOURCE: return Inventory('unsupported',reason='Avature adapter requires ManTech\'s verified unfiltered careers page.',source_url=url,ats='Avature')
    client=_SiteClient(transport or CareersTransport(interval=SITE_INTERVAL))
    jobs=[]
    try:
        saved = _checkpoint_read(checkpoint_path, SOURCE, company_id)
        if saved and saved.get('phase') in {'listing', 'details'}:
            total, entries = saved['total'], [tuple(item) for item in saved['entries']]
            completed = {str(key): value for key, value in saved['jobs'].items()}
        else:
            total,first=_listing(client,0); entries=[]; seen=set()
            for offset in range(0,total,PAGE_SIZE):
                current,part=(total,first) if offset == 0 else _listing(client,offset)
                if current != total: raise FetchError('partial','Avature inventory changed during pagination.')
                for item in part:
                    if item[0] in seen: raise FetchError('partial','Avature listing repeated a posting ID.')
                    seen.add(item[0]); entries.append(item)
            if len(entries) != total:
                raise FetchError('partial','Avature inventory did not exhaust the published cohort.')
            _checkpoint_write(checkpoint_path, total=total, entries=entries, jobs={}, phase='details', company_id=company_id)
            completed={}
        ids = [item[0] for item in entries]
        if len(ids) != total or len(set(ids)) != total or any(not str(i).isdigit() for i in ids):
            raise FetchError('partial','Avature inventory has duplicate or non-numeric posting IDs.')
        for item in entries:
            ident = item[0]
            if ident in completed:
                continue
            try:
                completed[ident] = _detail(client,item,company_id,company)
            except FetchError:
                _checkpoint_write(checkpoint_path, total=total, entries=entries, jobs=completed, phase='details', company_id=company_id)
                jobs = list(completed.values())
                raise
            _checkpoint_write(checkpoint_path, total=total, entries=entries, jobs=completed, phase='details', company_id=company_id)
        jobs = [completed[ident] for ident in ids]
        checked_entries=[]
        for offset in range(0, max(total, 1), PAGE_SIZE):
            checked, part = _listing(client, offset)
            if checked != total: raise FetchError('partial','Avature inventory changed during retrieval.')
            checked_entries.extend(part)
        if len(jobs) != total or len(checked_entries) != total or set(checked_entries) != set(entries):
            raise FetchError('partial','Avature inventory changed during retrieval.')
        _checkpoint_write(checkpoint_path, total=total, entries=entries, jobs=completed, phase='complete', company_id=company_id)
        return Inventory('complete',jobs,f'Avature: retrieved {len(jobs)} complete postings and rechecked the public inventory.',SOURCE,'Avature')
    except FetchError as error: return Inventory(error.status if not jobs else 'partial',jobs,error.reason,SOURCE,'Avature')
    except (ValueError,TypeError,AttributeError,UnicodeError): return Inventory('partial',jobs,'Avature public schema validation failed.',SOURCE,'Avature')
