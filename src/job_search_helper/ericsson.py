"""Scoped normal-transport adapter for Ericsson's public Eightfold board."""
from __future__ import annotations

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


def _snapshot(client):
    first, total = _search(client, 0)
    entries = list(first)
    for start in range(PAGE_SIZE, total, PAGE_SIZE):
        page, page_total = _search(client, start)
        if page_total != total:
            raise FetchError("partial", "Ericsson Eightfold total changed during pagination.")
        entries.extend(page)
    ids = [_identity(entry) for entry in entries]
    if len(ids) != total or len(set(ids)) != len(ids):
        raise FetchError("partial", "Ericsson Eightfold inventory has duplicate or missing postings.")
    return entries, ids


def fetch_ericsson(careers_url: str, company_id: str, company: str, transport=None) -> Inventory:
    if not _source_ok(careers_url, company_id, company):
        return Inventory("unsupported", reason="Ericsson requires its verified Eightfold careers board.", source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport(interval=0.15)
    try:
        entries, ids = _snapshot(client)
        jobs = [_detail(client, entry) for entry in entries]
        reread, reread_ids = _snapshot(client)
        if reread_ids != ids:
            raise FetchError("partial", "Ericsson Eightfold inventory changed during reread.")
        return Inventory("complete", jobs, f"Ericsson: retrieved {len(jobs)} full postings and rechecked the published inventory.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError):
        return Inventory("partial", [], "Ericsson Eightfold response validation failed.", SOURCE, ATS)
