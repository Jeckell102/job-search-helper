"""Composite adapters for Redwire Space and Redwire Defense Tech."""
from __future__ import annotations
from html.parser import HTMLParser
import json, re, time
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SPACE_SOURCE = "https://careers.rdw.com/jobs/search"
DEFENSE_SOURCE = "https://jobs.jobvite.com/edgeautonomy-careers/jobs"
SOURCE = SPACE_SOURCE
HOST, DEFENSE_HOST = "careers.rdw.com", "jobs.jobvite.com"
ATS = "Redwire careers (Space + Defense Tech)"
SPACE_ATS, DEFENSE_ATS = "Redwire Space (Clinch)", "Redwire Defense Tech (Jobvite)"
COMPANY_ID, COMPANY = "COMP-0378", "Redwire"
MAX_PAGES, MAX_JOBS = 100, 10000


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.scripts=[]; self._a=None; self._s=None
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"): self._a=[a["href"],[]]
        if tag=="script" and a.get("type","").lower()=="application/ld+json": self._s=[]
    def handle_data(self, data):
        if self._a is not None:self._a[1].append(data)
        if self._s is not None:self._s.append(data)
    def handle_endtag(self, tag):
        if tag=="a" and self._a is not None:self.links.append((self._a[0],text(" ".join(self._a[1]))));self._a=None
        if tag=="script" and self._s is not None:self.scripts.append("".join(self._s));self._s=None


class RedwireSession:
    """One reusable anonymous session with independent host pacing."""
    def __init__(self, transport=None, interval=.4, sleep=time.sleep):
        self.transport=transport or CareersTransport(); self.interval=interval; self.sleep=sleep; self.last_by_host={}
    def get(self, url):
        host=urlsplit(url).hostname or ""; last=self.last_by_host.get(host,0.0)
        self.sleep(max(0.0,self.interval-(time.monotonic()-last))); self.last_by_host[host]=time.monotonic()
        return self.transport.get(url)


def _valid(url, host, path, cid, company):
    try:
        p=urlsplit(url); return (cid==COMPANY_ID and str(company).strip().casefold()==COMPANY.casefold()
          and p.scheme=="https" and p.hostname==host and p.path.rstrip("/")==path and not p.query and not p.fragment)
    except (AttributeError,TypeError,ValueError): return False

def _read(client,url,label):
    r=client.get(url)
    if not isinstance(r,HTTPResponse): raise FetchError("failed",f"Redwire {label} transport returned an invalid response.")
    if r.status in {401,403,429} or _challenge(r,expect_html=True): raise FetchError("blocked",f"Redwire {label} board was blocked (HTTP {r.status}).")
    if r.status!=200: raise FetchError("partial",f"Redwire {label} board HTTP {r.status}.")
    body=r.body.decode("utf-8","replace")
    if not body.strip(): raise FetchError("partial",f"Redwire {label} board was blank.")
    return body

def _space_listing(client,progress=None):
    first=_read(client,SPACE_SOURCE,"Space"); pages={1:first}; p=_Page();p.feed(first);p.close(); nums=set()
    for href,_ in p.links:
        u=urljoin(SPACE_SOURCE,href); q=urlsplit(u)
        if q.hostname==HOST and q.path.rstrip("/")=="/jobs/search":
            m=re.search(r"(?:^|&)page=(\d+)(?:&|$)",q.query)
            if m: nums.add(int(m.group(1)))
    for n in range(2,min(MAX_PAGES,max(nums or {1}))+1): pages[n]=_read(client,f"{SPACE_SOURCE}?page={n}","Space")
    out=[];seen=set()
    for body in pages.values():
        p=_Page();p.feed(body);p.close()
        for href,title in p.links:
            u=urljoin(SPACE_SOURCE,href); q=urlsplit(u)
            if q.scheme!="https" or q.hostname!=HOST or not q.path.startswith("/jobs/") or q.path.rstrip("/")=="/jobs/search" or q.query or q.fragment or u in seen: continue
            if not title.strip(): raise FetchError("partial","Redwire Space listing contained a posting without a title.")
            seen.add(u);out.append((u,title.strip()))
    if not out: raise FetchError("partial","Redwire Space listing exposed no verifiable job links.")
    if progress is not None: progress.save_listing({"queue":[],"visited":[u for u,_ in out],"complete":True})
    return out

def _posting(body,label):
    p=_Page();p.feed(body);p.close()
    for raw in p.scripts:
        try:v=json.loads(raw)
        except (TypeError,ValueError):continue
        for x in (v if isinstance(v,list) else [v]):
            if isinstance(x,dict) and x.get("@type")=="JobPosting":return x
    raise FetchError("partial",f"Redwire {label} detail page lacked a valid JobPosting record.")

