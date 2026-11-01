"""ATLAS Space Operations' first-party careers page and role pages."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, text
from .discovery import CareersTransport


SOURCE = "https://atlasspace.com/careers/"
HOST = "atlasspace.com"
PREFIX = "/careers/"
ATS = "ATLAS Space careers"
COMPANY_ID = "COMP-0362"
COMPANY = "ATLAS Space Operations"
_ZERO_OPENINGS = re.compile(
    r"\b(?:no current openings|no active job openings|no open positions|no available positions|"
    r"no jobs (?:are|were) found|please continue to check back)\b", re.IGNORECASE
)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.heading = []
        self._heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"h1", "h2", "h3"} and not self.heading:
            self._heading = True
        if tag in {"p", "li", "div", "br", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"} and self._heading:
            self._heading = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == PREFIX.rstrip("/")
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"ATLAS careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"ATLAS careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "ATLAS careers page was blank.")
    page = _Page()
    page.feed(body)
    page.close()
    visible = text(" ".join(page.parts))
    if not visible or len(visible) < 40:
        raise FetchError("partial", "ATLAS careers page had no verifiable content.")
    return page, visible


def _role_urls(page):
    urls = []
    for href in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.startswith(PREFIX) and parsed.path.rstrip("/") != PREFIX.rstrip("/")
                and not parsed.query and not parsed.fragment and candidate not in urls):
            urls.append(candidate)
    return sorted(urls)


def _job(page, url, company_id, company):
    title = text(" ".join(page.heading))
    description = text(" ".join(page.parts))
    if not title or len(description) < 100:
        raise FetchError("partial", "ATLAS role page lacks a complete title or description.")
    return _base({"id": url}, ATS, company_id, company) | {
        "title": title, "description": description, "url": url,
    }


def fetch_atlas_space(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="ATLAS adapter requires the verified ATLAS company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first, first_text = _read(client, SOURCE)
        first_urls = _role_urls(first)
        explicit_zero = bool(_ZERO_OPENINGS.search(first_text))
        if explicit_zero and first_urls:
            raise FetchError("partial", "ATLAS careers page conflicts with its no-openings statement.")
        if not first_urls and not explicit_zero:
            raise FetchError("partial", "ATLAS careers page has no role links or explicit no-openings statement.")
        for role_url in first_urls:
            page, _ = _read(client, role_url)
            jobs.append(_job(page, role_url, company_id, company))
        second, second_text = _read(client, SOURCE)
        second_urls = _role_urls(second)
        second_zero = bool(_ZERO_OPENINGS.search(second_text))
        if first_urls != second_urls or (not first_urls and explicit_zero != second_zero):
            raise FetchError("partial", "ATLAS careers inventory changed during the reread.")
        if not first_urls and not (explicit_zero and second_zero):
            raise FetchError("partial", "ATLAS empty inventory was not revalidated explicitly.")
        return Inventory("complete", jobs, f"ATLAS: retrieved {len(jobs)} published role pages and rechecked the careers page.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", jobs, "ATLAS careers response validation failed.", SOURCE, ATS)
