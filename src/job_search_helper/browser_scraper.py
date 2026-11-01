"""Optional browser fallback for careers pages that block direct HTTP reads."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from urllib.parse import parse_qsl, unquote, urljoin, urlsplit

from .ats import Inventory, has_lever_scope
from .core import canonicalize_url, plain_text
from .browser_progress import BrowserProgress

MAX_BROWSER_JOBS = 1000
MAX_BROWSER_PAGES = 500
FIRST_DETAIL_TIMEOUT_MS = 15000
MAX_BROWSER_SECONDS = 300
MAX_CONSECUTIVE_DETAIL_FAILURES = 5
JOB_HINT = re.compile(r"\b(job|career|position|opening|role|requisition|req)\b", re.I)
DETAIL_HINT = re.compile(r"\b(responsibilities|requirements|qualifications|salary|compensation|about the role|what you.ll do)\b", re.I)
NO_OPENINGS = re.compile(r"\b(no open positions|no current openings|no jobs were found|check back soon)\b", re.I)
GENERIC_LINK_TITLES = {"career", "careers", "job", "jobs", "open positions", "current openings", "join our team", "career growth"}
NON_JOB_LINK_TITLES = {
    "eeo", "e-verify", "e verify", "contact us", "contact", "accessibility", "equal employment opportunity",
    "facebook", "instagram", "linkedin", "twitter", "x", "youtube", "share",
    "share this job", "report this job", "save job", "sign in", "log in", "apply now",
    "all jobs", "view job", "job search", "career search", "career paths", "career areas",
    "career events", "career opportunities", "job openings", "job alert", "job application form",
}
NON_JOB_TITLE_HINT = re.compile(
    r"\b(see who .+ hired|report this job|share this job|sign[ -]?in|log[ -]?in|forgot password|"
    r"cookie settings|talent community|job alerts?|job categories|early career|internships?)\b", re.I
)
NON_JOB_PATH_HINT = re.compile(
    r"/(?:login|signin|sign-in|uas/login|auth|account|privacy|terms|benefits)(?:/|$)|"
    r"/(?:data/)?navigation-links/(?:footer|header)/|/data/field-sources/|/(?:eeo|e-verify|contact-us)(?:/|$)|/(?:footer|header)/(?:facebook|instagram|linkedin|twitter|x|youtube)(?:/|$)",
    re.I,
)
JOB_PATH_SEGMENTS = {"job", "jobs", "jobdetail", "jobdetails", "position", "positions",
                     "job-detail", "job-details", "position", "positions", "opening", "openings",
                     "requisition", "requisitions", "vacancy", "vacancies"}
LISTING_PATH_SEGMENTS = {
    "job", "jobs", "search", "search-jobs", "career-search", "career-paths", "career-areas",
    "categories", "job-categories", "events", "alerts", "job-alerts", "talent-community",
    "join-talent-community", "intern-page", "early-career", "early-careers", "career-growth", "cookiesettings",
    "jobalertregister", "applicationmethods",
}
JOB_QUERY_KEYS = {"gh_jid", "lv_jid", "jobid", "job_id", "postingid", "posting_id", "requisitionid", "reqid"}
# Exact navigation segments observed in saved browser retry queues. Do not
# match substrings in real titles such as employee-relations-manager.
NON_JOB_PAGE_SEGMENTS = {
    '_wp_link_placeholder', 'employee-testimonials', 'testimonials', 'our-facility',
    'candidate-resources', 'application-faqs', 'employment-scams', 'our-teams',
    'programs-and-partnerships', 'internship-program', 'internships-and-early-careers',
    'military-talent', 'roles-and-missions', 'professional-development',
    'a-rewarding-workplace', 'perks', 'preparing-for-an-interview',
    'why-employee-owned-matters', 'about-boston-metro-north', 'why-psi',
    'by-capability', 'product', 'products', 'settings',
}
CAREER_LISTING_PAGES = {
    'open-positions', 'open-roles', 'current-openings', 'job-openings',
    'job-opportunities', 'jobs', 'positions', 'vacancies',
}
CAREER_NAVIGATION_PAGES = {'saab-life', 'students', 'students-and-graduates', 'graduates'}
TITLE_KEYS = ("title", "jobTitle", "name", "positionTitle", "postingTitle")
URL_KEYS = ("url", "jobUrl", "applyUrl", "postingUrl", "externalUrl", "jobDetailUrl")
ID_KEYS = ("id", "jobId", "postingId", "reqId", "requisitionId", "referenceNumber")
DESCRIPTION_KEYS = ("description", "jobDescription", "descriptionHtml", "descriptionPlain", "summary")
LOCATION_KEYS = ("location", "jobLocation", "locations", "city", "state")


class DetailUnavailable(ValueError):
    """A locally generated detail failure safe to persist in checkpoints."""


class ListingUnavailable(ValueError):
    """A public, locally generated reason that is safe to include in status."""


def _same_site(base: str, candidate: str) -> bool:
    base_host = urlsplit(base).hostname or ""
    candidate_host = urlsplit(candidate).hostname or ""
    return candidate_host == base_host or candidate_host.endswith("." + base_host)


def _posting_id(url: str) -> str:
    try:
        return "browser-" + hashlib.sha256(canonicalize_url(url).encode()).hexdigest()[:24]
    except ValueError:
        return ""


def _career_listing_url(source: str, candidate: str) -> bool:
    """Recognize an unfiltered job-list landing page, never a posting detail."""
    base, parsed = urlsplit(source), urlsplit(candidate)
    return ((parsed.scheme, parsed.hostname, parsed.port) == (base.scheme, base.hostname, base.port)
            and not base.query and not parsed.query and not parsed.fragment
            and unquote(parsed.path.rstrip('/').rsplit('/', 1)[-1]).casefold().removesuffix('.html') in CAREER_LISTING_PAGES)


def _non_job_link(title: str, url: str) -> bool:
    text = plain_text(title).strip().casefold()
    parsed = urlsplit(url)
    try:
        query_keys = {key.casefold() for key, value in parse_qsl(parsed.query, max_num_fields=80) if value}
    except ValueError:
        return True
    # Confirmed listing/filter routes from the persisted detail queue. Keep
    # explicit job-ID query links and actual detail paths eligible. Pagination
    # discovery is separate and can still visit these board pages.
    known_listing = (
        parsed.hostname in {'www.axon.com', 'axon.com'}
        and parsed.path.rstrip('/') == '/careers/all'
    ) or (
        parsed.hostname == 'www.rohde-schwarz.com'
        and re.fullmatch(r'/(?:[a-z]{2,3}(?:-[a-z]{2})?/)?career/jobs/career-jobboard_[0-9]+\.html', parsed.path, re.I)
    )
    if known_listing and not query_keys & JOB_QUERY_KEYS:
        return True
    if parsed.hostname == "careers.mantech.com" and not _mantech_title_from_url(url):
        return True
    if parsed.hostname in {"www.northropgrumman.com", "northropgrumman.com"}:
        return True  # Corporate CMS records cannot establish job identity.
    segments = [unquote(part).casefold().removesuffix('.html')
                for part in parsed.path.split('/') if part]
    navigation = (any(part in NON_JOB_PAGE_SEGMENTS or part.startswith('life-at-')
                      for part in segments)
                  or bool(segments and segments[-1] in CAREER_LISTING_PAGES and not query_keys & JOB_QUERY_KEYS)
                  or bool(segments and segments[-1] in CAREER_NAVIGATION_PAGES
                          and any(part in {'career', 'careers'} for part in segments[:-1])))
    return (text in NON_JOB_LINK_TITLES or bool(NON_JOB_TITLE_HINT.search(text))
            or bool(NON_JOB_PATH_HINT.search(parsed.path)) or navigation)


def _mantech_title_from_url(url: str) -> str:
    """Recover a title only from ManTech's confirmed, numbered detail route."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'careers.mantech.com':
        return ''
    match = re.fullmatch(r'/en_US/careers/JobDetail/([^/]+)/[0-9]+/?', parsed.path)
    return plain_text(unquote(match[1]).replace('-', ' ')) if match else ''


