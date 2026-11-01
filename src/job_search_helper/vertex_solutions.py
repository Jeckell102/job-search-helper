"""Guarded source adapter for Vertex Solutions' official careers page.

Vertex's public careers page links to an Indeed employer-management dashboard.
That dashboard is not a public, employer-scoped listing feed, so this adapter
must never turn an inaccessible/empty response into a complete zero-job scan.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory
from .discovery import CareersTransport

SOURCE = "https://www.vertexsolutions.com/careers/"
ATS = "Indeed employer dashboard"
COMPANY_ID = "COMP-0338"
COMPANY = "Vertex Solutions"


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self.links.append(href)


def _verified_source(url: str, company_id: str, company: str) -> bool:
    parsed = urlsplit(url)
    return (
        company_id == COMPANY_ID
        and company.strip().casefold() == COMPANY.casefold()
        and parsed.scheme == "https"
        and parsed.hostname == "www.vertexsolutions.com"
        and parsed.path.rstrip("/") == "/careers"
        and not parsed.query
        and not parsed.fragment
    )


def fetch_vertex_solutions(url: str, company_id: str, company: str, transport=None) -> Inventory:
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Vertex Solutions adapter requires the verified official careers source.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in {401, 403, 429}:
            raise FetchError("blocked", f"Vertex Solutions careers page blocked (HTTP {response.status}).")
        if response.status != 200:
            raise FetchError("partial", f"Vertex Solutions careers page HTTP {response.status}.")
        parser = _Links()
        parser.feed(response.body.decode("utf-8", "replace"))
        indeed = [
            urljoin(SOURCE, href) for href in parser.links
            if urlsplit(urljoin(SOURCE, href)).hostname == "employers.indeed.com"
        ]
        if not indeed:
            raise FetchError("partial", "Vertex Solutions careers page no longer exposes its open-positions link.")
        raise FetchError(
            "blocked",
            "Vertex Solutions links to an Indeed employer-management dashboard, not a public employer-scoped job listing feed; stable inventory cannot be established.",
        )
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, ATS)
    except Exception as exc:
        return Inventory("failed", [], f"Vertex Solutions live source access failed ({type(exc).__name__}).", SOURCE, ATS)
