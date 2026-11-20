"""Blues official careers adapter.

Blues currently publishes its openings CTA as a LinkedIn company link.  The
public LinkedIn guest surface does not provide a complete, employer-scoped
inventory with reusable full descriptions, so this adapter deliberately
returns ``partial`` and records the verified blocker rather than treating the
absence of an enumerable feed as zero openings.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory
from .discovery import CareersTransport

COMPANY_ID = "COMP-0281"
COMPANY = "Blues"
SOURCE = "https://blues.com/bluescareers/"
LINKEDIN_HOSTS = {"www.linkedin.com", "linkedin.com"}


class _Links(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.links: list[str] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            self._href = urljoin(self.source, attrs.get("href", ""))
            self._text = []

    def handle_data(self, data):
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            text = " ".join("".join(self._text).split()).casefold()
            if "linkedin" in text or "open position" in text or "job" in text:
                self.links.append(self._href)
            self._href = ""
            self._text = []


def _linkedin_links(body: bytes) -> list[str]:
    parser = _Links(SOURCE)
    parser.feed(body.decode("utf-8", "replace"))
    return [link for link in parser.links if urlsplit(link).hostname in LINKEDIN_HOSTS]


def fetch_blues(careers_url, company_id, company, transport=None):
    if (company_id != COMPANY_ID or company.casefold() != COMPANY.casefold()
            or careers_url.rstrip("/") != SOURCE.rstrip("/")):
        return Inventory("unsupported", [], "Blues adapter received an unexpected company or source.", careers_url, "Blues careers", browser_fallback_allowed=False)

    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Blues official careers source HTTP {response.status}; public inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"Blues official careers source HTTP {response.status}; inventory completeness is unknown.")
        body = response.body
        text = body.decode("utf-8", "replace").casefold()
        if "careers at blues" not in text or "open positions" not in text:
            raise FetchError("partial", "Blues careers source changed; official identity or Open Positions section could not be verified.")
        links = _linkedin_links(body)
        if not links:
            raise FetchError("partial", "Blues Open Positions section exposed no verifiable public recruiting destination; inventory completeness is unknown.")
        raise FetchError("partial", "Blues official Open Positions link is LinkedIn-only; no public employer-scoped inventory or full descriptions are available to verify.")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, "Blues careers", browser_fallback_allowed=False)
    except Exception as exc:
        return Inventory("partial", [], f"Blues official careers source transport failed ({type(exc).__name__}); inventory completeness is unknown.", SOURCE, "Blues careers", browser_fallback_allowed=False)


__all__ = ["COMPANY_ID", "COMPANY", "SOURCE", "fetch_blues"]