def _repair_mantech_progress(progress: BrowserProgress):
    # Old checkpoints include search pages and the visually hidden brand h1.
    # Keep checkpoint evidence on disk, but exclude non-jobs from this scrape.
    for url, entry in list(progress.entries().items()):
        if urlsplit(url).hostname != 'careers.mantech.com':
            continue
        title = _mantech_title_from_url(url)
        if not title:
            del progress.entries()[url]
        elif entry['job'] is not None and entry['job'].get('title', '').strip().casefold() == 'mantech':
            progress.save_job(url, dict(entry['job'], title=title))


def _exclude_saved_navigation(progress: BrowserProgress, careers_url: str):
    # Apply current exclusions to resumed work as well as new links. Retain
    # the original checkpoint on disk for audit; never delete job history.
    listing = progress.listing(careers_url)
    changed = False
    for url, entry in list(progress.entries().items()):
        if _career_listing_url(careers_url, url) and url not in listing['visited'] and url not in listing['queue']:
            listing['queue'].append(url)
            changed = True
        if _non_job_link(entry['link'].get('title', ''), url):
            del progress.entries()[url]
    if changed:
        listing['complete'] = False
        progress.save_listing(listing)


def _looks_like_posting_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or _non_job_link("", url):
        return False
    segments = [part.casefold() for part in parsed.path.split("/") if part]
    try:
        query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=30)}
    except ValueError:
        return False
    if any(part in {"jobalertregister", "applicationmethods"} for part in segments):
        return False
    if query_keys & JOB_QUERY_KEYS:
        return True
    for index, part in enumerate(segments):
        if part in JOB_PATH_SEGMENTS and index < len(segments) - 1:
            return segments[index + 1] not in LISTING_PATH_SEGMENTS
    # Some company sites use /career/<job-slug> rather than /jobs/<id>.
    return any(part in {"career", "careers"} and index < len(segments) - 1
               and segments[index + 1] not in LISTING_PATH_SEGMENTS
               for index, part in enumerate(segments))


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
        structured_title = any(record.get(key) for key in ("jobTitle", "positionTitle", "postingTitle"))
        structured_id = any(record.get(key) for key in ("jobId", "postingId", "reqId", "requisitionId", "referenceNumber"))
        if (not url.startswith("http") or not _same_site(base_url, url) or _non_job_link(title, url)
                or not (_looks_like_posting_url(url) or (structured_title and structured_id))):
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
    # Avature's detail URLs end in a numeric internal ID.  The title is the
    # preceding slug, even when the visible title does not contain "job".
    if len(parts) >= 3 and parts[-3].casefold() == "jobdetail":
        if value and len(value) <= 140 and value.casefold() not in GENERIC_LINK_TITLES:
            return value
        return plain_text(unquote(parts[-2]).replace('-', ' '))[:140]
    slug = re.sub(r"[-_]+", " ", parts[-1])
    slug = re.sub(r"\b[0-9a-f]{8,}\b", "", slug, flags=re.I)
    return " ".join(slug.split()).title()[:140]


