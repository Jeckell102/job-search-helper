"""Komatsu's public, employer-scoped Jobs2Web board.

The JSON endpoint is a second membership source, not a stable identity
source: current responses can omit requisition ids. The official HTML board
therefore owns canonical identity; JSON records must reconcile to it.
"""
from __future__ import annotations
import json, re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit
from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _base, text

SOURCE = "https://komatsu.jobs/viewalljobs/"
SEARCH = "https://komatsu.jobs/services/recruiting/v1/jobs"
HOST = "komatsu.jobs"
PAGE_SIZE, MAX_PAGES = 50, 100

def _canonical(value):
    p = urlsplit(value)
    if p.scheme != "https" or p.hostname != HOST or p.username or p.password or p.query or p.fragment:
        return ""
    path = re.sub(r"/{2,}", "/", p.path)
    if not re.fullmatch(r"/job/[^/]+/[1-9][0-9]{2,24}(?:-en_US)?/?", path):
        return ""
    return urlunsplit(("https", HOST, path.rstrip("/"), "", ""))

def _identity(url):
    m = re.search(r"/([1-9][0-9]{2,24})(?:-en_US)?/?$", urlsplit(url).path)
    return m.group(1) if m else ""

class _Listing(HTMLParser):
    def __init__(self, body):
        super().__init__(); self.links=[]; self._a=None; self._href=""
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "a" and "jobTitle-link" in set(a.get("class", "").split()): self._a=[]; self._href=a.get("href", "")
    def handle_data(self, data):
        if self._a is not None: self._a.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            self.links.append((self._href, text("".join(self._a)))); self._a=None; self._href=""

class _Detail(HTMLParser):
    def __init__(self, body):
        super().__init__(); self.title=[]; self.description=[]; self.canonical=[]; self._title=0; self._description=0
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "link" and a.get("rel") == "canonical": self.canonical.append(a.get("href", ""))
        if a.get("itemprop") == "title": self._title=1
        elif self._title and tag not in {"br","img","meta","link","input"}: self._title+=1
        if a.get("itemprop") == "description": self._description=1
        elif self._description and tag not in {"br","img","meta","link","input"}: self._description+=1
    def handle_data(self, data):
        if self._title: self.title.append(data)
        if self._description: self.description.append(data)
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag not in {"br","img","meta","link","input"}:
            if self._title: self._title-=1
            if self._description: self._description-=1

def _get(client, url):
    r=client.get(url)
    if not isinstance(r, HTTPResponse) or r.status != 200:
        status="blocked" if isinstance(r, HTTPResponse) and r.status in (401,403,429) else "partial"
        raise FetchError(status, f"Komatsu public page unavailable: {url}")
    return r.body.decode("utf-8", "replace")

def _html_page(client, start):
    url=SOURCE if not start else f"{SOURCE}{start}/"; body=_get(client,url)
    ranges=re.findall(r"Results\s*<b>\s*(\d+)\s*[–-]\s*(\d+)\s*</b>\s*of\s*<b>\s*(\d+)\s*</b>", body, re.I)
    if not ranges or len(set(ranges)) != 1: raise FetchError("partial", "Komatsu HTML board did not expose one consistent published result range.")
    first,last,total=map(int,ranges[0])
    if first != start+1 or first > last or last > total: raise FetchError("partial", "Komatsu HTML board published an invalid result range.")
    p=_Listing(body); p.feed(body); entries=[]; seen=set()
    for href,title in p.links:
        canonical=_canonical(urljoin(SOURCE,href)); ident=_identity(canonical)
        if not canonical or not ident or not title.strip(): raise FetchError("partial", "Komatsu HTML board published a non-canonical job link.")
        if ident in seen: raise FetchError("partial", "Komatsu HTML board repeated a posting identity.")
        seen.add(ident); entries.append((ident,title.strip(),canonical))
    if len(entries) != last-first+1 or len(entries) != min(PAGE_SIZE,total-start): raise FetchError("partial", "Komatsu HTML membership disagreed with its published range.")
    return total,entries

def _api_key(record):
    for key in ("url","jobUrl","detailUrl","canonicalUrl"):
        candidate=_canonical(str(record.get(key,"")))
        if candidate: return candidate
    ident=record.get("id") or record.get("jobReqId") or record.get("requisitionId"); slug=record.get("urlTitle") or record.get("slug")
    if isinstance(ident,(str,int)) and re.fullmatch(r"[1-9][0-9]{2,24}(?:-en_US)?",str(ident)) and isinstance(slug,str) and slug:
        return _canonical(f"https://{HOST}/job/{slug}/{ident}")
    return ""

