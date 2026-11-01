"""Read-only HTML adapter for SmartRecruiters Attrax career portals.

Attrax publishes a server-rendered, paginated inventory rather than the
standard SmartRecruiters JSON API.  The adapter deliberately stays scoped to
the pinned employer host and validates every public detail page before
returning a complete inventory.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://careers.wabtec.com/jobs"
HOST = "careers.wabtec.com"
MAX_PAGES = 100


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href = None
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.parts = []

    def handle_data(self, data):
        if self.href is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, " ".join("".join(self.parts).split())))
            self.href = None
            self.parts = []


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heading: list[str] = []
        self.body: list[str] = []
        self.in_h1 = False
        self.in_body = False

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.in_h1 = True
        if tag == "body":
            self.in_body = True

    def handle_data(self, data):
        if self.in_h1:
            self.heading.append(data)
        if self.in_body:
            self.body.append(data)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False
        if tag == "body":
            self.in_body = False


# Attrax defaults this tenant to 12 cards per page and caps the page index at
# 25.  The public results-per-page control explicitly supports 48, which keeps
# the complete 747-result Wabtec inventory within the provider's page bound.
PAGE_SIZE = 48


def _page_url(page: int) -> str:
    return f"{SOURCE}?page={page}&size={PAGE_SIZE}"


def _safe_job_url(href: str) -> str | None:
    absolute = urljoin(SOURCE, href)
    p = urlsplit(absolute)
    if p.scheme != "https" or p.hostname != HOST or p.query or p.fragment:
        return None
    if not re.fullmatch(r"/job/[^/]+-jid-[0-9]+", p.path):
        return None
    return absolute


def _listing(transport):
    links: dict[str, str] = {}
    expected = None
    for page in range(1, MAX_PAGES + 1):
        response = transport.get(_page_url(page))
        if response.status != 200:
            raise FetchError("blocked" if response.status in (401, 403, 429) else "partial",
                             "Attrax public job listing was unavailable.")
        html = response.body.decode("utf-8", "replace")
        match = re.search(r"\b([0-9]{1,5})\s+result\(s\)", html, re.I)
        if match:
            count = int(match.group(1))
            expected = count if expected is None else expected
            if count != expected:
                raise FetchError("partial", "Attrax inventory count changed during pagination.")
        parser = _Links()
        parser.feed(html)
        before = len(links)
        for href, label in parser.links:
            url = _safe_job_url(href)
            if url:
                links[url] = label
        if expected is not None and len(links) >= expected:
            return links, expected
        if len(links) == before and page > 1:
            break
    if expected is None or len(links) != expected:
        raise FetchError("partial", "Attrax pagination ended before its published inventory count.")
    return links, expected


def _detail(transport, url, company_id, company):
    response = transport.get(url)
    # Attrax occasionally republishes a posting under a corrected slug while
    # retaining the same numeric JID in the listing.  Follow only a bounded,
    # same-host canonical redirect; CareersTransport deliberately refuses
    # automatic redirects so the adapter must validate this explicitly.
    if response.status in (301, 302, 307, 308):
        location = response.headers.get("Location") or response.headers.get("location")
        canonical = _safe_job_url(urljoin(url, location or "")) if location else None
        old_id = re.search(r"-jid-([0-9]+)$", urlsplit(url).path)
        new_id = re.search(r"-jid-([0-9]+)$", urlsplit(canonical).path) if canonical else None
        if not canonical or not old_id or not new_id or old_id.group(1) != new_id.group(1):
            raise FetchError("partial", "Attrax job detail redirect changed posting identity.")
        response = transport.get(canonical)
        url = canonical
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial",
                         "Attrax job detail was unavailable.")
    parser = _Detail()
    parser.feed(response.body.decode("utf-8", "replace"))
    title = text(" ".join(parser.heading))
    body = text(" ".join(parser.body))
    if not title or not body or len(body) < 80:
        raise ValueError("Attrax job detail lacks a complete title or description.")
    ident = re.search(r"-jid-([0-9]+)$", urlsplit(url).path).group(1)
    row = _base({"id": ident}, "SmartRecruiters Attrax", company_id, company)
    row.update(title=title, description=body, url=url)
    return row


def fetch_attrax(url, company_id, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="Attrax adapter requires its verified Wabtec jobs page.",
                         source_url=url, ats="SmartRecruiters Attrax")
    client = transport or CareersTransport()
    jobs = []
    try:
        links, expected = _listing(client)
        ids = set()
        ordered_links = sorted(links)
        def read_detail(link):
            # CareersTransport owns a rate-limit clock; use one instance per
            # worker so independent public detail requests remain bounded.
            worker = (CareersTransport(timeout=client.timeout, interval=client.interval)
                      if client.__class__.__name__ == "CareersTransport" else client)
            try:
                return link, _detail(worker, link, company_id, company), None
            except (FetchError, AttributeError, TypeError, ValueError, UnicodeError) as error:
                return link, None, error
        pool = ThreadPoolExecutor(max_workers=4) if client.__class__.__name__ == "CareersTransport" else None
        try:
            detail_iter = pool.map(read_detail, ordered_links) if pool else map(read_detail, ordered_links)
            for link, row, error in detail_iter:
                if error is not None:
                    if isinstance(error, FetchError):
                        raise error
                    raise FetchError("partial", "Attrax job detail schema validation failed.") from error
                if row["posting_id"] in ids:
                    raise FetchError("partial", "Attrax inventory contains duplicate posting IDs.")
                ids.add(row["posting_id"])
                jobs.append(row)
        finally:
            if pool:
                pool.shutdown(wait=True)
        if len(jobs) != expected:
            raise FetchError("partial", "Attrax detail inventory does not match its listing count.")
        check, check_expected = _listing(client)
        if check_expected != expected or set(check) != set(links):
            raise FetchError("partial", "Attrax inventory changed during the final recheck.")
        return Inventory("complete", jobs,
                         f"SmartRecruiters Attrax: retrieved {len(jobs)} full postings and rechecked the public inventory.",
                         SOURCE, "SmartRecruiters Attrax")
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, "SmartRecruiters Attrax")
    except (AttributeError, TypeError, ValueError, UnicodeError):
        return Inventory("partial", jobs, "Attrax public careers schema validation failed.", SOURCE,
                         "SmartRecruiters Attrax")