def _looks_like_job(text: str, href: str) -> bool:
    combined = f"{text} {href}"
    # A provider-specific route such as Avature's ``/JobDetail/`` is a
    # stronger signal than title text; "JobDetail" has no word boundary
    # between "job" and "detail", so JOB_HINT alone would reject it.
    if not _looks_like_posting_url(href) or _non_job_link(text, href):
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


def _listing_pages(page, careers_url: str) -> list[str]:
    """Return same-site job-list landing pages and same-board pagination.

    A generic browser scrape may collect these pages but never treats the
    result as complete: unlike named ATS adapters, page controls alone do not
    prove a stable total.  The tight URL and label checks prevent navigation,
    category, and footer links from becoming crawl targets.
    """
    anchors = page.locator("a").evaluate_all(
        """nodes => nodes.map(a => ({href: a.href || a.getAttribute('href') || '',
                                      text: (a.innerText || a.textContent || '').trim(),
                                      rel: a.getAttribute('rel') || '',
                                      aria: a.getAttribute('aria-label') || ''}))"""
    )
    base = urlsplit(careers_url)
    pages = []
    for anchor in anchors:
        url = urljoin(careers_url, str(anchor.get("href") or ""))
        parsed = urlsplit(url)
        if _career_listing_url(careers_url, url) and parsed.path.rstrip('/') != base.path.rstrip('/'):
            pages.append(canonicalize_url(url))
            continue
        same_origin = (parsed.scheme, parsed.hostname) == (base.scheme, base.hostname)
        same_listing = parsed.path.rstrip("/") == base.path.rstrip("/")
        avature_search = (parsed.path.rstrip("/") == base.path.rstrip("/") + "/SearchJobs")
        if not same_origin or not (same_listing or avature_search):
            continue
        label = plain_text(" ".join(str(anchor.get(k) or "") for k in ("text", "rel", "aria"))).casefold()
        try:
            query = dict(parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20))
        except ValueError:
            continue
        numbered = any(key.casefold() in {"page", "p", "pr", "pagenumber", "pageindex"}
                       and value.isdigit() and 0 <= int(value) < MAX_BROWSER_PAGES
                       for key, value in query.items())
        offset_pagination = any(key.casefold() in {"joboffset", "offset", "start"}
                                and value.isdigit() and 0 <= int(value) < MAX_BROWSER_PAGES * 100
                                for key, value in query.items())
        if numbered or offset_pagination or (same_listing and (label in {"next", "next page"} or "next page" in label)):
            try:
                pages.append(canonicalize_url(url))
            except ValueError:
                continue
    return list(dict.fromkeys(pages))


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


