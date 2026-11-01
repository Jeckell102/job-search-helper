"""Company-scoped browser inventory for SAIC's public Talemetry careers site.

SAIC's employer-owned board is server rendered but presents a Cloudflare
challenge to the non-browser transport.  Its public HTML has a bounded,
numbered listing and full descriptions on employer-hosted detail pages.  This
adapter deliberately supports only that exact SAIC board and never follows
application or alert routes.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit, urlunsplit
import json
import re
import sys
import time

from .ats import FetchError, Inventory, _base, text


SOURCE = "https://jobs.saic.com/search/jobs"
ROOT = "https://jobs.saic.com"
COMPANY_ID = "COMP-0002"
COMPANY = "SAIC"
PAGE_SIZE = 25
MAX_PAGES = 100
MAX_JOBS = PAGE_SIZE * MAX_PAGES
DETAIL_INTERVAL = 0.2
_JOB_PATH = re.compile(r"^/jobs/([0-9]+)-[A-Za-z0-9-]+/?$")
_PAGE_PATH = "/search/jobs/in"


def _supported(url: str, company_id: str, company: str) -> bool:
    return url == SOURCE and company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()


def fetch_saic(url: str, company_id: str, company: str, transport=None) -> Inventory:
    """Signal the required safe browser path without making a challenge request."""
    if not _supported(url, company_id, company):
        return Inventory("unsupported", reason="SAIC adapter requires its verified unfiltered public board.",
                         source_url=url, ats="SAIC TalentBrew")
    return Inventory("blocked",
                     reason="SAIC public inventory requires the verified browser adapter.",
                     source_url=SOURCE, ats="SAIC TalentBrew")


def _listing_url(number: int) -> str:
    if not 1 <= number <= MAX_PAGES:
        raise FetchError("partial", "SAIC listing page is outside the safe page limit.")
    if number == 1:
        return SOURCE
    return urlunsplit(("https", "jobs.saic.com", _PAGE_PATH, f"page={number}", ""))


def _same_page_url(actual: str, expected_number: int) -> bool:
    parsed = urlsplit(actual)
    if (parsed.scheme != "https" or parsed.hostname != "jobs.saic.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        return False
    if expected_number == 1:
        return parsed.path == "/search/jobs" and not parsed.query
    return parsed.path == _PAGE_PATH and parse_qs(parsed.query) == {"page": [str(expected_number)]}


def _status(response) -> None:
    value = getattr(response, "status", None)
    if value in (401, 403, 429):
        raise FetchError("blocked", f"SAIC public careers page returned HTTP {value}.")
    if value != 200:
        raise FetchError("partial", "SAIC public careers page was unavailable.")


def _links(page, number: int) -> tuple[list[tuple[str, str, str]], int]:
    anchors = page.locator("a").evaluate_all(
        """els => els.filter(e => new URL(e.href).pathname.startsWith("/jobs/"))
                    .map(e => ({href: e.href, title: e.innerText.trim()}))"""
    )
    if not isinstance(anchors, list):
        raise FetchError("partial", "SAIC listing returned invalid job links.")
    entries, seen = [], set()
    for anchor in anchors:
        if not isinstance(anchor, dict) or not isinstance(anchor.get("href"), str):
            raise FetchError("partial", "SAIC listing returned malformed job links.")
        parsed = urlsplit(anchor["href"])
        match = _JOB_PATH.fullmatch(parsed.path)
        title = text(anchor.get("title"))
        if (parsed.scheme != "https" or parsed.hostname != "jobs.saic.com"
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment or not match or not title):
            raise FetchError("partial", "SAIC listing has an invalid job identity.")
        ident = match.group(1)
        canonical = urlunsplit(("https", "jobs.saic.com", parsed.path, "", ""))
        if ident in seen:
            raise FetchError("partial", "SAIC listing repeats a posting identity.")
        seen.add(ident)
        entries.append((ident, title, canonical))
    pagination = page.locator(".pagination a").evaluate_all(
        """els => els.map(e => ({href: e.href, title: e.innerText.trim()}))"""
    )
    if not isinstance(pagination, list):
        raise FetchError("partial", "SAIC pagination did not render.")
    numbers = set()
    for anchor in pagination:
        if not isinstance(anchor, dict) or not isinstance(anchor.get("href"), str):
            raise FetchError("partial", "SAIC pagination link is malformed.")
        parsed = urlsplit(anchor["href"])
        query = parse_qs(parsed.query)
        title = text(anchor.get("title"))
        if title.casefold() in {"next", "previous"}:
            continue
        if (parsed.scheme != "https" or parsed.hostname != "jobs.saic.com"
                or parsed.path != _PAGE_PATH or query.keys() != {"page"}
                or len(query["page"]) != 1 or not query["page"][0].isdigit()
                or not 1 <= int(query["page"][0]) <= MAX_PAGES or parsed.username or parsed.password
                or parsed.port not in (None, 443)):
            raise FetchError("partial", "SAIC pagination scope is invalid.")
        numbers.add(int(query["page"][0]))
    pages = max(numbers, default=1)
    if pages > MAX_PAGES or (number > 1 and pages < number):
        raise FetchError("partial", "SAIC pagination does not cover the requested page.")
    expected = PAGE_SIZE if number < pages else range(1, PAGE_SIZE + 1)
    if len(entries) not in (expected if isinstance(expected, range) else (expected,)):
        raise FetchError("partial", "SAIC listing page size is incomplete.")
    return entries, pages


def _listing(page, number: int) -> tuple[list[tuple[str, str, str]], int]:
    response = page.goto(_listing_url(number), wait_until="domcontentloaded", timeout=30000)
    _status(response)
    if not _same_page_url(page.url, number):
        raise FetchError("partial", "SAIC listing left its verified public page.")
    return _links(page, number)


def _all_listings(page, company_id: str) -> tuple[list[tuple[str, str, str]], int]:
    first, pages = _listing(page, 1)
    entries, seen = [], set()
    for number in range(1, pages + 1):
        current, current_pages = (first, pages) if number == 1 else _listing(page, number)
        if current_pages != pages:
            raise FetchError("partial", "SAIC listing page count changed during pagination.")
        for entry in current:
            if entry[0] in seen:
                raise FetchError("partial", "SAIC listing repeated a posting identity.")
            seen.add(entry[0])
            entries.append(entry)
        print(json.dumps({"event": "inventory_page", "provider": "SAIC TalentBrew",
                          "company_id": company_id, "page": number, "listed": len(entries),
                          "pages": pages}), file=sys.stderr)
    return entries, pages


def _details(page, entry: tuple[str, str, str], company_id: str, company: str) -> dict:
    ident, listing_title, url = entry
    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    _status(response)
    parsed = urlsplit(page.url)
    if urlunsplit(("https", "jobs.saic.com", parsed.path, "", "")) != url:
        raise FetchError("partial", "SAIC job detail changed its canonical URL.")
    heading = page.locator("h1")
    description = page.locator(".the-description")
    if heading.count() != 1 or description.count() != 1:
        raise FetchError("partial", "SAIC job detail lacks one title or description section.")
    title, full_description = text(heading.inner_text()), text(description.inner_text())
    fields = text(page.locator(".job-details__main").inner_text())
    requisition = re.search(r"(?m)^Job ID:\s*([^\s]+)", fields)
    if title != listing_title or not full_description or requisition is None:
        raise FetchError("partial", "SAIC job detail lacks matching title, requisition, or description.")
    def field(label: str) -> str:
        match = re.search(r"(?m)^" + re.escape(label) + r":\s*(.+)$", fields)
        return text(match.group(1)) if match else ""
    row = _base({"id": ident}, "SAIC TalentBrew", company_id, company)
    row.update(title=title, req_id=requisition.group(1), url=url, description=full_description,
               location=field("Location"), department=field("Category"),
               work_arrangement=field("Potential for Remote Work"),
               created_at=field("Date Posted"))
    return row


def scan(context, company_id: str, company: str, *, max_jobs: int = MAX_JOBS) -> Inventory:
    """Read every public listing page and its corresponding public detail."""
    jobs = []
    listing_page = context.new_page()
    detail_page = context.new_page()
    try:
        entries, pages = _all_listings(listing_page, company_id)
        if pages * PAGE_SIZE > max_jobs:
            raise FetchError("partial", "SAIC inventory exceeds the configured safe job limit.")
        if not entries or len(entries) > max_jobs:
            raise FetchError("partial", "SAIC public listing was empty or exceeded the safe job limit.")
        last_request = 0.0
        for entry in entries:
            time.sleep(max(0.0, DETAIL_INTERVAL - (time.monotonic() - last_request)))
            last_request = time.monotonic()
            jobs.append(_details(detail_page, entry, company_id, company))
            if len(jobs) % 100 == 0 or len(jobs) == len(entries):
                print(json.dumps({"event": "posting_progress", "provider": "SAIC TalentBrew",
                                  "company_id": company_id, "fetched": len(jobs),
                                  "total": len(entries)}), file=sys.stderr)
        checked, checked_pages = _all_listings(listing_page, company_id)
        if checked_pages != pages or checked != entries or len(jobs) != len(entries):
            raise FetchError("partial", "SAIC public inventory changed during retrieval.")
        return Inventory("complete", jobs,
                         f"SAIC: retrieved {len(jobs)} full public postings and rechecked the inventory.",
                         SOURCE, "SAIC TalentBrew")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, SOURCE, "SAIC TalentBrew")
    except Exception as error:
        return Inventory("partial", jobs,
                         f"SAIC public browser data failed validation ({type(error).__name__}).",
                         SOURCE, "SAIC TalentBrew")
    finally:
        listing_page.close()
        detail_page.close()


def fetch_saic_browser(url: str, company_id: str, company: str, *, max_jobs: int = MAX_JOBS) -> Inventory:
    if not _supported(url, company_id, company):
        return Inventory("unsupported", reason="SAIC adapter requires its verified unfiltered public board.",
                         source_url=url, ats="SAIC TalentBrew")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                return scan(browser.new_context(), company_id, company, max_jobs=max_jobs)
            finally:
                browser.close()
    except Exception as error:
        return Inventory("partial", reason=f"SAIC public browser inventory failed ({type(error).__name__}).",
                         source_url=SOURCE, ats="SAIC TalentBrew")
