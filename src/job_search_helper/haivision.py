"""Haivision's bounded first-party static careers pages."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://www.haivision.com/about/careers/"

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.parts=[]; self.heading=[]; self.in_heading=False
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag == "a" and a.get("href"): self.links.append(a["href"])
        if tag in {"h1","h2"}: self.in_heading=True; self.heading=[]
    def handle_data(self, data):
        self.parts.append(data)
        if self.in_heading: self.heading.append(data)
    def handle_endtag(self, tag):
        if tag in {"h1","h2"}: self.in_heading=False

def _read(client, url):
    r=client.get(url)
    if r.status in (401,403,429): raise FetchError("blocked", "Haivision careers page was blocked.")
    if r.status != 200: raise FetchError("partial", f"Haivision careers page HTTP {r.status}.")
    return r.body.decode("utf-8", "replace")

def _inventory(html, company_id, company):
    p=_Page(); p.feed(html); host=urlsplit(SOURCE).hostname
    urls=[]
    for href in p.links:
        u=urljoin(SOURCE,href); q=urlsplit(u)
        if q.scheme=="https" and q.hostname==host and q.path.startswith("/about/careers/") and q.path.rstrip("/") != "/about/careers" and u not in urls: urls.append(u)
    if len(urls) != 4: raise FetchError("partial", f"Haivision careers link set changed; found {len(urls)} job links.")
    return urls

def fetch_haivision(careers_url, company_id, company, transport=None):
    client=transport or CareersTransport()
    try:
        first=_read(client, SOURCE); urls=_inventory(first,company_id,company); jobs=[]
        for u in urls:
            page=_Page(); page.feed(_read(client,u)); body=text(" ".join(page.parts))
            title=text(page.heading[0] if page.heading else "")
            if not title or len(body) < 500: raise FetchError("partial", "Haivision job detail lacks a full description.")
            jobs.append(_base({"id":u},"Browser",company_id,company) | {"title":title,"description":body,"url":u})
        second=_inventory(_read(client,SOURCE),company_id,company)
        if second != urls: raise FetchError("partial", "Haivision careers link set changed during reread.")
        return Inventory("complete",jobs,f"Haivision: retrieved {len(jobs)} full postings and rechecked the four-link inventory.",SOURCE,"Haivision")
    except FetchError as e: return Inventory(e.status,[],e.reason,SOURCE,"Haivision")
    except Exception as e: return Inventory("partial",[],f"Haivision validation failed ({type(e).__name__}).",SOURCE,"Haivision")
