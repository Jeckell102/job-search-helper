"""Deployable Technologies' scoped WordPress Job Manager inventory."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://deployabletechnologies.com/careers/"
HOST = "deployabletechnologies.com"
ENDPOINT = "https://deployabletechnologies.com/jm-ajax/get_listings/"
ATS = "Deployable Technologies careers"
COMPANY_ID = "COMP-0302"
COMPANY = "Deployable Technologies"


class _Listing(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.records = []
        self.current = None
        self.capture = None
        self.list_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "li" and "job_listing" in classes:
            self.current = {"id": "", "status": "", "url": "", "title": "", "company": "", "location": "", "job_type": ""}
            self.current["id"] = next((part.removeprefix("post-") for part in (attrs.get("class") or "").split() if part.startswith("post-")), "")
            self.current["status"] = "expired" if "status-expired" in classes else "active"
            self.list_depth = 1
        elif tag == "li" and self.current is not None:
            self.list_depth += 1
        if self.current is None:
            return
        if tag == "a" and attrs.get("href") and not self.current["url"]:
            self.current["url"] = attrs["href"]
        if tag == "h3": self.capture = "title"
        elif tag == "strong": self.capture = "company"
        elif tag == "div" and "location" in classes: self.capture = "location"
        elif tag == "li" and any(part.startswith("job-type") for part in classes): self.capture = "job_type"

    def handle_data(self, data):
        if self.current is not None and self.capture:
            self.current[self.capture] += " " + data

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if tag in {"h3", "strong", "div", "li"}:
            self.capture = None
        if tag == "li":
            self.list_depth -= 1
            if self.list_depth == 0:
                if self.current.get("id"):
                    self.records.append(self.current)
                self.current = None


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = []
        self._heading = False

    def handle_starttag(self, tag, attrs):
        if tag in {"h1", "h2", "h3"}: self._heading = True
        if tag in {"p", "li", "div", "h1", "h2", "h3", "br"}: self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading: self.title.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2", "h3"}: self._heading = False


def _verified_source(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == HOST and p.path.rstrip("/") == "/careers"
                and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _get(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Deployable Technologies source blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Deployable Technologies source HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _listing(client, page=None):
    url = ENDPOINT if page is None else ENDPOINT + "?page=" + str(page)
    payload = json.loads(_get(client, url))
    if not isinstance(payload, dict) or not isinstance(payload.get("html"), str):
        raise FetchError("partial", "Deployable Technologies Job Manager returned an invalid payload.")
    try:
        pages = int(payload.get("max_num_pages", 0))
    except (TypeError, ValueError):
        raise FetchError("partial", "Deployable Technologies pagination metadata was invalid.") from None
    if pages < 1 or pages > 100:
        raise FetchError("partial", "Deployable Technologies pagination metadata was invalid.")
    parser = _Listing(); parser.feed(payload["html"]); parser.close()
    return parser.records, pages


def _detail(client, record):
    url = urljoin(SOURCE, record["url"])
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname != HOST or p.query == "" and p.path.rstrip("/") != "/":
        raise FetchError("partial", "Deployable Technologies detail was outside employer scope.")
    html = _get(client, url)
    parser = _Detail(); parser.feed(html); parser.close()
    body = text(" ".join(parser.parts))
    if "this listing has expired" in body.casefold():
        return None
    title = text(" ".join(parser.title)) or text(record["title"])
    if not title or len(body) < 100 or "deployable technologies" not in body.casefold():
        raise FetchError("partial", "Deployable Technologies active detail lacks a full scoped description.")
    row = _base({"id": record["id"]}, ATS, COMPANY_ID, COMPANY)
    row.update(title=title, description=body, url=url, location=text(record["location"]),
               work_arrangement="Remote" if "remote" in record["location"].casefold() else "")
    return row


def fetch_deployable(careers_url, company_id, company, transport=None):
    if not _verified_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="Deployable Technologies adapter requires the verified employer careers source.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first, pages = _listing(client)
        records = list(first)
        for page in range(2, pages + 1):
            current, current_pages = _listing(client, page)
            if current_pages != pages: raise FetchError("partial", "Deployable pagination changed during scan.")
            records.extend(current)
        ids = [r["id"] for r in records]
        if not records or len(ids) != len(set(ids)):
            raise FetchError("partial", "Deployable listing returned no records or duplicate IDs.")
        for record in records:
            if record["status"] != "active":
                continue
            job = _detail(client, record)
            if job is None: raise FetchError("partial", "Deployable listing status contradicted its detail page.")
            jobs.append(job)
        check, check_pages = _listing(client)
        if check_pages != pages or [r["id"] for r in check] != ids:
            raise FetchError("partial", "Deployable listing changed during reread.")
        return Inventory("complete", jobs, f"Deployable Technologies: retrieved {len(jobs)} active postings and rechecked the full listing.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        return Inventory("partial", jobs, "Deployable Technologies response validation failed.", SOURCE, ATS)
