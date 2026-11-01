"""Symbotic's first-party WordPress careers inventory."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.symbotic.com/careers/jobs/"
HOST = "www.symbotic.com"
PREFIX = "/careers/jobs/"
ATS = "Symbotic careers"
COMPANY_ID = "COMP-0200"
COMPANY = "Symbotic"
ROLE_RE = re.compile(r"^/careers/jobs/[A-Za-z0-9_-]+/?$")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.headings = []
        self._heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append((attrs["href"], ""))
        if tag in {"h1", "h2", "h3"}:
            self._heading = True
            self.headings.append([])
        if tag in {"p", "li", "div", "br", "h1", "h2", "h3", "title"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading and self.headings:
            self.headings[-1].append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"}:
            self._heading = False


def _verified_source(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == HOST
                and p.path.rstrip("/") == PREFIX.rstrip("/")
                and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Symbotic careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Symbotic careers page HTTP {response.status}.")
    page = _Page()
    page.feed(response.body.decode("utf-8", "replace"))
    page.close()
    visible = text(" ".join(page.parts))
    if len(visible) < 80:
        raise FetchError("partial", "Symbotic careers page was blank or too short.")
    return page, visible


def _role_urls(page):
    urls = []
    for href, _ in page.links:
        candidate = urljoin(SOURCE, href)
        p = urlsplit(candidate)
        if (p.scheme == "https" and p.hostname == HOST and ROLE_RE.fullmatch(p.path)
                and not p.query and not p.fragment and candidate not in urls):
            urls.append(candidate)
    return urls


def _job(page, url, company_id, company):
    headings = [text(" ".join(parts)) for parts in page.headings if text(" ".join(parts))]
    title = next((h for h in headings if h.casefold() not in {"apply now", "open positions"}), "")
    description = text(" ".join(page.parts))
    if not title or len(description) < 180 or "symbotic" not in description.casefold():
        raise FetchError("partial", "Symbotic role page lacks a complete employer-scoped description.")
    rid = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    return _base({"id": rid}, ATS, company_id, company) | {
        "title": title, "description": description, "url": url,
    }


def fetch_symbotic(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Symbotic adapter requires its verified official jobs page.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first, _ = _read(client, SOURCE)
        first_urls = _role_urls(first)
        if not first_urls:
            raise FetchError("partial", "Symbotic careers page exposed no verifiable role links.")
        for role_url in first_urls:
            detail, _ = _read(client, role_url)
            jobs.append(_job(detail, role_url, company_id, company))
        second, _ = _read(client, SOURCE)
        second_urls = _role_urls(second)
        if first_urls != second_urls:
            raise FetchError("partial", "Symbotic careers inventory changed during the reread.")
        return Inventory("complete", jobs, f"Symbotic: retrieved {len(jobs)} published role pages and rechecked the careers page.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, OSError, TypeError, UnicodeError, ValueError):
        return Inventory("partial", jobs, "Symbotic careers response validation failed.", SOURCE, ATS)
