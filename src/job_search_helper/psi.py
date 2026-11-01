"""Physical Sciences Inc.'s employer-owned public job search."""
from __future__ import annotations

import json
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, HTTPTransport, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://www.psicorp.com/careers/open-positions/"
SEARCH = "https://www.psicorp.com/wp-admin/admin-ajax.php"
HOST = "www.psicorp.com"
MAX_PAGES = 100


class _Listing(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.title, self.href, self._in_title = [], "", False
        self.feed(body); self.close()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "h3" and "info__title" in values.get("class", "").split(): self._in_title = True
        if tag == "a" and values.get("href"): self.href = values["href"]

    def handle_data(self, value):
        if self._in_title: self.title.append(value)

    def handle_endtag(self, tag):
        if tag == "h3": self._in_title = False


def _listing(client, page):
    response = client.post_form(SEARCH, {"action": "job_positions_search", "paged": page})
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial", "PSI public job search was unavailable.")
    try:
        data = json.loads(response.body.decode("utf-8")); total = int(data["results_count"]); pages = int(data["total_pages"]); cards = data["posts"]
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "PSI public job search returned an invalid schema.") from None
    if not isinstance(cards, list) or total < 0 or not 1 <= pages <= MAX_PAGES or len(cards) > total:
        raise FetchError("partial", "PSI public job search returned inconsistent pagination.")
    rows = []
    for card in cards:
        if not isinstance(card, str): raise FetchError("partial", "PSI public job search returned an invalid posting.")
        parsed = _Listing(card); title = text(" ".join(parsed.title)); url = urljoin(SOURCE, parsed.href)
        parts = urlsplit(url)
        if not title or parts.scheme != "https" or parts.hostname != HOST or not parts.path.startswith("/careers/open-positions/") or parts.query or parts.fragment:
            raise FetchError("partial", "PSI public job search returned a posting outside its official careers scope.")
        rows.append((parts.path.rstrip("/").rsplit("/", 1)[-1], title, url))
    return rows, total, pages


def _detail(client, url):
    response = client.get(url)
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial", "PSI public job detail was unavailable.")
    return text(response.body.decode("utf-8", "replace"))


def fetch_psi(careers_url, company_id, company, transport=None, detail_transport=None):
    if careers_url != SOURCE:
        return Inventory("unsupported", reason="PSI adapter requires its verified unfiltered public openings page.", source_url=careers_url, ats="PSI careers")
    listings = transport or HTTPTransport(); details = detail_transport or CareersTransport()
    jobs = []
    try:
        first, total, pages = _listing(listings, 1); rows = list(first)
        for page in range(2, pages + 1):
            current, current_total, current_pages = _listing(listings, page)
            if current_total != total or current_pages != pages: raise FetchError("partial", "PSI public inventory changed during pagination.")
            rows.extend(current)
        if len(rows) != total or len({row[0] for row in rows}) != len(rows): raise FetchError("partial", "PSI public inventory did not reconcile with its published count.")
        for ident, listed_title, url in rows:
            description = _detail(details, url)
            if len(description) < 250 or listed_title not in description: raise FetchError("partial", "PSI public job detail lacks a matching title or full description.")
            row = _base({"id": ident}, "PSI careers", company_id, company); row.update(title=listed_title, description=description, url=url); jobs.append(row)
        check, check_total, check_pages = _listing(listings, 1)
        if check != first or check_total != total or check_pages != pages: raise FetchError("partial", "PSI public inventory changed during the scan.")
        return Inventory("complete", jobs, f"PSI careers: retrieved {len(jobs)} complete postings and rechecked the public inventory.", SOURCE, "PSI careers")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, SOURCE, "PSI careers")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", jobs, "PSI public careers schema validation failed.", SOURCE, "PSI careers")
