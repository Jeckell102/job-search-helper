"""COMROD's published careers table and public WordPress role pages."""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://www.comrod.com/about/careers/"
HOST = "www.comrod.com"


def _plain(value):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value)).split())


def _listing(transport):
    response = transport.get(SOURCE)
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial", "COMROD careers page was unavailable.")
    html = response.body.decode("utf-8")
    table = re.search(r"<h3>Current opportunities at Comrod</h3>\s*<table>(.*?)</table>", html, re.S | re.I)
    if not table:
        raise FetchError("partial", "COMROD current-opportunities table was not found.")
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1), re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)
        if len(cells) != 3:
            continue
        match = re.search(r'href=["\']([^"\']+)["\']', cells[2], re.I)
        title = _plain(cells[1])
        if not match or not title:
            raise FetchError("partial", "COMROD careers row lacks a complete public role link.")
        url = "https://" + HOST + match.group(1) if match.group(1).startswith("/") else match.group(1)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != HOST or not parsed.path.startswith("/about/careers/") or parsed.query or parsed.fragment:
            raise FetchError("partial", "COMROD role link is outside the published careers scope.")
        rows.append((title, url))
    if not (1 <= len(rows) <= 100) or len({url for _, url in rows}) != len(rows):
        raise FetchError("partial", "COMROD careers table has an invalid role inventory.")
    return rows


def _detail(transport, url):
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    endpoint = f"https://{HOST}/wp-json/wp/v2/pages?slug={quote(slug)}"
    response = transport.get(endpoint)
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial", "COMROD public role detail was unavailable.")
    try:
        records = json.loads(response.body.decode("utf-8"))
        if type(records) is not list or len(records) != 1 or type(records[0].get("id")) is not int:
            raise ValueError
        record = records[0]
        if record.get("link") != url:
            raise ValueError
        title = text(_plain((record.get("title") or {}).get("rendered", "")))
        description = text((record.get("content") or {}).get("rendered", ""))
        if not title or not description:
            raise ValueError
        return str(record["id"]), title, description
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "COMROD public role detail has an invalid schema.") from None


def fetch_comrod(url, cid, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="COMROD adapter requires its verified unfiltered careers page.", source_url=url, ats="COMROD careers")
    client = transport or CareersTransport()
    jobs = []
    try:
        rows = _listing(client)
        for listed_title, detail_url in rows:
            ident, title, description = _detail(client, detail_url)
            comparable = lambda value: re.sub(r"[^\\w]", "", value.casefold())
            if not comparable(title).startswith(comparable(listed_title)):
                raise FetchError("partial", "COMROD listing and public detail titles disagree.")
            row = _base({"id": ident}, "COMROD careers", cid, company)
            row.update(title=title, description=description, url=detail_url)
            jobs.append(row)
        if len({job["posting_id"] for job in jobs}) != len(jobs) or _listing(client) != rows:
            raise FetchError("partial", "COMROD current opportunities changed during the scan.")
        return Inventory("complete", jobs, f"COMROD: retrieved {len(jobs)} complete postings and rechecked the public careers table.", SOURCE, "COMROD careers")
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, SOURCE, "COMROD careers")
