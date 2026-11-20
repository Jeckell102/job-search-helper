"""Scythe Robotics' official Dover-powered careers page."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://app.dover.com/jobs/scytherobotics"
OFFICIAL_SOURCE = "https://joinscythe.com/"
HOST = "app.dover.com"
ATS = "Dover careers"
COMPANY_ID = "COMP-0506"
COMPANY = "Scythe Robotics"
NO_POSITIONS = re.compile(r"no\s+positions\s+available\s+at\s+this\s+time", re.I)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._anchor = ""
        self._anchor_text: list[str] = []
        self._title_text: list[str] = []
        self._in_title = False
        self._heading_text: list[str] = []
        self._in_heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._anchor = attrs["href"]
            self._anchor_text = []
        if tag == "title":
            self._in_title = True
        if tag in {"h1", "h2"}:
            self._in_heading = True
        if tag in {"title", "h1", "h2", "h3", "p", "li", "div", "main"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._anchor:
            self._anchor_text.append(data)
        if self._in_title:
            self._title_text.append(data)
        if self._in_heading:
            self._heading_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor:
            self.links.append((self._anchor, text(" ".join(self._anchor_text))))
            self._anchor = ""
            self._anchor_text = []
        if tag == "title":
            self._in_title = False
        if tag in {"h1", "h2"}:
            self._in_heading = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path == "/jobs/scytherobotics"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Scythe Robotics careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Scythe Robotics careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "Scythe Robotics careers page was blank.")
    page = _Page()
    page.feed(body)
    page.close()
    visible = text(" ".join(page.parts))
    identity = "scythe robotics" in visible.casefold() or "joinscythe" in body.casefold()
    if len(visible) < 40 or not identity or "careers" not in visible.casefold():
        raise FetchError("partial", "Scythe Robotics careers identity or content is missing.")
    return page, visible


def _role_urls(page, page_url):
    urls = []
    for href, title in page.links:
        candidate = urljoin(page_url, href)
        parsed = urlsplit(candidate)
        path = parsed.path.casefold()
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and "/careers/" in path and path.rstrip("/") != "/careers"
                and not path.endswith("/audit") and title
                and candidate not in urls):
            urls.append(candidate)
    return urls


def _pagination_urls(page, page_url):
    found = []
    for href, _ in page.links:
        candidate = urljoin(page_url, href)
        parsed = urlsplit(candidate)
        query = parsed.query.casefold()
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path == "/jobs/scytherobotics"
                and query and any(key in query for key in ("page=", "offset=", "cursor="))
                and candidate not in found):
            found.append(candidate)
    return found


def _job(page, url):
    description = text(" ".join(page.parts))
    title = next((title for href, title in page.links if urljoin(url, href) == url), "")
    if not title:
        title = text(" ".join(page._heading_text)) or text(" ".join(page._title_text))
    if not title or len(description) < 100:
        raise FetchError("partial", "Scythe Robotics role page lacks a complete title or description.")
    return _base({"id": url}, ATS, COMPANY_ID, COMPANY) | {
        "title": title, "description": description, "url": url,
    }


def fetch_scythe_robotics(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Scythe Robotics adapter requires the verified official careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        def snapshot():
            listing_urls = [SOURCE]
            pages = []
            for page_url in listing_urls:
                page, visible = _read(client, page_url)
                pages.append((page_url, page, visible))
                for next_url in _pagination_urls(page, page_url):
                    if next_url not in listing_urls:
                        if len(listing_urls) >= 200:
                            raise FetchError("partial", "Scythe Robotics pagination limit reached before termination.")
                        listing_urls.append(next_url)
            role_urls = []
            texts = []
            for page_url, page, visible in pages:
                role_urls.extend(u for u in _role_urls(page, page_url) if u not in role_urls)
                texts.append(visible)
            return pages, role_urls, texts

        first_pages, first_urls, first_texts = snapshot()
        explicit_zero = any(NO_POSITIONS.search(value) for value in first_texts)
        if explicit_zero and first_urls:
            raise FetchError("partial", "Scythe Robotics page conflicts with its no-positions statement.")
        jobs = [_job(_read(client, role_url)[0], role_url) for role_url in first_urls]
        second_pages, second_urls, second_texts = snapshot()
        second_zero = any(NO_POSITIONS.search(value) for value in second_texts)
        if first_urls != second_urls or (not first_urls and explicit_zero != second_zero):
            raise FetchError("partial", "Scythe Robotics careers inventory changed during the reread.")
        if not first_urls and not (explicit_zero and second_zero):
            raise FetchError("partial", "Scythe Robotics page has no role links or validated no-positions statement.")
        return Inventory("complete", jobs,
                         f"Scythe Robotics: retrieved {len(jobs)} Dover role pages and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, locals().get("jobs", []), error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", locals().get("jobs", []), "Scythe Robotics careers response validation failed.", SOURCE, ATS)
