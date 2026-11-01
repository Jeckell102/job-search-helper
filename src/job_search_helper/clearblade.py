"""ClearBlade's first-party Webflow careers cards."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.clearblade.com/company/careers"
HOST = "www.clearblade.com"
ATS = "ClearBlade careers"
COMPANY_ID = "COMP-0275"
COMPANY = "ClearBlade"
CARD_CLASS = "cop_cms_item"
CARD_TITLE_CLASS = "cop_card_title"
CARD_SECTION_MARKER = re.compile(r"\bopen positions\b", re.I)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.cards: list[dict] = []
        self._card: dict | None = None
        self._card_depth = 0
        self._h3 = False
        self._paragraph = False
        self._anchor = False
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "div" and CARD_CLASS in classes:
            if self._card is not None:
                self._finish_card()
            self._card = {"title": [], "description": [], "apply": []}
            self._card_depth = 1
            return
        if self._card is not None and tag == "div":
            self._card_depth += 1
        if self._card is not None and tag == "h3" and CARD_TITLE_CLASS in classes:
            self._h3 = True
        if self._card is not None and tag in {"p", "li"}:
            self._paragraph = True
        if self._card is not None and tag == "a" and attrs.get("href"):
            self._anchor = True
            self._anchor_text = []
            self._card.setdefault("anchor_href", []).append(attrs["href"])
        if tag in {"h1", "h2", "h3", "p", "li", "div", "title"}:
            self.parts.append(" ")

    def handle_data(self, data):
        self.parts.append(data)
        if self._card is None:
            return
        if self._h3:
            self._card["title"].append(data)
        if self._paragraph:
            self._card["description"].append(data)
        if self._anchor:
            self._anchor_text.append(data)

    def handle_endtag(self, tag):
        if self._card is None:
            return
        if tag == "h3":
            self._h3 = False
        if tag in {"p", "li"}:
            self._paragraph = False
        if tag == "a":
            self._anchor = False
        if tag == "div":
            self._card_depth -= 1
            if self._card_depth == 0:
                self._finish_card()

    def _finish_card(self):
        if self._card is not None:
            self.cards.append(self._card)
        self._card = None
        self._card_depth = 0
        self._h3 = self._paragraph = self._anchor = False


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") in {"/careers", "/company/careers"}
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client, url):
    response = client.get(url)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"ClearBlade careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"ClearBlade careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "ClearBlade careers page was blank.")
    page = _Page()
    page.feed(body)
    page.close()
    visible = text(" ".join(page.parts))
    if len(visible) < 80 or "clearblade" not in visible.casefold() or not CARD_SECTION_MARKER.search(visible):
        raise FetchError("partial", "ClearBlade careers identity or open-position section is missing.")
    return page, visible


def _card_identity(title: str) -> str:
    return "clearblade-card-" + re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")


def _cards(page, company_id, company):
    found = {}
    for raw in page.cards:
        title = text(" ".join(raw["title"]))
        description = text(" ".join(raw["description"]))
        if not title or not description:
            raise FetchError("partial", "ClearBlade published role card lacks a title or complete description.")
        identity = _card_identity(title)
        job = _base({"id": identity}, ATS, company_id, company) | {
            "title": title, "description": description, "url": SOURCE + "#" + identity,
        }
        prior = found.get(identity)
        if prior is not None and prior["description"] != description:
            raise FetchError("partial", "ClearBlade published role cards have a conflicting duplicate identity.")
        found[identity] = job
    if not found:
        raise FetchError("partial", "ClearBlade careers page has no complete published role cards.")
    return [found[key] for key in sorted(found)]


def fetch_clearblade(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="ClearBlade adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first, _ = _read(client, SOURCE)
        first_jobs = _cards(first, company_id, company)
        first_signature = [(job["posting_id"], job["title"], job["description"]) for job in first_jobs]
        second, _ = _read(client, SOURCE)
        second_jobs = _cards(second, company_id, company)
        second_signature = [(job["posting_id"], job["title"], job["description"]) for job in second_jobs]
        if first_signature != second_signature:
            raise FetchError("partial", "ClearBlade published role-card inventory changed during the reread.")
        return Inventory("complete", first_jobs,
                         f"ClearBlade: retrieved {len(first_jobs)} published role cards and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "ClearBlade careers response validation failed.", SOURCE, ATS)
