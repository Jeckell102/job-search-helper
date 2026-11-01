"""KUKA's public vacancies feed with an explicit KUKA employer scope."""
from html.parser import HTMLParser
from urllib.parse import urljoin
from .ats import FetchError, Inventory, _base, _json, text
from .discovery import CareersTransport

SOURCE = "https://www.kuka.com/en-us/company/careers/vacancies"
FEED = "https://www.kuka.com/en-us/api/job/getjobs?searchrootpath=DCB6206EA76F4CCFAAC81F77D8E1FFC2&filters=BE72163E70594C11A60DAB1ADA205839%7CFC4F967286724664972D3368B99637F3"
KUKA_FACET = "BE72163E70594C11A60DAB1ADA205839|FC4F967286724664972D3368B99637F3"

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.head=[]; self.in_head=False
    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2"}: self.in_head=True; self.head=[]
    def handle_data(self, data):
        self.parts.append(data)
        if self.in_head: self.head.append(data)
    def handle_endtag(self, tag):
        if tag in {"h1", "h2"}: self.in_head=False

def _read(client, url):
    r=client.get(url)
    if r.status in (401,403,429): raise FetchError("blocked", "KUKA public vacancies endpoint was blocked.")
    if r.status != 200: raise FetchError("partial", f"KUKA endpoint HTTP {r.status}.")
    return r.body.decode("utf-8", "replace")

def _feed(client):
    data=_json(FEED, client)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list): raise FetchError("partial", "KUKA vacancies feed returned an unexpected schema.")
    rows=data["items"]
    if len(rows) != 115 or any(not isinstance(x, dict) or KUKA_FACET not in (x.get("facets") or []) for x in rows):
        raise FetchError("partial", "KUKA employer-scoped feed changed or contains non-KUKA postings.")
    urls=[]
    for row in rows:
        u=urljoin(SOURCE, str(row.get("href", "")))
        if not u.startswith("https://www.kuka.com/") or u in urls: raise FetchError("partial", "KUKA feed contained an invalid or duplicate posting URL.")
        urls.append(u)
    return rows, urls

def fetch_kuka(careers_url, company_id, company, transport=None):
    client=transport or CareersTransport()
    try:
        rows, urls=_feed(client); jobs=[]
        for row,u in zip(rows,urls):
            p=_Page(); p.feed(_read(client,u)); body=text(" ".join(p.parts)); title=text(p.head[0] if p.head else row.get("headline"))
            if not title or len(body)<500: raise FetchError("partial", "KUKA detail lacks a full description.")
            jobs.append(_base({"id":u},"KUKA",company_id,company)|{"title":title,"description":body,"url":u,"location":text(row.get("location"))})
        _, reread=_feed(client)
        if reread != urls: raise FetchError("partial", "KUKA employer-scoped inventory changed during reread.")
        return Inventory("complete",jobs,f"KUKA: retrieved {len(jobs)} employer-scoped postings with full descriptions.",SOURCE,"KUKA")
    except FetchError as e: return Inventory(e.status,[],e.reason,SOURCE,"KUKA")
    except Exception as e: return Inventory("partial",[],f"KUKA validation failed ({type(e).__name__}).",SOURCE,"KUKA")