# Read the job content itself. Background analytics need not become idle.
# Briefly require stable text to avoid saving the first fragment of a render.
DETAIL_CONTENT = r"""({fallbackTitle, settle}) => {
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const body = clean(document.body?.innerText);
    if (/verify you are human|checking your browser|access denied|just a moment/i.test(body.slice(0, 1500))) return false;
    const mantechDetail = location.hostname === 'careers.mantech.com' &&
        /^\/en_US\/careers\/JobDetail\/[^/]+\/[0-9]+\/?$/.test(location.pathname);
    let title = mantechDetail
        ? clean(document.querySelector('h2.banner__text__title')?.innerText) || fallbackTitle
        : clean(document.querySelector('h1')?.innerText) || fallbackTitle;
    let description = '';
    const walk = value => {
        if (!value || typeof value !== 'object') return;
        const types = [].concat(value['@type'] || []);
        if (types.includes('JobPosting') && value.description && value.title) {
            title = clean(value.title);
            const doc = new DOMParser().parseFromString(value.description, 'text/html');
            description = clean(doc.body.textContent);
        }
        for (const child of Object.values(value)) {
            if (Array.isArray(child)) child.forEach(walk);
            else if (child && typeof child === 'object') walk(child);
        }
    };
    for (const node of document.querySelectorAll('script[type="application/ld+json"]')) {
        try { walk(JSON.parse(node.textContent)); } catch (_) {}
    }
    if (!description) {
        const selectors = '[itemprop="description"], [data-automation-id="jobPostingDescription"], .job-description, #job-description, .jobDescription, .job-detail-description';
        description = [...document.querySelectorAll(selectors)].map(n => clean(n.innerText)).filter(Boolean).join('\n');
    }
    if (!description) {
        const text = clean(document.querySelector('main, [role="main"], article')?.innerText) || body;
        if (/\b(responsibilities|requirements|qualifications|about the role|what you.ll do)\b/i.test(text)) description = text;
    }
    if (!title || description.length < 120) return false;
    const value = {title, description};
    if (!settle) return value;
    const signature = title + '\n' + description;
    const previous = window.__jshDetailContent;
    if (!previous || previous.signature !== signature) {
        window.__jshDetailContent = {signature, at: performance.now()};
        return false;
    }
    return performance.now() - previous.at >= 500 ? value : false;
}"""


def _fetch_detail(browser, link, timeout_ms):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    detail = browser.new_page()
    started = time.monotonic()
    try:
        try:
            response = detail.goto(link['url'], wait_until='commit', timeout=timeout_ms)
            if response is not None and response.status >= 400:
                raise DetailUnavailable(f'Job detail HTTP {response.status}')
            remaining = max(1, timeout_ms - int((time.monotonic() - started) * 1000))
            handle = detail.wait_for_function(DETAIL_CONTENT,
                arg={'fallbackTitle': link['title'], 'settle': True}, timeout=remaining, polling=100)
            try:
                content = handle.json_value()
            finally:
                handle.dispose()
        except BrowserTimeout:
            # Navigation can time out after useful HTML has already arrived.
            content = detail.evaluate(DETAIL_CONTENT, {'fallbackTitle': link['title'], 'settle': False})
        if not content or not content.get('description'):
            raise DetailUnavailable('Job description not available yet')
        return content
    finally:
        # Also run after timeouts, extraction errors, and interruption.
        try:
            detail.close()
        except Exception:
            pass


