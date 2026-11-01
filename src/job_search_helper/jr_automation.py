"""JR Automation's employer-filtered Hitachi Careers board."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit

from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://careers.hitachi.com/jobs?filter%5Bbrand%5D%5B0%5D=JR%20Automation"
HOST = "careers.hitachi.com"
MAX_PAGES = 100


class _DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld = []
        self.canonical = []
        self.visible = []
        self._script = False
        self._style = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "canonical" in (attrs.get("rel") or "").split():
            self.canonical.append(attrs.get("href", ""))
        if tag == "script":
            self._script = True
            self._buf = []
        elif tag in {"style", "noscript"}:
            self._style = True

    def handle_data(self, data):
        if self._script:
            self._buf.append(data)
        elif not self._style:
            self.visible.append(data)

    def handle_endtag(self, tag):
        if tag == "script":
            self.ld.append("".join(self._buf))
            self._script = False
            self._buf = []
        elif tag in {"style", "noscript"}:
            self._style = False


def _body(client, url):
    response = client.get(url)
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial",
                         "JR Automation public careers page was unavailable.")
    return response.body.decode("utf-8", "replace")


def _preload(body):
    marker = "window.__PRELOAD_STATE__ ="
    pos = body.find(marker)
    if pos < 0:
        raise FetchError("partial", "JR Automation board did not expose its public inventory state.")
    try:
        state, _ = json.JSONDecoder().raw_decode(body[pos + len(marker):].lstrip())
    except (ValueError, TypeError):
        raise FetchError("partial", "JR Automation board inventory state was malformed.") from None
    search = state.get("jobSearch") if isinstance(state, dict) else None
    if not isinstance(search, dict) or type(search.get("totalJob")) is not int or type(search.get("jobs")) is not list:
        raise FetchError("partial", "JR Automation board inventory state had an invalid schema.")
    return search


def _page_url(page):
    return SOURCE if page == 1 else SOURCE + "&page=" + str(page)


def _listing(client, page):
    search = _preload(_body(client, _page_url(page)))
    total = search["totalJob"]
    records = search["jobs"]
    if total < 0 or len(records) > 100 or (total and not records):
        raise FetchError("partial", "JR Automation board published an invalid page.")
    out = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise FetchError("partial", "JR Automation board contained a malformed posting.")
        ident = record.get("requisitionID")
        title = text(record.get("title"))
        original = record.get("originalURL")
        brand = record.get("brandName")
        legal = {f.get("value") for f in record.get("customFields", [])
                 if isinstance(f, dict) and f.get("cfKey") == "cf_legal_name"}
        if (not isinstance(ident, str) or not re.fullmatch(r"R[0-9]{4,24}", ident)
                or not title or not isinstance(original, str) or not original or original.startswith("//")
                or brand != "JR Automation" or legal != {"JR Automation"} or ident in seen):
            raise FetchError("partial", "JR Automation board contained an out-of-scope or duplicate posting.")
        detail = urljoin(SOURCE, quote(original, safe="/?=&%"))
        parsed = urlsplit(detail)
        if parsed.scheme != "https" or parsed.hostname != HOST or parsed.query or parsed.fragment:
            raise FetchError("partial", "JR Automation posting URL was outside the verified board scope.")
        seen.add(ident)
        out.append((ident, title, detail, record))
    return total, out


def _job_detail(client, item, company_id, company):
    ident, listed_title, detail_url, record = item
    body = _body(client, detail_url)
    # JSON-LD is the public full body; require exactly one posting object.
    parser = _DetailParser()
    parser.feed(body)
    postings = []
    for raw in parser.ld:
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            continue
        values = value if isinstance(value, list) else [value]
        postings.extend(v for v in values if isinstance(v, dict) and
                        (v.get("@type") == "JobPosting" or "JobPosting" in (v.get("@type") or [])))
    canonical = [href for href in parser.canonical if href]
    if len(postings) != 1 or len(canonical) != 1:
        raise FetchError("partial", f"JR Automation posting {ident} lacked a unique public detail record.")
    posting = postings[0]
    description = posting.get("description")
    ident_meta = posting.get("identifier")
    canonical_url = urljoin(detail_url, canonical[0])
    parsed = urlsplit(canonical_url)
    if (not isinstance(description, str) or len(text(description)) < 100
            or not isinstance(ident_meta, dict) or ident_meta.get("value") != ident
            or text(posting.get("title")) != listed_title
            or parsed.scheme != "https" or parsed.hostname != HOST
            or parsed.query or parsed.fragment or canonical_url != detail_url
            or "JR Automation" not in text(" ".join(parser.visible))):
        raise FetchError("partial", f"JR Automation posting {ident} failed identity or full-body validation.")
    row = _base({"id": ident}, "Hitachi Careers (JR Automation)", company_id, company)
    locations = record.get("locations") or []
    location = next((text(x.get("locationParsedText") or x.get("locationText"))
                     for x in locations if isinstance(x, dict) and text(x.get("locationParsedText") or x.get("locationText"))), "")
    row.update(title=listed_title, description=description, url=detail_url, req_id=ident,
               location=location, created_at=text(posting.get("datePosted")))
    return row


def fetch_jr_automation(url, company_id, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="JR Automation requires its verified Hitachi brand-filtered board.",
                         source_url=url, ats="Hitachi Careers (JR Automation)")
    client = transport or CareersTransport()
    jobs = []
    try:
        total, first = _listing(client, 1)
        pages = (total + 9) // 10
        if total != 64 or pages > MAX_PAGES:
            raise FetchError("partial", "JR Automation published an invalid filtered inventory size.")
        entries = list(first)
        if len(entries) != min(10, total):
            raise FetchError("partial", "JR Automation first page length disagreed with its inventory.")
        for page in range(2, pages + 1):
            check_total, current = _listing(client, page)
            if check_total != total or len(current) != min(10, total - len(entries)):
                raise FetchError("partial", "JR Automation pagination changed during enumeration.")
            entries.extend(current)
        if len(entries) != total or len({x[0] for x in entries}) != total:
            raise FetchError("partial", "JR Automation inventory was incomplete or duplicated.")
        with ThreadPoolExecutor(max_workers=8) as pool:
            jobs = list(pool.map(lambda item: _job_detail(client, item, company_id, company), entries))
        initial = {(x[0], x[1], x[2]) for x in entries}
        reread = []
        for page in range(1, pages + 1):
            check_total, current = _listing(client, page)
            reread.extend(current)
            if check_total != total:
                raise FetchError("partial", "JR Automation filtered inventory changed during the scan.")
        if {(x[0], x[1], x[2]) for x in reread} != initial:
            raise FetchError("partial", "JR Automation filtered inventory changed during the scan.")
        return Inventory("complete", jobs, f"JR Automation: retrieved {len(jobs)} complete postings and rechecked the filtered inventory.", SOURCE, "Hitachi Careers (JR Automation)")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, SOURCE, "Hitachi Careers (JR Automation)")
    except (AttributeError, KeyError, TypeError, ValueError):
        return Inventory("partial", jobs, "JR Automation public careers schema validation failed.", SOURCE, "Hitachi Careers (JR Automation)")
