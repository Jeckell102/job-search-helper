"""Paced, resumable General Dynamics Land Systems public search."""
from __future__ import annotations

import json
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from .ats import FetchError, HTTPResponse, Inventory, HTTPTransport, _base, text
from .detail_checkpoint import checkpoint_payload, reusable_details

SOURCE = "https://www.gd.com/careers/job-search?state=H4sIAAjv5GoAAx2KQQqAIBQFrxJv3QlaB23atfRLfPS3Sgu1QMS7Z%2B5mmClga4PEiEnpEQcbSY2hCsGzE8JEMBxEwm4ud7PPhJHw8vlIbPUfu%2FRzmYeVvR22HJO41quuGvUDfvIOQ2YAAAA%3D"
LANDING = "https://www.gdls.com/careers/"
COMPANY_LABEL = "GD Land Systems"
HOST = "www.gd.com"
MAX_PAGES = 100
MAX_JOBS = 5000
RETRIES = 3
DEFAULT_CHECKPOINT = os.environ.get("GDLS_CHECKPOINT_PATH", "/tmp/gdls-progress.json")
TRANSIENT = {408, 429, 500, 502, 503, 504}


def safe_public_path(parsed):
    """Allow this scoped listing, bounded pages, and GDLS-only detail routes."""
    if parsed.hostname != HOST or parsed.fragment:
        return False
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query = dict(pairs)
    if len(query) != len(pairs):
        return False
    if parsed.path == "/careers/job-search":
        expected_state = dict(parse_qsl(urlsplit(SOURCE).query))["state"]
        return (set(query) <= {"state", "page"} and query.get("state") == expected_state
                and ("page" not in query or (query["page"].isdigit()
                     and 0 <= int(query["page"]) < MAX_PAGES)))
    return (not parsed.query and bool(re.fullmatch(
        r"/careers/[A-Za-z0-9-]+-[0-9]+-gdls-opportunity/?", parsed.path)))


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.headings = []
        self.page_links = []
        self._href = ""
        self._anchor = []
        self._heading = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self._href, self._anchor = attrs["href"], []
        if tag in {"h1", "h2", "h3"}:
            self._heading = []

    def handle_data(self, data):
        self.parts.append(data)
        if self._href:
            self._anchor.append(data)
        if self._heading is not None:
            self._heading.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            label = text(" ".join(self._anchor))
            self.links.append((self._href, label))
            if re.search(r"[?&]page=\d+", self._href, re.I) or label in {"1", "2", "3", "4", "5"}:
                self.page_links.append(self._href)
            self._href, self._anchor = "", []
        if tag in {"h1", "h2", "h3"} and self._heading is not None:
            self.headings.append(text(" ".join(self._heading)))
            self._heading = None


def _parse(body):
    page = _Page()
    page.feed(body)
    page.close()
    return page


def _atomic(path, payload):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                           prefix=target.name + ".", delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, target)


