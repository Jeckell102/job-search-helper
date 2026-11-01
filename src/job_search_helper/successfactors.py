"""Bounded public SAP SuccessFactors (Jobs2Web) careers boards."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

ABACO_SOURCE = "https://jobs.ametek.com/go/Abaco/8908500/?q=&sortColumn=referencedate&sortDirection=desc"
KOMATSU_SOURCE = "https://komatsu.jobs/viewalljobs/"
SITES = {
    ABACO_SOURCE: "jobs.ametek.com",
    "https://careers.qorvo.com/search/?locale=en_US": "careers.qorvo.com",
    "https://careers.ses.com/search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_customfield3=&optionsFacetsDD_customfield5=": "careers.ses.com",
    "https://careers.belden.com/search/?q=": "careers.belden.com",
    "https://jobs.hii-tsd.com/search/?q=&sortColumn=referencedate&sortDirection=desc": "jobs.hii-tsd.com",
    "https://careers.leonardodrs.com/go/All-Jobs/8131200/": "careers.leonardodrs.com",
    "https://careers.thalesdsi.com/search/?q=": "careers.thalesdsi.com",
    "https://jobs.deere.com/successfactors/search/?q=&locationsearch=": "jobs.deere.com",
    "https://jobs.deere.com/search/?q=&sortColumn=referencedate&sortDirection=desc": "jobs.deere.com",
    "https://jobs.teradyne.com/Universal-Robots/search/?q=&sortColumn=referencedate&sortDirection=desc": "jobs.teradyne.com",
    KOMATSU_SOURCE: "komatsu.jobs",
    "https://jobs.sick.com/usa?locale=en_US": "jobs.sick.com",
}
PAGE_SIZE, MAX_PAGES = 25, 100
KOMATSU_PAGE_SIZE = 50
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _Page(HTMLParser):
    def __init__(self, body):
        super().__init__(); self.links=[]; self.current=None; self.description=[]; self.depth=0; self.title=[]; self.title_depth=0
        self.display=[]; self.display_depth=0; self.business_unit=[]; self.unit_depth=0; self.canonicals=[]; self.description_count=0
        self.feed(body)
    def handle_starttag(self, tag, attrs):
        a=dict(attrs); classes=set(a.get("class", "").split())
        if tag == 'link' and a.get('rel') == 'canonical': self.canonicals.append(a.get('href', ''))
        if tag == "a" and "jobTitle-link" in classes: self.current=[a.get("href", ""), []]
        if self.display_depth:
            self.display.append(self.get_starttag_text())
            if tag not in VOID_TAGS: self.display_depth += 1
        elif "jobDisplayShell" in classes: self.display_depth=1
        if a.get("data-careersite-propertyid") == "businessunit": self.unit_depth=1
        elif self.unit_depth and tag not in VOID_TAGS: self.unit_depth += 1
        if a.get("itemprop") == "description": self.depth=1; self.description_count += 1
        elif self.depth:
            self.description.append(self.get_starttag_text())
            if tag not in VOID_TAGS: self.depth += 1
        if a.get("itemprop") == "title": self.title_depth=1; self.title.append("")
        elif self.title_depth and tag not in VOID_TAGS: self.title_depth += 1
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS: self.handle_endtag(tag)
    def handle_data(self, data):
        if self.current is not None: self.current[1].append(data)
        if self.depth: self.description.append(data)
        if self.title_depth: self.title[-1] += data
        if self.display_depth: self.display.append(data)
        if self.unit_depth: self.business_unit.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.links.append((self.current[0], text("".join(self.current[1])))); self.current=None
        if tag in VOID_TAGS: return
        if self.depth:
            self.depth -= 1
            if self.depth: self.description.append('</' + tag + '>')
        if self.title_depth: self.title_depth -= 1
        if self.unit_depth: self.unit_depth -= 1
        if self.display_depth:
            self.display_depth -= 1
            if self.display_depth: self.display.append('</' + tag + '>')


def _get(client, url):
    # A board can require hundreds of public pages. Retry a temporary read
    # failure locally rather than discarding its complete inventory at once.
    for attempt in range(3):
        try:
            r = client.get(url)
        except FetchError as exc:
            if exc.status != "failed" or attempt == 2:
                raise
        else:
            if r.status == 200:
                return r.body.decode("utf-8", "replace")
            if r.status not in {408, 500, 502, 503, 504} or attempt == 2:
                raise FetchError("blocked" if r.status in (401,403,429) else "partial", "SuccessFactors public page was unavailable.")
        time.sleep(0.5 * (attempt + 1))


def _listing(client, source, start):
    # Jobs2Web boards are not uniform.  Leonardo DRS publishes its offset as
    # a path segment (``.../8131200/25/``), not as a ``startrow`` query
    # parameter.  Sending that parameter is silently ignored and would make
    # every page after the first repeat page one.
    if source == ABACO_SOURCE:
        parsed=urlsplit(source)
        url=urlunsplit((parsed.scheme, parsed.netloc, parsed.path + (str(start) + '/' if start else ''), parsed.query, ''))
    elif source == KOMATSU_SOURCE:
        parsed = urlsplit(source)
        url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path + (str(start) + '/' if start else ''), '', ''))
    elif source == "https://careers.leonardodrs.com/go/All-Jobs/8131200/":
        url = source + ("" if start == 0 else str(start) + "/") + "?q=&sortColumn=referencedate&sortDirection=desc"
    elif source == "https://careers.thalesdsi.com/search/?q=":
        url = source + "&sortColumn=referencedate&sortDirection=desc" + ("&startrow=" + str(start) if start else "")
    elif source == "https://jobs.teradyne.com/Universal-Robots/search/?q=&sortColumn=referencedate&sortDirection=desc":
        url = source + ("&startrow=" + str(start) if start else "")
    else:
        sep="&" if "?" in source else "?"; url=source + ("" if start == 0 else sep + "q=&sortColumn=referencedate&sortDirection=desc&startrow=" + str(start))
    body=_get(client,url); page=_Page(body)
    ranges=re.findall(r"Results\s*<b>\s*(\d+)\s*[–-]\s*(\d+)\s*</b>\s*of\s*<b>\s*(\d+)\s*</b>",body,re.I)
    if not ranges or len(set(ranges)) != 1: raise FetchError("partial", "SuccessFactors listing did not expose one consistent published result range.")
    first,last,total=map(int,ranges[0])
    if first != start + 1 or first > last or last > total: raise FetchError("partial", "SuccessFactors listing published an invalid result range.")
    entries=[]; seen=set()
    for href,title in page.links:
        url=urljoin(source,href); p=urlsplit(url); ident=re.search(r"/(\d{4,})/?$",p.path)
        if p.scheme != "https" or p.hostname != urlsplit(source).hostname or not ident or not title: raise FetchError("partial", "SuccessFactors listing had an invalid posting link.")
        if ident.group(1) not in seen:
            seen.add(ident.group(1)); entries.append((ident.group(1),title,url))
    expected_count=last-first+1
    if len(entries) != expected_count: raise FetchError("partial", "SuccessFactors listing range disagrees with posting links.")
    if source not in {"https://careers.thalesdsi.com/search/?q=", ABACO_SOURCE, KOMATSU_SOURCE} and len(entries) != min(PAGE_SIZE,max(0,total-start)):
        raise FetchError("partial", "SuccessFactors listing page size disagrees with published total.")
    if source == KOMATSU_SOURCE and len(entries) != min(KOMATSU_PAGE_SIZE, max(0, total-start)):
        raise FetchError("partial", "Komatsu listing page size disagrees with published total.")
    return total,entries,last


def _leonardo_sitemap(client, source, expected_total):
    """Read Leonardo's explicit, company-hosted sitemap as stable membership."""
    parsed = urlsplit(source)
    sitemap_url = f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"
    body = _get(client, sitemap_url)
    if "<!doctype" in body.casefold() or "<!entity" in body.casefold():
        raise FetchError("partial", "Leonardo DRS sitemap contained unsafe XML declarations.")
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise FetchError("partial", "Leonardo DRS sitemap was malformed XML.") from None
    local = lambda tag: tag.rsplit("}", 1)[-1]
    if local(root.tag) != "urlset":
        raise FetchError("partial", "Leonardo DRS sitemap did not contain a URL set.")
    locs = []
    for child in list(root):
        if local(child.tag) != "url":
            raise FetchError("partial", "Leonardo DRS sitemap contained a non-URL entry.")
        loc_children = [node for node in list(child) if local(node.tag) == "loc"]
        if len(loc_children) != 1 or loc_children[0].text is None or list(loc_children[0]):
            raise FetchError("partial", "Leonardo DRS sitemap contained an invalid URL entry.")
        locs.append(loc_children[0].text)
    if not locs or len(locs) > 2500:
        raise FetchError("partial", "Leonardo DRS sitemap contained an invalid number of jobs.")
    by_id = {}
    for raw in locs:
        # ElementTree has already decoded XML entities in text nodes.
        candidate = raw.strip()
        p = urlsplit(candidate)
        match = re.fullmatch(r"/job/[^/]+/(\d{4,24})/", p.path)
        if (p.scheme != "https" or p.hostname != parsed.hostname or p.port not in (None, 443)
                or p.username or p.password or p.query or p.fragment or not match):
            raise FetchError("partial", "Leonardo DRS sitemap contained an invalid or foreign job URL.")
        ident = match.group(1)
        if ident in by_id or candidate in by_id.values():
            raise FetchError("partial", "Leonardo DRS sitemap contained duplicate job identities.")
        by_id[ident] = candidate
    if len(by_id) != expected_total:
        raise FetchError("partial", "Leonardo DRS sitemap count disagrees with the published inventory.")
    return by_id


