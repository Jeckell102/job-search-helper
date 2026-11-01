"""Company-scoped General Dynamics Land Systems public careers search."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, HTTPTransport, _base, text

SOURCE = "https://www.gd.com/careers/job-search?state=H4sIAAjv5GoAAx2KQQqAIBQFrxJv3QlaB23atfRLfPS3Sgu1QMS7Z%2B5mmClga4PEiEnpEQcbSY2hCsGzE8JEMBxEwm4ud7PPhJHw8vlIbPUfu%2FRzmYeVvR22HJO41quuGvUDfvIOQ2YAAAA%3D"
LANDING = "https://www.gdls.com/careers/"
COMPANY_LABEL = "GD Land Systems"


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.parts: list[str] = []
        self._href = ""
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._href = attrs["href"]
            self._anchor = []

    def handle_data(self, data):
        self.parts.append(data)
        if self._href:
            self._anchor.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, text(" ".join(self._anchor))))
            self._href = ""
            self._anchor = []


def _read(transport, url: str) -> str:
    response = transport.get(url)
    if response.status in (401, 403, 429):
        raise FetchError("blocked", f"General Dynamics public careers route returned HTTP {response.status}.")
    if response.status != 200:
        raise FetchError("partial", f"General Dynamics public careers route returned HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    lowered = body[:12000].casefold()
    if any(marker in lowered for marker in ("cloudflare", "azure waf", "just a moment", "you have been blocked", "human verification")):
        raise FetchError("blocked", "General Dynamics public careers route returned an access challenge.")
    return body


def _listing(html: str):
    page = _Page()
    page.feed(html)
    rows = []
    seen = set()
    for href, title in page.links:
        url = urljoin(SOURCE, href)
        parsed = urlsplit(url)
        if parsed.hostname != "www.gd.com" or not re.search(r"-gdls-opportunity/?$", parsed.path, re.I):
            continue
        if url in seen:
            continue
        seen.add(url)
        rows.append((url, title))
    return rows, text(" ".join(page.parts))


def _detail(html: str, url: str, company_id: str, company: str):
    page = _Page()
    page.feed(html)
    body = text(" ".join(page.parts))
    match = re.search(r"-(\d+)-gdls-opportunity/?$", url)
    if not match or len(body) < 120:
        raise FetchError("partial", "GD Land Systems detail lacked a stable ID or full description.")
    title = next((title for link, title in page.links if link == url and title), "")
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = text(title_match.group(1)) if title_match else ""
    if not title:
        raise FetchError("partial", "GD Land Systems detail lacked a title.")
    row = _base({"id": match.group(1)}, "GD Land Systems", company_id, company)
    row.update(title=title, url=url, description=body, req_id=match.group(1))
    return row


def fetch_gd_land_systems(careers_url, company_id, company, transport=None):
    client = transport or HTTPTransport()
    try:
        first = _read(client, SOURCE)
        first_rows, first_text = _listing(first)
        if not first_rows:
            raise FetchError("partial", "GD Land Systems filter returned no verifiable postings.")
        if COMPANY_LABEL.casefold() not in first_text.casefold():
            raise FetchError("partial", "GD Land Systems company facet was not present in the returned inventory.")
        jobs = [_detail(_read(client, url), url, company_id, company) for url, _ in first_rows]
        second_rows, second_text = _listing(_read(client, SOURCE))
        if [url for url, _ in second_rows] != [url for url, _ in first_rows]:
            raise FetchError("partial", "GD Land Systems listing membership changed during reread.")
        if COMPANY_LABEL.casefold() not in second_text.casefold():
            raise FetchError("partial", "GD Land Systems scope disappeared during reread.")
        return Inventory("complete", jobs, f"GD Land Systems: retrieved {len(jobs)} scoped postings and rechecked membership.", SOURCE, "GD Land Systems")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, "GD Land Systems")
    except (OSError, ValueError, TypeError):
        return Inventory("failed", [], "GD Land Systems validation failed; inventory completeness is unknown.", SOURCE, "GD Land Systems")