def _checkpoint(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if (not isinstance(value, dict) or value.get("source_url") != SOURCE
            or value.get("company_id") != "COMP-0097"
            or not isinstance(value.get("entries"), list)
            or not isinstance(value.get("jobs"), list)):
        return None
    return value


def _save(path, *, entries, jobs, phase, pages, reason=""):
    _atomic(path, checkpoint_payload({"source_url": SOURCE, "company_id": "COMP-0097",
                   "scope": COMPANY_LABEL, "entries": entries, "jobs": jobs,
                   "phase": phase, "pages": pages, "reason": reason,
                   "saved_at": time.time()}))


def _pause(client, attempt, headers):
    retry_after = (headers or {}).get("retry-after", (headers or {}).get("Retry-After", ""))
    try:
        delay = min(3.0, max(0.0, float(retry_after)))
    except (ValueError, TypeError):
        delay = min(2.0, 0.35 * (attempt + 1))
    sleeper = getattr(client, "sleep", None)
    if sleeper:
        sleeper(delay)


def _read(client, url):
    last = None
    for attempt in range(RETRIES):
        response = client.get(url)
        if not isinstance(response, HTTPResponse):
            raise FetchError("failed", "GD Land Systems transport returned an invalid response.")
        last = response
        if response.status in (401, 403):
            raise FetchError("blocked", f"General Dynamics public careers route returned HTTP {response.status}.")
        if response.status in TRANSIENT and attempt < RETRIES - 1:
            _pause(client, attempt, response.headers)
            continue
        if response.status != 200:
            status = "blocked" if response.status == 429 else "partial"
            raise FetchError(status, f"General Dynamics public careers route returned HTTP {response.status} after bounded retries.")
        body = response.body.decode("utf-8", "replace")
        lowered = body[:20000].casefold()
        if any(marker in lowered for marker in ("cloudflare", "azure waf", "just a moment", "you have been blocked", "human verification")):
            raise FetchError("blocked", "General Dynamics public careers route returned an access challenge.")
        return body
    raise FetchError("failed", f"General Dynamics public careers route failed after {RETRIES} attempts (HTTP {getattr(last, 'status', 'unknown')}).")


def _page_url(page_url, number):
    parsed = urlsplit(page_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "page"]
    query.append(("page", str(number)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def _listing(html, base_url=SOURCE):
    page = _parse(html)
    rows, seen = [], set()
    for href, title in page.links:
        url = urljoin(base_url, href)
        parsed = urlsplit(url)
        if (parsed.hostname != HOST or not re.search(r"-gdls-opportunity/?$", parsed.path, re.I) or not title):
            continue
        if url not in seen:
            seen.add(url)
            rows.append((url, title))
    pages = set()
    for href in page.page_links:
        match = re.search(r"[?&]page=(\d+)", urljoin(base_url, href))
        if match:
            pages.add(int(match.group(1)))
    return rows, pages, text(" ".join(page.parts))


def _inventory(client, checkpoint_path):
    previous = _checkpoint(checkpoint_path)
    first = _read(client, SOURCE)
    rows, advertised, body_text = _listing(first)
    if not rows or COMPANY_LABEL.casefold() not in body_text.casefold():
        raise FetchError("partial", "GD Land Systems filter returned no verifiable scoped postings.")
    if any(page < 0 or page >= MAX_PAGES for page in advertised):
        raise FetchError("partial", "GD Land Systems pagination exceeded the safety bound.")
    page_numbers = set(advertised) or {0}
    if page_numbers != set(range(max(page_numbers) + 1)):
        raise FetchError("partial", "GD Land Systems pagination is incomplete or non-contiguous.")
    all_rows = list(rows)
    for number in sorted(page_numbers - {0}):
        page_rows, ignored, page_text = _listing(_read(client, _page_url(SOURCE, number)))
        if COMPANY_LABEL.casefold() not in page_text.casefold():
            raise FetchError("partial", "GD Land Systems scope disappeared on a paginated result.")
        all_rows.extend(page_rows)
    if len(all_rows) > MAX_JOBS:
        raise FetchError("partial", "GD Land Systems inventory exceeded the safety bound.")
    entries = []
    for url, title in all_rows:
        match = re.search(r"-(\d+)-gdls-opportunity/?$", url, re.I)
        if not match:
            raise FetchError("partial", "GD Land Systems listing contained an invalid posting URL.")
        entries.append({"posting_id": match.group(1), "url": url, "title": title})
    ids = [entry["posting_id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise FetchError("partial", "GD Land Systems listing repeated a posting ID.")
    previous_jobs = reusable_details(previous, entries,
                                     entry_id=lambda entry: entry["posting_id"],
                                     job_id=lambda job: job["posting_id"])
    _save(checkpoint_path, entries=entries, jobs=list(previous_jobs.values()), phase="listing", pages=sorted(page_numbers))
    return entries, sorted(page_numbers)


def _detail(html, url, company_id, company):
    page = _parse(html)
    body = text(" ".join(page.parts))
    match = re.search(r"-(\d+)-gdls-opportunity/?$", url, re.I)
    title = page.headings[0] if page.headings else ""
    if not title:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = text(title_match.group(1)) if title_match else ""
    if not match or not title or len(body) < 120:
        raise FetchError("partial", "GD Land Systems detail lacked a stable ID, title, or full description.")
    row = _base({"id": match.group(1)}, COMPANY_LABEL, company_id, company)
    row.update(title=title, url=url, description=body, req_id=match.group(1))
    return row


def fetch_gd_land_systems(careers_url, company_id, company, transport=None, checkpoint_path=None):
    if company_id != "COMP-0097" or company.casefold() != "general dynamics land systems":
        return Inventory("unsupported", [], "GD Land Systems requires its verified company identity.", SOURCE, COMPANY_LABEL)
    client = transport or HTTPTransport(interval=0.6)
    checkpoint_path = checkpoint_path or os.environ.get("GDLS_CHECKPOINT_PATH", DEFAULT_CHECKPOINT)
    jobs = []
    try:
        entries, pages = _inventory(client, checkpoint_path)
        saved = _checkpoint(checkpoint_path) or {}
        saved_jobs = {str(row.get("posting_id")): row for row in saved.get("jobs", []) if isinstance(row, dict)}
        for entry in entries:
            ident = entry["posting_id"]
            if ident in saved_jobs and len(text(saved_jobs[ident].get("description", ""))) >= 120:
                continue
            row = _detail(_read(client, entry["url"]), entry["url"], company_id, company)
            if row["title"].casefold() not in entry["title"].casefold() and entry["title"].casefold() not in row["title"].casefold():
                raise FetchError("partial", "GD Land Systems detail title did not match the scoped listing.")
            saved_jobs[ident] = row
            _save(checkpoint_path, entries=entries, jobs=list(saved_jobs.values()), phase="details", pages=pages)
        second_entries, second_pages = _inventory(client, checkpoint_path)
        if second_entries != entries or second_pages != pages:
            raise FetchError("partial", "GD Land Systems listing membership changed during reconciliation.")
        jobs = [saved_jobs[e["posting_id"]] for e in entries]
        if len(jobs) != len(entries) or any(len(text(row.get("description", ""))) < 120 for row in jobs):
            raise FetchError("partial", "GD Land Systems details do not cover the complete current inventory.")
        _save(checkpoint_path, entries=entries, jobs=jobs, phase="complete", pages=pages)
        return Inventory("complete", jobs, f"GD Land Systems: retrieved {len(jobs)} scoped postings and reconciled {len(pages)} pages.", SOURCE, COMPANY_LABEL)
    except FetchError as exc:
        return Inventory(exc.status, jobs, exc.reason, SOURCE, COMPANY_LABEL)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, UnicodeError) as exc:
        return Inventory("partial", jobs, f"GD Land Systems validation failed: {exc}", SOURCE, COMPANY_LABEL)