def _dealer(record):
    vals=[record.get(k,"") for k in ("employer","company","businessUnit","businessunit","category","employmentType")]
    return any("independent dealer" in str(v).casefold() or str(v).casefold()=="dealer" for v in vals)

def _api_records(client):
    records=[]; total=None
    for page in range(MAX_PAGES):
        r=client.post(SEARCH,{"keywords":"","locale":"en_US","location":"","pageNumber":page,"sortBy":"recent"},headers={"Content-Type":"application/json"})
        if not isinstance(r,HTTPResponse): raise FetchError("failed","Komatsu API transport returned an invalid response.")
        if r.status in (401,403,429): raise FetchError("blocked",f"Komatsu API returned HTTP {r.status}.")
        if r.status != 200: raise FetchError("partial",f"Komatsu API returned HTTP {r.status}.")
        try: payload=json.loads(r.body)
        except (UnicodeDecodeError,json.JSONDecodeError): raise FetchError("partial","Komatsu API returned non-JSON data.") from None
        rows=payload.get("jobSearchResult") if isinstance(payload,dict) else None; current=payload.get("totalJobs") if isinstance(payload,dict) else None
        if not isinstance(rows,list) or not isinstance(current,int) or current < 0: raise FetchError("partial","Komatsu API returned an invalid inventory envelope.")
        if total is None: total=current
        elif total != current: raise FetchError("partial","Komatsu API total changed during pagination.")
        records.extend(row.get("response") for row in rows if isinstance(row,dict) and isinstance(row.get("response"),dict))
        if not rows or len(records) >= total: break
    if total is None or len(records) != total: raise FetchError("partial","Komatsu API membership was incomplete.")
    return records

def fetch_komatsu(url, company_id, company, transport=None):
    if url != SOURCE: return Inventory("unsupported",reason="Komatsu adapter requires the verified komatsu.jobs source.",source_url=url,ats="SuccessFactors")
    client=transport or HTTPTransport()
    try:
        total,entries=_html_page(client,0); start=PAGE_SIZE
        while start < total:
            page_total,page=_html_page(client,start)
            if page_total != total: raise FetchError("partial","Komatsu HTML inventory changed during pagination.")
            entries.extend(page); start+=PAGE_SIZE
            if start//PAGE_SIZE > MAX_PAGES: raise FetchError("partial","Komatsu HTML page limit reached.")
        if len(entries) != total: raise FetchError("partial","Komatsu HTML inventory count disagreed with total.")
        html_map={e[2]:e for e in entries}; api_map={}
        for record in _api_records(client):
            if _dealer(record): continue
            key=_api_key(record)
            if not key: raise FetchError("partial","Komatsu API published a record without a canonical identity.")
            if key in api_map: raise FetchError("partial","Komatsu API repeated a canonical posting identity.")
            api_map[key]=record
        if set(api_map) != set(html_map): raise FetchError("partial","Komatsu API/HTML membership diverged; API-only records were not accepted.")
        reread=[]
        for start in range(0,total,PAGE_SIZE):
            check_total,page=_html_page(client,start)
            if check_total != total: raise FetchError("partial","Komatsu HTML inventory changed during reread.")
            reread.extend(page)
        if reread != entries: raise FetchError("partial","Komatsu HTML membership changed during reread.")
        def detail(entry):
            ident,listed_title,detail_url=entry; p=_Detail(""); p.feed(_get(client,detail_url)); canonical=[_canonical(c) for c in p.canonical if _canonical(c)]
            title=text("".join(p.title)); description=text("".join(p.description))
            if canonical != [detail_url] or not title or not description: raise FetchError("partial",f"Komatsu posting {ident} lacks its canonical URL or full body.")
            row=_base({"id":ident},"SuccessFactors",company_id,company); row.update(title=listed_title or title,url=detail_url,description=description,req_id=ident); return row
        with ThreadPoolExecutor(max_workers=12) as pool: jobs=list(pool.map(detail,entries))
        return Inventory("complete",jobs,f"Komatsu: reconciled {len(jobs)} HTML/API postings with canonical full bodies.",SOURCE,"SuccessFactors")
    except FetchError as exc: return Inventory(exc.status,[],exc.reason,SOURCE,"SuccessFactors")
    except (AttributeError,TypeError,ValueError): return Inventory("partial",[],"Komatsu public schema validation failed.",SOURCE,"SuccessFactors")
