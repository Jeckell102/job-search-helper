"""Amentum's public Clinch Talent careers inventory.

Only the verified Amentum employer host and its unfiltered public listing are
accepted. Requests use ordinary anonymous GETs; no application endpoints,
cookies, or candidate data are accessed.
"""
from __future__ import annotations

import math
import re
import sys
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, text
from .discovery import CareersTransport
from .shared_boards import Scripts, checked, schema_job


HOST = "www.amentumcareers.com"
LISTING_PATH = "/jobs/search"
LISTING_URL = f"https://{HOST}{LISTING_PATH}"
PAGE_SIZE = 30
MAX_JOBS = 10_000


def supports_amentum(ats: str, url: str) -> bool:
    """Recognize only Amentum's verified, unfiltered public listing."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (ats.casefold() == "amentum careers" or parsed.hostname == HOST) and (
        parsed.scheme == "https" and parsed.hostname == HOST
        and parsed.path.rstrip("/") == LISTING_PATH and not parsed.query and not parsed.fragment
        and not parsed.username and not parsed.password and parsed.port in (None, 443)
    )


def _listing_url(page: int) -> str:
    return LISTING_URL if page == 1 else f"{LISTING_URL}?page={page}"


def _total(body: str) -> int:
    match = re.search(r"Displaying\s*<b[^>]*>.*?</b>\s*of\s*<b[^>]*>\s*([0-9,]+)\s*</b>\s*in\s+total", body, re.I | re.S)
    if not match:
        raise FetchError("partial", "Amentum listing total is missing or ambiguous.")
    total = int(match.group(1).replace(",", ""))
    if not 0 <= total <= MAX_JOBS:
        raise FetchError("partial", "Amentum listing total is outside the supported bound.")
    return total


def _rows(body: str) -> list[dict[str, str]]:
    rows = []
    pattern = re.compile(r"<tr\b(?=[^>]*\bdata-job-url=)[^>]*\bdata-job-url=(['\"])(.*?)\1[^>]*>(.*?)</tr>", re.I | re.S)
    for _, url, row in pattern.findall(body):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != HOST or not re.fullmatch(r"/jobs/[a-z0-9-]+", parsed.path, re.I)
                or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise FetchError("partial", "Amentum listing contains an invalid public job URL.")
        title_match = re.search(r"<td\b[^>]*\bclass=(['\"])[^'\"]*job-search-results-title[^'\"]*\1[^>]*>.*?<a\b[^>]*>(.*?)</a>", row, re.I | re.S)
        requisition_match = re.search(r"<td\b[^>]*\bclass=(['\"])[^'\"]*job-search-results-requisition-identifiers[^'\"]*\1[^>]*>(.*?)</td>", row, re.I | re.S)
        title = text(title_match.group(2)) if title_match else ""
        requisition = text(requisition_match.group(2)) if requisition_match else ""
        if not title or not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", requisition):
            raise FetchError("partial", "Amentum listing lacks a stable title or requisition identifier.")
        rows.append({"url": url, "title": title, "requisition": requisition})
    return rows


def _page(transport, number: int, expected_total: int | None = None) -> tuple[int, list[dict[str, str]]]:
    body = checked(transport.get(_listing_url(number)), True)
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


def posting(transport, entry: dict[str, str], company_id: str, company: str) -> dict:
    body = checked(transport.get(entry["url"]), True)
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


def fetch_amentum(url: str, company_id: str, company: str, transport=None) -> Inventory:
    jobs, failures = [], []
    if not supports_amentum("Amentum careers", url):
        return Inventory("unsupported", reason="Amentum requires its verified unfiltered public jobs/search URL.", source_url=url, ats="Amentum careers")
    try:
        transport = transport or CareersTransport()
        entries, first = listing(transport)
        for entry in entries:
            try:
                jobs.append(posting(transport, entry, company_id, company))
            except FetchError as error:
                if error.status == "blocked":
                    raise
                failures.append(entry["requisition"] + ": " + error.reason)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                failures.append(entry["requisition"] + ": malformed public posting data")
            if len(jobs) and len(jobs) % 100 == 0:
                print(f"{company}: Amentum careers fetched {len(jobs)}/{len(entries)} jobs.", file=sys.stderr)
        final_total, final_first = _page(transport, 1, len(entries))
        if final_total != len(entries) or final_first != first:
            failures.append("Amentum public board changed during detail retrieval.")
        if len(jobs) != len(entries):
            failures.append("Amentum normalized posting count does not match the public inventory.")
        if failures:
            return Inventory("partial", jobs, " ".join(dict.fromkeys(failures)), LISTING_URL, "Amentum careers")
        return Inventory("complete", jobs, f"Amentum careers: retrieved {len(jobs)} full public postings and rechecked the first listing page.", LISTING_URL, "Amentum careers")
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, error.reason, LISTING_URL, "Amentum careers")
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs, "Amentum public listing or detail schema failed validation.", LISTING_URL, "Amentum careers")
