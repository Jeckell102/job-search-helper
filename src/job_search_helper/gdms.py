"""General Dynamics Mission Systems' public, server-rendered careers pages.

The employer-owned search page publishes employer-scoped posting links and
each public detail page exposes the complete description. This adapter never
uses the General Dynamics parent search, application routes, or a filtered
search URL.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport


SOURCE = "https://gdmissionsystems.com/careers/job-search"
HOST = "gdmissionsystems.com"
MAX_PAGES = 100
MAX_JOBS = 5000
DETAIL = re.compile(r"^/careers/(.+)-(20[0-9]{2}-[0-9]+)-opportunity/?$", re.I)


class _Listing(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.pages = set()
        self.current = None
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        parsed = urlsplit(href)
        match = DETAIL.match(parsed.path)
        if match and not parsed.query and not parsed.fragment:
            self.current = (href, [])
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.path.rstrip("/") == "/careers/job-search" and set(query) == {"page"}:
            value = query["page"]
            if len(value) == 1 and value[0].isdigit():
                self.pages.add(int(value[0]))

    def handle_data(self, value):
        if self.current is not None:
            self.current[1].append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            href, label = self.current
            self.rows.append((href, text("".join(label))))
            self.current = None


class _Detail(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.words = []
        self.in_h1 = False
        self.skip = 0
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        if tag == "h1":
            self.in_h1 = True

    def handle_data(self, value):
        if self.skip:
            return
        self.words.append(value)
        if self.in_h1:
            self.title.append(value)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1


def _page_url(number):
    return SOURCE if number == 0 else SOURCE + "?" + urlencode({"page": number})


def _get(client, url):
    response = client.get(url)
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial",
                         "GDMS public careers page was unavailable.")
    return response.body.decode("utf-8", "replace")


def _entries(body):
    parsed = _Listing(body)
    rows = []
    seen = set()
    for href, label in parsed.rows:
        url = urljoin(SOURCE, href)
        pieces = urlsplit(url)
        match = DETAIL.match(pieces.path)
        if (pieces.scheme != "https" or pieces.hostname != HOST or pieces.query or pieces.fragment
                or not match or not label):
            raise FetchError("partial", "GDMS listing contains an invalid public posting.")
        ident = match.group(2)
        if ident in seen:
            raise FetchError("partial", "GDMS listing repeated a posting ID.")
        seen.add(ident)
        rows.append((ident, label, f"https://{HOST}" + pieces.path.rstrip("/")))
    if not rows or len(rows) > MAX_JOBS:
        raise FetchError("partial", "GDMS listing did not expose a bounded public inventory.")
    return rows, parsed.pages


def _inventory(client):
    first, page_numbers = _entries(_get(client, SOURCE))
    if any(page < 0 or page >= MAX_PAGES for page in page_numbers):
        raise FetchError("partial", "GDMS listing has an invalid pagination scope.")
    expected = set(range(max(page_numbers, default=0) + 1))
    if page_numbers and page_numbers != expected:
        raise FetchError("partial", "GDMS listing pagination is incomplete or non-contiguous.")
    rows = list(first)
    for number in sorted(expected - {0}):
        page_rows, ignored = _entries(_get(client, _page_url(number)))
        rows.extend(page_rows)
        if len(rows) > MAX_JOBS:
            raise FetchError("partial", "GDMS public inventory exceeded the bounded limit.")
    ids = [ident for ident, _, _ in rows]
    if len(ids) != len(set(ids)):
        raise FetchError("partial", "GDMS listing repeated a posting across pages.")
    return rows, expected


def fetch_gdms(careers_url, company_id, company, transport=None):
    if careers_url != SOURCE:
        return Inventory("unsupported", reason="GDMS adapter requires its verified unfiltered public job-search page.",
                         source_url=careers_url, ats="GDMS Careers")
    client = transport or CareersTransport()
    jobs = []
    try:
        entries, pages = _inventory(client)
        for ident, listed_title, url in entries:
            detail = _Detail(_get(client, url))
            title = text("".join(detail.title))
            description = text(" ".join(detail.words))
            if title != listed_title or len(description) < 250:
                raise FetchError("partial", "GDMS job detail lacks a matching title or full public description.")
            row = _base({"id": ident}, "GDMS Careers", company_id, company)
            row.update(title=title, description=description, url=url)
            jobs.append(row)
        check_entries, check_pages = _inventory(client)
        if check_entries != entries or check_pages != pages:
            raise FetchError("partial", "GDMS inventory changed during the scan.")
        return Inventory("complete", jobs,
                         f"GDMS: retrieved {len(jobs)} complete postings and rechecked the public inventory.",
                         SOURCE, "GDMS Careers")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, SOURCE, "GDMS Careers")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", jobs, "GDMS public careers schema validation failed.", SOURCE, "GDMS Careers")
