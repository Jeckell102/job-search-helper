"""Fischer Connectors' first-party static job-openings inventory."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://fischerconnectors.com/en/about-us/join-us/job-openings/"
HOSTS = {"fischerconnectors.com", "www.fischerconnectors.com"}
ATS = "Fischer Connectors careers"
COMPANY_ID = "COMP-0491"
COMPANY = "Fischer Connectors"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.heading = []
        self._heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"h1", "h2"}:
            self._heading = True
            self.heading = []

    def handle_data(self, data):
        self.parts.append(data)
        if self._heading:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag in {"h1", "h2"}:
            self._heading = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname in HOSTS
                and parsed.path.rstrip("/") == "/en/about-us/join-us/job-openings"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Fischer Connectors page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Fischer Connectors page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "Fischer Connectors page was blank.")
    return body


def _job_urls(html):
    page = _Page()
    page.feed(html)
    urls = []
    for href in page.links:
        url = urljoin(SOURCE, href)
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname in HOSTS
                and parsed.path.startswith("/en/job-opening/")
                and parsed.path.rstrip("/") != "/en/job-opening"
                and not parsed.query and not parsed.fragment and url not in urls):
            urls.append(url)
    if not urls:
        raise FetchError("partial", "Fischer Connectors openings page exposed no job-detail links.")
    return urls


def _job(url, html):
    page = _Page()
    page.feed(html)
    title = text(" ".join(page.heading))
    body = text(" ".join(page.parts))
    if not title or len(body) < 500:
        raise FetchError("partial", f"Fischer Connectors detail {url} lacks a full description.")
    return _base({"id": url}, ATS, COMPANY_ID, COMPANY) | {
        "title": title,
        "description": body,
        "url": url,
    }


def fetch_fischer_connectors(careers_url, company_id, company, transport=None):
    if not _verified_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="Fischer Connectors requires its verified first-party openings page.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first_urls = _job_urls(_read(client, SOURCE))
        jobs = [_job(url, _read(client, url)) for url in first_urls]
        second_urls = _job_urls(_read(client, SOURCE))
        if second_urls != first_urls:
            raise FetchError("partial", "Fischer Connectors job inventory changed during the reread.")
        return Inventory("complete", jobs,
                         f"Fischer Connectors: retrieved {len(jobs)} full postings and rechecked the openings page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "Fischer Connectors response validation failed.", SOURCE, ATS)
