"""South Shore Controls' first-party careers listing and published roles."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://southshorecontrols.com/career-opportunities/"
HOST = "southshorecontrols.com"
PREFIX = "/career-opportunities"
ATS = "South Shore Controls careers"
COMPANY_ID = "COMP-0403"
COMPANY = "South Shore Controls"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.parts, self.headings = [], [], []
        self.detail_parts, self.role_headings = [], []
        self._heading = False
        self._capture_detail = False
        self._in_form = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "form":
            self._in_form = True
            self._capture_detail = False
        if tag in {"h1", "h2", "h3"}:
            self._heading = True
            if tag == "h2" and not self._in_form and not self.role_headings:
                self.detail_parts = []
                self._capture_detail = True
                self.role_headings = []
        if tag in {"p", "li", "div", "br", "h1", "h2", "h3", "title"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading and data.strip().casefold() == "contact information":
            self._capture_detail = False
        if self._capture_detail and not self._in_form:
            self.detail_parts.append(data)
        if self._heading:
            self.headings.append(data)
            if self._capture_detail and not self._in_form:
                self.role_headings.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"}:
            self._heading = False
        if tag == "form":
            self._in_form = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == PREFIX
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url, *, listing=False):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"South Shore Controls careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"South Shore Controls careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "South Shore Controls careers page was blank.")
    page = _Page()
    page.feed(body)
    page.close()
    visible = text(" ".join(page.parts))
    if not visible or len(visible) < 40:
        raise FetchError("partial", "South Shore Controls careers page had no verifiable content.")
    if listing and ("south shore" not in visible.casefold()
                    or "career" not in visible.casefold()
                    or "available roles" not in visible.casefold()):
        raise FetchError("partial", "South Shore Controls careers identity or listing section is missing.")
    return page, visible


def _role_urls(page):
    urls = []
    for href in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/").startswith(PREFIX)
                and parsed.path.rstrip("/") != PREFIX
                and not parsed.query and not parsed.fragment
                and candidate not in urls):
            urls.append(candidate)
    return sorted(urls)


def _job(page, url, company_id, company):
    title = text(" ".join(dict.fromkeys(page.role_headings))) or text(" ".join(page.headings[-1:]))
    description = text(" ".join(page.detail_parts or page.parts))
    lowered = description.casefold()
    if (not title or len(description) < 100 or "south shore controls" not in lowered
            or not any(marker in lowered for marker in ("position overview", "responsibilities", "qualifications", "skills"))):
        raise FetchError("partial", "South Shore Controls role page lacks a complete title or description.")
    return _base({"id": url}, ATS, company_id, company) | {
        "title": title, "description": description, "url": url,
    }


def fetch_south_shore_controls(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="South Shore Controls adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first, _ = _read(client, SOURCE, listing=True)
        first_urls = _role_urls(first)
        if not first_urls:
            raise FetchError("partial", "South Shore Controls careers page has no published role links.")
        for role_url in first_urls:
            page, _ = _read(client, role_url)
            jobs.append(_job(page, role_url, company_id, company))
        second, _ = _read(client, SOURCE, listing=True)
        second_urls = _role_urls(second)
        if first_urls != second_urls:
            raise FetchError("partial", "South Shore Controls careers inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"South Shore Controls: retrieved {len(jobs)} published role pages and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", jobs, "South Shore Controls careers response validation failed.", SOURCE, ATS)