def _scoped_taleo_cards(page, company_id: str, company: str, ats: str) -> list[dict]:
    """Read server-rendered, company-scoped Taleo cards when present."""
    records = page.locator(".career-reference-wrapper").evaluate_all(
        """nodes => nodes.map(node => {
            const value = selector => (node.querySelector(selector)?.innerText || '').trim();
            const link = node.querySelector('a[href*="/jobdetail.ftl?job="]');
            return {
                url: link?.href || '', title: (link?.innerText || '').trim(),
                city: value('.career-reference__city'), state: value('.career-reference__state'),
                country: value('.career-reference__country'), date: value('.career-reference__date'),
                reference: value('.career-reference__reference-number'),
                description: value('.accordion__content__inner')
            };
        })"""
    )
    jobs = []
    seen = set()
    for record in records:
        url = str(record.get("url") or "")
        parsed = urlsplit(url)
        try:
            values = dict(parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=20))
        except ValueError:
            continue
        posting_id = values.get("job", "")
        from .taleo import BOARD, is_taleo_host
        if (not is_taleo_host(parsed.hostname) or not BOARD.fullmatch(parsed.path)
                or not parsed.path.casefold().endswith("/jobdetail.ftl")
                or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", posting_id)
                or posting_id in seen):
            continue
        title = plain_text(str(record.get("title") or ""))
        description = plain_text(str(record.get("description") or ""))
        if not title or not description:
            continue
        seen.add(posting_id)
        location = ", ".join(part.rstrip(" ,") for part in (
            plain_text(str(record.get("city") or "")),
            plain_text(str(record.get("state") or "")),
            plain_text(str(record.get("country") or "")),
        ) if part.rstrip(" ,"))
        jobs.append({
            "company_id": company_id,
            "company": company,
            "ats": ats or "Taleo",
            "posting_id": posting_id,
            "req_id": posting_id,
            "url": parsed._replace(query=f"job={posting_id}", fragment="").geturl(),
            "title": title,
            "location": location,
            "work_arrangement": "Remote" if "remote" in f"{location} {description}".casefold() else "",
            "compensation": "",
            "description": description[:50000],
            "department": "",
            "created_at": re.sub(r"^Posted Date:\s*", "", plain_text(str(record.get("date") or "")), flags=re.I),
            "updated_at": "",
            "is_listed": True,
        })
    return jobs


def _scoped_page_links(page, careers_url: str) -> list[str]:
    links = page.locator('a[href*="page="]').evaluate_all("nodes => nodes.map(node => node.href || '')")
    origin = urlsplit(careers_url)
    results = []
    for link in links:
        parsed = urlsplit(str(link))
        if (parsed.scheme, parsed.hostname, parsed.path.rstrip("/")) != (
                origin.scheme, origin.hostname, origin.path.rstrip("/")):
            continue
        try:
            values = dict(parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=10))
        except ValueError:
            continue
        if set(values) == {"page"} and values["page"].isdigit() and int(values["page"]) < 100:
            results.append(careers_url if int(values["page"]) == 0 else parsed._replace(fragment="").geturl())
    return results


