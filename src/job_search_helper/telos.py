"""Telos Corporation's public HRsmart board."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text

SOURCE = "https://telos.hua.hrsmart.com/hr/ats/JobSearch/index"
HOST = "telos.hua.hrsmart.com"
VIEW = "https://telos.hua.hrsmart.com/hr/ats/JobSearch/viewAll/jobSearchPaginationExternal_pageSize:100/jobSearchPaginationExternal_page:1"


class _Listing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.rows=[]; self.row=None; self.cell=[]; self.link=None; self.display=""
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "tr" and self.row is None: self.row=[]
        elif self.row is not None and tag == "td": self.cell=[]
        elif self.row is not None and tag == "a" and a.get("href"):
            self.link=a["href"]
        if a.get("class") and "displaycount" in a["class"]: self.cell=[]
    def handle_data(self, data):
        if self.row is not None and self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag == "td" and self.row is not None and self.cell is not None:
            self.row.append((text(" ".join(self.cell)), self.link)); self.cell=None; self.link=None
        elif tag == "tr" and self.row is not None:
            if any(href and "/Posting/view/" in href for _,href in self.row): self.rows.append(self.row)
            self.row=None


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.stack=[]; self.parts={}; self.current=None
    def handle_starttag(self, tag, attrs):
        aid=dict(attrs).get("id", "")
        if aid.startswith("job_details_"):
            self.current=aid; self.parts[aid]=[]
        if self.current: self.stack.append(tag)
    def handle_data(self, data):
        if self.current: self.parts[self.current].append(data)
    def handle_endtag(self, tag):
        if self.current and self.stack:
            self.stack.pop()
            if not self.stack: self.current=None


def _read(client, url):
    response=client.get(url)
    if response.status in (401,403,429): raise FetchError("blocked", f"Telos HRsmart HTTP {response.status}.")
    if response.status != 200: raise FetchError("partial", f"Telos HRsmart HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _listing(html):
    page=_Listing(); page.feed(html); out=[]
    for row in page.rows:
        href=next((h for _,h in row if h and "/Posting/view/" in h), None)
        if not href: continue
        u=urljoin(VIEW, href); p=urlsplit(u)
        if p.scheme != "https" or p.hostname != HOST or not p.path.startswith("/hr/ats/Posting/view/"): raise FetchError("partial", "Telos listing contained an unsafe detail URL.")
        rid=p.path.rsplit("/",1)[-1]
        if not rid.isdigit(): raise FetchError("partial", "Telos listing contained a malformed requisition ID.")
        cells=[v for v,_ in row]
        out.append((rid, cells[0] if cells else "", u, cells))
    if not out: raise FetchError("partial", "Telos HRsmart listing contained no verifiable jobs.")
    if len({x[0] for x in out}) != len(out): raise FetchError("partial", "Telos HRsmart listing contained duplicate requisition IDs.")
    return out


def fetch_telos(careers_url, company_id, company, transport=None):
    from .discovery import CareersTransport
    client=transport or CareersTransport(); jobs=[]
    if company_id != "COMP-0308" or company.casefold() != "telos corporation" or careers_url.rstrip("/") not in {"https://www.telos.com/careers", SOURCE.rstrip("/")}:
        return Inventory("unsupported", reason="Telos requires its verified official careers route.", source_url=careers_url, ats="HRsmart")
    try:
        first=_listing(_read(client, VIEW)); ids={x[0] for x in first}
        for rid, listed_title, url, cells in first:
            d=_Detail(); d.feed(_read(client,url)); title=text(" ".join(d.parts.get("job_details_ats_requisition_title", [])))
            desc=text(" ".join(d.parts.get("job_details_ats_requisition_description", []) + d.parts.get("job_details_ats_requisition_requirements", [])))
            loc=text(" ".join(d.parts.get("job_details_hua_location_id", [])))
            if not title or not desc or len(desc) < 200: raise FetchError("partial", f"Telos detail {rid} lacks a complete employer-scoped description.")
            if listed_title and title.casefold() != listed_title.casefold(): raise FetchError("partial", f"Telos detail {rid} title differs from listing.")
            row=_base({"id":rid}, "HRsmart", company_id, company); row.update(title=title, description=desc, location=loc, url=url, requisition_id=rid)
            jobs.append(row)
        second=_listing(_read(client, VIEW))
        if {x[0] for x in second} != ids or {x[0]:x[1] for x in second} != {x[0]:x[1] for x in first}: raise FetchError("partial", "Telos HRsmart inventory changed during scan.")
        return Inventory("complete", jobs, f"Telos HRsmart: retrieved {len(jobs)} full postings and rechecked the public inventory.", VIEW, "HRsmart")
    except FetchError as e: return Inventory(e.status if not jobs else "partial", jobs, e.reason, VIEW, "HRsmart")
    except (AttributeError, TypeError, ValueError, UnicodeError): return Inventory("partial", jobs, "Telos HRsmart public schema validation failed.", VIEW, "HRsmart")
