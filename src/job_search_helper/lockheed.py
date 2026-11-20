"""Lockheed Martin's anonymous Eightfold public board.

The board is a rendered application, so the browser establishes the tenant
and the adapter then uses only the observed public PCSx search/detail routes.
Listing membership is snapshotted before details and re-read after details;
partial checkpoints are never treated as a complete inventory.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import parse_qsl, urlencode, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, text
from .detail_checkpoint import checkpoint_payload, reusable_details

SOURCE = "https://lockheedmartin.eightfold.ai/careers"
ROOT = "https://lockheedmartin.eightfold.ai"
COMPANY_ID = "COMP-0074"
COMPANY = "Lockheed Martin"
ATS = "Eightfold"
PAGE_SIZE = 10
MAX_JOBS = 10000
DEFAULT_CHECKPOINT = "work/full-integrations-20261029/lockheed/evidence/checkpoint.json"
# The public PCSx API is read sequentially through the browser-established
# request context.  Five requests per second keeps a bounded, auditable pace
# while allowing the current multi-thousand-posting inventory to finish in a
# practical validation window.
MIN_REQUEST_INTERVAL = 0.20


def _source_ok(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == "lockheedmartin.eightfold.ai"
                and p.path.rstrip("/") == "/careers" and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _atomic_write(path, payload):
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                            prefix=target.name + ".", delete=False) as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, target)


def _read_checkpoint(path):
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if (not isinstance(data, dict) or data.get("source_url") != SOURCE
            or data.get("company_id") != COMPANY_ID
            or not isinstance(data.get("entries"), list)
            or not isinstance(data.get("ids"), list)
            or not isinstance(data.get("jobs"), list)):
        return None
    return data


def _save(path, *, entries, ids, jobs, total, phase):
    _atomic_write(path, checkpoint_payload({"source_url": SOURCE, "company_id": COMPANY_ID,
                         "total": total, "entries": entries, "ids": ids,
                         "jobs": jobs, "phase": phase}))


def _identity(entry):
    if not isinstance(entry, dict):
        raise FetchError("partial", "Lockheed Eightfold posting is not an object.")
    ident = str(entry.get("id", ""))
    if (not re.fullmatch(r"[1-9][0-9]{0,15}", ident)
            or not isinstance(entry.get("name"), str) or not entry["name"].strip()
            or entry.get("positionUrl") != f"/careers/job/{ident}"):
        raise FetchError("partial", "Lockheed Eightfold posting identity is not verified.")
    return ident


class ReplayClient:
    """Small protocol used by tests and by the browser-backed client."""
    def __init__(self, search, details):
        self._search, self._details = search, details

    def search(self, start):
        return self._search(start)

    def detail(self, ident):
        return self._details(ident)


def _listing(client, start, expected=None):
    data = client.search(start)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    entries, total = data.get("positions"), data.get("count")
    if (not isinstance(entries, list) or type(total) is not int or not 0 <= total <= MAX_JOBS
            or len(entries) != min(PAGE_SIZE, max(0, total - start))
            or data.get("appliedFilters") not in ({}, None)
            or (expected is not None and total != expected)):
        raise FetchError("partial", "Lockheed Eightfold pagination, total, or scope changed.")
    for entry in entries:
        _identity(entry)
    return entries, total


def _detail(client, entry):
    ident = _identity(entry)
    data = client.detail(ident)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    description = text(data.get("jobDescription")) if isinstance(data, dict) else ""
    if (not isinstance(data, dict) or _identity(data) != ident
            or data.get("name") != entry.get("name")
            or data.get("displayJobId") != entry.get("displayJobId")
            or data.get("publicUrl") != ROOT + entry["positionUrl"]
            or len(description.strip()) < 100):
        raise FetchError("partial", f"Lockheed posting {ident} has no matching full detail.")
    row = _base({"id": ident}, ATS, COMPANY_ID, COMPANY)
    locations = data.get("standardizedLocations") or data.get("locations") or []
    if not isinstance(locations, list) or not all(isinstance(v, str) for v in locations):
        raise FetchError("partial", "Lockheed location data is malformed.")
    row.update(title=text(data["name"]), description=description,
               url=data["publicUrl"], req_id=text(data.get("displayJobId")),
               location="; ".join(locations), department=text(data.get("department")),
               work_arrangement=text(data.get("workLocationOption")))
    return row


def scan(client, company_id=COMPANY_ID, company=COMPANY, checkpoint_path=None):
    saved = _read_checkpoint(checkpoint_path)
    jobs_by_id = {}
    entries, ids, total = [], [], None
    try:
        # Establish current membership before reusing interrupted detail work.
        first, total = _listing(client, 0)
        entries = list(first)
        _save(checkpoint_path, entries=entries, ids=[], jobs=[], total=total, phase="listing")
        for start in range(PAGE_SIZE, total, PAGE_SIZE):
            page, page_total = _listing(client, start, total)
            entries.extend(page)
            # A large live board can take several minutes to enumerate.  Keep
            # its observed membership as durable evidence even if a browser
            # context is interrupted before detail retrieval begins.
            _save(checkpoint_path, entries=entries, ids=[], jobs=[], total=total, phase="listing")
        jobs_by_id = reusable_details(saved, entries, entry_id=_identity,
                                      job_id=lambda job: job["posting_id"])
        ids = [_identity(entry) for entry in entries]
        if len(ids) != total or len(set(ids)) != total:
            raise FetchError("partial", "Lockheed Eightfold inventory has duplicate or missing postings.")
        _save(checkpoint_path, entries=entries, ids=ids, jobs=list(jobs_by_id.values()), total=total, phase="details")
        for entry in entries:
            ident = _identity(entry)
            if ident not in jobs_by_id:
                jobs_by_id[ident] = _detail(client, entry)
                _save(checkpoint_path, entries=entries, ids=ids, jobs=list(jobs_by_id.values()), total=total, phase="details")
        jobs = [jobs_by_id[ident] for ident in ids]
        reread_entries, reread_total = [], None
        first, reread_total = _listing(client, 0)
        reread_entries.extend(first)
        for start in range(PAGE_SIZE, reread_total, PAGE_SIZE):
            page, page_total = _listing(client, start, reread_total)
            reread_entries.extend(page)
        reread_ids = [_identity(entry) for entry in reread_entries]
        if reread_total != total or reread_ids != ids or reread_entries != entries:
            raise FetchError("partial", "Lockheed Eightfold membership changed during reread.")
        _save(checkpoint_path, entries=entries, ids=ids, jobs=jobs, total=total, phase="complete")
        return Inventory("complete", jobs, f"Lockheed: retrieved {len(jobs)} full postings and rechecked the tenant inventory.", SOURCE, ATS)
    except FetchError as error:
        _save(checkpoint_path, entries=entries or (saved or {}).get("entries", []),
             ids=ids or (saved or {}).get("ids", []), jobs=list(jobs_by_id.values()),
             total=total if total is not None else (saved or {}).get("total"),
             phase="blocked" if error.status == "blocked" else "details")
        return Inventory(error.status, list(jobs_by_id.values()), error.reason, SOURCE, ATS)
    except Exception as error:
        _save(checkpoint_path, entries=entries or (saved or {}).get("entries", []),
             ids=ids or (saved or {}).get("ids", []), jobs=list(jobs_by_id.values()),
             total=total if total is not None else (saved or {}).get("total"),
             phase="listing" if entries and not ids else "details")
        return Inventory("partial", list(jobs_by_id.values()), f"Lockheed Eightfold validation failed ({type(error).__name__}).", SOURCE, ATS)


class BrowserClient:
    def __init__(self, context, root=ROOT, domain="lockheedmartin.com",
                 min_interval=MIN_REQUEST_INTERVAL):
        self.context, self.root, self.domain, self.min_interval, self.last = (
            context, root, domain, min_interval, 0.0)

    def _get(self, kind, params):
        time.sleep(max(0.0, self.min_interval - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        response = self.context.request.get(self.root + "/api/pcsx/" + kind + "?" + urlencode(params),
                                            max_redirects=0, timeout=30000)
        try:
            if response.status in (401, 403, 429):
                raise FetchError("blocked", f"Lockheed Eightfold HTTP {response.status}.")
            return json.loads(HTTPResponse(response.status, response.body(), response.headers).body)
        finally:
            response.dispose()

    def search(self, start):
        return self._get("search", {"domain": self.domain, "query": "", "location": "", "start": start})

    def detail(self, ident):
        return self._get("position_details", {"position_id": ident, "domain": self.domain, "hl": "en"})


def fetch_lockheed(url, company_id, company, *, checkpoint_path=None, headless=True):
    if not _source_ok(url, company_id, company):
        return Inventory("unsupported", reason="Lockheed requires its exact unfiltered Eightfold careers board.", source_url=SOURCE, ats=ATS)
    path = checkpoint_path or os.environ.get("LOCKHEED_CHECKPOINT_PATH", DEFAULT_CHECKPOINT)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                context = browser.new_context()
                page = context.new_page()
                captured = []
                page.on("request", lambda request: captured.append(request.url) if "/api/pcsx/search" in request.url else None)
                response = page.goto(SOURCE, wait_until="domcontentloaded", timeout=30000)
                if not response or response.status != 200 or urlsplit(page.url).hostname != urlsplit(SOURCE).hostname:
                    raise FetchError("blocked", "Lockheed Eightfold careers page did not grant anonymous access.")
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                domains = {dict(parse_qsl(urlsplit(value).query)).get("domain") for value in captured}
                domains.discard(None)
                if len(domains) != 1 or not re.fullmatch(r"[A-Za-z0-9.-]+", next(iter(domains), "")):
                    raise FetchError("partial", "Lockheed Eightfold tenant/search scope was not established.")
                return scan(BrowserClient(context, ROOT, next(iter(domains))), checkpoint_path=path)
            finally:
                browser.close()
    except FetchError as error:
        return Inventory(error.status, reason=error.reason, source_url=SOURCE, ats=ATS)
    except ImportError:
        return Inventory("unsupported", reason="Lockheed requires the optional Playwright browser dependency.", source_url=SOURCE, ats=ATS)
    except Exception as error:
        return Inventory("partial", reason=f"Lockheed browser could not complete the inventory ({type(error).__name__}).", source_url=SOURCE, ats=ATS)