def _scoped_browser_inventory(page, careers_url: str, company_id: str, company: str,
                              ats: str, timeout_ms: int, *, deadline: float | None = None) -> Inventory | None:
    jobs, seen = [], set()
    queue, visited = [careers_url], set()
    expected_total = None
    maximum_total = None
    counts_changed = False
    first_ids = None
    while queue and len(visited) < 100 and len(jobs) < MAX_BROWSER_JOBS:
        if deadline is not None and time.monotonic() >= deadline:
            return Inventory('partial', jobs, 'Browser time limit reached; scoped inventory remains incomplete.', careers_url, ats or 'Taleo')
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        remaining_ms = timeout_ms if deadline is None else max(1, int((deadline - time.monotonic()) * 1000))
        page.goto(url, wait_until="domcontentloaded", timeout=min(timeout_ms, remaining_ms))
        text_value = _page_text(page)
        cards = _scoped_taleo_cards(page, company_id, company, ats)
        if not cards and len(visited) == 1:
            return None
        match = re.search(r"\b([0-9][0-9,]*)\s+job\(s\)\s+match your search criteria\b", text_value, re.I)
        total = int(match.group(1).replace(",", "")) if match else None
        if expected_total is None:
            expected_total = total
        elif total is not None and total != expected_total:
            counts_changed = True
        if total is not None:
            maximum_total = max(maximum_total or 0, total)
        page_ids = []
        for job in cards:
            page_ids.append(job["posting_id"])
            if job["posting_id"] not in seen:
                seen.add(job["posting_id"])
                jobs.append(job)
        if first_ids is None:
            first_ids = page_ids
        for link in _scoped_page_links(page, careers_url):
            if link not in visited and link not in queue:
                queue.append(link)
        if maximum_total is not None and cards:
            page_count = min(100, math.ceil(maximum_total / len(cards)))
            parsed_source = urlsplit(careers_url)
            for number in range(page_count):
                link = careers_url if number == 0 else parsed_source._replace(query=f"page={number}", fragment="").geturl()
                if link not in visited and link not in queue:
                    queue.append(link)
    if counts_changed or expected_total is None or len(jobs) != maximum_total:
        reason = (f"Browser fallback retrieved {len(jobs)} scoped postings"
                  + (f" out of maximum reported total {maximum_total}." if maximum_total is not None else ", but no trustworthy total was shown."))
        if counts_changed:
            reason = "Browser-scoped careers count changed during pagination. " + reason
        return Inventory("partial", jobs, reason, careers_url, ats or "Taleo")
    if deadline is not None and time.monotonic() >= deadline:
        return Inventory('partial', jobs, 'Browser time limit reached before the scoped inventory recheck.', careers_url, ats or 'Taleo')
    remaining_ms = timeout_ms if deadline is None else max(1, int((deadline - time.monotonic()) * 1000))
    page.goto(careers_url, wait_until="domcontentloaded", timeout=min(timeout_ms, remaining_ms))
    check = _scoped_taleo_cards(page, company_id, company, ats)
    if [job["posting_id"] for job in check] != first_ids:
        return Inventory("partial", jobs, "Browser-scoped careers page changed during the scan.", careers_url, ats or "Taleo")
    return Inventory("complete", jobs, f"Browser fallback scraped all {len(jobs)} scoped Taleo postings.", careers_url, ats or "Taleo")


