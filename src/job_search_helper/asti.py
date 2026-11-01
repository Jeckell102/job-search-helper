"""ASTi's first-party static available-positions page."""
from __future__ import annotations
from html.parser import HTMLParser
from .ats import FetchError, Inventory, _base, text

SOURCE = "https://www.asti-usa.com/jobs/positions.html"

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.depth=0; self.active=False; self.cur=None; self.in_title=False; self.jobs=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="div" and "accordion-group" in a.get("class",""):
            self.active=True; self.depth=1; self.cur={"title":[],"body":[]}; return
        if self.active:
            if tag=="div": self.depth+=1
            if tag=="h3": self.in_title=True
            elif self.depth>=1 and tag in {"p","li","h4","h5","strong","br"}: self.cur["body"].append(" ")
    def handle_data(self,data):
        if not self.active: return
        if self.in_title: self.cur["title"].append(data)
        else: self.cur["body"].append(data)
    def handle_endtag(self,tag):
        if not self.active: return
        if tag=="h3": self.in_title=False
        if tag=="div":
            self.depth-=1
            if self.depth==0:
                title=text(" ".join(self.cur["title"])); body=text(" ".join(self.cur["body"]))
                if title and body: self.jobs.append((title,body))
                self.active=False; self.cur=None

def _read(client):
    r=client.get(SOURCE)
    if r.status in (401,403,429): raise FetchError("blocked",f"ASTi positions HTTP {r.status}.")
    if r.status!=200: raise FetchError("partial",f"ASTi positions HTTP {r.status}.")
    return r.body.decode("utf-8","replace")

def _parse(html):
    p=_Page(); p.feed(html); out=[]; seen=set()
    for title,body in p.jobs:
        if title in seen: continue
        seen.add(title)
        if len(body)<500 or "asti" not in body.casefold(): raise FetchError("partial","ASTi position lacks a complete employer-scoped description.")
        rid="asti-"+"-".join(x for x in title.casefold().split() if x.isalnum())
        row=_base({"id":rid},"ASTi careers","COMP-0336","Advanced Simulation Technology inc. (ASTi)")
        row.update(title=title,description=body,url=SOURCE); out.append(row)
    if len(out)!=2: raise FetchError("partial",f"ASTi positions page exposed {len(out)} verifiable roles, expected the two published positions.")
    return out

def fetch_asti(careers_url,company_id,company,transport=None):
    from .discovery import CareersTransport
    if company_id!="COMP-0336" or company.casefold()!="advanced simulation technology inc. (asti)" or careers_url.rstrip("/") not in {"https://www.asti-usa.com/careers","https://www.asti-usa.com/jobs/positions.html"}:
        return Inventory("unsupported",reason="ASTi requires its verified first-party positions page.",source_url=careers_url,ats="ASTi careers")
    client=transport or CareersTransport(); jobs=[]
    try:
        first=_parse(_read(client)); jobs=first; second=_parse(_read(client))
        if {j["posting_id"] for j in first}!={j["posting_id"] for j in second}: raise FetchError("partial","ASTi position inventory changed during scan.")
        return Inventory("complete",jobs,f"ASTi: retrieved {len(jobs)} full postings and rechecked the positions page.",SOURCE,"ASTi careers")
    except FetchError as e: return Inventory(e.status if not jobs else "partial",jobs,e.reason,SOURCE,"ASTi careers")
    except (TypeError,ValueError,AttributeError,UnicodeError): return Inventory("partial",jobs,"ASTi positions schema validation failed.",SOURCE,"ASTi careers")
