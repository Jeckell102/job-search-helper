"""Grex Defense's bounded first-party static careers pages."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport
SOURCE="https://grexdefense.com/careers"
class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.parts=[]; self.heading=[]; self.in_heading=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="a" and a.get("href"): self.links.append(a["href"])
        if tag in {"h1","h2"}: self.in_heading=True; self.heading=[]
    def handle_data(self,data):
        self.parts.append(data)
        if self.in_heading:self.heading.append(data)
    def handle_endtag(self,tag):
        if tag in {"h1","h2"}: self.in_heading=False
def _read(client,url):
    r=client.get(url)
    if r.status in (401,403,429): raise FetchError("blocked","Grex Defense careers page was blocked.")
    if r.status!=200: raise FetchError("partial",f"Grex Defense page HTTP {r.status}.")
    return r.body.decode("utf-8","replace")
def _urls(html):
    p=_Page();p.feed(html);out=[]
    for href in p.links:
        u=urljoin(SOURCE,href);q=urlsplit(u)
        if q.scheme=="https" and q.hostname in {"grexdefense.com","www.grexdefense.com"} and q.path.startswith("/careers/") and q.path.rstrip("/")!="/careers" and u not in out:out.append(u)
    return out
def fetch_grex_defense(careers_url,company_id,company,transport=None):
    client=transport or CareersTransport()
    try:
        first=_read(client,SOURCE);urls=_urls(first)
        if len(urls)!=5:raise FetchError("partial",f"Grex Defense careers link set changed; found {len(urls)} job links.")
        jobs=[]
        for u in urls:
            p=_Page();p.feed(_read(client,u));body=text(" ".join(p.parts));title=text(p.heading[0] if p.heading else "")
            if not title or len(body)<500:raise FetchError("partial","Grex Defense detail lacks a full description.")
            jobs.append(_base({"id":u},"Browser",company_id,company)|{"title":title,"description":body,"url":u})
        if _urls(_read(client,SOURCE))!=urls:raise FetchError("partial","Grex Defense link set changed during reread.")
        return Inventory("complete",jobs,f"Grex Defense: retrieved {len(jobs)} full postings and rechecked the five-link inventory.",SOURCE,"Grex Defense")
    except FetchError as e:return Inventory(e.status,[],e.reason,SOURCE,"Grex Defense")
    except Exception as e:return Inventory("partial",[],f"Grex Defense validation failed ({type(e).__name__}).",SOURCE,"Grex Defense")
