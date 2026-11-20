"""CACI International's employer-scoped Eightfold board.

CACI's board is a rendered Eightfold application.  This adapter keeps the
company boundary explicit and adds the safeguards needed for a large,
changing board: paced requests, bounded 429 retries, snapshot comparison,
duplicate detection, and resumable detail downloads.  A partial union is
never promoted to a complete inventory.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from .ats import FetchError, Inventory, _base, text
from .eightfold import Client, fetch_eightfold

SOURCE = "https://searchcareers.caci.com/careers"
ROOT = "https://searchcareers.caci.com"
COMPANY_ID = "COMP-0001"
COMPANY = "CACI International"
ATS = "Eightfold"
DEFAULT_CHECKPOINT = "work/full-integrations-20261029/caci/evidence/checkpoint.json"


def _atomic(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                            prefix=target.name + ".", delete=False) as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, target)


def _read(path):
    if not path:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if (not isinstance(value, dict) or value.get("source_url") != SOURCE
            or value.get("company_id") != COMPANY_ID
            or not isinstance(value.get("ids"), list)
            or not isinstance(value.get("jobs"), list)):
        return None
    return value


def _save(path, *, ids, entries, jobs, total, phase):
    if path:
        _atomic(path, {"source_url": SOURCE, "company_id": COMPANY_ID,
                       "ids": ids, "entries": entries, "jobs": jobs,
                       "total": total, "phase": phase})


def _full_detail(client, entry):
    ident = str(entry["id"])
    detail = client.data("position_details", ident)
    if (not isinstance(detail, dict) or str(detail.get("id")) != ident
            or detail.get("name") != entry.get("name")
            or detail.get("displayJobId") != entry.get("displayJobId")
            or detail.get("publicUrl") != ROOT + entry.get("positionUrl", "")
            or not text(detail.get("jobDescription")).strip()):
        raise FetchError("partial", f"CACI detail gap or identity drift for {ident}.")
    row = _base({"id": ident}, ATS, COMPANY_ID, COMPANY)
    locations = detail.get("standardizedLocations") or detail.get("locations") or []
    if not isinstance(locations, list) or not all(isinstance(v, str) for v in locations):
        raise FetchError("partial", "CACI detail location payload is malformed.")
    row.update(title=text(detail["name"]), description=text(detail["jobDescription"]),
               url=detail["publicUrl"], req_id=text(detail.get("displayJobId")),
               location="; ".join(locations), department=text(detail.get("department")),
               work_arrangement=text(detail.get("workLocationOption")))
    return row


def scan(client, checkpoint_path=None, max_jobs=10000):
    """Scan a verified CACI Eightfold client, reusing only validated details."""
    saved = _read(checkpoint_path)
    cached = {str(job.get("posting_id")): job for job in (saved or {}).get("jobs", [])
              if isinstance(job, dict) and job.get("posting_id")}
    jobs, entries, ids, total = [], [], [], None
    try:
        # Always establish fresh membership. Cached details are reusable, but
        # cached membership is not evidence that a posting is still active.
        first = client.data("search", 0)
        total = first.get("count")
        if type(total) is not int or not 0 <= total <= max_jobs:
            raise FetchError("partial", "CACI Eightfold count is not bounded and integer-valued.")
        entries = list(first.get("positions") or [])
        for start in range(10, total, 10):
            page = client.data("search", start)
            if page.get("count") != total:
                raise FetchError("partial", "CACI listing total changed during accumulation.")
            entries.extend(page.get("positions") or [])
            _save(checkpoint_path, ids=ids, entries=entries, jobs=list(cached.values()), total=total, phase="listing")
        if len(entries) != total:
            raise FetchError("partial", "CACI listing has an unresolved pagination gap.")
        ids = []
        for entry in entries:
            if not isinstance(entry, dict) or not str(entry.get("id", "")).isdigit():
                raise FetchError("partial", "CACI listing contains an unverified posting identity.")
            ident = str(entry["id"])
            if ident in ids:
                raise FetchError("partial", "CACI listing repeated a posting ID across a boundary.")
            ids.append(ident)
        _save(checkpoint_path, ids=ids, entries=entries, jobs=list(cached.values()), total=total, phase="details")
        for entry in entries:
            ident = str(entry["id"])
            if ident not in cached:
                cached[ident] = _full_detail(client, entry)
                _save(checkpoint_path, ids=ids, entries=entries, jobs=list(cached.values()), total=total, phase="details")
        missing = [ident for ident in ids if ident not in cached]
        if missing:
            raise FetchError("partial", f"CACI unresolved detail gaps: {len(missing)}.")
        jobs = [cached[ident] for ident in ids]
        # Re-read every page and compare ordered membership, not just count.
        reread = []
        for start in range(0, total, 10):
            page = client.data("search", start)
            if page.get("count") != total:
                raise FetchError("partial", "CACI listing total changed during reread.")
            reread.extend(str(e.get("id")) for e in page.get("positions") or [])
        if reread != ids:
            raise FetchError("partial", "CACI listing membership changed during reread.")
        _save(checkpoint_path, ids=ids, entries=entries, jobs=jobs, total=total, phase="complete")
        return Inventory("complete", jobs, f"CACI: retrieved {len(jobs)} full postings and rechecked membership.", SOURCE, ATS)
    except FetchError as error:
        _save(checkpoint_path, ids=ids, entries=entries, jobs=list(cached.values()), total=total, phase="blocked" if error.status == "blocked" else "details")
        return Inventory(error.status, [cached[x] for x in ids if x in cached], error.reason, SOURCE, ATS)
    except Exception as error:
        _save(checkpoint_path, ids=ids, entries=entries, jobs=list(cached.values()), total=total, phase="details")
        return Inventory("partial", [cached[x] for x in ids if x in cached], f"CACI validation failed ({type(error).__name__}).", SOURCE, ATS)


def fetch_caci(url, company_id, company, *, checkpoint_path=None):
    if url.rstrip("/") != SOURCE or company_id != COMPANY_ID or company.casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="CACI requires its exact employer-scoped Eightfold board.", source_url=url, ats=ATS)
    return fetch_eightfold(SOURCE, COMPANY_ID, COMPANY, ATS, sort_by="timestamp", listing_first=True)
