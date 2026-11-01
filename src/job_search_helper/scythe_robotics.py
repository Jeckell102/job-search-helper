"""Scythe Robotics' official Dover-powered careers page."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://joinscythe.com/"
HOST = "joinscythe.com"
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

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._anchor = attrs["href"]
            self._anchor_text = []
        if tag in {"title", "h1", "h2", "h3", "p", "li", "div", "main"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._anchor:
            self._anchor_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor:
            self.links.append((self._anchor, text(" ".join(self._anchor_text))))
            self._anchor = ""
            self._anchor_text = []


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client):
    response = client.get(SOURCE)
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


def _role_urls(page):
    urls = []
    for href, title in page.links:
        candidate = urljoin(SOURCE, href)
        parsed = urlsplit(candidate)
        path = parsed.path.casefold()
        if (parsed.scheme == "https" and parsed.hostname == HOST
                and "/careers/" in path and path.rstrip("/") != "/careers"
                and not path.endswith("/audit") and title
                and candidate not in urls):
            urls.append(candidate)
    return urls


def _job(page, url):
    description = text(" ".join(page.parts))
    title = next((title for href, title in page.links if href == url), "")
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
        first, first_text = _read(client)
        first_urls = _role_urls(first)
        explicit_zero = bool(NO_POSITIONS.search(first_text))
        if explicit_zero and first_urls:
            raise FetchError("partial", "Scythe Robotics page conflicts with its no-positions statement.")
        jobs = [_job(_read(client)[0], role_url) for role_url in first_urls]
        second, second_text = _read(client)
        second_urls = _role_urls(second)
        second_zero = bool(NO_POSITIONS.search(second_text))
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
