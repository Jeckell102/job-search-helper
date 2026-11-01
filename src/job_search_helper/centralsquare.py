"""CentralSquare Technologies' official HireBridge career center."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
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
        self._anchor: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href", "").lower().find("/v3/jobs/jobdetails.aspx") >= 0:
            self._anchor = {"href": attrs["href"], "title": ""}
            self._text = []

    def handle_data(self, data):
        if self._anchor is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            title = text(" ".join(self._text))
            self._anchor["title"] = title
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
        self._title = tag == "p" and "jobtitle" in classes
        self._location = tag == "span" and "joblocation" in classes

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
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"CentralSquare HireBridge page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"CentralSquare HireBridge page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "CentralSquare HireBridge page was blank.")
    return body


def _list(body):
    page = _Listing()
    page.feed(body)
    page.close()
    found = {}
    for raw in page.jobs:
        parsed = urlsplit(urljoin(SOURCE, raw["href"]))
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
        canonical = urljoin(SOURCE, raw["href"])
        if key in found and found[key][0] != raw["title"]:
            raise FetchError("partial", "CentralSquare listing contained conflicting duplicate job IDs.")
        found[key] = (raw["title"], canonical)
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
    client = transport or CareersTransport()
    try:
        first = _list(_read(client, SOURCE))
        jobs = []
        for jid, (title, detail) in sorted(first.items()):
            jobs.append(_job(client, detail, title))
        second = _list(_read(client, SOURCE))
        if first != second:
            raise FetchError("partial", "CentralSquare HireBridge inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"CentralSquare Technologies: retrieved {len(jobs)} published roles and rechecked the HireBridge board.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "CentralSquare HireBridge response validation failed.", SOURCE, ATS)
