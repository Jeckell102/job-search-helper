"""Amentum's public Clinch Talent inventory with resumable verification."""
from __future__ import annotations

import json
import math
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, text, _challenge, HTTPResponse
from .discovery import CareersTransport
from .shared_boards import Scripts, checked, schema_job


HOST = "www.amentumcareers.com"
LISTING_PATH = "/jobs/search"
LISTING_URL = f"https://{HOST}{LISTING_PATH}"
PAGE_SIZE = 30
MAX_JOBS = 10_000
ATS = "Amentum careers"
COMPANY_ID = "COMP-0005"
COMPANY = "Amentum"


def supports_amentum(ats: str, url: str) -> bool:
    """Recognize only Amentum's verified, unfiltered public listing."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (isinstance(ats, str) and ats.casefold() == ATS.casefold()) and (
        parsed.scheme == "https" and parsed.hostname == HOST
        and parsed.path.rstrip("/") == LISTING_PATH and not parsed.query and not parsed.fragment
        and not parsed.username and not parsed.password and parsed.port in (None, 443)
    )


def _listing_url(page: int) -> str:
    return LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"


class _Rows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and a.get("data-job-url"):
            self.row = {"url": a["data-job-url"], "title": "", "requisition": ""}
        if self.row is not None and tag == "td":
            klass = a.get("class", "")
            if "job-search-results-title" in klass:
                self.cell = "title"; self.parts = []
            elif "job-search-results-requisition-identifiers" in klass:
                self.cell = "requisition"; self.parts = []

    def handle_data(self, data):
        if self.cell is not None:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None and self.row is not None:
            self.row[self.cell] = text(" ".join(self.parts))
            self.cell = None; self.parts = []
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row); self.row = None


def _total(body: str) -> int:
    match = re.search(r"Displaying\s+[^<]*<b[^>]*>\s*[0-9,]+\s*</b>\s*of\s*<b[^>]*>\s*([0-9,]+)", body, re.I | re.S)
    if not match:
        match = re.search(r"Displaying\s+[^<]*\s+of\s+([0-9,]+)\s+in total", body, re.I | re.S)
    if not match:
        raise FetchError("partial", "Amentum listing total is missing or ambiguous.")
    total = int(match.group(1).replace(",", ""))
    if not 0 <= total <= MAX_JOBS:
        raise FetchError("partial", "Amentum listing total is outside the supported bound.")
    return total


def _rows(body: str) -> list[dict[str, str]]:
    parser = _Rows(); parser.feed(body); parser.close()
    rows = []
    for row in parser.rows:
        parsed = urlsplit(row["url"])
        if (parsed.scheme != "https" or parsed.hostname != HOST or not re.fullmatch(r"/jobs/[a-z0-9-]+", parsed.path, re.I)
                or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise FetchError("partial", "Amentum listing contains an invalid public job URL.")
        title, requisition = row["title"], row["requisition"]
        if not title or not re.fullmatch(r"R[0-9]{7}", requisition):
            raise FetchError("partial", "Amentum listing lacks a stable title or requisition identifier.")
        rows.append(row)
    return rows


def _read(client, url: str) -> str:
    response = client.get(url)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Amentum transport returned an invalid response.")
    if response.status in (401, 403, 429) or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Amentum Clinch returned HTTP {response.status}: denied access or browser challenge.")
    if not 200 <= response.status < 300:
        raise FetchError("partial", f"Amentum Clinch returned HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    if not body.strip():
        raise FetchError("partial", "Amentum Clinch returned a blank page.")
    return body


def _page(transport, number: int, expected_total: int | None = None) -> tuple[int, list[dict[str, str]]]:
    body = _read(transport, _listing_url(number))
    if "Amentum" not in body or "job-search-results" not in body:
        raise FetchError("partial", "Amentum verified public listing container is missing.")
    total = _total(body)
    if expected_total is not None and total != expected_total:
        raise FetchError("partial", "Amentum listing count changed during pagination.")
    rows = _rows(body)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    expected_rows = min(PAGE_SIZE, max(0, total - (number - 1) * PAGE_SIZE))
    if number < 1 or number > pages or len(rows) != expected_rows:
        raise FetchError("partial", "Amentum listing pagination does not reconcile with its reported total.")
    return total, rows


def listing(transport) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    total, first = _page(transport, 1)
    entries = list(first)
    for number in range(2, math.ceil(total / PAGE_SIZE) + 1):
        _, rows = _page(transport, number, total)
        entries.extend(rows)
    urls = [entry["url"] for entry in entries]
    requisitions = [entry["requisition"] for entry in entries]
    if len(entries) != total or len(urls) != len(set(urls)) or len(requisitions) != len(set(requisitions)):
        raise FetchError("partial", "Amentum public inventory contains duplicate or missing posting identities.")
    return entries, first


def _atomic(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", delete=False) as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush(); os.fsync(stream.fileno()); temporary = stream.name
    os.replace(temporary, path)


def _read_checkpoint(path):
    if path is None:
        return None
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, UnicodeError):
        return None
    if (not isinstance(value, dict) or value.get("source_url") != LISTING_URL
            or value.get("company_id") != COMPANY_ID or not isinstance(value.get("entries"), list)
            or not isinstance(value.get("ids"), list) or not isinstance(value.get("jobs"), list)):
        return None
    return value


def _write_checkpoint(path, *, total, entries, ids, jobs, phase, page=0):
    if path is not None:
        _atomic(Path(path), {"source_url": LISTING_URL, "company_id": COMPANY_ID, "total": total,
                             "entries": entries, "ids": ids, "jobs": jobs, "phase": phase, "last_page": page})


def _snapshot(client, checkpoint_path=None):
    saved = _read_checkpoint(checkpoint_path)
    if saved and saved.get("phase") in {"listing", "details", "complete"}:
        entries, total, ids = saved["entries"], saved.get("total"), saved["ids"]
        if type(total) is int and len(entries) == total and len(ids) == total and len(set(ids)) == total:
            return entries, ids, total, saved.get("jobs", [])
    total, first = _page(client, 1)
    entries = list(first)
    _write_checkpoint(checkpoint_path, total=total, entries=entries, ids=[], jobs=[], phase="listing", page=1)
    for page in range(2, math.ceil(total / PAGE_SIZE) + 1):
        page_total, rows = _page(client, page, total)
        if page_total != total:
            raise FetchError("partial", "Amentum listing total changed during pagination.")
        entries.extend(rows)
        _write_checkpoint(checkpoint_path, total=total, entries=entries, ids=[], jobs=[], phase="listing", page=page)
    ids = [entry["requisition"] for entry in entries]
    if len(entries) != total or len(set(ids)) != total:
        raise FetchError("partial", "Amentum inventory has duplicate or missing requisitions.")
    _write_checkpoint(checkpoint_path, total=total, entries=entries, ids=ids, jobs=[], phase="details", page=math.ceil(total / PAGE_SIZE))
    return entries, ids, total, []


def posting(transport, entry: dict[str, str], company_id: str, company: str) -> dict:
    body = _read(transport, entry["url"])
    records = Scripts(body).jobs()
    if len(records) != 1:
        raise FetchError("partial", "Amentum job page lacks a unique structured public job description.")
    record = records[0]
    identifier = record.get("identifier") or {}
    posting_id = identifier.get("value") if isinstance(identifier, dict) else ""
    if (not isinstance(posting_id, str) or not re.fullmatch(r"[a-f0-9]{32}", posting_id)
            or text(record.get("title")) != entry["title"]
            or text((record.get("hiringOrganization") or {}).get("name")) != "Amentum"):
        raise FetchError("partial", "Amentum structured job identity does not match its public listing.")
    result = schema_job(record, entry["url"], posting_id, "Amentum careers", company_id, company)
    result["req_id"] = entry["requisition"]
    return result


def fetch_amentum(url: str, company_id: str, company: str, transport=None, checkpoint_path=None) -> Inventory:
    if not supports_amentum(ATS, url) or company_id != COMPANY_ID or company.casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="Amentum requires its verified unfiltered public jobs/search URL.", source_url=url, ats="Amentum careers")
    try:
        transport = transport or CareersTransport(interval=0.75)
        entries, ids, total, saved_jobs = _snapshot(transport, checkpoint_path)
        completed = {str(job.get("req_id")): job for job in saved_jobs if isinstance(job, dict)}
        for entry in entries:
            if entry["requisition"] not in completed:
                completed[entry["requisition"]] = posting(transport, entry, company_id, company)
                _write_checkpoint(checkpoint_path, total=total, entries=entries, ids=ids, jobs=list(completed.values()), phase="details")
            if len(completed) and len(completed) % 100 == 0:
                print(f"{company}: Amentum Clinch fetched {len(completed)}/{total} jobs.", file=sys.stderr)
        jobs = [completed[ident] for ident in ids]
        final_total, final_first = _page(transport, 1, total)
        if final_total != total or final_first != entries[:len(final_first)]:
            raise FetchError("partial", "Amentum inventory changed during final reconciliation.")
        _write_checkpoint(checkpoint_path, total=total, entries=entries, ids=ids, jobs=jobs, phase="complete")
        return Inventory("complete", jobs, f"Amentum Clinch: retrieved {len(jobs)} full public postings and reconciled the first listing page.", LISTING_URL, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, LISTING_URL, ATS)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        return Inventory("partial", [], "Amentum Clinch response validation failed; inventory is incomplete.", LISTING_URL, ATS)
