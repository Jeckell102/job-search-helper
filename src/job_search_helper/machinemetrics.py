"""MachineMetrics' first-party careers page and featured roles."""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.machinemetrics.com/careers/"
ATS = "MachineMetrics careers"
COMPANY_ID = "COMP-0278"
COMPANY = "MachineMetrics"
HOST = "www.machinemetrics.com"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.roles: list[dict[str, list[str]]] = []
        self._role: dict[str, list[str]] | None = None
        self._tag = ""
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").casefold()
        if tag in {"h3", "h4"} and self._role is None and "job" in classes + " ":
            self._role = {"title": [], "description": [], "url": []}
            self._tag = "title"
        elif self._role is not None and tag in {"p", "li"}:
            self._tag = "description"
        elif self._role is not None and tag == "a" and attrs.get("href"):
            self._role["url"].append(attrs["href"])

    def handle_data(self, data):
        if self._role is not None and self._tag in {"title", "description"}:
            self._role[self._tag].append(data)

    def handle_endtag(self, tag):
        if self._role is None:
            return
        if tag in {"h3", "h4"}:
            self._tag = "description"
        if tag in {"p", "li"}:
            self._tag = "description"
    def close(self):
        super().close()
        if self._role is not None:
            self.roles.append(self._role)
            self._role = None


def _verified_source(url, company_id, company):
    try:
        parsed = urlsplit(url)
        return (company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()
                and parsed.scheme == "https" and parsed.hostname == HOST
                and parsed.path.rstrip("/") == "/careers"
                and not parsed.query and not parsed.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _read(client):
    response = client.get(SOURCE)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"MachineMetrics careers page blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"MachineMetrics careers page HTTP {response.status}.")
    page = _Page()
    page.feed(response.body.decode("utf-8", "replace"))
    page.close()
    return page


def _jobs(page, company_id, company):
    jobs = []
    for raw in page.roles:
        title = text(" ".join(raw["title"]))
        description = text(" ".join(raw["description"]))
        if not title or len(description) < 120:
            raise FetchError("partial", "MachineMetrics featured role lacks a complete description.")
        posting_id = "machinemetrics-" + "-".join(title.casefold().split())
        job = _base({"id": posting_id}, ATS, company_id, company) | {
            "title": title, "description": description,
            "url": SOURCE + "#" + posting_id,
        }
        jobs.append(job)
    if not jobs:
        raise FetchError("partial", "MachineMetrics careers page has no complete featured roles.")
    return jobs


def fetch_machinemetrics(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="MachineMetrics adapter requires the verified company and careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        first = _jobs(_read(client), company_id, company)
        second = _jobs(_read(client), company_id, company)
        signature = lambda rows: [(j["posting_id"], j["title"], j["description"]) for j in rows]
        if signature(first) != signature(second):
            raise FetchError("partial", "MachineMetrics featured-role inventory changed during the reread.")
        return Inventory("complete", first,
                         f"MachineMetrics: retrieved {len(first)} featured roles and rechecked the careers page.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "MachineMetrics careers response validation failed.", SOURCE, ATS)
