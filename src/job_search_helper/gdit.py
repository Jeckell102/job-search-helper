"""General Dynamics Information Technology's scoped Workday inventory.

GDIT's board is large and occasionally rate-limits detail reads.  This adapter
keeps listing and detail progress durable, treats a missing detail as a closed
posting only when the next listing confirms its removal, and never treats an
access or transient failure as closure.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge, _json, text
from .workday import _job_path, _posting
from .detail_checkpoint import checkpoint_payload, reusable_details

SOURCE = "https://gdit.wd5.myworkdayjobs.com/External_Career_Site"
ROOT = "https://gdit.wd5.myworkdayjobs.com/wday/cxs/gdit/External_Career_Site"
HOST = "gdit.wd5.myworkdayjobs.com"
SITE = "External_Career_Site"
ATS = "Workday"
COMPANY_ID = "COMP-0011"
COMPANY = "General Dynamics Information Technology"
PAGE_SIZE = 20
MAX_PAGES = 500
DEFAULT_CHECKPOINT = os.environ.get("GDIT_CHECKPOINT_PATH", "/tmp/gdit-progress.json")


def _source_ok(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == HOST
                and p.path.rstrip("/") == "/External_Career_Site"
                and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _atomic(path, value):
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                           prefix=target.name + ".", delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, target)


def _read_checkpoint(path):
    if path is None:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if (not isinstance(value, dict) or value.get("source_url") != SOURCE
            or value.get("company_id") != COMPANY_ID
            or not isinstance(value.get("entries"), list)
            or not isinstance(value.get("ids"), list)
            or not isinstance(value.get("jobs"), list)):
        return None
    return value


def _write_checkpoint(path, *, entries, ids, jobs, closed_ids, phase, total=None):
    _atomic(path, checkpoint_payload({"source_url": SOURCE, "company_id": COMPANY_ID,
                   "entries": entries, "ids": ids, "jobs": jobs,
                   "closed_ids": sorted(closed_ids), "phase": phase,
                   "total": total}))


def _pause(client, attempt, headers):
    retry_after = headers.get("retry-after", headers.get("Retry-After", "")) if headers else ""
    try:
        delay = min(2.0, max(0.0, float(retry_after)))
    except (ValueError, TypeError):
        delay = min(2.0, 0.25 * (attempt + 1))
    sleeper = getattr(client, "sleep", time.sleep)
    sleeper(delay)


def _gdit_json(url, client, payload=None, *, detail=False):
    """Read JSON with a small retry budget and distinct 404 closure semantics."""
    last = None
    for attempt in range(3):
        try:
            response = client.get(url) if payload is None else client.post(url, payload)
        except FetchError as error:
            if error.status == "blocked":
                raise
            if attempt < 2:
                _pause(client, attempt, {})
                continue
            raise FetchError("blocked", "GDIT Workday listing/detail access failed after bounded retries; inventory is unverified.") from error
        if not isinstance(response, HTTPResponse):
            raise FetchError("failed", "GDIT transport returned an invalid response.")
        if response.status == 404 and detail:
            return None, "closed"
        if _challenge(response) or response.status in {401, 403}:
            raise FetchError("blocked", f"GDIT Workday access denied (HTTP {response.status}).")
        if response.status in {408, 429, 500, 502, 503, 504}:
            last = response
            if attempt < 2:
                _pause(client, attempt, response.headers)
                continue
            raise FetchError("failed", f"GDIT Workday transient HTTP {response.status}; inventory unavailable.")
        if not 200 <= response.status < 300:
            raise FetchError("failed", f"GDIT Workday HTTP {response.status}; inventory unavailable.")
        try:
            return json.loads(response.body), "ok"
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise FetchError("partial", "GDIT Workday returned non-JSON data.") from None
    raise FetchError("failed", "GDIT Workday request failed after bounded retries.")


def _listing(client, checkpoint_path):
    saved = _read_checkpoint(checkpoint_path)
    entries, ids = [], []
    total = None
    for page in range(MAX_PAGES):
        payload = {"appliedFacets": {}, "limit": PAGE_SIZE,
                   "offset": page * PAGE_SIZE, "searchText": ""}
        data, _ = _gdit_json(ROOT + "/jobs", client, payload)
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list) or type(data.get("total")) is not int:
            raise FetchError("partial", "GDIT Workday listing schema is invalid.")
        if total is None:
            total = data["total"]
        elif data["total"] != total:
            raise FetchError("partial", "GDIT Workday listing total changed during pagination.")
        rows = data["jobPostings"]
        if len(rows) > PAGE_SIZE or page * PAGE_SIZE + len(rows) > total:
            raise FetchError("partial", "GDIT Workday listing page is inconsistent with its total.")
        for row in rows:
            path = _job_path(row.get("externalPath") if isinstance(row, dict) else None)
            if path in ids:
                raise FetchError("partial", "GDIT Workday listing contains duplicate posting paths.")
            ids.append(path)
            entries.append(row)
        cached = reusable_details(saved, entries,
                                  entry_id=lambda entry: _job_path(entry["externalPath"]),
                                  job_id=lambda job: _job_path(urlsplit(job["url"]).path.split(SITE, 1)[1]))
        _write_checkpoint(checkpoint_path, entries=entries, ids=ids,
                          jobs=list(cached.values()), closed_ids=set(), phase="listing", total=total)
        if len(entries) == total:
            return entries, ids, list(cached.values()), set()
        if not rows:
            raise FetchError("partial", "GDIT Workday listing ended before its advertised total.")
    raise FetchError("partial", "GDIT Workday listing exceeded its page cap.")


def _detail(client, path, company_id, company):
    data, state = _gdit_json(ROOT + path, client, detail=True)
    if state == "closed":
        return None, "closed"
    return _posting(data, path, SITE, HOST, company_id, company), "ok"


def _scan(url, company_id, company, client, checkpoint_path):
    entries, paths, saved_jobs, closed = _listing(client, checkpoint_path)
    completed = {str(row.get("posting_id")): row for row in saved_jobs if isinstance(row, dict)}
    by_path = {path: entry for path, entry in zip(paths, entries)}
    for path in paths:
        if path in closed:
            continue
        existing = next((row for row in completed.values() if row.get("url", "").endswith(SITE + path)), None)
        if existing and existing.get("description"):
            continue
        row, state = _detail(client, path, company_id, company)
        if state == "closed":
            closed.add(path)
        else:
            if len(text(row.get("description"))) < 80:
                raise FetchError("partial", "GDIT Workday detail has an incomplete description.")
            completed[row["posting_id"]] = row
        _write_checkpoint(checkpoint_path, entries=entries, ids=paths,
                          jobs=list(completed.values()), closed_ids=closed,
                          phase="details", total=len(entries))
    # A 404 is only a closed posting if the fresh listing no longer contains it.
    current_entries, current_paths, _, _ = _listing(client, None)
    if current_paths != paths or current_entries != entries:
        raise FetchError("partial", "GDIT Workday listing IDs changed during detail retrieval.")
    if closed:
        raise FetchError("partial", "GDIT Workday detail returned a closed ID still present in the listing.")
    jobs = list(completed.values())
    if len(jobs) != len(paths) or any(not text(row.get("description")) for row in jobs):
        raise FetchError("partial", "GDIT Workday details do not cover every current listing ID.")
    _write_checkpoint(checkpoint_path, entries=entries, ids=paths, jobs=jobs,
                      closed_ids=set(), phase="complete", total=len(paths))
    return Inventory("complete", jobs, f"GDIT Workday: retrieved {len(jobs)} complete postings and reconciled current IDs.", url, ATS)


def fetch_gdit(careers_url, company_id, company, transport=None, checkpoint_path=None):
    if not _source_ok(careers_url, company_id, company):
        return Inventory("unsupported", reason="GDIT requires its verified scoped Workday board.", source_url=SOURCE, ats=ATS)
    checkpoint_path = checkpoint_path or os.environ.get("GDIT_CHECKPOINT_PATH", DEFAULT_CHECKPOINT)
    try:
        from .ats import HTTPTransport
        client = transport or HTTPTransport(interval=0.6)
        return _scan(careers_url, company_id, company, client, checkpoint_path)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, UnicodeError) as error:
        return Inventory("partial", [], f"GDIT Workday response validation failed: {error}", SOURCE, ATS)
