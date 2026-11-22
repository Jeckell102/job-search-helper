"""Read-only official ATS adapters with bounded careers-page discovery.

Sources (checked 2026-09-17):
https://docs.greenhouse.io/job-board.html
https://github.com/lever/postings-api
https://developers.ashbyhq.com/docs/public-job-posting-api
https://docs.oracle.com/en/cloud/saas/taleo-enterprise/25a/otccu/c-customcareersectionurls.html

``complete`` means the public board inventory was retrieved, not that every
posting meets the candidate's criteria. No HTTP failure establishes closure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import json
import re
import socket
import sys
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_HOSTS = frozenset({
    "boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com",
})
BOARD_HOSTS = API_HOSTS | frozenset({
    "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co",
    "jobs.eu.lever.co", "jobs.ashbyhq.com", "workforcenow.adp.com", "recruiting.paylocity.com",
})
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PAGE_SIZE = 100
MAX_PAGES = 200
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def is_workday_host(host: str | None) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.wd[0-9]+\.myworkdayjobs\.com", host or ""))


def is_icims_host(host: str | None) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.icims\.com", host or ""))


def is_board_host(host: str | None) -> bool:
    if host in BOARD_HOSTS or is_workday_host(host) or is_icims_host(host):
        return True
    from .taleo import is_taleo_host
    return is_taleo_host(host)


@dataclass
class Inventory:
    status: str
    jobs: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    source_url: str = ""
    ats: str = ""


@dataclass
class HTTPResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class FetchError(Exception):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_api_url(url: str) -> None:
    parsed = urlsplit(url)
    workday = False
    if is_workday_host(parsed.hostname):
        from .workday import safe_api_path
        workday = safe_api_path(parsed)
    icims = False
    if is_icims_host(parsed.hostname):
        from .icims import safe_portal_path
        icims = safe_portal_path(parsed)
    adp = False
    if parsed.hostname == "workforcenow.adp.com":
        from .adp import safe_api_path
        adp = safe_api_path(parsed)
    paylocity = False
    if parsed.hostname == "recruiting.paylocity.com":
        from .paylocity import safe_portal_path
        paylocity = safe_portal_path(parsed)
    taleo = False
    from .taleo import is_taleo_host, safe_portal_path as taleo_safe_portal_path
    if is_taleo_host(parsed.hostname):
        taleo = taleo_safe_portal_path(parsed)
    if (parsed.scheme != "https" or (parsed.hostname not in API_HOSTS and not workday and not icims and not adp and not paylocity and not taleo)
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise FetchError("unsupported", "Only pinned official HTTPS API endpoints are allowed.")


def _delay(headers: Mapping[str, str], attempt: int) -> float:
    """Honor a bounded Retry-After delay, including its HTTP-date form."""
    value = next((v for k, v in headers.items() if k.lower() == "retry-after"), "")
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            seconds = (stamp - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = float(2 ** attempt)
    return max(0.0, min(8.0, seconds))


def _challenge(response: HTTPResponse, *, expect_html: bool = False) -> bool:
    preview = response.body[:8192].decode("utf-8", "replace").lower()
    # Do not mistake a JSON job mentioning CAPTCHA technology for a challenge.
    if not expect_html and 200 <= response.status < 300 and not preview.lstrip().startswith("<"):
        return False
    markers = ("verify you are human", "cf-chl-", "human verification")
    # Ordinary careers pages often embed reCAPTCHA for application forms.
    markers += (("<title>just a moment", "<title>captcha", "<title>access denied")
                if expect_html else ("captcha",))
    return any(marker in preview for marker in markers)


def _blocked_reason(response: HTTPResponse) -> str:
    """Return a safe manual-review reason without exposing response bodies."""
    if _challenge(response):
        return "Human verification detected; manual review required."
    if response.status in (401, 403):
        return f"HTTP {response.status}: access denied; manual review required; no automatic retry."
    return ""


class HTTPTransport:
    """Timeouts, rate limiting and bounded retries; never follows redirects.

    GET and Workday listing-search POST requests send no authentication or profile.
    Error bodies and request details are intentionally excluded from errors.
    """

    def __init__(self, *, timeout: float = 25, interval: float = 0.4,
                 sleep: Callable[[float], None] = time.sleep):
        self.timeout = timeout
        self.interval = interval
        self.sleep = sleep
        self.last_request = 0.0
        self.opener = build_opener(_NoRedirect())

    def get(self, url: str) -> HTTPResponse:
        return self._request(url)

    def post(self, url: str, payload: dict) -> HTTPResponse:
        parsed = urlsplit(url)
        from .taleo import is_taleo_host
        taleo_search = is_taleo_host(parsed.hostname) and parsed.path == "/careersection/rest/jobboard/searchjobs"
        if not ((is_workday_host(parsed.hostname) and parsed.path.endswith("/jobs")) or taleo_search):
            raise FetchError("unsupported", "POST is restricted to public Workday and Taleo listing searches.")
        return self._request(url, payload)

    def _request(self, url: str, payload: dict | None = None) -> HTTPResponse:
        _safe_api_url(url)
        parsed_url = urlsplit(url)
        from .taleo import is_taleo_host
        expect_html = (is_icims_host(parsed_url.hostname) or parsed_url.hostname == "recruiting.paylocity.com"
                       or (is_taleo_host(parsed_url.hostname) and parsed_url.path != "/careersection/rest/jobboard/searchjobs"))
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        for attempt in range(3):
            self.sleep(max(0.0, self.interval - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            request = Request(url, data=body, headers={
                "User-Agent": "JobSearchHelper/1.0 (public job-board inventory; read-only)",
                "Accept": "text/html" if expect_html else "application/json", "Accept-Encoding": "identity",
                **({"Content-Type": "application/json"} if payload is not None else {}),
                **({"tz": "GMT-05:00", "tzname": "America/New_York"}
                   if payload is not None and is_taleo_host(parsed_url.hostname) else {}),
            }, method="POST" if payload is not None else "GET")
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    response_body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(response_body) > MAX_RESPONSE_BYTES:
                        raise FetchError("partial", "API response exceeded the safe size limit.")
                    result = HTTPResponse(response.status, response_body, dict(response.headers))
            except HTTPError as exc:
                # Redirects remain HTTP errors; do not send requests to Location.
                result = HTTPResponse(exc.code, exc.read(8192), dict(exc.headers))
                exc.close()
            except (URLError, TimeoutError, socket.timeout, ConnectionError):
                if attempt == 2:
                    raise FetchError("failed", "Network/timeout failure after bounded retries.") from None
                self.sleep(float(2 ** attempt))
                continue
            if result.status in (401, 403) or _challenge(result, expect_html=expect_html):
                return result
            if result.status in RETRY_STATUSES and attempt < 2:
                self.sleep(_delay(result.headers, attempt))
                continue
            return result
        raise FetchError("failed", "Request did not complete.")


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("p", "li", "div"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)
    # Greenhouse can HTML-encode the markup more than once.
    value = unescape(unescape(value))
    parser = _TextParser()
    parser.feed(value)
    parser.close()  # JSH_AMPERSAND_FIX: flush buffered trailing entity text
    return "\n".join(" ".join(line.split()) for line in "".join(parser.parts).splitlines()
                     if line.strip())


def _join(values: list[Any]) -> str:
    return "\n".join(part for part in (text(v) for v in values) if part)


def _url(value: Any, fallback: str = "") -> str:
    value = str(value or fallback).strip()
    p = urlsplit(value)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise ValueError("Missing or invalid official posting URL.")
    # Posting URLs are output only; the adapter never requests them.
    return value


def resolve_board(ats: str, careers_url: str) -> tuple[str, str, str]:
    """Return (adapter name, board token, API root) without guessing employer slugs."""
    p = urlsplit(careers_url.strip())
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError("Provide a verified official ATS board HTTPS URL.")
    parts = [part for part in p.path.split("/") if part]
    host = p.hostname.lower()
    board = ""
    if host == "recruiting.paylocity.com":
        from .paylocity import resolve_paylocity
        return resolve_paylocity(ats, careers_url)
    from .taleo import is_taleo_host, resolve_taleo
    if is_taleo_host(host):
        return resolve_taleo(ats, careers_url)
    if host == "workforcenow.adp.com":
        from .adp import resolve_adp
        return resolve_adp(ats, careers_url)
    if is_workday_host(host):
        from .workday import resolve_workday
        return resolve_workday(ats, careers_url)
    if is_icims_host(host):
        from .icims import resolve_icims
        return resolve_icims(ats, careers_url)
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        name, root = "Greenhouse", "https://boards-api.greenhouse.io/v1/boards/"
        board = parse_qs(p.query).get("for", [""])[0] if parts[:1] == ["embed"] else (parts[0] if parts else "")
    elif host == "boards-api.greenhouse.io" and parts[:2] == ["v1", "boards"]:
        name, root = "Greenhouse", "https://boards-api.greenhouse.io/v1/boards/"
        board = parts[2] if len(parts) > 2 else ""
    elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        name = "Lever"
        root = "https://api.eu.lever.co/v0/postings/" if host == "jobs.eu.lever.co" else "https://api.lever.co/v0/postings/"
        board = parts[0] if parts else ""
    elif host in {"api.lever.co", "api.eu.lever.co"} and parts[:2] == ["v0", "postings"]:
        name, root = "Lever", f"https://{host}/v0/postings/"
        board = parts[2] if len(parts) > 2 else ""
    elif host == "jobs.ashbyhq.com":
        name, root = "Ashby", "https://api.ashbyhq.com/posting-api/job-board/"
        board = parts[0] if parts else ""
    elif host == "api.ashbyhq.com" and parts[:2] == ["posting-api", "job-board"]:
        name, root = "Ashby", "https://api.ashbyhq.com/posting-api/job-board/"
        board = parts[2] if len(parts) > 2 else ""
    else:
        raise ValueError("Unsupported employer URL: record its verified official ATS board URL; no slug is guessed.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", board):
        raise ValueError("ATS URL has no valid board token.")
    configured = ats.strip().lower()
    recognized = [name for name in ("greenhouse", "lever", "ashby", "workday", "icims", "adp", "paylocity", "taleo") if name in configured]
    if recognized and name.lower() not in recognized:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    return name, board, root


def _json(url: str, transport: Any, payload: dict | None = None) -> Any:
    _safe_api_url(url)
    response = transport.get(url) if payload is None else transport.post(url, payload)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Transport must return HTTPResponse.")
    if reason := _blocked_reason(response):
        raise FetchError("blocked", reason)
    if not 200 <= response.status < 300:
        message = ("Redirect refused; verify the official board URL." if 300 <= response.status < 400
                   else f"HTTP {response.status}; inventory unavailable, not evidence of closure.")
        raise FetchError("failed", message)
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        preview = response.body[:8192].decode("utf-8", "replace").lower()
        if any(marker in preview for marker in ("captcha", "verify you are human", "cf-chl-", "human verification")):
            raise FetchError("blocked", "Human verification detected; manual review required.") from None
        raise FetchError("partial", "API returned non-JSON data; inventory completeness unknown.") from None


def _base(item: dict, name: str, company_id: str, company: str) -> dict:
    public_id = item.get("id")
    if public_id is not None and (not isinstance(public_id, (str, int)) or isinstance(public_id, bool)):
        raise ValueError("Posting ID must be a string or integer.")
    return {"company_id": company_id, "company": company, "ats": name,
            "posting_id": str(public_id or ""), "req_id": "", "url": "",
            "title": "", "location": "", "work_arrangement": "", "compensation": "",
            "description": "", "department": "", "created_at": "", "updated_at": "",
            "is_listed": True}


def _posting(item: Any, name: str, board: str, company_id: str, company: str, root: str) -> dict:
    if not isinstance(item, dict):
        raise ValueError("Posting is not an object.")
    row = _base(item, name, company_id, company)
    if name == "Greenhouse":
        location = item.get("location") or {}
        departments = item.get("departments") or []
        if not isinstance(location, dict) or not isinstance(departments, list):
            raise ValueError("Malformed Greenhouse location/departments.")
        row.update(title=text(item.get("title")), location=text(location.get("name")),
                   req_id=str(item.get("requisition_id") or ""),
                   url=_url(item.get("absolute_url")), description=text(item.get("content")),
                   department=_join([x.get("name", "") for x in departments if isinstance(x, dict)]),
                   created_at=str(item.get("first_published") or ""), updated_at=str(item.get("updated_at") or ""),
                   compensation=text(item.get("pay_input_ranges") or ""))
    elif name == "Lever":
        categories = item.get("categories") or {}
        lists = item.get("lists") or []
        if not isinstance(categories, dict) or not isinstance(lists, list) or any(not isinstance(x, dict) for x in lists):
            raise ValueError("Malformed Lever categories/lists.")
        all_locations = categories.get("allLocations") or []
        if not isinstance(all_locations, list):
            raise ValueError("Malformed Lever locations.")
        locations = list(dict.fromkeys([str(categories.get("location") or ""), *map(str, all_locations)]))
        description_parts = [item.get("descriptionPlain") or item.get("description") or _join([
            item.get("openingPlain") or item.get("opening"), item.get("descriptionBodyPlain") or item.get("descriptionBody")])]
        for section in lists:
            description_parts.extend([section.get("text"), section.get("content")])
        description_parts.append(item.get("additionalPlain") or item.get("additional"))
        row.update(title=text(item.get("text")), location="; ".join(x for x in locations if x),
                   url=_url(item.get("hostedUrl")), work_arrangement=text(item.get("workplaceType")),
                   compensation=_join([item.get("salaryRange") or "", item.get("salaryDescriptionPlain") or item.get("salaryDescription")]),
                   description=_join(description_parts), department=_join([categories.get("department"), categories.get("team")]),
                   created_at=str(item.get("createdAt") or ""), updated_at=str(item.get("updatedAt") or ""))
    else:
        row["url"] = _url(item.get("jobUrl"))
        job_url = urlsplit(row["url"])
        path = [x for x in job_url.path.split("/") if x]
        if not row["posting_id"] and job_url.hostname == "jobs.ashbyhq.com" and len(path) == 2 and path[0] == board:
            row["posting_id"] = path[1]
        secondary = item.get("secondaryLocations") or []
        if not isinstance(secondary, list) or any(not isinstance(x, dict) for x in secondary):
            raise ValueError("Malformed Ashby locations.")
        listed = item.get("isListed", True)
        if not isinstance(listed, bool):
            raise ValueError("Malformed Ashby isListed.")
        row.update(title=text(item.get("title")),
                   location="; ".join(dict.fromkeys(x for x in [text(item.get("location")), *[text(x.get("location")) for x in secondary]] if x)),
                   work_arrangement=text(item.get("workplaceType") or ("Remote" if item.get("isRemote") is True else "")),
                   compensation=text(item.get("compensation") or ""),
                   description=text(item.get("descriptionPlain") or item.get("descriptionHtml")),
                   department=_join([item.get("department"), item.get("team")]),
                   created_at=str(item.get("publishedAt") or ""), updated_at=str(item.get("updatedAt") or ""),
                   is_listed=listed)
    missing = [field for field in ("posting_id", "title", "description") if not row[field]]
    if missing:
        raise ValueError("Missing required normalized fields: " + ", ".join(missing))
    return row


# ATS_DIAGNOSTICS_V1
def _skip_diagnostic(item, provider, page, item_index, exc):
    """Bounded public-source details; never print raw exception payloads."""
    record = item if isinstance(item, dict) else {}
    known_errors = {
        "Posting is not an object.",
        "Posting ID must be a string or integer.",
        "Missing or invalid official posting URL.",
        "Malformed Greenhouse location/departments.",
        "Malformed Lever categories/lists.",
        "Malformed Lever locations.",
        "Malformed Ashby locations.",
        "Malformed Ashby isListed.",
    }
    message = str(exc)
    if message.startswith("Missing required normalized fields: "):
        reason = message
    elif message in known_errors:
        reason = message
    else:
        reason = "Unsupported field shape or parsing error (" + type(exc).__name__ + ")."
    def bounded(value, limit):
        return str(value)[:limit] if isinstance(value, (str, int)) else ""
    return {
        "event": "posting_skipped", "provider": provider,
        "page": page + 1, "item_on_page": item_index + 1,
        "posting_id": bounded(record.get("id"), 160),
        "title": bounded(record.get("text") or record.get("title"), 240),
        "url": bounded(record.get("hostedUrl") or record.get("absolute_url") or record.get("jobUrl"), 800),
        "reason": reason,
        "field_types": {k: type(record[k]).__name__ for k in (
            "id", "text", "title", "hostedUrl", "absolute_url", "jobUrl",
            "descriptionPlain", "description", "descriptionBodyPlain", "descriptionBody",
            "openingPlain", "opening", "lists", "additionalPlain", "additional",
            "categories", "content", "descriptionHtml") if k in record},
    }


def fetch_inventory(ats: str, careers_url: str, company_id: str, company: str,
                    transport: Any = None, *, discovery_transport: Any = None) -> Inventory:
    """Retrieve official board data; a transport with get(url) is injectable.

    Ashby unlisted postings remain present with is_listed=False, preventing
    false disappearance counts; callers must not discover/review those rows.
    """
    discovery_note = ""
    if not isinstance(careers_url, str) or not careers_url.strip():
        return Inventory("unsupported", reason="Missing Official Careers URL; add the employer's careers page or ATS board URL.")
    from .taleo_careers import fetch_scoped_taleo_careers, supports_scoped_taleo_careers
    if supports_scoped_taleo_careers(ats, careers_url):
        from .discovery import CareersTransport
        return fetch_scoped_taleo_careers(
            careers_url, company_id, company, discovery_transport or CareersTransport()
        )
    try:
        name, board, root = resolve_board(ats, careers_url)
    except (ValueError, TypeError) as exc:
        from .discovery import discover_board, public_careers_url
        try:
            page_url = public_careers_url(careers_url)
            # A malformed known board or configuration mismatch is not a
            # reason to fall back to fetching the board's HTML.
            if is_board_host(urlsplit(page_url).hostname):
                return Inventory("unsupported", reason=str(exc), source_url=careers_url)
            (name, board, root), evidence_url = discover_board(ats, page_url, discovery_transport)
            evidence = urlsplit(evidence_url)._replace(query="", fragment="").geturl()
            discovery_note = f"Discovered {name} board {root}{board} from {evidence}. "
        except FetchError as error:
            return Inventory(error.status, reason=error.reason, source_url=careers_url)
        except (OSError, ValueError, TypeError, AttributeError):
            return Inventory("failed", reason="Careers page transport or parsing failed; discovery did not complete.", source_url=careers_url)
    transport = transport or HTTPTransport()
    if name == "Paylocity":
        from .paylocity import fetch_paylocity
        result = fetch_paylocity(board, root, company_id, company, transport)
        result.ats = name
        result.reason = discovery_note + result.reason
        return result
    if name == "Taleo":
        from .taleo import fetch_taleo
        result = fetch_taleo(board, root, company_id, company, transport)
        result.ats = name
        result.reason = discovery_note + result.reason
        return result
    if name == "ADP":
        from .adp import fetch_adp
        result = fetch_adp(board, root, company_id, company, transport)
        result.ats = name
        result.reason = discovery_note + result.reason
        return result
    if name == "iCIMS":
        from .icims import fetch_icims
        result = fetch_icims(board, root, company_id, company, transport)
        result.ats = name
        result.reason = discovery_note + result.reason
        return result
    if name == "Workday":
        from .workday import fetch_workday
        result = fetch_workday(board, root, company_id, company, transport)
        result.ats = name
        result.reason = discovery_note + result.reason
        return result
    jobs: list[dict] = []
    seen: set[str] = set()
    issues: list[str] = []
    skipped = 0
    source_url = root + board
    if name == "Greenhouse":
        source_url += "/jobs?content=true"
    elif name == "Ashby":
        source_url += "?includeCompensation=true"
    try:
        for page in range(MAX_PAGES if name == "Lever" else 1):
            url = source_url
            if name == "Lever":
                url += "?" + urlencode({"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE})
            data = _json(url, transport)
            if name == "Lever":
                entries = data
            elif isinstance(data, dict) and isinstance(data.get("jobs"), list):
                entries = data["jobs"]
            else:
                raise FetchError("partial", "Unexpected inventory schema; no complete inventory established.")
            if not isinstance(entries, list):
                raise FetchError("partial", "Expected an array of postings.")
            if name == "Greenhouse":
                total = (data.get("meta") or {}).get("total") if isinstance(data.get("meta"), dict) else None
                if not isinstance(total, int) or isinstance(total, bool) or total != len(entries):
                    issues.append("Greenhouse meta.total missing or inconsistent with inventory size.")
            if name == "Lever" and len(entries) > PAGE_SIZE:
                raise FetchError("partial", "Lever returned more records than requested; pagination is untrusted.")
            if name == "Lever" and not entries:
                break
            duplicate = False
            for item_index, item in enumerate(entries):
                try:
                    row = _posting(item, name, board, company_id, company, root)
                except (ValueError, TypeError, AttributeError) as exc:
                    skipped += 1
                    if skipped <= 50:
                        print(json.dumps(_skip_diagnostic(item, name, page, item_index, exc), ensure_ascii=True), file=sys.stderr)
                    issues.append("One or more malformed/incomplete postings were skipped.")
                    continue
                key = row["posting_id"]
                if key in seen:
                    duplicate = True
                    issues.append("Duplicate posting IDs or repeated pagination detected.")
                    continue
                seen.add(key)
                jobs.append(row)
            if name == "Lever":
                if duplicate:
                    break
                # Continue until an empty page: also detects a server silently
                # capping the page below the requested limit.
                if len(entries) < PAGE_SIZE:
                    # With an explicit limit, a short page normally terminates.
                    # Request once more using its ACTUAL size to verify no tail
                    # was silently omitted. The loop offset would otherwise skip.
                    next_url = source_url + "?" + urlencode({"mode": "json", "skip": page * PAGE_SIZE + len(entries), "limit": PAGE_SIZE})
                    tail = _json(next_url, transport)
                    if not isinstance(tail, list) or tail:
                        issues.append("Lever short page did not terminate at an empty follow-up page; inventory is partial.")
                    break
                if page == MAX_PAGES - 1:
                    issues.append("Lever page cap reached before a confirmed inventory end.")
        status = "partial" if issues else "complete"
        reason = discovery_note + " ".join(dict.fromkeys(issues))
        if skipped:
            reason += f" Skipped postings: {skipped}; diagnostic details printed for the first {min(skipped, 50)}."
        return Inventory(status, jobs, reason.strip(), source_url, ats=name)
    except FetchError as exc:
        status = "blocked" if exc.status == "blocked" else ("partial" if jobs else exc.status)
        reason = discovery_note + exc.reason + (f" Skipped postings before failure: {skipped}." if skipped else "")
        return Inventory(status, jobs, reason, source_url, ats=name)
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs,
                         discovery_note + "Unexpected transport or schema failure; inventory not complete.", source_url, ats=name)
