"""Amphenol Aerospace's employer-scoped AcquireTM board."""
from __future__ import annotations

from hashlib import sha256
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from .ats import (ACQUIRETM_PAGINATION_CODE, ACQUIRETM_REFRESH_TIMEOUT_MS, FetchError,
                  HTTPResponse, Inventory, outcome_failure, text)
from .shared_boards import Links, Scripts, checked, schema_job

SOURCE = "https://amphenol-aerospace.acquiretm.com/home.aspx"
HOST = urlsplit(SOURCE).hostname
DETAIL_PATH = "/job_details_clean.aspx"
MAX_LISTINGS = 10_000
MAX_PAGES = 400
MIN_DESCRIPTION = 120
RATE_MARKERS = ("too many requests", "rate limit", "rate-limit", "temporarily blocked", "request limit", "try again later", "service unavailable")
EMPLOYER_LABELS = {"amphenol aerospace", "amphenol aerospace operations"}


def _label(value: object) -> str:
    return re.sub(r"\s+", " ", text(value)).strip().casefold()


def _rate_limited(body: bytes) -> bool:
    sample = body[:64_000].decode("utf-8", "replace").casefold()
    return any(marker in sample for marker in RATE_MARKERS)


def parse_listing(body: str):
    totals = re.findall(r"\b(\d+)\s+positions found\.", text(body), re.I)
    if len(totals) != 1 or not 0 <= int(totals[0]) <= MAX_LISTINGS:
        raise FetchError("partial", "AcquireTM listing total missing or ambiguous.")
    rows: dict[str, dict[str, str]] = {}
    pages: set[int] = set()
    for attrs, title in Links(body).links:
        url = urljoin(SOURCE, attrs.get("href", ""))
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        if (parsed.scheme == "https" and parsed.hostname == HOST and parsed.path == DETAIL_PATH
                and set(query) == {"ID"} and len(query["ID"]) == 1 and query["ID"][0].isdigit()):
            ident = query["ID"][0]
            role = text(title)
            if ident in rows or not role:
                raise FetchError("partial", "AcquireTM duplicate job or missing title.")
            rows[ident] = {"id": ident, "title": role, "url": url}
        match = re.fullmatch(r"Go to page ([0-9]+) of job results", attrs.get("aria-label", ""))
        if match:
            pages.add(int(match[1]))
    return int(totals[0]), rows, pages


def _wait_for_listing_membership_change(page, known, timeout: int = ACQUIRETM_REFRESH_TIMEOUT_MS) -> None:
    """Wait for the clicked board page to expose a new validated listing ID."""
    try:
        page.wait_for_function(
            """({path, seen}) => {
                const previous = new Set(seen);
                return Array.from(document.querySelectorAll('a[href]')).some(anchor => {
                    const url = new URL(anchor.href);
                    const id = url.searchParams.get('ID');
                    return url.origin === location.origin && url.pathname === path
                        && /^[0-9]+$/.test(id || '') && !previous.has(id);
                });
            }""",
            arg={'path': DETAIL_PATH, 'seen': sorted(known)}, timeout=timeout,
        )
    except Exception as exc:
        raise FetchError("partial", "AcquireTM pagination did not expose a new same-board listing.") from exc


def _ids_digest(rows):
    raw = json.dumps(sorted(rows), separators=(',', ':')).encode('ascii')
    return sha256(raw).hexdigest()


