"""Read-only adapter for public Gusto Recruiting boards."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://jobs.gusto.com/boards/robinson-unmanned-ab0be6b1-c413-41d2-9d68-f62c878589e4"
BOARD_HOST = "jobs.gusto.com"
POSTING_RE = re.compile(r"^/postings/[a-z0-9][a-z0-9-]*$", re.I)


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text_parts: list[str] = []
        self.json_ld: list[str] = []
        self._script: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag == "script" and attrs.get("type", "").lower() == "application/ld+json":
            self._script = []

    def handle_data(self, data):
        self.text_parts.append(data)
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.json_ld.append("".join(self._script))
            self._script = None


def _read(client, url):
    response = client.get(url)
    if response.status in (401, 403, 429):
        raise FetchError("blocked", f"Gusto public board HTTP {response.status}; access was denied.")
    if response.status != 200:
        raise FetchError("partial", f"Gusto public board HTTP {response.status}; inventory is incomplete.")
    return response.body.decode("utf-8", "replace")


def _posting_links(html):
    page = _Page()
    page.feed(html)
    links = []
    for href in page.links:
        absolute = urljoin(SOURCE, href)
        parsed = urlsplit(absolute)
        if parsed.hostname == BOARD_HOST and POSTING_RE.fullmatch(parsed.path) and not parsed.query and not parsed.fragment:
            canonical = f"https://{BOARD_HOST}{parsed.path}"
            if canonical not in links:
                links.append(canonical)
    return links, page


def _json_ld(html):
    page = _Page()
    page.feed(html)
    for raw in page.json_ld:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                for nested in item["@graph"]:
                    if isinstance(nested, dict) and nested.get("@type") == "JobPosting":
                        return nested
    return None


def _location(value):
    if isinstance(value, list):
        return "; ".join(x for x in (_location(item) for item in value) if x)
    if not isinstance(value, dict):
        return text(value)
    address = value.get("address") or value
    if not isinstance(address, dict):
        return text(address)
    return ", ".join(x for x in (
        text(address.get("addressLocality")), text(address.get("addressRegion")),
        text(address.get("addressCountry")),
    ) if x)


def _row(data, url, company_id, company):
    title = text(data.get("title"))
    description = text(data.get("description"))
    if not title or len(description) < 80:
        raise FetchError("partial", "Gusto posting lacks a complete JSON-LD title or description.")
    ident = urlsplit(url).path.rsplit("/", 1)[-1]
    row = _base({"id": ident}, "Gusto", company_id, company)
    organization = data.get("hiringOrganization") or {}
    org_name = text(organization.get("name")) if isinstance(organization, dict) else ""
    if org_name and company.casefold() not in org_name.casefold() and "robinson" not in org_name.casefold():
        raise FetchError("partial", "Gusto posting employer identity does not match the queued company.")
    row.update(title=title, description=description, url=url,
               location=_location(data.get("jobLocation")),
               work_arrangement=text(data.get("jobLocationType")),
               compensation=text(data.get("baseSalary")),
               created_at=text(data.get("datePosted")),
               updated_at=text(data.get("dateModified")))
    return row


def fetch_gusto(careers_url, company_id, company, transport=None):
    client = transport or CareersTransport()
    jobs = []
    try:
        board = _read(client, SOURCE)
        links, page = _posting_links(board)
        visible = " ".join(page.text_parts).casefold()
        if not links and not any(phrase in visible for phrase in ("no open positions", "no positions currently", "no current openings")):
            raise FetchError("partial", "Gusto board exposed no postings and no authoritative zero-openings statement.")
        for url in links:
            jobs.append(_row(_json_ld(_read(client, url)) or {}, url, company_id, company))
        second, _ = _posting_links(_read(client, SOURCE))
        if second != links:
            raise FetchError("partial", "Gusto board changed during the installed reread.")
        return Inventory("complete", jobs, f"Gusto: retrieved {len(jobs)} full postings with a stable board reread.", SOURCE, "Gusto")
    except FetchError as exc:
        return Inventory(exc.status, jobs, exc.reason, SOURCE, "Gusto")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", jobs, "Gusto board schema validation failed; inventory completeness unknown.", SOURCE, "Gusto")
