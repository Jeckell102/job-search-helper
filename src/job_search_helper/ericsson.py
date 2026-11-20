"""Scoped normal-transport adapter for Ericsson's public Eightfold board."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode, urlsplit

from .ats import FetchError, Inventory, _base, _json, text
from .discovery import CareersTransport

SOURCE = "https://jobs.ericsson.com/careers"
ROOT = "https://jobs.ericsson.com"
DOMAIN = "ericsson.com"
ATS = "Ericsson Eightfold"
COMPANY_ID = "COMP-0136"
COMPANY = "Ericsson"
PAGE_SIZE = 10
MAX_JOBS = 10000


def _source_ok(url: str, company_id: str, company: str) -> bool:
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == "jobs.ericsson.com"
                and p.path.rstrip("/") == "/careers" and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _search(client, start: int):
    query = urlencode({"domain": DOMAIN, "query": "", "location": "", "start": str(start)})
    data = _json(f"{ROOT}/api/pcsx/search?{query}", client)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict):
        raise FetchError("partial", "Ericsson Eightfold search response was not an object.")
    entries, total = data.get("positions"), data.get("count")
    if not isinstance(entries, list) or type(total) is not int or not 0 <= total <= MAX_JOBS:
        raise FetchError("partial", "Ericsson Eightfold search metadata is invalid.")
    expected = min(PAGE_SIZE, max(0, total - start))
    if len(entries) != expected or data.get("appliedFilters") not in ({}, None):
        raise FetchError("partial", "Ericsson Eightfold pagination or scope changed.")
    return entries, total


def _identity(entry):
    if not isinstance(entry, dict):
        raise FetchError("partial", "Ericsson posting is not an object.")
    ident = str(entry.get("id", ""))
    if not ident.isdigit() or not 1 <= len(ident) <= 16 or entry.get("positionUrl") != f"/careers/job/{ident}":
        raise FetchError("partial", "Ericsson posting identity is not verified.")
    if not isinstance(entry.get("name"), str) or not entry["name"].strip():
        raise FetchError("partial", "Ericsson posting has no title.")
    return ident


def _detail(client, entry):
    ident = _identity(entry)
    query = urlencode({"position_id": ident, "domain": DOMAIN, "hl": "en"})
    data = _json(f"{ROOT}/api/pcsx/position_details?{query}", client)
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        data = data["data"]
    if not isinstance(data, dict) or str(data.get("id")) != ident or data.get("name") != entry.get("name"):
        raise FetchError("partial", "Ericsson detail identity mismatch.")
    description = text(data.get("jobDescription"))
    if len(description) < 100:
        raise FetchError("partial", f"Ericsson posting {ident} has no full description.")
    row = _base({"id": ident}, ATS, COMPANY_ID, COMPANY)
    row.update(
        title=text(data.get("name")),
        description=description,
        url=ROOT + entry["positionUrl"],
        req_id=text(data.get("displayJobId") or entry.get("displayJobId")),
        location="; ".join(data.get("standardizedLocations") or data.get("locations") or []),
        department=text(data.get("department")),
        work_arrangement=text(data.get("workLocationOption")),
    )
    return row


def _checkpoint_read(path):
    if path is None:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, ValueError, TypeError):
        return None
    if (not isinstance(value, dict) or value.get("source_url") != SOURCE
            or value.get("company_id") != COMPANY_ID
            or type(value.get("total")) is not int
            or not isinstance(value.get("entries"), list)
            or not isinstance(value.get("ids"), list)
            or not isinstance(value.get("jobs"), list)):
        return None
    return value


def _checkpoint_write(path, *, total, entries, ids, jobs, phase):
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_url": SOURCE, "company_id": COMPANY_ID, "total": total,
        "entries": entries, "ids": ids, "jobs": jobs, "phase": phase,
    }
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent,
                            prefix=target.name + ".", delete=False) as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
        temporary = stream.name
    os.replace(temporary, target)


def _snapshot(client, checkpoint_path=None):
    saved = _checkpoint_read(checkpoint_path)
    if saved and saved["phase"] in {"listing", "details", "complete"}:
        entries, ids, total = saved["entries"], saved["ids"], saved["total"]
        if len(entries) == total and len(ids) == total and len(set(ids)) == total:
            return entries, ids, total, saved.get("jobs", [])
    first, total = _search(client, 0)
    entries = list(first)
    _checkpoint_write(checkpoint_path, total=total, entries=entries,
                      ids=[], jobs=[], phase="listing")
    for start in range(PAGE_SIZE, total, PAGE_SIZE):
        page, page_total = _search(client, start)
        if page_total != total:
            raise FetchError("partial", "Ericsson Eightfold total changed during pagination.")
        entries.extend(page)
        _checkpoint_write(checkpoint_path, total=total, entries=entries,
                          ids=[], jobs=[], phase="listing")
    ids = [_identity(entry) for entry in entries]
    if len(ids) != total or len(set(ids)) != len(ids):
        raise FetchError("partial", "Ericsson Eightfold inventory has duplicate or missing postings.")
    _checkpoint_write(checkpoint_path, total=total, entries=entries,
                      ids=ids, jobs=[], phase="details")
    return entries, ids, total, []


def fetch_ericsson(careers_url: str, company_id: str, company: str, transport=None,
                   checkpoint_path=None) -> Inventory:
    if not _source_ok(careers_url, company_id, company):
        return Inventory("unsupported", reason="Ericsson requires its verified Eightfold careers board.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport(interval=0.15)
    try:
        entries, ids, total, jobs = _snapshot(client, checkpoint_path)
        completed = {str(job.get("posting_id")): job for job in jobs if isinstance(job, dict)}
        for entry in entries:
            ident = _identity(entry)
            if ident not in completed:
                completed[ident] = _detail(client, entry)
                _checkpoint_write(checkpoint_path, total=total, entries=entries,
                                  ids=ids, jobs=list(completed.values()), phase="details")
        jobs = [completed[ident] for ident in ids]
        reread, reread_ids, reread_total, _ = _snapshot(client, None)
        if reread_total != total:
            raise FetchError("partial", "Ericsson Eightfold inventory count changed during reread.")
        if reread_ids != ids:
            raise FetchError("partial", "Ericsson Eightfold inventory changed during reread.")
        _checkpoint_write(checkpoint_path, total=total, entries=entries,
                          ids=ids, jobs=jobs, phase="complete")
        return Inventory("complete", jobs, f"Ericsson: retrieved {len(jobs)} full postings and rechecked the published inventory.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "Ericsson Eightfold response validation failed.", SOURCE, ATS)