def _observe_late_refresh(page, started_ns, total, first, previous, premature_body):
    deadline_ns = started_ns + ACQUIRETM_REFRESH_TIMEOUT_MS * 1_000_000
    premature_ns = time.monotonic_ns()
    remaining = (deadline_ns - premature_ns) // 1_000_000
    if remaining <= 0:
        return None
    try:
        previous_total, previous_rows, previous_pages = parse_listing(previous)
        if (previous_total != total or previous_rows != first or 2 not in previous_pages
                or _rate_limited(previous.encode('utf-8')) or _rate_limited(premature_body.encode('utf-8'))):
            return None
        # Inspect the same click's result. A spinner or unrelated DOM change
        # cannot satisfy this wait for a new same-board posting ID.
        page.wait_for_function(
            """({path, seen}) => {
                const previous = new Set(seen);
                return Array.from(document.querySelectorAll('a[href]')).some(anchor => {
                    const url = new URL(anchor.href);
                    const id = url.searchParams.get('ID');
                    return url.origin === location.origin && url.pathname === path
                        && /^[0-9]+$/.test(id || '') && !previous.has(id);
                });
            }""",
            arg={'path': DETAIL_PATH, 'seen': sorted(first)}, timeout=remaining,
        )
        if page.url != SOURCE:
            return None
        body = page.content()
        if _rate_limited(body.encode('utf-8')):
            return None
        refreshed_total, refreshed, _ = parse_listing(body)
    except Exception:
        return None
    refreshed_ns = time.monotonic_ns()
    if (refreshed_total != total or not refreshed or first.keys() & refreshed.keys()
            or len(first) + len(refreshed) > total or refreshed_ns > deadline_ns):
        return None
    first_digest = _ids_digest(first)
    return outcome_failure('pagination_regression', ACQUIRETM_PAGINATION_CODE, evidence={
        'page': 2, 'advertised_total': total,
        'first_page_count': len(first), 'refreshed_page_count': len(refreshed),
        'first_page_ids_sha256': first_digest,
        'premature_page_ids_sha256': first_digest,
        'refreshed_page_ids_sha256': _ids_digest(refreshed),
        'premature_elapsed_ms': (premature_ns - started_ns) // 1_000_000,
        'refreshed_elapsed_ms': (refreshed_ns - started_ns) // 1_000_000,
    })


def inventory(page, *, diagnose_pagination=False):
    page.goto(SOURCE, wait_until="domcontentloaded", timeout=30_000)
    if page.url != SOURCE:
        raise FetchError("partial", "AcquireTM board redirected.")
    total, rows, pages = parse_listing(page.content())
    visited = {1}
    pending = pages - visited
    while pending:
        number = min(pending)
        if not 1 < number <= MAX_PAGES:
            raise FetchError("partial", "AcquireTM page bound exceeded.")
        previous = page.content()
        try:
            page.get_by_role("link", name=f"Go to page {number} of job results", exact=True).click(timeout=8_000)
        except Exception as exc:
            raise FetchError("partial", "AcquireTM pagination control disappeared.") from exc
        started_ns = time.monotonic_ns() if diagnose_pagination and number == 2 and visited == {1} else None
        _wait_for_listing_membership_change(page, rows)
        if page.url != SOURCE:
            raise FetchError("partial", "AcquireTM pagination left the verified board.")
        current_body = page.content()
        current_total, part, discovered = parse_listing(current_body)
        if current_total != total or rows.keys() & part.keys():
            evidence = None
            if started_ns is not None and current_total == total and part == rows and len(rows) < total:
                evidence = _observe_late_refresh(page, started_ns, total, rows, previous, current_body)
            raise FetchError("partial", "AcquireTM total changed or pagination repeated.", outcome_failure=evidence)
        rows.update(part)
        visited.add(number)
        pending = (pending | discovered) - visited
    if len(rows) != total:
        raise FetchError("partial", "AcquireTM retrieved count disagrees with public total.")
    return rows


def _employer_matches(value: object) -> bool:
    return _label(value) in EMPLOYER_LABELS


def _description_from_jsonld(record: dict) -> str:
    description = text(record.get("description"))
    if len(description) < MIN_DESCRIPTION:
        raise FetchError("partial", "AcquireTM JobPosting does not contain a full description body.")
    if _rate_limited(description.encode()):
        raise FetchError("blocked", "AcquireTM detail returned a rate-limit body.")
    return description