def fetch_browser_inventory(ats: str, careers_url: str, company_id: str, company: str,
                            *, headless: bool = True, timeout_ms: int = 30000,
                            progress: BrowserProgress | None = None) -> Inventory:
    """Open a browser and scrape visible job links/details from a public careers page.

    This is intentionally generic and explicit. It is a fallback for blocked
    public pages, not proof of closure when it fails or finds no jobs.
    """
    if not careers_url or urlsplit(careers_url).scheme != "https":
        return Inventory("unsupported", reason="Browser fallback requires an HTTPS careers URL.", source_url=careers_url, ats=ats or "Browser")
    if has_lever_scope(careers_url):
        return Inventory("unsupported", reason="Lever filter scope cannot be verified by browser fallback.", source_url=careers_url, ats="Lever")
    from .northrop import supports_northrop, fetch_northrop
    if supports_northrop(careers_url):
        return fetch_northrop(careers_url, company_id, company, headless=headless, timeout_ms=timeout_ms)
    from .mtsi import supports_mtsi, fetch_mtsi
    if supports_mtsi(careers_url):
        return fetch_mtsi(careers_url, company_id, company)
    if ats.casefold() == "eightfold" or urlsplit(careers_url).hostname.endswith(".eightfold.ai"):
        from .eightfold import fetch_eightfold
        return fetch_eightfold(careers_url, company_id, company, ats)
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
    progress = progress or BrowserProgress()
    _repair_mantech_progress(progress)
    _exclude_saved_navigation(progress, careers_url)
    listing = progress.listing(careers_url)
    error = ''
    deadline = time.monotonic() + MAX_BROWSER_SECONDS
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            try:
                page = browser.new_page()
                def capture_response(response):
                    try:
                        headers = {str(k).casefold(): str(v) for k, v in response.headers.items()}
                        url = response.url
                        if "json" not in headers.get("content-type", "") or not _same_site(careers_url, url):
                            return
                        payload = json.loads(response.text())
                    except Exception:
                        return
                    # Persist discovered identities, even when the response only
                    # contains a teaser. Detail pages must supply the description.
                    progress.discover([{'url': job['url'], 'title': job['title'], 'template': job}
                        for job in jobs_from_json_payload(payload, url, company_id, company, ats)])

                page.on("response", capture_response)
                if not listing['visited'] and not progress.entries():
                    scoped = _scoped_browser_inventory(page, careers_url, company_id, company, ats, timeout_ms, deadline=deadline)
                    if scoped is not None:
                        return scoped
                visited = set(listing['visited'])
                pages_this_run = 0
                while listing['queue'] and pages_this_run < MAX_BROWSER_PAGES:
                    if time.monotonic() >= deadline:
                        error = f'Browser time limit reached ({MAX_BROWSER_SECONDS} seconds); saved progress retained.'
                        break
                    listing_url = listing['queue'][0]
                    try:
                        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                        response = page.goto(listing_url, wait_until='domcontentloaded', timeout=min(timeout_ms, remaining_ms))
                        if response is not None and response.status >= 400:
                            raise ListingUnavailable(f'Listing HTTP {response.status}')
                        page.wait_for_timeout(500)
                        links = _extract_links(page, careers_url)
                        candidates = _listing_pages(page, page.url or listing_url)
                        text = _page_text(page)
                        if not links and not candidates and not progress.entries() and not NO_OPENINGS.search(text):
                            raise ListingUnavailable('Listing has no verifiable job links yet')
                    except Exception as exc:
                        detail = f': {exc}' if isinstance(exc, ListingUnavailable) else ''
                        error = f'Listing discovery needs retry ({type(exc).__name__}{detail}).'
                        break
                    progress.discover(links)
                    visited.add(listing_url)
                    listing['queue'].pop(0)
                    for candidate in candidates:
                        if candidate not in visited and candidate not in listing['queue']:
                            listing['queue'].append(candidate)
                    listing.update(visited=sorted(visited), complete=not listing['queue'])
                    progress.save_listing(listing)
                    pages_this_run += 1
                # Finish the first pass before retrying slow/failed URLs once.
                # Try details quickly first; keep the full configured timeout
                # for the retry and never exceed a caller's shorter timeout.
                # Any remaining failures stay durable for the next resume.
                budget_exhausted = False
                for _pass in range(2):
                    consecutive_failures = 0
                    detail_timeout_ms = min(timeout_ms, FIRST_DETAIL_TIMEOUT_MS) if _pass == 0 else timeout_ms
                    for url, entry in list(progress.entries().items()):
                        if entry['job'] is not None:
                            continue
                        remaining_ms = int((deadline - time.monotonic()) * 1000)
                        if remaining_ms <= 0:
                            error = f'Browser time limit reached ({MAX_BROWSER_SECONDS} seconds); saved progress retained.'
                            budget_exhausted = True
                            break
                        link = entry['link']
                        try:
                            content = _fetch_detail(browser, link, min(detail_timeout_ms, remaining_ms))
                        except Exception as exc:
                            detail = f': {exc}' if isinstance(exc, DetailUnavailable) else ''
                            progress.failed(url, type(exc).__name__ + detail)
                            consecutive_failures += 1
                            if consecutive_failures >= MAX_CONSECUTIVE_DETAIL_FAILURES:
                                error = (f'Stopped this detail pass after {consecutive_failures} consecutive failures; '
                                         'unresolved URLs and saved descriptions retained.')
                                break
                            continue
                        consecutive_failures = 0
                        job = {"company_id": company_id, "company": company, "ats": ats or "Browser",
                            "posting_id": _posting_id(url), "req_id": "", "url": url,
                            "location": "", "work_arrangement": "", "compensation": "",
                            "department": "", "created_at": "", "updated_at": "", "is_listed": True,
                            **link.get('template', {}), "url": url, "title": content['title'],
                            "description": content['description']}
                        # Commit each success before requesting the next page.
                        progress.save_job(url, job)
                    if budget_exhausted:
                        break
                page.close()
            finally:
                browser.close()
    except PlaywrightError as exc:
        error = f"Browser fallback needs retry ({type(exc).__name__})."
    except Exception as exc:
        error = f"Browser fallback needs retry ({type(exc).__name__})."
    entries = progress.entries()
    jobs = [entry['job'] for entry in entries.values() if entry['job'] is not None]
    pending = [url for url, entry in entries.items() if entry['job'] is None]
    discovery_incomplete = not progress.listing(careers_url)['complete']
    reason = (f"Browser fallback saved {len(jobs)} job descriptions; {len(pending)} job URLs await retry. "
              "Inventory completeness unknown; no closure inference. " + error).strip()
    return Inventory("partial", jobs, reason, careers_url, ats or "Browser",
                     browser_pending_urls=pending, browser_discovery_incomplete=discovery_incomplete)


