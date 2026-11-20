"""Vislink Technologies' employer-published static careers inventory."""
from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://www.vislink.com/about/careers/"
HOSTS = {"www.vislink.com", "vislink.com"}


def _canonical(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parsed.scheme.lower(), (parsed.hostname or "").lower(), path, "", ""))


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.parts: list[str] = []
        self.h1: list[str] = []
        self.h5: list[str] = []
        self._heading: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(str(attrs["href"]))
        if tag == "h1":
            self._heading = self.h1
        elif tag == "h5":
            self._heading = self.h5

    def handle_data(self, data):
        value = " ".join(str(data).split())
        if value:
            self.parts.append(value)
            if self._heading is not None:
                self._heading.append(value)

    def handle_endtag(self, tag):
        if tag in {"h1", "h5"}:
            self._heading = None


def _read(client, url: str) -> str:
    response = client.get(url)
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"Vislink careers page HTTP {response.status}: access denied or human verification.")
    if response.status != 200:
        raise FetchError("partial", f"Vislink careers page HTTP {response.status}.")
    return response.body.decode("utf-8", "replace")


def _job_urls(html: str) -> list[str]:
    page = _Page(); page.feed(html)
    found: list[str] = []
    for href in page.links:
        url = _canonical(urljoin(SOURCE, href))
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname in HOSTS
                and parsed.path.startswith("/careers/")
                and parsed.path.rstrip("/") != "/careers"
                and url not in found):
            found.append(url)
    return found


def _job(html: str, url: str, company_id: str, company: str) -> dict:
    page = _Page(); page.feed(html)
    title = text(" ".join(page.h1))
    body = text(" ".join(page.parts))
    # Keep the parser bounded to substantive role pages. The installed
    # pipeline cannot infer a complete posting from a missing detail.
    if not title or len(body) < 120 or "position overview" not in body.casefold():
        raise FetchError("partial", f"Vislink detail is missing or lacks a full description: {url}")
    posting_id = "browser-" + sha256(url.encode()).hexdigest()[:24]
    return _base({"id": posting_id}, "Vislink careers", company_id, company) | {
        "posting_id": posting_id, "req_id": "", "title": title,
        "description": body, "url": url,
    }


def fetch_vislink(careers_url, company_id, company, transport=None):
    if _canonical(careers_url) != SOURCE:
        return Inventory("unsupported", reason="Vislink adapter requires the verified official careers page.",
                         source_url=careers_url, ats="Vislink careers")
    client = transport or CareersTransport()
    try:
        first_html = _read(client, SOURCE)
        urls = _job_urls(first_html)
        if not urls:
            raise FetchError("partial", "Vislink careers page exposed no verifiable role links.")
        jobs = [_job(_read(client, url), url, company_id, company) for url in urls]
        second_urls = _job_urls(_read(client, SOURCE))
        if second_urls != urls:
            raise FetchError("partial", "Vislink role inventory changed during the scan.")
        return Inventory("complete", jobs,
                         f"Vislink: retrieved {len(jobs)} full postings and rechecked the static role inventory.",
                         SOURCE, "Vislink careers")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, "Vislink careers")
    except (AttributeError, TypeError, ValueError, UnicodeError) as error:
        return Inventory("partial", [], f"Vislink careers schema validation failed ({type(error).__name__}).",
                         SOURCE, "Vislink careers")