def posting(body: str, entry: dict, cid: str, company: str):
    if _rate_limited(body.encode("utf-8", "replace")):
        raise FetchError("blocked", "AcquireTM detail returned a rate-limit page.")
    records = Scripts(body).jobs()
    if len(records) != 1:
        raise FetchError("partial", "AcquireTM detail lacks one unique JSON-LD JobPosting.")
    record = records[0]
    identifier = record.get("identifier") or {}
    value = identifier.get("value") if isinstance(identifier, dict) else identifier
    if (record.get("url") != entry["url"] or str(value) != entry["id"] or text(record.get("title")) != entry["title"]):
        raise FetchError("partial", "AcquireTM job identity does not match its listing.")
    organization = record.get("hiringOrganization") or {}
    if not isinstance(organization, dict) or not _employer_matches(organization.get("name")):
        raise FetchError("partial", "AcquireTM detail employer label is outside Amphenol Aerospace scope.")
    _description_from_jsonld(record)
    return schema_job(record, entry["url"], entry["id"], "AcquireTM", cid, company)


class _DetailClient:
    """Bounded detail client with a per-scan cache of validated response bodies."""
    def __init__(self, request, *, interval: float = 0.8, max_attempts: int = 3, sleep=time.sleep):
        self.request, self.interval, self.max_attempts, self.sleep = request, interval, max_attempts, sleep
        self.last_request = 0.0
        self.bodies: dict[str, str] = {}

    def _cooldown(self, headers, attempt: int) -> None:
        elapsed = time.monotonic() - self.last_request
        if elapsed < self.interval:
            self.sleep(self.interval - elapsed)
        value = next((v for k, v in headers.items() if k.casefold() == "retry-after"), "")
        try:
            delay = float(value)
        except (TypeError, ValueError):
            try:
                stamp = parsedate_to_datetime(value)
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                delay = (stamp - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 2 ** attempt
        self.sleep(max(0.0, min(8.0, delay)))

    def get_body(self, url: str) -> str:
        if url in self.bodies:
            return self.bodies[url]
        for attempt in range(self.max_attempts):
            self._cooldown({}, attempt)
            self.last_request = time.monotonic()
            try:
                response = self.request.get(url, max_redirects=0, timeout=30_000)
                body = response.body() if callable(getattr(response, "body", None)) else response.body
                status, headers = response.status, response.headers
            except Exception as exc:
                if attempt + 1 == self.max_attempts:
                    raise FetchError("partial", "AcquireTM detail request timed out after bounded retries.") from exc
                continue
            if status == 429 or status in {408, 500, 502, 503, 504}:
                if attempt + 1 == self.max_attempts:
                    status_name = "blocked" if status == 429 else "partial"
                    raise FetchError(status_name, "AcquireTM detail request remained rate-limited or unavailable.")
                self._cooldown(headers, attempt)
                continue
            decoded = checked(HTTPResponse(status, body, headers), True)
            if _rate_limited(body):
                if attempt + 1 == self.max_attempts:
                    raise FetchError("blocked", "AcquireTM detail returned a rate-limit page after bounded retries.")
                self._cooldown(headers, attempt)
                continue
            self.bodies[url] = decoded
            return decoded
        raise FetchError("partial", "AcquireTM detail request failed.")


def fetch_acquiretm(url, cid, company, *, request_factory=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="AcquireTM requires the verified unfiltered employer board.", source_url=url, ats="AcquireTM")
    jobs: list[dict] = []
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                diagnose = (cid == "COMP-0490" and isinstance(company, str)
                            and company.casefold() == "amphenol aerospace")
                entries = inventory(page, diagnose_pagination=diagnose)
                client = _DetailClient(request_factory or context.request)
                for entry in entries.values():
                    jobs.append(posting(client.get_body(entry["url"]), entry, cid, company))
                if inventory(page) != entries:
                    raise FetchError("partial", "AcquireTM listing changed during detail scan.")
            finally:
                browser.close()
        return Inventory("complete", jobs, f"AcquireTM: verified all {len(jobs)} full postings and rechecked the complete scoped listing.", url, "AcquireTM")
    except FetchError as exc:
        return Inventory(exc.status, jobs, str(exc), url, "AcquireTM", outcome_failure=exc.outcome_failure)
    except Exception as exc:
        return Inventory("partial", jobs, f"AcquireTM public scan failed ({type(exc).__name__}).", url, "AcquireTM")
