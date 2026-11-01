"""Exyn's first-party embedded open-positions page."""
from __future__ import annotations
from html.parser import HTMLParser
import re
from .ats import FetchError, Inventory, _base, text

SOURCE="https://www.exyn.com/about/careers"

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.active=False; self.depth=0; self.in_title=False; self.content_depth=None; self.cur=None; self.jobs=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=="div" and "slide-inner" in a.get("class",""):
            self.active=True; self.depth=1; self.cur={"title":[],"body":[]}; return
        if self.active and tag == "div": self.depth+=1
        if self.active and tag=="h3" and "slide-title" in a.get("class",""): self.in_title=True
        if self.active and tag=="div" and "slide-content" in a.get("class",""): self.content_depth=self.depth
    def handle_data(self,data):
        if not self.active: return
        if self.in_title: self.cur["title"].append(data)
        if self.content_depth is not None and self.depth>=self.content_depth: self.cur["body"].append(data)
    def handle_endtag(self,tag):
        if not self.active: return
        if tag=="h3": self.in_title=False
        if tag=="div":
            if self.content_depth==self.depth: self.content_depth=None
            self.depth-=1
            if self.depth==0:
                title=text(" ".join(self.cur["title"])); body=text(" ".join(self.cur["body"]))
                if title and body: self.jobs.append((title,body))
                self.active=False; self.cur=None

def _read(client):
    r=client.get(SOURCE)
    if r.status in (401,403,429): raise FetchError("blocked",f"Exyn careers HTTP {r.status}.")
    if r.status!=200: raise FetchError("partial",f"Exyn careers HTTP {r.status}.")
    return r.body.decode("utf-8","replace")

def _parse(html):
    p=_Page(); p.feed(html); out=[]; seen=set()
    for title,body in p.jobs:
        if title in seen: continue
        seen.add(title)
        if len(body)<500 or "exyn" not in body.casefold(): raise FetchError("partial","Exyn role page lacks a complete employer-scoped description.")
        rid=re.sub(r"[^a-z0-9]+","-",title.casefold()).strip("-"); row=_base({"id":rid},"Exyn careers", "COMP-0328", "Exyn Technologies")
        row.update(title=title,description=body,url=SOURCE); out.append(row)
    if not out: raise FetchError("partial","Exyn careers page contained no verifiable roles.")
    return out

def fetch_exyn(careers_url, company_id, company, transport=None):
    from .discovery import CareersTransport
    if company_id!="COMP-0328" or company.casefold()!="exyn technologies" or careers_url.rstrip("/")!=SOURCE: return Inventory("unsupported",reason="Exyn requires its verified official careers page.",source_url=careers_url,ats="Exyn careers")
    client=transport or CareersTransport(); jobs=[]
    try:
        first=_parse(_read(client)); jobs=first; second=_parse(_read(client))
        if {j["posting_id"] for j in first}!={j["posting_id"] for j in second}: raise FetchError("partial","Exyn open-role inventory changed during scan.")
        return Inventory("complete",jobs,f"Exyn: retrieved {len(jobs)} full postings and rechecked the careers page.",SOURCE,"Exyn careers")
    except FetchError as e: return Inventory(e.status if not jobs else "partial",jobs,e.reason,SOURCE,"Exyn careers")
    except (TypeError,ValueError,AttributeError,UnicodeError): return Inventory("partial",jobs,"Exyn careers schema validation failed.",SOURCE,"Exyn careers")
