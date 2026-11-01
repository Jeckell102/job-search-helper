"""Redwire's official Clinch career-site inventory."""
from __future__ import annotations

from html.parser import HTMLParser
import json
import re
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://careers.rdw.com/jobs/search"
HOST = "careers.rdw.com"
ATS = "Redwire careers (Clinch)"
COMPANY_ID = "COMP-0378"
COMPANY = "Redwire"
MAX_PAGES = 100


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.scripts = []
        self._anchor = None
        self._script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._anchor = {"href": attrs["href"], "parts": []}
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._script = []

    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor["parts"].append(data)
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            self.links.append((self._anchor["href"], text(" ".join(self._anchor["parts"]))))
            self._anchor = None
        if tag == "script" and self._script is not None:
            self.scripts.append("".join(self._script))
            self._script = None


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == "/jobs/search"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Redwire careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Redwire careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "Redwire careers page was blank.")
    return body


def _page_number(url):
    match = re.search(r"(?:[?&])page=(\d+)(?:&|$)", url)
    return int(match.group(1)) if match else 1


def _listing(client):
    first = _read(client, SOURCE)
    pages = {1: first}
    parser = _Page(); parser.feed(first); parser.close()
    page_numbers = {_page_number(url) for url, _ in parser.links
                    if urlsplit(urljoin(SOURCE, url)).hostname == HOST
                    and urlsplit(urljoin(SOURCE, url)).path.rstrip("/") == "/jobs/search"}
    maximum = min(MAX_PAGES, max(page_numbers or {1}))
    for number in range(2, maximum + 1):
        pages[number] = _read(client, f"{SOURCE}?page={number}")

    jobs = []
    seen = set()
    for number in range(1, maximum + 1):
        parsed = _Page(); parsed.feed(pages[number]); parsed.close()
        for href, title in parsed.links:
            url = urljoin(SOURCE, href)
            item = urlsplit(url)
            if (item.scheme != "https" or item.hostname != HOST
                    or not item.path.startswith("/jobs/")
                    or item.path.rstrip("/") == "/jobs/search"
                    or item.query or item.fragment or url in seen):
                continue
            if not title:
                raise FetchError("partial", "Redwire listing contained a posting without a title.")
            seen.add(url)
            jobs.append((url, title))
    if not jobs:
        raise FetchError("partial", "Redwire careers search exposed no verifiable job links.")
    return jobs


def _jobposting(body):
    page = _Page(); page.feed(body); page.close()
    for raw in page.scripts:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for item in candidates:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    raise FetchError("partial", "Redwire detail page lacked a valid JobPosting record.")


def _locations(value):
    if not isinstance(value, list):
        value = [value]
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        address = item.get("address") if isinstance(item.get("address"), dict) else {}
        parts = [address.get(key) for key in ("addressLocality", "addressRegion", "addressCountry")]
        rendered = ", ".join(str(part).strip() for part in parts if part)
        if rendered and rendered not in result:
            result.append(rendered)
    return "; ".join(result)


def _jobs(client, listing):
    result = []
    for url, listed_title in listing:
        posting = _jobposting(_read(client, url))
        title = text(posting.get("title"))
        description = text(posting.get("description"))
        if not title or title != listed_title or len(description) < 200:
            raise FetchError("partial", f"Redwire detail is incomplete for {listed_title}.")
        identifier = posting.get("identifier")
        if isinstance(identifier, dict):
            identifier = identifier.get("value")
        row = _base({"id": identifier or url}, ATS, COMPANY_ID, COMPANY)
        row.update(title=title, description=description, url=url,
                   location=_locations(posting.get("jobLocation")),
                   created_at=text(posting.get("datePosted")),
                   updated_at=text(posting.get("datePosted")))
        result.append(row)
    return result


def fetch_redwire(careers_url, company_id, company, transport=None):
    if not _verified_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="Redwire requires its verified Clinch careers search URL.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        listing = _listing(client)
        jobs = _jobs(client, listing)
        reread = _listing(client)
        if [url for url, _ in reread] != [url for url, _ in listing]:
            raise FetchError("partial", "Redwire inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"Redwire: retrieved {len(jobs)} full Clinch postings and rechecked the inventory.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "Redwire response validation failed.", SOURCE, ATS)