def fetch_successfactors(url, company_id, company, transport=None):
    host=SITES.get(url)
    if not host: return Inventory("unsupported",reason="SuccessFactors adapter requires a verified employer board.",source_url=url,ats="SuccessFactors")
    client=transport or CareersTransport(); jobs=[]; seen=set(); entries_all=[]
    try:
        total,first,_next=_listing(client,url,0)
        if url == "https://careers.leonardodrs.com/go/All-Jobs/8131200/":
            sitemap = _leonardo_sitemap(client, url, total)
            first_map = {ident: (title, detail_url) for ident, title, detail_url in first}
            if not set(first_map) <= set(sitemap) or any(sitemap[ident] != detail_url for ident, (_, detail_url) in first_map.items()):
                raise FetchError("partial", "Leonardo DRS first listing page is outside the verified sitemap.")
            entries_all = [(ident, "", detail_url) for ident, detail_url in sitemap.items()]
        else:
            sitemap = None
        page_snapshots={0: (total, first, _next)}
        if sitemap is None:
            start=0; pages=0
            while start < total:
                current_total,entries,next_start=(total,first,_next) if start == 0 else _listing(client,url,start)
                page_snapshots[start]=(current_total, entries, next_start)
                if current_total != total: raise FetchError("partial","SuccessFactors inventory changed during pagination.")
                for ident,title,detail_url in entries:
                    if ident in seen: raise FetchError("partial","SuccessFactors listing repeated a posting ID.")
                    seen.add(ident); entries_all.append((ident,title,detail_url))
                if next_start <= start: raise FetchError("partial", "SuccessFactors pagination did not advance.")
                start=next_start; pages += 1
                if pages > MAX_PAGES: raise FetchError("partial", "SuccessFactors page limit reached; inventory incomplete.")
        def detail_row(entry):
            ident,title,detail_url=entry; detail=_Page(_get(client,detail_url))
            detail_title = text("".join(detail.title))
            if (not detail_title or (url != "https://careers.leonardodrs.com/go/All-Jobs/8131200/" and detail_title != title)
                    or not text("".join(detail.description))): raise FetchError("partial",f"SuccessFactors posting {ident} lacks a matching title or full description.")
            description=text("".join(detail.description))
            requisition = ''
            if url == 'https://careers.leonardodrs.com/go/All-Jobs/8131200/':
                if (detail.canonicals != [detail_url] or detail.depth or detail.title_depth or detail.display_depth
                        or detail.description_count != 1 or len(detail.title) != 1):
                    raise FetchError("partial", f"Leonardo DRS posting {ident} lacks a matching canonical identity or complete job body.")
                requisitions = re.findall(r'^Job ID:[ \t]*(\d{4,24})\b', description, re.M)
                requisition = requisitions[0] if len(set(requisitions)) == 1 else ''
            if url == ABACO_SOURCE:
                if (detail.canonicals != [detail_url] or text(''.join(detail.business_unit)) != 'Abaco Business Unit'
                        or not detail.display or detail.depth or detail.display_depth or detail.unit_depth or detail.title_depth):
                    raise FetchError("partial", "Abaco detail does not expose a complete, company-scoped job body.")
                description=text(''.join(detail.display))
            row=_base({"id":ident},"SuccessFactors",company_id,company); row.update(title=detail_title if not title else title,url=detail_url,description=description,req_id=requisition); return row
        with ThreadPoolExecutor(max_workers=12) as pool: jobs=list(pool.map(detail_row,entries_all))
        if len(jobs) != total: raise FetchError("partial","SuccessFactors records do not match published total.")
        if sitemap is not None:
            job_titles = {job["posting_id"]: job["title"] for job in jobs}
            if any(job_titles.get(ident) != title for ident, (title, _) in first_map.items()):
                raise FetchError("partial", "Leonardo DRS first listing titles did not match verified details.")
        if sitemap is not None:
            checked_sitemap = _leonardo_sitemap(client, url, total)
            if checked_sitemap != sitemap:
                raise FetchError("partial", "Leonardo DRS sitemap changed during the scan.")
            check_total, check_first, _ = _listing(client, url, 0)
            job_titles = {job["posting_id"]: job["title"] for job in jobs}
            if check_total != total or any(ident not in checked_sitemap or checked_sitemap[ident] != detail_url
                                           or job_titles.get(ident) != title
                                           for ident, title, detail_url in check_first):
                raise FetchError("partial", "Leonardo DRS first listing page changed during the scan.")
        elif url in {"https://careers.thalesdsi.com/search/?q=", ABACO_SOURCE, KOMATSU_SOURCE}:
            for page_start, (saved_total, saved_entries, saved_next) in page_snapshots.items():
                check_total, check_entries, check_next = _listing(client, url, page_start)
                if (check_total, check_entries, check_next) != (saved_total, saved_entries, saved_next):
                    raise FetchError("partial", "SuccessFactors inventory changed during scan.")
        else:
            check_total,check,_check_next=_listing(client,url,0)
            if check_total != total or check != first: raise FetchError("partial","SuccessFactors inventory changed during scan.")
        return Inventory("complete",jobs,f"SuccessFactors: retrieved {len(jobs)} complete postings and rechecked the public inventory.",url,"SuccessFactors")
    except FetchError as e: return Inventory(e.status if not jobs else "partial",jobs,e.reason,url,"SuccessFactors")
    except (ValueError,TypeError,AttributeError): return Inventory("partial",jobs,"SuccessFactors public schema validation failed.",url,"SuccessFactors")
