"""DSI Innovations' first-party employment-opportunities page."""
from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://dsiinnovations.com/employment-opportunities/"
HOSTS = {"dsiinnovations.com", "www.dsiinnovations.com"}
ATS = "DSI Innovations careers"
COMPANY_ID = "COMP-0391"
COMPANY = "DSI Innovations"
_ROLE_START = re.compile(r"\b(?:an|a)\s+(.+?)\s+to\s+support\b", re.I)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []
        self._section = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section":
            if self._section is None:
                self._section = {"depth": 1, "parts": [], "links": []}
            else:
                self._section["depth"] += 1
            return
        if self._section is None:
            return
        if tag in {"div", "p", "li", "br", "h1", "h2", "h3", "h4", "strong"}:
            self._section["parts"].append(" ")
        if tag == "a" and attrs.get("href"):
            self._section["links"].append(attrs["href"])

    def handle_data(self, data):
        if self._section is not None:
            self._section["parts"].append(data)

    def handle_endtag(self, tag):
        if self._section is None or tag != "section":
            return
        self._section["depth"] -= 1
        if self._section["depth"] == 0:
            self.sections.append(self._section)
            self._section = None


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname in HOSTS
                and parsed.path.rstrip("/") == "/employment-opportunities"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client):
    response = client.get(SOURCE)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"DSI Innovations careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"DSI Innovations careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "DSI Innovations careers page was blank.")
    page = _Page()
    page.feed(body)
    page.close()
    return page


def _jobs(page):
    result = []
    seen = set()
    for section in page.sections:
        body = text(" ".join(section["parts"]))
        # Elementor wraps the whole page and the hidden mobile layout in
        # very large sections; only the bounded role sections are inventory.
        if len(body) > 10000:
            continue
        if "DSI Innovations is growing" not in body or "Responsibilities of the" not in body:
            continue
        match = _ROLE_START.search(body)
        if not match:
            raise FetchError("partial", "DSI role description has no verifiable role title.")
        title = text(match.group(1))
        if not title or len(body) < 500 or "Qualifications of the" not in body:
            raise FetchError("partial", f"DSI {title or 'role'} description is incomplete.")
        apply_urls = [
            urljoin(SOURCE, href) for href in section["links"]
            if urlsplit(urljoin(SOURCE, href)).hostname in HOSTS
        ]
        if not apply_urls:
            raise FetchError("partial", f"DSI {title} has no first-party application route.")
        key = (title.casefold(), body)
        if key in seen:
            continue
        seen.add(key)
        posting_id = f"dsi-innovations-{re.sub(r'[^a-z0-9]+', '-', title.casefold()).strip('-')}"
        row = _base({"id": posting_id}, ATS, COMPANY_ID, COMPANY)
        row.update(title=title, description=body, url=apply_urls[0])
        result.append(row)
    if not result:
        raise FetchError("partial", "DSI Innovations page exposed no complete current role descriptions.")
    return sorted(result, key=lambda row: row["title"].casefold())


def fetch_dsi_innovations(careers_url, company_id, company, transport=None):
    if not _verified_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="DSI Innovations requires its verified first-party employment page.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first = _jobs(_read(client))
        second = _jobs(_read(client))
        if [(j["posting_id"], j["description"]) for j in first] != [(j["posting_id"], j["description"]) for j in second]:
            raise FetchError("partial", "DSI Innovations role inventory changed during the reread.")
        return Inventory("complete", first, f"DSI Innovations: retrieved {len(first)} full role descriptions and rechecked the employment page.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "DSI Innovations response validation failed.", SOURCE, ATS)
