"""Black River Systems' first-party WordPress job-opportunities page."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://www.blackriversystems.com/job-opportunities/"
HOST = "www.blackriversystems.com"
PREFIX = "/2026/"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.headings = []
        self._heading = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"h1", "h2"}:
            self._heading = []

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2"} and self._heading is not None:
            self.headings.append(text(" ".join(self._heading)))
            self._heading = None


def _read(client, url):
    response = client.get(url)
    if response.status in (401, 403, 429):
        raise FetchError("blocked", "Black River public careers page was blocked.")
    if response.status != 200:
        raise FetchError("partial", f"Black River public careers page HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _links(html):
    page = _Page(); page.feed(html)
    out = []
    for href in page.links:
        url = urljoin(SOURCE, href); parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.startswith(PREFIX) and parsed.path.rstrip("/") != PREFIX.rstrip("/")
                and not parsed.query and not parsed.fragment and url not in out):
            out.append(url)
    return out


def fetch_black_river(careers_url, company_id, company, transport=None):
    client = transport or CareersTransport()
    jobs = []
    try:
        first = _links(_read(client, SOURCE))
        if len(first) != 14:
            raise FetchError("partial", f"Black River job link set changed; found {len(first)} links.")
        seen = set()
        for url in first:
            page = _Page(); page.feed(_read(client, url))
            title = page.headings[0] if page.headings else ""
            body = text(" ".join(page.parts))
            if not title or len(body) < 500 or "black river" not in body.casefold():
                raise FetchError("partial", "Black River job detail lacks a complete employer-scoped description.")
            posting_id = urlsplit(url).path.rstrip("/")
            if posting_id in seen:
                raise FetchError("partial", "Black River job link set has duplicate posting IDs.")
            seen.add(posting_id)
            row = _base({"id": posting_id}, "Black River WordPress", company_id, company)
            row.update(title=title, description=body, url=url)
            jobs.append(row)
        second = _links(_read(client, SOURCE))
        if second != first:
            raise FetchError("partial", "Black River job link set changed during the scan.")
        return Inventory("complete", jobs, f"Black River: retrieved {len(jobs)} full postings and rechecked the public inventory.", SOURCE, "Black River WordPress")
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, "Black River WordPress")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", jobs, "Black River WordPress schema validation failed.", SOURCE, "Black River WordPress")
