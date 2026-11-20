"""Aero Systems West's first-party careers-page adapter.

The employer site is the only acceptable source for this company.  Search
aggregators are intentionally not used: one syndicated posting cannot prove
the employer's current inventory.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://aerosystemswest.com/careers/"
HOSTS = {"aerosystemswest.com", "www.aerosystemswest.com"}
ATS = "Aero Systems West careers"
COMPANY_ID = "COMP-0182"
COMPANY = "Aero Systems West"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.parts: list[str] = []
        self.headings: list[str] = []
        self._heading: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"h1", "h2", "h3"}:
            self._heading = []
        if tag in {"p", "li", "div", "br", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"} and self._heading is not None:
            heading = text(" ".join(self._heading))
            if heading:
                self.headings.append(heading)
            self._heading = None


def _valid_source(url: str, company_id: str, company: str) -> bool:
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return False
    return (company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()
            and parsed.scheme == "https" and parsed.hostname in HOSTS
            and parsed.path.rstrip("/") == "/careers" and not parsed.query and not parsed.fragment)


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"Aero Systems West careers page blocked (HTTP {response.status}).")
    if response.status == 404:
        raise FetchError("partial", "Aero Systems West careers URL returned HTTP 404; no current employer board is published there.")
    if response.status != 200:
        raise FetchError("partial", f"Aero Systems West careers page returned HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    page = _Page()
    page.feed(body)
    page.close()
    visible = text(" ".join(page.parts))
    if len(visible) < 40:
        raise FetchError("partial", "Aero Systems West careers page has no verifiable content.")
    return page, visible


def _role_urls(page: _Page) -> list[str]:
    urls = []
    for href in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.hostname in HOSTS
                and parsed.path.rstrip("/") != "/careers"
                and any(token in parsed.path.casefold() for token in ("/job", "/career", "/position", "/opening"))
                and not parsed.query and not parsed.fragment and candidate not in urls):
            urls.append(candidate)
    return urls


def _job(page: _Page, url: str, company_id: str, company: str) -> dict:
    title = page.headings[0] if page.headings else ""
    description = text(" ".join(page.parts))
    if not title or len(description) < 100:
        raise FetchError("partial", "Aero Systems West role page lacks a full title or description.")
    return _base({"id": url}, ATS, company_id, company) | {
        "title": title, "description": description, "url": url,
    }


def fetch_aero_systems_west(careers_url, company_id, company, transport=None):
    if not _valid_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="Aero Systems West adapter requires the verified employer careers URL.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first, _ = _read(client, SOURCE)
        urls = _role_urls(first)
        if not urls:
            raise FetchError("partial", "Aero Systems West published no employer-scoped role links; aggregator listings cannot establish inventory.")
        jobs = [_job(_read(client, url)[0], url, company_id, company) for url in urls]
        second, _ = _read(client, SOURCE)
        if _role_urls(second) != urls:
            raise FetchError("partial", "Aero Systems West employer inventory changed during the reread.")
        return Inventory("complete", jobs, f"Aero Systems West: retrieved {len(jobs)} full employer role pages and rechecked the source.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "Aero Systems West careers source validation failed.", SOURCE, ATS)
