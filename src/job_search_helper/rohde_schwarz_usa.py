"""Rohde & Schwarz USA's first-party, offset-paged careers board."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport


SOURCE = "https://www.rohde-schwarz.com/us/career/jobs/career-jobboard_251573.html"
HOST = "www.rohde-schwarz.com"
ATS = "Rohde & Schwarz USA careers"
PAGE_SIZE = 30
DETAIL_RE = re.compile(r"^/us/career/jobs/[A-Za-z0-9][^/]*_251563-(\d+)\.html$")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.anchor: dict[str, str] | None = None
        self.links: list[tuple[str, str]] = []
        self.parts: list[str] = []
        self.h1: list[str] = []
        self.in_h1 = False
        self.json_ld: list[str] = []
        self.in_json_ld = False
        self._json_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main":
            self.main_depth += 1
        if tag == "a" and attrs.get("href"):
            self.anchor = {"href": attrs["href"], "text": ""}
        if self.main_depth and tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")
        if self.main_depth and tag == "h1":
            self.in_h1 = True
        if tag == "script" and attrs.get("type", "").casefold() == "application/ld+json":
            self.in_json_ld = True
            self._json_parts = []

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            self.links.append((self.anchor["href"], self.anchor["text"]))
            self.anchor = None
        if tag == "h1":
            self.in_h1 = False
        if tag == "main" and self.main_depth:
            self.main_depth -= 1
        if tag == "script" and self.in_json_ld:
            self.json_ld.append("".join(self._json_parts))
            self.in_json_ld = False
            self._json_parts = []
        if self.main_depth and tag in {"p", "li", "div"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["text"] += data
        if self.main_depth:
            self.parts.append(data)
            if self.in_h1:
                self.h1.append(data)
        if self.in_json_ld:
            self._json_parts.append(data)


class _StalePosting(Exception):
    pass


def _read(client, url: str) -> str:
    response = client.get(url)
    if response.status == 410:
        raise _StalePosting(url)
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"Rohde & Schwarz USA public careers page returned HTTP {response.status}.")
    if response.status != 200:
        raise FetchError("partial", f"Rohde & Schwarz USA public careers page HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _source_url(offset: int = 0) -> str:
    url = SOURCE + "?term=%2A&filter%5BrsCountry%5D%5B%5D=USA"
    return url if offset == 0 else url + f"&offset={offset}"


def _links(html: str) -> dict[str, str]:
    page = _Page()
    page.feed(html)
    result = {}
    for href, label in page.links:
        absolute = urljoin(SOURCE, href.strip())
        parsed = urlsplit(absolute)
        match = DETAIL_RE.fullmatch(parsed.path)
        if parsed.scheme != "https" or parsed.hostname != HOST or parsed.query or parsed.fragment or not match:
            continue
        if label.strip():
            result[match.group(1)] = absolute
    return result


def _declared_usa_total(html: str) -> int:
    match = re.search(r'id=["\']filter_USA["\'][^>]*>.*?<span[^>]*class=["\'][^"\']*job-search-result-count', html, re.I | re.S)
    if not match:
        raise FetchError("partial", "Rohde & Schwarz USA page omitted its USA result total.")
    tail = html[match.end():]
    count = re.search(r">\s*(\d+)\s*</span>", tail)
    if not count:
        raise FetchError("partial", "Rohde & Schwarz USA page contained an invalid USA result total.")
    total = int(count.group(1))
    if not 1 <= total <= 1000:
        raise FetchError("partial", "Rohde & Schwarz USA page contained an unsafe result total.")
    return total


def _job(client, url: str, company_id: str, company: str, posting_id: str) -> dict:
    page = _Page()
    page.feed(_read(client, url))
    title = text("".join(page.h1))
    description = text("".join(page.parts))
    if not title or len(description) < 500:
        raise FetchError("partial", "Rohde & Schwarz USA detail page lacks a full description.")
    if "rohde & schwarz" not in description.casefold():
        raise FetchError("partial", "Rohde & Schwarz USA detail page lacks employer identity.")
    reference = posting_id
    for raw in page.json_ld:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
            identifier = payload.get("identifier")
            if isinstance(identifier, dict) and identifier.get("value"):
                reference = str(identifier["value"])
            break
    row = _base({"id": reference}, ATS, company_id, company)
    row.update(title=title, url=url, description=description)
    return row


def _inventory(client, offset: int = 0) -> tuple[int, dict[str, str]]:
    html = _read(client, _source_url(offset))
    return (_declared_usa_total(html) if offset == 0 else -1), _links(html)


def fetch_rohde_schwarz_usa(careers_url, company_id, company, transport=None):
    if (careers_url.rstrip("/") != SOURCE or company_id != "COMP-0151"
            or company.casefold() != "rohde & schwarz usa"):
        return Inventory("unsupported", reason="Rohde & Schwarz USA adapter requires its verified USA job board.",
                         source_url=careers_url, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    stale = 0
    try:
        total, first_page = _inventory(client)
        all_links = dict(first_page)
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            _, page_links = _inventory(client, offset)
            if not page_links:
                raise FetchError("partial", f"Rohde & Schwarz USA page at offset {offset} was empty before {total} postings.")
            all_links.update(page_links)
        if len(all_links) != total:
            raise FetchError("partial", f"Rohde & Schwarz USA declared {total} USA postings but exposed {len(all_links)} unique links.")
        for posting_id, url in all_links.items():
            try:
                jobs.append(_job(client, url, company_id, company, posting_id))
            except _StalePosting:
                stale += 1
        _, reread_first = _inventory(client)
        reread_links = dict(reread_first)
        for offset in range(PAGE_SIZE, total, PAGE_SIZE):
            _, page_links = _inventory(client, offset)
            reread_links.update(page_links)
        if set(reread_links) != set(all_links):
            raise FetchError("partial", "Rohde & Schwarz USA inventory changed during the stable reread.")
        stale_note = f" Excluded {stale} board-listed withdrawn posting(s) returning HTTP 410." if stale else ""
        return Inventory("complete", jobs, f"Rohde & Schwarz USA careers: retrieved all {len(all_links)} published USA postings and rechecked the paged inventory; {len(jobs)} live details retained.{stale_note}", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, KeyError, TypeError, ValueError):
        return Inventory("partial", jobs, "Rohde & Schwarz USA careers schema validation failed.", SOURCE, ATS)
