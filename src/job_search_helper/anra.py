"""ANRA Technologies' first-party WordPress careers posts."""
from __future__ import annotations
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE="https://www.anratechnologies.com/home/careers/"
HOST="www.anratechnologies.com"
PREFIX="/home/"

class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.links=[]; self.parts=[]; self.headings=[]; self._h=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href'): self.links.append(a['href'])
        if tag in {'h1','h2'}: self._h=[]
    def handle_data(self,data):
        self.parts.append(data)
        if self._h is not None: self._h.append(data)
    def handle_endtag(self,tag):
        if tag in {'h1','h2'} and self._h is not None: self.headings.append(text(' '.join(self._h))); self._h=None

def _read(client,url):
    r=client.get(url)
    if r.status in (401,403,429): raise FetchError('blocked','ANRA careers page was blocked.')
    if r.status != 200: raise FetchError('partial',f'ANRA careers page HTTP {r.status}.')
    return r.body.decode('utf-8','replace')

def _links(html):
    # Job cards are the six h2-linked WordPress posts; navigation links under
    # the same /home/ namespace are deliberately excluded.
    out=[]
    for href in re.findall(r'<h2[^>]*>\s*<a[^>]+href=["\']([^"\']+)', html, re.I|re.S):
        u=urljoin(SOURCE,href); q=urlsplit(u)
        if q.scheme=='https' and q.hostname==HOST and q.path.startswith(PREFIX) and q.path.rstrip('/') != '/home/careers' and not q.query and not q.fragment and u not in out:
            out.append(u)
    return out

def fetch_anra(careers_url,company_id,company,transport=None):
    client=transport or CareersTransport(); jobs=[]
    try:
        first=_links(_read(client,SOURCE))
        if len(first)!=6: raise FetchError('partial',f'ANRA careers link set changed; found {len(first)} links.')
        seen=set()
        for url in first:
            p=_Page(); p.feed(_read(client,url)); title=next((h for h in p.headings if h.lower() not in {'careers','home careers'}),'')
            body=text(' '.join(p.parts))
            if not title or len(body)<500 or 'anra' not in body.casefold(): raise FetchError('partial','ANRA detail lacks a complete employer-scoped description.')
            ident=urlsplit(url).path.rstrip('/')
            if ident in seen: raise FetchError('partial','ANRA careers link set has duplicate posting IDs.')
            seen.add(ident); row=_base({'id':ident},'ANRA WordPress',company_id,company); row.update(title=title,description=body,url=url); jobs.append(row)
        if _links(_read(client,SOURCE)) != first: raise FetchError('partial','ANRA careers link set changed during the scan.')
        return Inventory('complete',jobs,f'ANRA: retrieved {len(jobs)} full postings and rechecked the public inventory.',SOURCE,'ANRA WordPress')
    except FetchError as e: return Inventory(e.status,jobs,e.reason,SOURCE,'ANRA WordPress')
    except (AttributeError,TypeError,ValueError): return Inventory('partial',jobs,'ANRA careers schema validation failed.',SOURCE,'ANRA WordPress')
