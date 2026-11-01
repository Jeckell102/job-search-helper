"""Public Applicant Manager careers portal for Elma Electronic.

Applicant Manager exposes an employer-scoped careers index and stable ``pos``
detail URLs.  The portal is HTML rather than a documented JSON API, so this
adapter deliberately validates the published index links and each detail page
before returning an inventory.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base
from .core import plain_text
from .discovery import CareersTransport

HOST = "theapplicantmanager.com"
SOURCE = "https://theapplicantmanager.com/careers?co=e1"


class ApplicantManagerTransport:
    """HTML transport restricted to Elma's pinned index and detail URLs."""
    def __init__(self, base=None):
        self.base = base or CareersTransport(accept="*/*")

    def get(self, url):
        if url != SOURCE and _detail_url(url, SOURCE) is None:
            raise FetchError("unsupported", "Applicant Manager transport is restricted to Elma's pinned public index and details.")
        return self.base.get(url)


def supports_applicant_manager(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        return (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path == "/careers" and query == {"co": ["e1"]})
    except (TypeError, ValueError):
        return False


class _Page(HTMLParser):
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    _EXCLUDED = {"script", "style", "template", "noscript", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href = ""
        self._anchor: list[str] = []
        self.headings: list[str] = []
        self._heading = False
        self._heading_text: list[str] = []
        self.title = ""
        self._title_tag = False
        self._title_text: list[str] = []
        self.job_text: list[str] = []
        self.job_containers = 0
        self._job_depth = 0
        self._excluded_depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if self._job_depth == 0 and "job_listing" in classes:
            self.job_containers += 1
            self._job_depth = 1
            return
        if self._job_depth:
            if self._excluded_depth:
                if tag not in self._VOID:
                    self._excluded_depth += 1
            elif tag in self._EXCLUDED:
                self._excluded_depth = 1
            elif tag not in self._VOID:
                self._job_depth += 1
        if tag == "a" and values.get("href"):
            self._href = values["href"]
            self._anchor = []
        if tag in {"h1", "h2", "h3"}:
            self._heading = True
            self._heading_text = []
        if tag == "title":
            self._title_tag = True
            self._title_text = []

    def handle_data(self, data):
        self.text.append(data)
        if self._job_depth and not self._excluded_depth:
            self.job_text.append(data)
        if self._href:
            self._anchor.append(data)
        if self._heading:
            self._heading_text.append(data)
        if self._title_tag:
            self._title_text.append(data)

    def handle_endtag(self, tag):
        if self._excluded_depth:
            if tag not in self._VOID:
                self._excluded_depth -= 1
            return
        if self._job_depth and tag not in self._VOID:
            self._job_depth -= 1
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor)))
            self._href = ""
            self._anchor = []
        if tag in {"h1", "h2", "h3"} and self._heading:
            value = plain_text(" ".join(self._heading_text))
            if value:
                self.headings.append(value)
            self._heading = False
            self._heading_text = []
        if tag == "title" and self._title_tag:
            self.title = plain_text(" ".join(self._title_text))
            self._title_tag = False
            self._title_text = []


def _get(url: str, transport) -> _Page:
    response = transport.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Applicant Manager transport returned an invalid response.")
    if response.status in (401, 403, 429):
        raise FetchError("blocked", f"Applicant Manager HTTP {response.status}: public portal access denied.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"Applicant Manager HTTP {response.status}; inventory unavailable.")
    page = _Page()
    page.feed(response.body.decode("utf-8", "replace"))
    page.close()
    return page


def _detail_url(href: str, source: str) -> tuple[str, str] | None:
    url = urljoin(source, href)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.path != "/jobs"
            or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment):
        return None
    query = parse_qs(parsed.query, keep_blank_values=True)
    values = query.get("pos")
    # Applicant Manager appends ``fs=1.0em`` to live job links.  The same
    # index also contains a Resume link with a ``pos`` parameter, so require
    # the live-job marker to avoid importing that non-job control.
    if (set(query) != {"pos", "fs"} or query.get("fs") != ["1.0em"]
            or not values or len(values) != 1
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{2,31}", values[0])):
        return None
    return url, values[0].upper()


def _listing(page: _Page, source: str):
    rows: dict[str, tuple[str, str]] = {}
    for href, anchor in page.links:
        found = _detail_url(href, source)
        if found:
            url, ident = found
            if ident in rows:
                raise FetchError("partial", "Applicant Manager careers index repeated a posting ID.")
            rows[ident] = (url, plain_text(anchor))
    if not rows:
        raise FetchError("partial", "Applicant Manager careers index exposed no stable job detail URLs.")
    return rows


def _detail(url: str, ident: str, expected_title: str, company_id: str, company: str, transport):
    page = _get(url, transport)
    if page.job_containers != 1:
        raise FetchError("partial", "Applicant Manager detail must contain exactly one job description container.")
    body = plain_text(" ".join(page.job_text))
    if not body or len(body) < 100:
        raise FetchError("partial", "Applicant Manager detail has no substantive public body.")
    full_page = plain_text(" ".join(page.text))
    # Applicant Manager pages include a visible title and company attribution.
    # Use the first non-empty heading-like anchor/title text, falling back to
    # the index title when the portal omits a semantic heading.
    title = page.headings[0] if page.headings else page.title
    # The public portal always exposes a company marker; reject unrelated
    # Applicant Manager tenants rather than importing cross-company jobs.
    if "elma" not in full_page.casefold() and company.casefold() not in full_page.casefold():
        raise FetchError("partial", "Applicant Manager detail is outside the verified Elma employer scope.")
    if not title or (expected_title and title.casefold() != expected_title.casefold()):
        raise FetchError("partial", "Applicant Manager detail lacks a title.")
    row = _base({"id": ident}, "Applicant Manager", company_id, company)
    row.update(req_id=ident, title=title, url=url, description=body, is_listed=True)
    return row


def fetch_applicant_manager(source: str, company_id: str, company: str, transport) -> Inventory:
    if not supports_applicant_manager(source):
        return Inventory("unsupported", reason="Applicant Manager adapter requires Elma's verified employer board.", source_url=source, ats="Applicant Manager")
    jobs: list[dict] = []
    try:
        first = _listing(_get(source, transport), source)
        for ident, (url, expected_title) in sorted(first.items()):
            jobs.append(_detail(url, ident, expected_title, company_id, company, transport))
        check = _listing(_get(source, transport), source)
        if check != first:
            raise FetchError("partial", "Applicant Manager employer inventory changed during the scan.")
        return Inventory("complete", jobs, f"Applicant Manager: retrieved {len(jobs)} full postings and rechecked the public inventory.", source, "Applicant Manager")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, source, "Applicant Manager")
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return Inventory("partial" if jobs else "failed", jobs, "Applicant Manager public schema validation failed.", source, "Applicant Manager")