def with_browser_fallback(fetcher):
    def fetch_resolved(ats: str, careers_url: str, company_id: str, company: str, progress_factory=None):
        progress_fetcher = getattr(fetcher, 'fetch_with_progress', None)
        if progress_factory is not None and progress_fetcher is not None:
            result = progress_fetcher(ats, careers_url, company_id, company, progress_factory=progress_factory)
        else:
            result = fetcher(ats, careers_url, company_id, company)
        # The generic browser cannot establish that a Lever UI filter was applied.
        if has_lever_scope(careers_url):
            return result
        from .dayforce import SOURCE as ESA_DAYFORCE_SOURCE
        if result.ats == "Dayforce" and careers_url == ESA_DAYFORCE_SOURCE:
            # This public board has a complete numeric-ID adapter. The shared
            # browser route uses a different URL contract and cannot fill a
            # structured-feed gap or establish its full description sections.
            return result
        # Generic visible links cannot verify these adapters' inventory or
        # employer scopes and use different posting identifiers.
        from .shared_boards import FAMILIES, fetch_shared_browser
        if result.ats == "SAIC TalentBrew":
            if result.status in {"blocked", "partial"}:
                from .saic import fetch_saic_browser
                browser_result = fetch_saic_browser(careers_url, company_id, company)
                return browser_result if len(browser_result.jobs) >= len(result.jobs) else result
            return result
        if result.ats in FAMILIES:
            if result.status in {"blocked", "partial"}:
                browser_result = fetch_shared_browser(ats, careers_url, company_id, company, **({'progress_factory': progress_factory} if progress_factory is not None else {}))
                return browser_result if len(browser_result.jobs) >= len(result.jobs) else result
            return result
        if result.ats == "Workday" and result.jobs:
            # Generic links use different IDs and cannot fill a structured feed gap.
            return result
        from .successfactors import SITES as SUCCESSFACTORS_SITES
        if result.ats == "SuccessFactors" and careers_url in SUCCESSFACTORS_SITES:
            # The verified adapter owns employer scope and numeric posting
            # identities. Generic browser links cannot prove completeness and
            # introduce incompatible URL-hash IDs for the same saved jobs.
            return result
        if result.ats in {"Phenom", "BambooHR", "Paycom", "UKG", "Gem", "ApplicantStack", "Teamtailor", "AcquireTM", "KBR"}:
            return result
        if result.status not in {"blocked", "failed", "unsupported", "partial"}:
            return result
        if (ats.casefold() in {"", "browser", "unknown"} and
                ("No supported ATS link" in result.reason or "not supported yet" in result.reason)):
            shared_result = fetch_shared_browser(ats, careers_url, company_id, company, **({'progress_factory': progress_factory} if progress_factory is not None else {}))
            if shared_result.ats in FAMILIES:
                return shared_result
        options = {'progress': progress_factory(careers_url)} if progress_factory is not None else {}
        browser_result = fetch_browser_inventory(ats, careers_url, company_id, company, **options)
        if browser_result.status == "complete":
            browser_result.reason = f"Direct fetch returned {result.status}: {result.reason}. {browser_result.reason}"
            return browser_result
        if result.jobs and browser_result.jobs:
            merged = {}
            for job in (*result.jobs, *browser_result.jobs):
                key = str(job.get("posting_id") or job.get("url") or "")
                if key:
                    merged.setdefault(key, job)
            result.jobs = list(merged.values())
        chosen = browser_result if len(browser_result.jobs) > len(result.jobs) else result
        chosen.browser_pending_urls = browser_result.browser_pending_urls
        chosen.browser_discovery_incomplete = browser_result.browser_discovery_incomplete
        if chosen.browser_pending_urls or chosen.browser_discovery_incomplete:
            chosen.status = 'partial'
        chosen.reason = (f"Direct fetch returned {result.status}: {result.reason}. "
                         f"Browser fallback returned {browser_result.status}: {browser_result.reason}")
        return chosen
    def wrapped(ats: str, careers_url: str, company_id: str, company: str, *, progress_factory=None):
        from .company_sources import repair_source
        ats, careers_url, note = repair_source(ats, careers_url, company_id, company)
        result = fetch_resolved(ats, careers_url, company_id, company, progress_factory)
        if note:
            result.reason = note + result.reason
        return result
    wrapped.fetch_with_progress = wrapped
    return wrapped
