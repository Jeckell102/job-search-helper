"""Baicells' first-party careers accordion.

Baicells publishes its openings as inline HubSpot accordion panels rather than
individual detail URLs or an ATS board.  Each panel is therefore emitted as a
stable, company-scoped posting whose URL is a deterministic fragment of the
official careers page.
"""
from __future__ import annotations

from hashlib import sha256
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport


SOURCE = "https://www.baicells.com/careers"
HOST = "www.baicells.com"
ATS = "Baicells careers"
COMPANY_ID = "COMP-0408"
COMPANY = "Baicells"


class _Accordion(HTMLParser):
    """Extract panel titles and all published text from accordion bodies."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.panels = []
        self.current = None
        self.title_depth = 0
        self.body_depth = 0

    @staticmethod
    def _classes(attrs):
        return set(dict(attrs).get("class", "").split())

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = self._classes(attrs)
        if tag == "div" and "panel" in classes and "panel-default" in classes:
            if self.current is not None:
                self.panels.append(self.current)
            self.current = {"title": [], "body": [], "panel_depth": 1}
            return
        if self.current is None:
            return
        if tag == "div" and self.current["panel_depth"]:
            self.current["panel_depth"] += 1
        if (tag == "a" and attrs_dict.get("role") == "button"
                and attrs_dict.get("data-toggle") == "collapse"):
            self.title_depth = 1
        elif self.title_depth:
            self.title_depth += 1
        if tag == "div" and ({"panel-body", "content"} & classes):
            self.body_depth = 1
        elif self.body_depth:
            self.body_depth += 1

    def handle_endtag(self, tag):
        if self.current is None:
            return
        if self.title_depth:
            self.title_depth -= 1
        if self.body_depth:
            self.body_depth -= 1
        if tag == "div" and self.current["panel_depth"]:
            self.current["panel_depth"] -= 1
            if self.current["panel_depth"] == 0:
                self.panels.append(self.current)
                self.current = None

    def handle_data(self, data):
        if self.current is None:
            return
        if self.title_depth:
            self.current["title"].append(data)
        if self.body_depth:
            self.current["body"].append(data)

    def close(self):
        super().close()
        if self.current is not None:
            self.panels.append(self.current)
            self.current = None


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path == "/careers" and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client):
    response = client.get(SOURCE)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Baicells careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Baicells careers page HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "Baicells careers page was blank.")
    parser = _Accordion()
    parser.feed(body)
    parser.close()
    visible = text(body)
    if "baicells" not in visible.casefold() or "career" not in visible.casefold():
        raise FetchError("partial", "Baicells careers identity is missing.")
    if not parser.panels:
        raise FetchError("partial", "Baicells careers page has no published accordion panels.")
    return parser.panels


def _records(panels, company_id, company):
    jobs = []
    seen = set()
    for panel in panels:
        title = text(" ".join(panel["title"])).strip()
        description = text(" ".join(panel["body"])).strip()
        if not title or len(title) > 220 or len(description) < 100:
            raise FetchError("partial", "Baicells accordion role lacks a complete title or description.")
        key = re.sub(r"\s+", " ", title).casefold()
        if key in seen:
            raise FetchError("partial", "Baicells careers inventory contains duplicate role identities.")
        seen.add(key)
        ident = "baicells-" + sha256(key.encode("utf-8")).hexdigest()[:24]
        url = f"{SOURCE}#job-{ident.removeprefix('baicells-')}"
        jobs.append(_base({"id": ident}, ATS, company_id, company) | {
            "title": title,
            "description": description,
            "url": url,
        })
    return jobs


def _fingerprint(jobs):
    return [(job["posting_id"], job["title"], sha256(job["description"].encode("utf-8")).hexdigest())
            for job in jobs]


def fetch_baicells(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Baicells adapter requires the verified Baicells company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    jobs = []
    try:
        first = _records(_read(client), company_id, company)
        second = _records(_read(client), company_id, company)
        if _fingerprint(first) != _fingerprint(second):
            raise FetchError("partial", "Baicells careers inventory changed during the reread.")
        return Inventory("complete", first,
                         f"Baicells: retrieved {len(first)} published accordion roles and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", jobs, "Baicells careers response validation failed.", SOURCE, ATS)
