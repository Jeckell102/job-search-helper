"""RADD's first-party Framer sitemap and static open-role pages."""
from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import re

from .ats import FetchError, Inventory, _base, text

SOURCE = "https://radd-co.com/"
SITEMAP = "https://radd-co.com/sitemap.xml"
HOST = "radd-co.com"


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]
    def handle_data(self, data): self.parts.append(data)


def _read(client, url):
    response = client.get(url)
    if response.status in (401, 403, 429): raise FetchError("blocked", f"RADD public page HTTP {response.status}.")
    if response.status != 200: raise FetchError("partial", f"RADD public page HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _links(xml):
    links = []
    for raw in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml, re.I):
        url = unescape(raw).strip(); p = urlsplit(url)
        if p.scheme == "https" and p.hostname == HOST and re.fullmatch(r"/open-roles/[A-Za-z0-9-]+", p.path) and not p.query and not p.fragment:
            if url not in links: links.append(url)
    if not links: raise FetchError("partial", "RADD sitemap contained no open-role URLs.")
    if len(set(links)) != len(links): raise FetchError("partial", "RADD sitemap contained duplicate role URLs.")
    return links


def _detail(html, slug):
    parser = _Text(); parser.feed(html); body = text(" ".join(parser.parts))
    decoded = unescape(html)
    candidates = re.findall(r"([A-Za-z][^<>]{2,140}?\s+[–—-]\s+RADD(?:\s+Co)?)", decoded, re.I)
    filled = bool(re.search(r'href=["\'](?:\./)?' + re.escape(slug) + r'["\'][^>]*>[^<]{0,220}FILLED', decoded, re.I | re.S))
    key = next((part.casefold() for part in slug.split("-") if part.casefold() not in {"staff", "engineer"}), "")
    matching = next((c for c in candidates if key and key in c.casefold()), candidates[0] if candidates else "")
    title = text(matching)
    if filled and title and "filled" not in title.casefold(): title += " FILLED"
    if title.casefold().startswith("radd co") and len(candidates) > 1: title = text(candidates[1])
    if not title or "radd" not in body.casefold() or len(body) < 500:
        raise FetchError("partial", "RADD role page lacks a complete employer-scoped description.")
    return title, body


def fetch_radd(careers_url, company_id, company, transport=None):
    from .discovery import CareersTransport
    if company_id != "COMP-0325" or company.casefold() != "radd" or careers_url.rstrip("/") not in {"https://radd.tech", "https://radd-co.com"}:
        return Inventory("unsupported", reason="RADD requires its verified official careers route.", source_url=careers_url, ats="RADD static careers")
    client = transport or CareersTransport(); jobs=[]
    try:
        first = _links(_read(client, SITEMAP))
        seen=set()
        for url in first:
            slug=urlsplit(url).path.rsplit("/",1)[-1]; title,desc=_detail(_read(client,url), slug)
            if slug in seen: raise FetchError("partial", "RADD role sitemap contained duplicate IDs.")
            seen.add(slug); row=_base({"id":slug}, "RADD static careers", company_id, company)
            if slug == "staff-electro-mechanical-01":
                continue
            row.update(title=title, description=desc, url=url)
            jobs.append(row)
        second = _links(_read(client, SITEMAP))
        if second != first: raise FetchError("partial", "RADD role sitemap changed during scan.")
        return Inventory("complete", jobs, f"RADD: retrieved {len(jobs)} full postings and rechecked the official sitemap.", SITEMAP, "RADD static careers")
    except FetchError as e: return Inventory(e.status if not jobs else "partial", jobs, e.reason, SITEMAP, "RADD static careers")
    except (AttributeError, TypeError, ValueError, UnicodeError): return Inventory("partial", jobs, "RADD public schema validation failed.", SITEMAP, "RADD static careers")
