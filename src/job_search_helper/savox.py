"""Savox Communications' first-party careers page and Teamtailor postings."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.savox.com/careers"
HOST = "www.savox.com"
TEAMTAILOR_HOST = "porkkanajakeppioy.teamtailor.com"
ATS = "Savox careers"
COMPANY_ID = "COMP-0494"
COMPANY = "Savox Communications"
ROLE_RE = re.compile(r"^/en/jobs/(\d+)-[A-Za-z0-9-]+$")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self._heading = False
        self.headings: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"h1", "h2", "h3", "h4", "p", "li", "div", "title"}:
            self.parts.append(" ")
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading = True

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading and data.strip():
            self.headings.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading = False


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._title = False
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
        if not self._skip and tag in {"h1", "h2", "h3", "p", "li", "div", "br", "title"}:
            self.parts.append(" ")
        if not self._skip and tag == "h1":
            self._title = True

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._title and data.strip():
            self.title_parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "h1":
            self._title = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == "/careers"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _get(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Savox careers source blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Savox careers source HTTP {response.status}.")
    if not response.body:
        raise FetchError("partial", "Savox careers source was blank.")
    return response


def _role_urls(page):
    found = []
    for href in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.hostname == TEAMTAILOR_HOST
                and ROLE_RE.fullmatch(parsed.path) and not parsed.query and not parsed.fragment
                and candidate not in found):
            found.append(candidate)
    return found


def _details(response, role_url, company_id, company):
    detail = _Detail()
    detail.feed(response.body.decode("utf-8", "replace"))
    detail.close()
    title = text(" ".join(detail.title_parts)).strip()
    visible = text(" ".join(detail.parts))
    if not title or not visible:
        raise FetchError("partial", "Savox posting lacks a title or description.")
    if "savox communications" not in visible.casefold() or len(visible) < 400:
        raise FetchError("partial", "Savox posting lacks a complete employer-scoped description.")
    # Remove Teamtailor chrome while preserving the substantive posting body.
    start_markers = ("Savox Communications designs and manufactures", "We are now looking for")
    start = min((visible.find(marker) for marker in start_markers if visible.find(marker) >= 0), default=0)
    end = visible.find("Career site", start)
    description = visible[start:end if end > start else None].strip()
    if len(description) < 400 or "How to Apply" not in description:
        raise FetchError("partial", "Savox posting description is incomplete.")
    posting_id = ROLE_RE.fullmatch(urlsplit(role_url).path).group(1)
    return _base({"id": posting_id}, ATS, company_id, company) | {
        "title": title,
        "description": description,
        "url": role_url,
    }


def fetch_savox(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Savox adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first = _get(client, SOURCE)
        page = _Page()
        page.feed(first.body.decode("utf-8", "replace"))
        page.close()
        visible = text(" ".join(page.parts))
        if "savox" not in visible.casefold() or "open positions" not in visible.casefold():
            raise FetchError("partial", "Savox careers identity or Open positions section is missing.")
        urls = _role_urls(page)
        if not urls:
            raise FetchError("partial", "Savox careers page has no published job links.")
        seen = set()
        for role_url in urls:
            if role_url in seen:
                raise FetchError("partial", "Savox careers page contains duplicate job links.")
            seen.add(role_url)
            jobs.append(_details(_get(client, role_url), role_url, company_id, company))
        second = _Page()
        second_response = _get(client, SOURCE)
        second.feed(second_response.body.decode("utf-8", "replace"))
        second.close()
        if _role_urls(second) != urls:
            raise FetchError("partial", "Savox careers inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"Savox: retrieved {len(jobs)} published roles and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", jobs, "Savox careers response validation failed.", SOURCE, ATS)
