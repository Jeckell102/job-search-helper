"""Tactical Edge's first-party careers page and published modal roles."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.tacticaledge.us/careers/"
HOST = "www.tacticaledge.us"
ATS = "Tactical Edge careers"
COMPANY_ID = "COMP-0453"
COMPANY = "Tactical Edge"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.roles: list[dict[str, list[str]]] = []
        self._role: dict[str, list[str]] | None = None
        self._modal_depth = 0
        self._heading = False
        self._capture = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag in {"h1", "h2", "h3", "p", "li", "div", "title"}:
            self.parts.append(" ")
        if tag == "div" and "fusion-modal" in classes:
            if self._role is not None:
                self._finish_role()
            self._role = {"title": [], "description": []}
            self._modal_depth = 1
            return
        if self._role is None:
            return
        if tag == "div":
            self._modal_depth += 1
        if tag == "h3" and self._modal_depth:
            self._heading = True
        if self._modal_depth and tag in {"p", "li", "h2", "h3"}:
            self._capture = True

    def handle_data(self, data):
        self.parts.append(data)
        if self._role is None:
            return
        if self._heading:
            self._role["title"].append(data)
        if self._capture:
            self._role["description"].append(data)

    def handle_endtag(self, tag):
        if self._role is None:
            return
        if tag == "h3":
            self._heading = False
        if tag in {"p", "li", "h2", "h3"}:
            self._capture = False
        if tag == "div":
            self._modal_depth -= 1
            if self._modal_depth == 0:
                self._finish_role()

    def _finish_role(self):
        if self._role is not None:
            self.roles.append(self._role)
        self._role = None
        self._modal_depth = 0
        self._heading = self._capture = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == "/careers"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client):
    response = client.get(SOURCE)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Tactical Edge careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Tactical Edge careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "Tactical Edge careers page was blank.")
    page = _Page()
    page.feed(body)
    page.close()
    visible = text(" ".join(page.parts))
    if (len(visible) < 80 or "tactical edge" not in visible.casefold()
            or "open positions" not in visible.casefold()):
        raise FetchError("partial", "Tactical Edge careers identity or Open Positions section is missing.")
    return page


def _jobs(page, company_id, company):
    found = {}
    for raw in page.roles:
        title = text(" ".join(raw["title"]))
        description = text(" ".join(raw["description"]))
        if not title or len(description) < 100:
            raise FetchError("partial", "Tactical Edge published role lacks a complete title or description.")
        if "tactical edge" not in description.casefold():
            raise FetchError("partial", "Tactical Edge role description has the wrong employer scope.")
        identity = "tactical-edge-" + title.casefold().replace(" ", "-")
        job = _base({"id": identity}, ATS, company_id, company) | {
            "title": title, "description": description,
            "url": SOURCE + "#" + identity,
        }
        prior = found.get(identity)
        if prior is not None and prior["description"] != description:
            raise FetchError("partial", "Tactical Edge published roles have a conflicting duplicate identity.")
        found[identity] = job
    if not found:
        raise FetchError("partial", "Tactical Edge careers page has no complete published roles.")
    return [found[key] for key in sorted(found)]


def fetch_tactical_edge(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Tactical Edge adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first = _jobs(_read(client), company_id, company)
        second = _jobs(_read(client), company_id, company)
        first_signature = [(job["posting_id"], job["title"], job["description"]) for job in first]
        second_signature = [(job["posting_id"], job["title"], job["description"]) for job in second]
        if first_signature != second_signature:
            raise FetchError("partial", "Tactical Edge careers inventory changed during the reread.")
        return Inventory("complete", first,
                         f"Tactical Edge: retrieved {len(first)} published roles and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "Tactical Edge careers response validation failed.", SOURCE, ATS)
