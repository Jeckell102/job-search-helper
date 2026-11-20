"""CentralSquare Technologies' official HireBridge career center."""
from __future__ import annotations

from html.parser import HTMLParser
import time
from urllib.parse import parse_qs, urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, _delay, text
from .discovery import CareersTransport

SOURCE = "https://recruit.hirebridge.com/v3/Jobs/list.aspx?cid=7724"
HOST = "recruit.hirebridge.com"
ATS = "CentralSquare HireBridge"
COMPANY_ID = "COMP-0473"
COMPANY = "CentralSquare Technologies"


class _Listing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.jobs: list[dict[str, str]] = []
        self.pagination: list[str] = []
        self._anchor: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag != "a" or not attrs.get("href"):
            return
        href = attrs["href"]
        lower = href.lower()
        if "/v3/jobs/jobdetails.aspx" in lower:
            self._anchor = {"href": href, "title": ""}
            self._text = []
        elif "/v3/jobs/list.aspx" in lower:
            self._anchor = {"href": href, "title": "", "pagination": "1"}
            self._text = []

    def handle_data(self, data):
        if self._anchor is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            title = text(" ".join(self._text))
            self._anchor["title"] = title
            if self._anchor.get("pagination"):
                self.pagination.append(self._anchor["href"])
            else:
                self.jobs.append(self._anchor)
            self._anchor = None
            self._text = []


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: list[str] = []
        self.location: list[str] = []
        self._skip = 0
        self._title = False
        self._location = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in {"p", "li", "div", "h1", "h2", "h3", "title", "br"}:
            self.parts.append(" ")
        self._title = "jobtitle" in classes
        self._location = "joblocation" in classes

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._title:
            self.title.append(data)
        if self._location:
            self.location.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag == "p":
            self._title = False
        if tag == "span":
            self._location = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path == "/v3/Jobs/list.aspx"
                and query == {"cid": ["7724"]} and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    """Read a public page with a small, Retry-After-aware retry budget."""
    for attempt in range(3):
        response = client.get(url)
        if response.status in {429, 500, 502, 503, 504} and attempt < 2:
            delay = _delay(response.headers, attempt)
            sleeper = getattr(client, "sleep", time.sleep)
            sleeper(delay)
            continue
        break
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"CentralSquare HireBridge page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"CentralSquare HireBridge page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "CentralSquare HireBridge page was blank.")
    return body


def _list(body, page_url=SOURCE):
    page = _Listing()
    page.feed(body)
    page.close()
    found = {}
    for raw in page.jobs:
        parsed = urlsplit(urljoin(page_url, raw["href"]))
        query = parse_qs(parsed.query)
        if (parsed.scheme != "https" or parsed.hostname != HOST
                or parsed.path != "/v3/Jobs/JobDetails.aspx"
                or set(query) != {"cid", "jid", "locvalue"}
                or query.get("cid") != ["7724"]
                or len(query.get("jid", [])) != 1 or not query["jid"][0].isdigit()
                or int(query["jid"][0]) <= 0):
            raise FetchError("partial", "CentralSquare listing contained an invalid job URL.")
        if not raw["title"]:
            raise FetchError("partial", "CentralSquare listing contained a blank job title.")
        key = query["jid"][0]
        canonical = urljoin(page_url, raw["href"])
        if key in found and found[key][0] != raw["title"]:
            raise FetchError("partial", "CentralSquare listing contained conflicting duplicate job IDs.")
        found[key] = (raw["title"], canonical)
    if not found:
        raise FetchError("partial", "CentralSquare HireBridge inventory had no verifiable job links.")
    next_pages = []
    for href in page.pagination:
        candidate = urljoin(page_url, href)
        parsed = urlsplit(candidate)
        query = parse_qs(parsed.query)
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.casefold() == "/v3/jobs/list.aspx"
                and query.get("cid") == ["7724"]
                and any(key in query for key in ("page", "p", "start", "offset"))
                and candidate not in next_pages):
            next_pages.append(candidate)
    return found, next_pages


def _inventory(client):
    """Enumerate every page advertised by HireBridge, without a page-count guess."""
    pending = [SOURCE]
    visited = set()
    found = {}
    while pending:
        page_url = pending.pop(0)
        if page_url in visited:
            continue
        visited.add(page_url)
        if len(visited) > 50:
            raise FetchError("partial", "CentralSquare HireBridge pagination exceeded the safety bound.")
        page_jobs, next_pages = _list(_read(client, page_url), page_url)
        for jid, value in page_jobs.items():
            if jid in found and found[jid] != value:
                raise FetchError("partial", "CentralSquare pagination contained conflicting duplicate job IDs.")
            found[jid] = value
        pending.extend(url for url in next_pages if url not in visited and url not in pending)
    if not found:
        raise FetchError("partial", "CentralSquare HireBridge inventory had no verifiable job links.")
    return found


def _job(client, url, expected_title):
    body = _read(client, url)
    page = _Detail()
    page.feed(body)
    page.close()
    title = text(" ".join(page.title)) or expected_title
    visible = text(" ".join(page.parts))
    if title.casefold() != expected_title.casefold() or len(visible) < 200:
        raise FetchError("partial", "CentralSquare job detail lacks a complete title or description.")
    if "centralsquare" not in visible.casefold() or "job description" not in visible.casefold():
        raise FetchError("partial", "CentralSquare job detail has the wrong employer or incomplete content.")
    parsed = urlsplit(url)
    location = text(" ".join(page.location))
    return _base({"id": parse_qs(parsed.query)["jid"][0]}, ATS, COMPANY_ID, COMPANY) | {
        "title": title, "location": location, "description": visible, "url": url,
    }


def fetch_centralsquare(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="CentralSquare adapter requires the verified HireBridge board.",
                         source_url=SOURCE, ats=ATS)
    # HireBridge is especially sensitive to bursty detail requests.  Keep the
    # normal configured scraper transport, but use a one-second minimum gap
    # for this board's listing/detail sequence.
    client = transport or CareersTransport(interval=1.0)
    try:
        first = _inventory(client)
        jobs = []
        for jid, (title, detail) in sorted(first.items()):
            jobs.append(_job(client, detail, title))
        second = _inventory(client)
        if first != second:
            raise FetchError("partial", "CentralSquare HireBridge inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"CentralSquare Technologies: retrieved {len(jobs)} published roles and rechecked the HireBridge board.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "CentralSquare HireBridge response validation failed.", SOURCE, ATS)
