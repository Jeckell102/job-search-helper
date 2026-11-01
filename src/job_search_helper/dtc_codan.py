"""DTC, a Codan Company jobs from the employer-scoped Codan board."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.dtccodan.com/about/careers/"
BOARD = "https://careers.codan.com.au/search/?q=DTC"
HOST = "careers.codan.com.au"
ATS = "DTC, a Codan Company careers"
COMPANY_ID = "COMP-0467"
COMPANY = "DTC, a Codan Company"


class _Listing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.current = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "jobTitle-link" in attrs.get("class", ""):
            self.current = [attrs.get("href", ""), []]

    def handle_data(self, data):
        if self.current is not None:
            self.current[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            href, parts = self.current
            self.links.append((href, text("".join(parts))))
            self.current = None


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.description, self.canonical = [], [], []
        self._title_depth = self._description_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonical.append(attrs.get("href", ""))
        if attrs.get("itemprop") == "title":
            self._title_depth = 1
        elif self._title_depth and tag not in {"br", "img", "meta", "input"}:
            self._title_depth += 1
        if attrs.get("itemprop") == "description":
            self._description_depth = 1
        elif self._description_depth and tag not in {"br", "img", "meta", "input"}:
            self._description_depth += 1

    def handle_data(self, data):
        if self._title_depth:
            self.title.append(data)
        if self._description_depth:
            self.description.append(data)

    def handle_endtag(self, tag):
        if self._title_depth and tag not in {"br", "img", "meta", "input"}:
            self._title_depth -= 1
        if self._description_depth and tag not in {"br", "img", "meta", "input"}:
            self._description_depth -= 1


def _verified_source(url, company_id, company):
    try:
        p = urlsplit(url)
        source_ok = (p.scheme == "https" and p.hostname == "www.dtccodan.com"
                     and p.path.rstrip("/") == "/about/careers" and not p.query and not p.fragment)
        board_ok = url == BOARD
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold() and (source_ok or board_ok))
    except (AttributeError, TypeError, ValueError):
        return False


def _get(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"DTC/Codan public careers board blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"DTC/Codan public careers board HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "DTC/Codan public careers board was blank.")
    return body


def _listing(body):
    ranges = re.findall(r"Results\s+(\d+)\s+(?:to|–)\s+(\d+)\s+of\s+(\d+)", body, re.I)
    if len(ranges) != 1:
        raise FetchError("partial", "DTC/Codan board did not expose one result range.")
    first, last, total = map(int, ranges[0])
    page = _Listing(); page.feed(body); page.close()
    entries = []
    seen = set()
    for href, title in page.links:
        candidate = urljoin(BOARD, href)
        p = urlsplit(candidate)
        match = re.search(r"/(\d{6,})/?$", p.path)
        if (p.scheme != "https" or p.hostname != HOST or not match or not title
                or p.query or p.fragment):
            raise FetchError("partial", "DTC/Codan board contained an invalid or duplicate job link.")
        if match.group(1) in seen:
            if any(existing[0] == match.group(1) and existing[1] != title for existing in entries):
                raise FetchError("partial", "DTC/Codan board repeated a job ID with conflicting titles.")
            continue
        seen.add(match.group(1)); entries.append((match.group(1), title, candidate))
    if first != 1 or last - first + 1 != len(entries) or last > total or total > 500:
        raise FetchError("partial", "DTC/Codan board range disagreed with job links.")
    return total, entries


def _job(body, ident, listed_title, detail_url):
    page = _Detail(); page.feed(body); page.close()
    title = text("".join(page.title))
    description = text(" ".join(page.description))
    lowered = description.casefold()
    if (page.canonical != [detail_url] or not title or title != listed_title
            or len(description) < 100 or "dtc" not in lowered
            or not any(marker in lowered for marker in ("codan", "dtc north america", "domo tactical"))):
        raise FetchError("partial", f"DTC/Codan posting {ident} lacked a complete scoped detail page.")
    return _base({"id": ident}, ATS, COMPANY_ID, COMPANY) | {
        "title": title, "description": description, "url": detail_url,
    }


def fetch_dtc_codan(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="DTC adapter requires the verified DTC/Codan careers source.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first = _listing(_get(client, BOARD))
        total, entries = first
        if total != len(entries):
            raise FetchError("partial", "DTC/Codan DTC-filtered board requires pagination beyond the first page.")
        jobs = [_job(_get(client, detail), ident, title, detail) for ident, title, detail in entries]
        second = _listing(_get(client, BOARD))
        if second != first:
            raise FetchError("partial", "DTC/Codan DTC-filtered inventory changed during reread.")
        return Inventory("complete", jobs, f"DTC/Codan: retrieved {len(jobs)} employer-scoped postings and reread the board.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "DTC/Codan careers response validation failed.", SOURCE, ATS)
