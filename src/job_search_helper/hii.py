"""Fail-closed HII Mission Technologies SuccessFactors inventory adapter.

HII's Jobs2Web board has reused requisition identities while changing the
display suffix on titles.  This adapter keys membership by the canonical
numeric posting identity, keeps a small atomic detail checkpoint, and accepts
only an explicit filled/closed response as closure.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from .ats import FetchError, Inventory, _base, text
from .detail_checkpoint import checkpoint_payload, reusable_details

# _Page is local to this adapter so HII's title/closure rules cannot change
# the behavior of the other SuccessFactors boards.
from html.parser import HTMLParser

SOURCE = "https://jobs.hii-tsd.com/search/?q=&sortColumn=referencedate&sortDirection=desc"
HOST = "jobs.hii-tsd.com"
COMPANY_ID = "COMP-0080"
COMPANY = "HII Mission Technologies"
PAGE_SIZE = 25
MAX_PAGES = 100
MAX_REREADS = 2
DEFAULT_CHECKPOINT = "work/full-integrations-20261029/hii/hii-checkpoint.json"
_ID = re.compile(r"/(\d{4,24})/?(?:$|[?#])")
_REQ = re.compile(r"(?:requisition|job\s*(?:req|id)|req(?:uisition)?)[\s:#-]*([A-Z0-9][A-Z0-9-]{2,})", re.I)
_CLOSED = re.compile(r"(?:position|job|requisition)\s+(?:has\s+been\s+)?(?:filled|closed)|no\s+longer\s+(?:available|accepting)|position\s+is\s+no\s+longer\s+available", re.I)


def normalize_title(value: str) -> str:
    """Normalize provider suffixes while retaining the meaningful title."""
    value = re.sub(r"\s+", " ", unescape(value or "")).strip()
    value = re.sub(r"\s*(?:[-|–—:]\s*)?(?:req(?:uisition)?\.?|job\s*id)\s*[:#-]?\s*[A-Z0-9][A-Z0-9-]*\s*$", "", value, flags=re.I)
    value = re.sub(r"\s*\([^)]*(?:req|requisition|job\s*id)[^)]*\)\s*$", "", value, flags=re.I)
    return value.strip(" -|–—:")


class _Page(HTMLParser):
    def __init__(self, body: str):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._anchor: list | None = None
        self.title: list[str] = []
        self.description: list[str] = []
        self.canonicals: list[str] = []
        self._title_depth = self._description_depth = 0
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") == "canonical":
            self.canonicals.append(attrs.get("href", ""))
        if tag == "a" and "jobTitle-link" in set(attrs.get("class", "").split()):
            self._anchor = [attrs.get("href", ""), []]
        if attrs.get("itemprop") == "title":
            self._title_depth = 1
        elif self._title_depth and tag not in {"br", "img", "meta", "input", "link"}:
            self._title_depth += 1
        if attrs.get("itemprop") == "description":
            self._description_depth = 1
        elif self._description_depth and tag not in {"br", "img", "meta", "input", "link"}:
            self._description_depth += 1

    def handle_data(self, data):
        if self._anchor is not None:
            self._anchor[1].append(data)
        if self._title_depth:
            self.title.append(data)
        if self._description_depth:
            self.description.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor is not None:
            self.links.append((self._anchor[0], text("".join(self._anchor[1]))))
            self._anchor = None
        if self._title_depth:
            self._title_depth -= 1
        if self._description_depth:
            self._description_depth -= 1


def _checkpoint_path(path=None):
    return Path(path or os.environ.get("HII_CHECKPOINT_PATH", DEFAULT_CHECKPOINT))


def _read_checkpoint(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("source") != SOURCE or value.get("company_id") != COMPANY_ID:
            return {}
        return value
    except (OSError, ValueError, TypeError):
        return {}


def _write_checkpoint(path, *, entries, jobs, closed, phase, total=None):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    value = checkpoint_payload({"source": SOURCE, "company_id": COMPANY_ID, "total": total,
             "entries": entries, "jobs": jobs, "closed": sorted(closed), "phase": phase})
    try:
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    except OSError:
        # A read-only installed environment must still return the live fetch
        # result; the caller records the inability to persist separately.
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def _get(client, url):
    last = None
    for attempt in range(3):
        try:
            response = client.get(url)
        except FetchError as exc:
            last = exc
            if exc.status != "failed" or attempt == 2:
                raise
        else:
            if response.status in {200, 404, 410}:
                return response
            if response.status in {408, 429, 500, 502, 503, 504} and attempt < 2:
                continue
            raise FetchError("blocked" if response.status in {401, 403} else "partial",
                             f"HII public board returned HTTP {response.status}.")
    raise last or FetchError("failed", "HII public board was unavailable.")


def _listing_url(start):
    if not 0 <= start < PAGE_SIZE * MAX_PAGES:
        raise FetchError("partial", "HII listing page exceeded the bounded page limit.")
    if start == 0:
        return SOURCE
    return SOURCE + "&startrow=" + str(start)


def _listing(client, start):
    response = _get(client, _listing_url(start))
    if response.status != 200:
        raise FetchError("partial", "HII listing page was unavailable.")
    body = response.body.decode("utf-8", "replace")
    ranges = re.findall(r"Results\s*<b>\s*(\d+)\s*[–-]\s*(\d+)\s*</b>\s*of\s*<b>\s*(\d+)\s*</b>", body, re.I)
    if not ranges or len(set(ranges)) != 1:
        raise FetchError("partial", "HII listing page did not publish one consistent result range.")
    first, last, total = map(int, ranges[0])
    if first != start + 1 or first > last or last > total:
        raise FetchError("partial", "HII listing page published an invalid result range.")
    page = _Page(body); entries = {}; seen_urls = set(); raw_count = 0
    for href, title in page.links:
        detail_url = urljoin(SOURCE, href); parsed = urlsplit(detail_url)
        match = _ID.search(parsed.path)
        if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.query or parsed.fragment
                or not match or not text(title)):
            raise FetchError("partial", "HII listing contained an invalid posting link.")
        ident = match.group(1); canonical = urlunsplit(("https", HOST, parsed.path, "", ""))
        if canonical in seen_urls:
            raw_count += 1
            continue
        seen_urls.add(canonical)
        raw_count += 1
        entries.setdefault(ident, {"id": ident, "title": normalize_title(title), "url": canonical})
    expected = last - first + 1
    if raw_count != expected or raw_count != min(PAGE_SIZE, total - start):
        raise FetchError("partial", "HII listing page is missing postings or repeats canonical IDs.")
    return total, entries, raw_count


def _snapshot(client):
    total, first, raw_count = _listing(client, 0); all_entries = dict(first); start = PAGE_SIZE
    while start < total:
        current_total, entries, page_count = _listing(client, start)
        if current_total != total:
            raise FetchError("partial", "HII published count changed during pagination.")
        raw_count += page_count
        for ident, entry in entries.items():
            all_entries.setdefault(ident, entry)
        start += PAGE_SIZE
    if raw_count != total:
        raise FetchError("partial", "HII pages did not account for the published inventory.")
    return total, all_entries


def _detail(client, entry):
    response = _get(client, entry["url"])
    if response.status in {404, 410}:
        return {"posting_id": entry["id"], "title": entry["title"], "url": entry["url"],
                "req_id": entry["id"], "is_closed": True,
                "description": "HII explicitly returned HTTP %s: posting is closed." % response.status}
    body = response.body.decode("utf-8", "replace"); page = _Page(body)
    visible = text(" ".join(page.description))
    if _CLOSED.search(body) and (not visible or not page.title):
        closure = text(re.sub(r"<[^>]+>", " ", body)) or "HII explicitly reported that the posting is closed."
        return {"posting_id": entry["id"], "title": entry["title"], "url": entry["url"],
                "req_id": entry["id"], "is_closed": True, "description": closure}
    detail_title = normalize_title(" ".join(page.title))
    if not detail_title or detail_title.casefold() != entry["title"].casefold() or not visible:
        raise FetchError("partial", f"HII posting {entry['id']} lacks a matching title or full description.")
    requisition = next(iter(dict.fromkeys(_REQ.findall(visible))), entry["id"])
    return {"posting_id": entry["id"], "title": detail_title, "url": entry["url"],
            "req_id": requisition, "description": visible, "is_closed": False}


def fetch_hii(url, company_id, company, transport=None, checkpoint_path=None):
    if url != SOURCE or company_id != COMPANY_ID or company.strip().casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="HII adapter requires its verified Mission Technologies board.", source_url=url, ats="SuccessFactors")
    client = transport
    if client is None:
        from .discovery import CareersTransport
        client = CareersTransport()
    path = _checkpoint_path(checkpoint_path); saved = _read_checkpoint(path)
    jobs_by_id = {}
    closed = set(); last_entries = None
    stable = False
    try:
        for reread in range(MAX_REREADS + 1):
            total, entries = _snapshot(client)
            if last_entries is not None and entries == last_entries:
                stable = True
                break
            previous = saved if last_entries is None else checkpoint_payload({
                "phase": "details", "entries": list(last_entries.values()),
                "jobs": list(jobs_by_id.values()),
            })
            jobs_by_id = reusable_details(previous, list(entries.values()),
                                          entry_id=lambda entry: entry["id"],
                                          job_id=lambda job: job["posting_id"])
            closed = set()
            last_entries = entries
            _write_checkpoint(path, entries=list(entries.values()), jobs=list(jobs_by_id.values()), closed=closed, phase="details", total=total)
            for ident, entry in entries.items():
                saved_job = jobs_by_id.get(ident)
                if saved_job and (saved_job.get("description") or saved_job.get("is_closed")):
                    saved_job["title"] = entry["title"]
                    saved_job["url"] = entry["url"]
                    continue
                job = _detail(client, entry); jobs_by_id[ident] = job
                if job.get("is_closed"): closed.add(ident)
                _write_checkpoint(path, entries=list(entries.values()), jobs=list(jobs_by_id.values()), closed=closed, phase="details", total=total)
        if not stable:
            raise FetchError("partial", "HII inventory did not stabilize within bounded rereads.")
        jobs = [jobs_by_id[ident] for ident in entries]
        if any(not job.get("description") for job in jobs):
            raise FetchError("partial", "HII inventory contains a posting without a full body or explicit closure.")
        _write_checkpoint(path, entries=list(entries.values()), jobs=jobs, closed=closed, phase="complete", total=total)
        rows = []
        for job in jobs:
            row = _base({"id": job["posting_id"]}, "SuccessFactors", company_id, company)
            row.update(title=job["title"], url=job["url"], description=job["description"], req_id=job["req_id"])
            if job.get("is_closed"): row["is_closed"] = True
            rows.append(row)
        return Inventory("complete", rows, f"HII: retrieved {len(rows)} current postings with full bodies or explicit closure and stable rereads.", SOURCE, "SuccessFactors")
    except FetchError as exc:
        _write_checkpoint(path, entries=list((last_entries or {}).values()), jobs=list(jobs_by_id.values()), closed=closed, phase="blocked", total=saved.get("total"))
        return Inventory(exc.status if not jobs_by_id else "partial", [], exc.reason, SOURCE, "SuccessFactors")
