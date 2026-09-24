"""Optional browser fallback for careers pages that block direct HTTP reads."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urljoin, urlsplit

from .ats import Inventory
from .core import canonicalize_url, plain_text

MAX_BROWSER_JOBS = 250
JOB_HINT = re.compile(r"\b(job|career|position|opening|role|requisition|req)\b", re.I)
DETAIL_HINT = re.compile(r"\b(responsibilities|requirements|qualifications|salary|compensation|about the role|what you.ll do)\b", re.I)
NO_OPENINGS = re.compile(r"\b(no open positions|no current openings|no jobs were found|check back soon)\b", re.I)
GENERIC_LINK_TITLES = {"career", "careers", "job", "jobs", "open positions", "current openings", "join our team"}
TITLE_KEYS = ("title", "jobTitle", "name", "positionTitle", "postingTitle")
URL_KEYS = ("url", "jobUrl", "applyUrl", "postingUrl", "externalUrl", "jobDetailUrl")
ID_KEYS = ("id", "jobId", "postingId", "reqId", "requisitionId", "referenceNumber")
DESCRIPTION_KEYS = ("description", "jobDescription", "descriptionHtml", "descriptionPlain", "summary")
LOCATION_KEYS = ("location", "jobLocation", "locations", "city", "state")


def _same_site(base: str, candidate: str) -> bool:
    base_host = urlsplit(base).hostname or ""
    candidate_host = urlsplit(candidate).hostname or ""
    return candidate_host == base_host or candidate_host.endswith("." + base_host)


def _posting_id(url: str) -> str:
    try:
        return "browser-" + hashlib.sha256(canonicalize_url(url).encode()).hexdigest()[:24]
    except ValueError:
        return ""


def _first_text(record: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return plain_text(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, dict):
            nested = _first_text(value, ("name", "title", "label", "value"))
            if nested:
                return nested
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(plain_text(item))
                elif isinstance(item, dict):
                    part = _first_text(item, ("name", "title", "label", "city", "state", "country"))
                    if part:
                        parts.append(part)
            if parts:
                return "; ".join(dict.fromkeys(parts))
    return ""


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def jobs_from_json_payload(payload, base_url: str, company_id: str, company: str, ats: str) -> list[dict]:
    jobs = []
    seen = set()
    for record in _walk_json(payload):
        title = _first_text(record, TITLE_KEYS)
        raw_url = _first_text(record, URL_KEYS)
        if not title or not raw_url or len(title) > 180:
            continue
        url = urljoin(base_url, raw_url)
        if not url.startswith("http") or not _same_site(base_url, url):
            continue
        posting_id = _first_text(record, ID_KEYS) or _posting_id(url)
        key = posting_id or url
        if key in seen:
            continue
        seen.add(key)
        jobs.append({
            "company_id": company_id,
            "company": company,
            "ats": ats or "Browser",
            "posting_id": posting_id,
            "req_id": _first_text(record, ("reqId", "requisitionId", "referenceNumber")),
            "url": url,
            "title": title,
            "location": _first_text(record, LOCATION_KEYS),
            "work_arrangement": _first_text(record, ("workplaceType", "workArrangement", "remoteType")),
            "compensation": _first_text(record, ("compensation", "salary", "pay", "payRange")),
            "description": _first_text(record, DESCRIPTION_KEYS),
            "department": _first_text(record, ("department", "team", "category")),
            "created_at": _first_text(record, ("createdAt", "postedAt", "datePosted")),
            "updated_at": _first_text(record, ("updatedAt", "lastModified")),
            "is_listed": True,
        })
        if len(jobs) >= MAX_BROWSER_JOBS:
            break
    return jobs


def _title_from_link(text: str, url: str) -> str:
    value = plain_text(text)
    if value and len(value) <= 140 and JOB_HINT.search(value):
        return value
    parts = [part for part in urlsplit(url).path.split("/") if part]
    if not parts:
        return value[:140]
    slug = re.sub(r"[-_]+", " ", parts[-1])
    slug = re.sub(r"\b[0-9a-f]{8,}\b", "", slug, flags=re.I)
    return " ".join(slug.split()).title()[:140]


def _looks_like_job(text: str, href: str) -> bool:
    combined = f"{text} {href}"
    if not JOB_HINT.search(combined):
        return False
    if plain_text(text).casefold() in GENERIC_LINK_TITLES:
        return False
    lowered = combined.casefold()
    return not any(skip in lowered for skip in ("privacy", "terms", "benefits", "linkedin.com/company"))


def _extract_links(page, base_url: str) -> list[dict]:
    anchors = page.locator("a").evaluate_all(
        """nodes => nodes.map(a => ({
            text: (a.innerText || a.textContent || '').trim(),
            href: a.href || a.getAttribute('href') || ''
        }))"""
    )
    seen = set()
    links = []
    try:
        base_key = canonicalize_url(base_url)
    except ValueError:
        base_key = base_url
    for anchor in anchors:
        href = urljoin(base_url, str(anchor.get("href") or ""))
        text = str(anchor.get("text") or "")
        if not href.startswith("http") or not _same_site(base_url, href) or not _looks_like_job(text, href):
            continue
        try:
            key = canonicalize_url(href)
        except ValueError:
            continue
        if key == base_key:
            continue
        if key in seen:
            continue
        seen.add(key)
        links.append({"url": href, "title": _title_from_link(text, href)})
        if len(links) >= MAX_BROWSER_JOBS:
            break
    return links


def _page_text(page) -> str:
    try:
        return plain_text(page.locator("body").inner_text(timeout=5000))
    except Exception:
        return ""


def _description(page, fallback: str) -> str:
    text = _page_text(page)
    if DETAIL_HINT.search(text):
        return text[:50000]
    return fallback[:50000]


def fetch_browser_inventory(ats: str, careers_url: str, company_id: str, company: str,
                            *, headless: bool = True, timeout_ms: int = 30000) -> Inventory:
    """Open a browser and scrape visible job links/details from a public careers page.

    This is intentionally generic and explicit. It is a fallback for blocked
    public pages, not proof of closure when it fails or finds no jobs.
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return Inventory(
            "unsupported",
            reason="Browser fallback requires the optional Playwright dependency. Install with: pip install '.[browser]' && python -m playwright install chromium",
            source_url=careers_url,
            ats=ats or "Browser",
        )
    if not careers_url or urlsplit(careers_url).scheme != "https":
        return Inventory("unsupported", reason="Browser fallback requires an HTTPS careers URL.", source_url=careers_url, ats=ats or "Browser")
    jobs = []
    json_jobs = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                def capture_response(response):
                    if len(json_jobs) >= MAX_BROWSER_JOBS:
                        return
                    try:
                        headers = {str(k).casefold(): str(v) for k, v in response.headers.items()}
                        url = response.url
                        if "json" not in headers.get("content-type", "") or not _same_site(careers_url, url):
                            return
                        payload = json.loads(response.text())
                    except Exception:
                        return
                    json_jobs.extend(jobs_from_json_payload(payload, url, company_id, company, ats))

                page.on("response", capture_response)
                page.goto(careers_url, wait_until="networkidle", timeout=timeout_ms)
                listing_text = _page_text(page)
                jobs.extend(json_jobs[:MAX_BROWSER_JOBS])
                if not jobs and NO_OPENINGS.search(listing_text):
                    return Inventory("partial", reason="Browser fallback found a reachable careers page with no open positions shown; inventory completeness unknown.", source_url=careers_url, ats=ats or "Browser")
                seen_urls = {job["url"] for job in jobs}
                links = _extract_links(page, careers_url)
                for link in links:
                    if link["url"] in seen_urls:
                        continue
                    try:
                        detail = browser.new_page()
                        detail.goto(link["url"], wait_until="networkidle", timeout=timeout_ms)
                        description = _description(detail, listing_text)
                        detail.close()
                    except Exception:
                        description = listing_text
                    if not link["title"] or not description:
                        continue
                    jobs.append({
                        "company_id": company_id,
                        "company": company,
                        "ats": ats or "Browser",
                        "posting_id": _posting_id(link["url"]),
                        "req_id": "",
                        "url": link["url"],
                        "title": link["title"],
                        "location": "",
                        "work_arrangement": "",
                        "compensation": "",
                        "description": description,
                        "department": "",
                        "created_at": "",
                        "updated_at": "",
                        "is_listed": True,
                    })
                    seen_urls.add(link["url"])
                page.close()
            finally:
                browser.close()
    except PlaywrightError as exc:
        return Inventory("blocked", reason=f"Browser fallback failed: {type(exc).__name__}", source_url=careers_url, ats=ats or "Browser")
    except Exception as exc:
        return Inventory("failed", reason=f"Browser fallback failed: {type(exc).__name__}", source_url=careers_url, ats=ats or "Browser")
    if not jobs:
        return Inventory("partial", reason="Browser fallback found no usable job links; inventory completeness unknown.", source_url=careers_url, ats=ats or "Browser")
    return Inventory("complete", jobs, f"Browser fallback scraped {len(jobs)} visible job posting(s).", careers_url, ats or "Browser")


def with_browser_fallback(fetcher):
    def wrapped(ats: str, careers_url: str, company_id: str, company: str):
        result = fetcher(ats, careers_url, company_id, company)
        if result.status not in {"blocked", "failed", "unsupported"}:
            return result
        browser_result = fetch_browser_inventory(ats, careers_url, company_id, company)
        if browser_result.status == "complete":
            browser_result.reason = f"Direct fetch returned {result.status}: {result.reason}. {browser_result.reason}"
            return browser_result
        browser_result.reason = f"Direct fetch returned {result.status}: {result.reason}. {browser_result.reason}"
        return browser_result
    return wrapped
