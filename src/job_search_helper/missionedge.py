"""MissionEdge Technologies' first-party careers inventory."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://missionedgetechnologies.com/careers/"
CAREERS_HOST = "missionedgetechnologies.com"
ROLE_HOST = "www.bringtheedge.tech"
ATS = "MissionEdge Technologies careers"
COMPANY_ID = "COMP-0454"
COMPANY = "MissionEdge Technologies"
ROLE_PATH = re.compile(r"^/jobs/[A-Za-z0-9-]+$")


class _Careers(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._href = attrs["href"]
            self._parts = []

    def handle_data(self, data):
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or not self._href:
            return
        self.links.append((self._href, text(" ".join(self._parts))))
        self._href = ""
        self._parts = []


class _Detail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_h1 = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "main":
            self.main_depth += 1
        if self.main_depth and tag in {"p", "li", "h1", "h2", "h3", "br", "div"}:
            self.parts.append("\n")
        if self.main_depth and tag == "h1":
            self.in_h1 = True

    def handle_data(self, data):
        if self.main_depth:
            self.parts.append(data)
            if self.in_h1:
                self.title_parts.append(data)

    def handle_endtag(self, tag):
        if self.main_depth and tag in {"p", "li", "div"}:
            self.parts.append("\n")
        if tag == "h1":
            self.in_h1 = False
        if tag == "main" and self.main_depth:
            self.main_depth -= 1


def _verified_source(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == CAREERS_HOST
                and p.path.rstrip("/") == "/careers" and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _get(client, url, label):
    response = client.get(url)
    if response.status == 404 and label == "role page":
        return None
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"MissionEdge {label} blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"MissionEdge {label} HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", f"MissionEdge {label} was blank.")
    return body


def _role_links(body):
    page = _Careers()
    page.feed(body)
    page.close()
    result = []
    seen = set()
    for href, title in page.links:
        p = urlsplit(href)
        if p.scheme != "https" or p.hostname != ROLE_HOST or not ROLE_PATH.fullmatch(p.path) or p.query or p.fragment:
            continue
        if not title or p.path in seen:
            continue
        seen.add(p.path)
        result.append((title, href))
    if not result:
        raise FetchError("partial", "MissionEdge careers page exposed no scoped role links.")
    return result


def _role(client, title, url):
    p = urlsplit(url)
    if p.hostname != ROLE_HOST or not ROLE_PATH.fullmatch(p.path) or p.query or p.fragment:
        raise FetchError("partial", f"MissionEdge role URL failed scope validation: {url}")
    raw = _get(client, url, "role page")
    if raw is None:
        return None
    page = _Detail()
    page.feed(raw)
    page.close()
    body = text(" ".join(page.parts))
    parsed_title = text(" ".join(page.title_parts)) or title
    # The careers page uses the generic CTA label "View job"; the detail
    # page's scoped h1 is the authoritative posting title in that case.
    if title.casefold() != "view job" and parsed_title.casefold() != title.casefold():
        raise FetchError("partial", f"MissionEdge role title drifted for {title}.")
    if len(body) < 500 or "apply now" not in body.casefold():
        raise FetchError("partial", f"MissionEdge {title} detail is incomplete.")
    row = _base({"id": p.path.rsplit("/", 1)[-1]}, ATS, COMPANY_ID, COMPANY)
    row.update(title=parsed_title, url=url, description=body)
    return row


def _inventory(client):
    links = _role_links(_get(client, SOURCE, "careers page"))
    jobs = [job for title, url in links if (job := _role(client, title, url)) is not None]
    ids = [job["posting_id"] for job in jobs]
    if len(ids) != len(set(ids)):
        raise FetchError("partial", "MissionEdge inventory contained duplicate posting IDs.")
    return jobs, [(title, url) for title, url in links]


def fetch_missionedge(careers_url, company_id, company, transport=None):
    if not _verified_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="MissionEdge requires its verified first-party careers page.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first, links = _inventory(client)
        second, links2 = _inventory(client)
        if links != links2 or [(j["posting_id"], j["description"]) for j in first] != [(j["posting_id"], j["description"]) for j in second]:
            raise FetchError("partial", "MissionEdge role inventory changed during the reread.")
        return Inventory("complete", first, f"MissionEdge Technologies: retrieved {len(first)} full role descriptions and rechecked the careers page.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "MissionEdge response validation failed.", SOURCE, ATS)