def _locations(value):
    if not isinstance(value,list):value=[value]
    out=[]
    for x in value:
        if not isinstance(x,dict):continue
        a=x.get("address") if isinstance(x.get("address"),dict) else {}
        s=", ".join(str(a[k]).strip() for k in ("addressLocality","addressRegion","addressCountry") if a.get(k))
        if s and s not in out:out.append(s)
    return "; ".join(out)

def _space_jobs(client,listing,progress=None):
    out=[]
    for url,listed in listing:
        j=_posting(_read(client,url,"Space"),"Space"); title=text(j.get("title")); desc=text(j.get("description"))
        if not title or title!=listed or len(desc)<200:raise FetchError("partial",f"Redwire Space detail is incomplete for {listed}.")
        ident=j.get("identifier"); ident=ident.get("value") if isinstance(ident,dict) else ident
        row=_base({"id":"space:"+str(ident or url)},SPACE_ATS,COMPANY_ID,COMPANY)
        row.update(title=title,description=desc,url=url,location=_locations(j.get("jobLocation")),created_at=text(j.get("datePosted")),updated_at=text(j.get("datePosted")))
        out.append(row)
        if progress is not None:progress.save_job(url,row)
    return out

def fetch_redwire_space(careers_url,company_id,company,transport=None,progress_factory=None):
    if not _valid(careers_url,HOST,"/jobs/search",company_id,company):return Inventory("unsupported",reason="Redwire Space requires its verified Clinch search URL.",source_url=careers_url,ats=SPACE_ATS)
    c=transport or RedwireSession(); progress=progress_factory(SPACE_SOURCE) if progress_factory else None
    try:
        listing=_space_listing(c,progress); jobs=_space_jobs(c,listing,progress); reread=_space_listing(c)
        if [u for u,_ in reread]!=[u for u,_ in listing]:raise FetchError("partial","Redwire Space inventory changed during the reread.")
        return Inventory("complete",jobs,f"Redwire Space: retrieved {len(jobs)} full Clinch postings and rechecked the inventory.",SPACE_SOURCE,SPACE_ATS)
    except FetchError as e:return Inventory(e.status,[],e.reason,SPACE_SOURCE,SPACE_ATS)

def fetch_redwire_defense(careers_url,company_id,company,transport=None):
    if not _valid(careers_url,DEFENSE_HOST,"/edgeautonomy-careers/jobs",company_id,company):return Inventory("unsupported",reason="Redwire Defense Tech requires its verified Jobvite board URL.",source_url=careers_url,ats=DEFENSE_ATS)
    try:
        from .shared_boards import fetch_shared
        return fetch_shared("Jobvite",DEFENSE_SOURCE,company_id,company,transport=transport or RedwireSession())
    except (AttributeError,TypeError,ValueError,OSError) as e:return Inventory("partial",reason=f"Redwire Defense Tech validation failed ({type(e).__name__}).",source_url=DEFENSE_SOURCE,ats=DEFENSE_ATS)

def _dedupe(jobs):
    out=[]; seen=set()
    for j in jobs:
        u=str(j.get("url","")).split("#",1)[0].rstrip("/").casefold(); key=("url",u) if u else ("job",text(j.get("title")).casefold(),text(j.get("location")).casefold())
        if key not in seen:seen.add(key);out.append(j)
    return out

def fetch_redwire(careers_url,company_id,company,transport=None,*,discovery_transport=None,progress_factory=None):
    if company_id!=COMPANY_ID or str(company).strip().casefold()!=COMPANY.casefold():return Inventory("unsupported",reason="Redwire adapter received an unexpected company scope.",source_url=careers_url,ats=ATS)
    c=transport or RedwireSession(discovery_transport); space=fetch_redwire_space(SPACE_SOURCE,company_id,company,c,progress_factory); defense=fetch_redwire_defense(DEFENSE_SOURCE,company_id,company,c); jobs=_dedupe(space.jobs+defense.jobs)
    if space.status=="complete" and defense.status=="complete": status="complete";reason=f"Redwire composite: both official source sets passed with {len(jobs)} de-duplicated postings."
    else: status="blocked" if "blocked" in {space.status,defense.status} else "partial";reason=f"Redwire composite incomplete: Space={space.status}; Defense Tech={defense.status}. "+"; ".join(x.reason for x in (space,defense) if x.reason)
    return Inventory(status,jobs,reason,SPACE_SOURCE+" + "+DEFENSE_SOURCE,ATS)
