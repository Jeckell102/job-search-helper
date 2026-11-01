"""Freefly Systems' first-party careers portal."""
from __future__ import annotations
import json, re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://freeflysystems.com/careers/open"
HOST = "freeflysystems.com"
ID_RE = re.compile(r"^c[a-z0-9]{20,32}$")

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.parts=[]; self.scripts=[]; self._script=None
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag == "script": self._script=[]
    def handle_data(self, data):
        self.parts.append(data)
        if self._script is not None: self._script.append(data)
    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script)); self._script=None

def _read(client, url):
    r=client.get(url)
    if r.status in (401,403,429): raise FetchError("blocked", "Freefly careers page was blocked.")
    if r.status != 200: raise FetchError("partial", f"Freefly careers page HTTP {r.status}.")
    return r.body.decode("utf-8", "replace")

def _listing(html):
    p=_Page(); p.feed(html); rows=[]
    for script in p.scripts:
        if not script.strip().startswith("["): continue
        try: candidate=json.loads(script)
        except (ValueError, TypeError): continue
        if isinstance(candidate,list) and candidate and all(isinstance(x,dict) for x in candidate) and all("id" in x and "title" in x for x in candidate):
            rows=candidate; break
    if not rows: raise FetchError("partial", "Freefly careers listing has no structured job inventory.")
    out=[]; seen=set()
    for row in rows:
        ident=row.get("id"); title=text(row.get("title"))
        if not isinstance(ident,str) or not ID_RE.fullmatch(ident) or not title or ident in seen:
            raise FetchError("partial", "Freefly careers listing has an invalid or duplicate posting.")
        seen.add(ident); out.append((ident,title))
    return out

def fetch_freefly(careers_url, company_id, company, transport=None):
    client=transport or CareersTransport(); jobs=[]
    try:
        first=_listing(_read(client,SOURCE))
        if len(first) != 15: raise FetchError("partial", f"Freefly careers inventory changed; found {len(first)} postings.")
        for ident,title in first:
            url=f"https://{HOST}/careers/{ident}"
            p=_Page(); p.feed(_read(client,url)); body=text(" ".join(p.parts))
            if len(body)<500 or "freefly" not in body.casefold(): raise FetchError("partial", "Freefly job detail lacks a complete employer-scoped body.")
            row=_base({"id":ident},"Freefly Careers",company_id,company)
            row.update(title=title,description=body,url=url); jobs.append(row)
        second=_listing(_read(client,SOURCE))
        if second != first: raise FetchError("partial", "Freefly careers inventory changed during the scan.")
        return Inventory("complete",jobs,f"Freefly: retrieved {len(jobs)} full postings and rechecked the public inventory.",SOURCE,"Freefly Careers")
    except FetchError as e: return Inventory(e.status,jobs,e.reason,SOURCE,"Freefly Careers")
    except (AttributeError,TypeError,ValueError): return Inventory("partial",jobs,"Freefly careers schema validation failed.",SOURCE,"Freefly Careers")
