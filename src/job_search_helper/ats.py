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
from http.client import HTTPException
import json
import re
import socket
import sys
import threading
import time
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_HOSTS = frozenset({
    "boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com",
    "l87m8knomj-dsn.algolia.net", "fs-4627.my.salesforce-sites.com", "myjobs.adp.com", "my.adp.com",
    "jobsatseptentrio.hire.trakstar.com",
})
# This Oracle tenant returns 406 when the public JSON endpoints receive an
# explicit JSON media type.  Its own public board works with wildcard content
# negotiation; keep the exception pinned to this verified tenant.
ORACLE_WILDCARD_ACCEPT_HOSTS = frozenset({
    "fa-eqzh-saasfaprod1.fa.ocs.oraclecloud.com",
})
BOARD_HOSTS = API_HOSTS | frozenset({
    "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co",
    "jobs.eu.lever.co", "jobs.ashbyhq.com", "workforcenow.adp.com", "recruiting.paylocity.com",
})
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
# Greenhouse publishes the entire board with full descriptions in one response.
MAX_GREENHOUSE_BOARD_BYTES = 64 * 1024 * 1024
PAGE_SIZE = 100
MAX_PAGES = 200
RETRY_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def is_workday_host(host: str | None) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.wd[0-9]+\.myworkdayjobs\.com", host or ""))


def is_icims_host(host: str | None) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.icims\.com", host or ""))


def is_oracle_host(host: str | None) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.fa\.(?:us[0-9]+|ocs)\.oraclecloud\.com", host or ""))


def is_board_host(host: str | None) -> bool:
    from .shared_boards import known_host
    if known_host(host):
        return True
    from .ukg import is_ukg_host
    if is_ukg_host(host):
        return True
    from .bamboohr import is_bamboohr_host
    if is_bamboohr_host(host):
        return True
    if host == "www.paycomonline.net" or host in BOARD_HOSTS or is_workday_host(host) or is_icims_host(host):
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
    browser_pending_urls: list[str] = field(default_factory=list)
    browser_discovery_incomplete: bool = False


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
    if parsed.hostname in {"workforcenow.adp.com", "workforcenow.cloud.adp.com"}:
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
    from .bamboohr import is_bamboohr_host, safe_api_path as bamboohr_safe_api_path
    bamboohr = is_bamboohr_host(parsed.hostname) and bamboohr_safe_api_path(parsed)
    from .ukg import is_ukg_host, safe_api_path as ukg_safe_api_path
    ukg = is_ukg_host(parsed.hostname) and ukg_safe_api_path(parsed)
    ublox_algolia = (parsed.hostname == "l87m8knomj-dsn.algolia.net"
                     and parsed.path == "/1/indexes/open_positions_en-US/query")
    ublox_detail = (parsed.hostname == "fs-4627.my.salesforce-sites.com"
                    and parsed.path == "/recruit/fRecruit__ApplyJob")
    adp_myjobs_config = (parsed.hostname == "myjobs.adp.com"
                         and bool(re.fullmatch(r"/public/staffing/v1/career-site/[a-z0-9-]+", parsed.path)))
    adp_myjobs_listing = (parsed.hostname == "my.adp.com"
                          and parsed.path == "/myadp_prefix/mycareer/public/staffing/v1/job-requisitions/apply-custom-filters")
    adp_myjobs_detail = (parsed.hostname == "my.adp.com"
                         and bool(re.fullmatch(r"/myadp_prefix/mycareer/public/staffing/v1/job-requisitions/search-meta/[0-9A-Za-z_-]+", parsed.path)))
    panasonic = (parsed.hostname == "careers.na.panasonic.com"
                 and parsed.path == "/api/jobs"
                 and set(parse_qs(parsed.query)) == {"page", "limit", "tags3"}
                 and len(parse_qs(parsed.query).get("page", [])) == 1
                 and len(parse_qs(parsed.query).get("limit", [])) == 1
                 and parse_qs(parsed.query).get("limit") == ["100"]
                 and parse_qs(parsed.query).get("page", [""])[0].isdigit()
                 and parse_qs(parsed.query).get("tags3", [""])[0] in {
                     "PCONA Panasonic Connect North America",
                     "PSG Panasonic Connect North America Professional Services",
                 })
    oracle = (is_oracle_host(parsed.hostname) and parsed.path in {
        "/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
        "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
    })
    wordpress_careers = ((parsed.hostname in {"greenseaiq.com", "searobotics.com", "airspan.com", "xtend.me"}
                          and parsed.path == "/wp-json/wp/v2/career"
                          and parse_qs(parsed.query) == {"per_page": ["100"], "page": [parsed.query.split("page=")[-1]]}
                          and parsed.query.startswith("per_page=100&page=")
                          and parsed.query[len("per_page=100&page="):].isdigit())
                         or (parsed.hostname == "airspan.com"
                             and parsed.path == "/wp-json/wp/v2/jobs"
                             and parse_qs(parsed.query) == {"per_page": ["100"], "page": [parsed.query.split("page=")[-1]]}
                             and parsed.query.startswith("per_page=100&page=")
                             and parsed.query[len("per_page=100&page="):].isdigit())
                         or (parsed.hostname == "www.jaia.tech"
                             and parsed.path == "/wp-json/wp/v2/posts"
                             and parse_qs(parsed.query) == {"categories": ["23"], "per_page": ["100"], "page": [parsed.query.split("page=")[-1]]}
                             and parsed.query.startswith("categories=23&per_page=100&page=")
                             and parsed.query[len("categories=23&per_page=100&page="):].isdigit()))
    xtend_detail = (parsed.hostname == "xtend.me" and parsed.path.startswith("/careers/") and not parsed.query and not parsed.fragment)
    psi_search = (parsed.hostname == "www.psicorp.com" and parsed.path == "/wp-admin/admin-ajax.php" and not parsed.query)
    kratos_search = (parsed.hostname == "apps3.pereless.com" and parsed.path == "/templates/magnetolive/api/" and parsed.query == "action=getJobs")
    trakstar_rss = (parsed.hostname == "jobsatseptentrio.hire.trakstar.com" and parsed.path == "/jobfeeds/jobsatSeptentrio" and not parsed.query)
    dayforce = (parsed.hostname == "jobs.dayforcehcm.com" and parsed.path in {"/api/geo/esa/jobposting/search", "/api/geo/multitech/jobposting/search"} and not parsed.query)
    kontron_query = parse_qs(parsed.query, keep_blank_values=True)
    kontron_api = (parsed.hostname == "www.kontron.com" and not parsed.fragment and (
        (parsed.path == "/api/cms/softgarden/jobs" and kontron_query == {"locale": ["en"]})
        or (parsed.path in {"/api/cms/softgarden/channels", "/api/paylocity/jobs"} and not parsed.query)
    ))
    kuka_api = (parsed.hostname == "www.kuka.com" and parsed.path == "/en-us/api/job/getjobs"
                and set(parse_qs(parsed.query)) == {"searchrootpath", "filters"}
                and parse_qs(parsed.query).get("searchrootpath") == ["DCB6206EA76F4CCFAAC81F77D8E1FFC2"]
                and parse_qs(parsed.query).get("filters") == ["BE72163E70594C11A60DAB1ADA205839|FC4F967286724664972D3368B99637F3"])
    digitalrecruiters = False
    if parsed.hostname == "api.digitalrecruiters.com":
        from .digitalrecruiters import safe_api_path
        digitalrecruiters = safe_api_path(parsed)
    from .hibob import safe_api_path as hibob_safe_api_path
    hibob = hibob_safe_api_path(parsed)
    # Breezy publishes its employer-scoped inventory at /json and full public
    # descriptions as HTML under /p/<12-char-id>-<slug>.  These are pinned by
    # the board host and are safe to fetch through the normal transport.
    breezy = (bool(re.fullmatch(r"[a-z0-9-]+\.breezy\.hr", parsed.hostname or ""))
              and (parsed.path in {"/", "/json"}
                   or bool(re.fullmatch(r"/p/[a-f0-9]{12}-[A-Za-z0-9-]+", parsed.path)))
              and not parsed.query and not parsed.fragment)
    shopify = (parsed.hostname == "onestopsystems.com"
               and bool(re.fullmatch(r"/pages/[a-z0-9-]+", parsed.path))
               and not parsed.query and not parsed.fragment)
    hrsmart = (parsed.hostname == "telos.hua.hrsmart.com"
               and (parsed.path in {"/hr/ats/JobSearch/index", "/hr/ats/JobSearch/viewAll",
                                   "/hr/ats/JobSearch/viewAll/jobSearchPaginationExternal_pageSize:100/jobSearchPaginationExternal_page:1"}
                    or bool(re.fullmatch(r"/hr/ats/Posting/view/[0-9]+", parsed.path)))
               and not parsed.query and not parsed.fragment)
    radd = (parsed.hostname == "radd-co.com" and (parsed.path == "/sitemap.xml" or bool(re.fullmatch(r"/open-roles/[A-Za-z0-9-]+", parsed.path))) and not parsed.query and not parsed.fragment)
    exyn = parsed.hostname == "www.exyn.com" and parsed.path == "/about/careers" and not parsed.query and not parsed.fragment
    if (parsed.scheme != "https" or (parsed.hostname not in API_HOSTS and not workday and not icims and not adp and not paylocity and not taleo and not bamboohr and not ukg and not oracle and not wordpress_careers and not xtend_detail and not psi_search and not kratos_search and not panasonic and not trakstar_rss and not breezy and not shopify and not dayforce and not digitalrecruiters and not hibob and not kontron_api and not kuka_api and not hrsmart and not radd and not exyn)
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise FetchError("unsupported", "Only pinned official HTTPS API endpoints are allowed.")
    if parsed.hostname in {"l87m8knomj-dsn.algolia.net", "fs-4627.my.salesforce-sites.com"} and not (ublox_algolia or ublox_detail):
        raise FetchError("unsupported", "Only the verified public u-blox job endpoints are allowed.")
    if parsed.hostname in {"myjobs.adp.com", "my.adp.com"} and not (adp_myjobs_config or adp_myjobs_listing or adp_myjobs_detail):
        raise FetchError("unsupported", "Only the verified public ADP MyJobs endpoints are allowed.")


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
    if any(marker in preview for marker in markers):
        return True
    # AWS WAF may return a 2xx HTML interstitial rather than a 403.  Its
    # browser-only challenge must not be mistaken for an empty job board.
    headers = {str(key).lower(): str(value).lower() for key, value in response.headers.items()}
    return expect_html and ("awswafcookiedomainlist" in preview
                            or "x-amzn-waf-action" in headers)


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
        # Detail validation may use a bounded worker pool.  Serialize only the
        # shared rate-limit clock; network I/O remains concurrent.
        self._rate_lock = threading.Lock()
        self.opener = build_opener(_NoRedirect())

    def get(self, url: str) -> HTTPResponse:
        return self._request(url)

    def get_with_headers(self, url: str, headers: Mapping[str, str]) -> HTTPResponse:
        """GET a pinned public endpoint with transient browser-flow headers."""
        return self._request(url, headers=headers)

    def post(self, url: str, payload: dict, headers: Mapping[str, str] | None = None) -> HTTPResponse:
        parsed = urlsplit(url)
        from .taleo import is_taleo_host
        taleo_search = is_taleo_host(parsed.hostname) and parsed.path == "/careersection/rest/jobboard/searchjobs"
        from .ukg import is_ukg_host, safe_api_path as ukg_safe_api_path, SEARCH as UKG_SEARCH
        ukg_search = is_ukg_host(parsed.hostname) and ukg_safe_api_path(parsed) and parsed.path.endswith(UKG_SEARCH)
        ublox_search = (parsed.hostname == "l87m8knomj-dsn.algolia.net"
                        and parsed.path == "/1/indexes/open_positions_en-US/query")
        kratos_search = (parsed.hostname == "apps3.pereless.com"
                         and parsed.path == "/templates/magnetolive/api/"
                         and parsed.query == "action=getJobs"
                         and headers == {"cid": "85347"})
        dayforce_search = (parsed.hostname == "jobs.dayforcehcm.com"
                           and parsed.path in {"/api/geo/esa/jobposting/search", "/api/geo/multitech/jobposting/search"}
                           and not parsed.query)
        digitalrecruiters_search = False
        if parsed.hostname == "api.digitalrecruiters.com":
            from .digitalrecruiters import safe_api_path, API_PATH as DIGITALRECRUITERS_PATH
            digitalrecruiters_search = (safe_api_path(parsed) and parsed.path == DIGITALRECRUITERS_PATH
                                        and payload == {"filters": {}} and not headers)
        if not ((is_workday_host(parsed.hostname) and parsed.path.endswith("/jobs")) or taleo_search or ukg_search or ublox_search or kratos_search or dayforce_search or digitalrecruiters_search):
            raise FetchError("unsupported", "POST is restricted to verified public job listing searches.")
        return self._request(url, payload, headers=headers)

    def post_form(self, url: str, payload: dict) -> HTTPResponse:
        """Submit the one pinned public PSI listing form, without cookies."""
        parsed = urlsplit(url)
        if (parsed.hostname != "www.psicorp.com" or parsed.path != "/wp-admin/admin-ajax.php"
                or parsed.query or set(payload) != {"action", "paged"}
                or payload.get("action") != "job_positions_search"
                or not isinstance(payload.get("paged"), int) or not 1 <= payload["paged"] <= 100):
            raise FetchError("unsupported", "Form POST is restricted to the verified PSI public job search.")
        return self._request(url, payload, form=True)

    def _request(self, url: str, payload: dict | None = None, headers: Mapping[str, str] | None = None,
                 form: bool = False) -> HTTPResponse:
        _safe_api_url(url)
        parsed_url = urlsplit(url)
        from .hibob import HOST as HIBOB_HOST, HEADERS as HIBOB_HEADERS
        if parsed_url.hostname == HIBOB_HOST and (payload is not None or headers != HIBOB_HEADERS):
            raise FetchError('unsupported', 'HiBob permits only the verified anonymous company routing header and public GET endpoints.')
        from .taleo import is_taleo_host
        from .ukg import is_ukg_host, SEARCH as UKG_SEARCH
        expect_html = ((is_ukg_host(parsed_url.hostname) and not parsed_url.path.endswith(UKG_SEARCH)) or is_icims_host(parsed_url.hostname) or parsed_url.hostname == "recruiting.paylocity.com"
                       or (parsed_url.hostname or "").endswith(".breezy.hr")
                       or (is_taleo_host(parsed_url.hostname) and parsed_url.path != "/careersection/rest/jobboard/searchjobs"))
        response_limit = (MAX_GREENHOUSE_BOARD_BYTES if payload is None
                          and parsed_url.hostname == "boards-api.greenhouse.io"
                          and re.fullmatch(r"/v1/boards/[A-Za-z0-9_-]+/jobs", parsed_url.path)
                          and parsed_url.query == "content=true" else MAX_RESPONSE_BYTES)
        body = (urlencode(payload).encode("utf-8") if form else json.dumps(payload).encode("utf-8")) if payload is not None else None
        for attempt in range(3):
            with self._rate_lock:
                self.sleep(max(0.0, self.interval - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
            accept = "*/*" if parsed_url.hostname in ORACLE_WILDCARD_ACCEPT_HOSTS else ("text/html" if expect_html else "application/json")
            request = Request(url, data=body, headers={
                "User-Agent": "JobSearchHelper/1.0 (public job-board inventory; read-only)",
                "Accept": accept, "Accept-Encoding": "identity",
                **({"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"} if payload is not None else {}),
                **({"X-Algolia-Application-Id": "L87M8KNOMJ", "X-Algolia-API-Key": "b5a0aca646f3378b36d8758634d16954"}
                   if parsed_url.hostname == "l87m8knomj-dsn.algolia.net" else {}),
                **({"tz": "GMT-05:00", "tzname": "America/New_York"}
                   if payload is not None and is_taleo_host(parsed_url.hostname) else {}),
                **(dict(headers or {})),
            }, method="POST" if payload is not None else "GET")
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    response_body = response.read(response_limit + 1)
                    if len(response_body) > response_limit:
                        raise FetchError("partial", "API response exceeded the safe size limit.")
                    result = HTTPResponse(response.status, response_body, dict(response.headers))
            except HTTPError as exc:
                # Redirects remain HTTP errors; do not send requests to Location.
                try:
                    error_body = exc.read(8192)
                except (HTTPException, OSError):
                    error_body = b""
                finally:
                    exc.close()
                result = HTTPResponse(exc.code, error_body, dict(exc.headers))
            except (URLError, TimeoutError, socket.timeout, ConnectionError, HTTPException):
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


def has_lever_scope(careers_url: str) -> bool:
    """Identify Lever filters which generic browser scraping cannot verify."""
    try:
        p = urlsplit(careers_url)
        if (p.hostname or "").lower() not in {"jobs.lever.co", "jobs.eu.lever.co", "api.lever.co", "api.eu.lever.co"}:
            return False
        scoped = {"location", "team", "department", "commitment", "workplacetype", "level"}
        return any(key.casefold() in scoped for key in parse_qs(p.query, keep_blank_values=True))
    except (ValueError, TypeError, AttributeError):
        return False


def lever_location_scope(careers_url: str) -> str:
    """Accept one exact location; reject filters that this adapter cannot verify."""
    p = urlsplit(careers_url)
    if (p.hostname or "").lower() not in {"jobs.lever.co", "jobs.eu.lever.co", "api.lever.co", "api.eu.lever.co"}:
        return ""
    query = parse_qs(p.query, keep_blank_values=True)
    for key, values in query.items():
        if key.casefold() in {"team", "department", "commitment", "workplacetype", "level"} and any(v.strip() for v in values):
            raise ValueError("Lever filter is not supported; verify the board scope.")
    locations = [value.strip() for key, values in query.items() if key.casefold() == "location" for value in values]
    if locations and (len(locations) != 1 or not locations[0] or len(locations[0]) > 256 or any(ord(c) < 32 for c in locations[0])):
        raise ValueError("Lever location filter must contain one valid location.")
    return locations[0] if locations else ""


def resolve_board(ats: str, careers_url: str) -> tuple[str, str, str]:
    """Return (adapter name, board token, API root) without guessing employer slugs."""
    p = urlsplit(careers_url.strip())
    if (p.scheme != "https" or not p.hostname or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError("Provide a verified official ATS board HTTPS URL.")
    parts = [unquote(part) for part in p.path.split("/") if part]
    host = p.hostname.lower()
    board = ""
    lever_location_scope(careers_url)
    if host == "jobsatseptentrio.hire.trakstar.com" and parts in ([], ["jobs"]) and not p.query and not p.fragment:
        configured = ats.strip().lower()
        if configured and "trakstar" not in configured:
            raise ValueError("ATS / Source disagrees with the verified Trakstar Hire URL.")
        return "Trakstar Hire", "jobsatSeptentrio", "https://jobsatseptentrio.hire.trakstar.com/jobfeeds/"
    from .shared_boards import known_host, resolve_shared
    if known_host(host):
        return resolve_shared(ats, careers_url)
    from .ukg import is_ukg_host, resolve_ukg
    if is_ukg_host(host):
        return resolve_ukg(ats, careers_url)
    if host == "www.paycomonline.net":
        from .paycom import resolve_paycom
        return resolve_paycom(ats, careers_url)
    from .bamboohr import is_bamboohr_host, resolve_bamboohr
    if is_bamboohr_host(host):
        return resolve_bamboohr(ats, careers_url)
    if host == "recruiting.paylocity.com":
        from .paylocity import resolve_paylocity
        return resolve_paylocity(ats, careers_url)
    from .taleo import is_taleo_host, resolve_taleo
    if is_taleo_host(host):
        return resolve_taleo(ats, careers_url)
    if host in {"workforcenow.adp.com", "workforcenow.cloud.adp.com"}:
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
    valid_board = (r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"
                   if name != "Ashby" else r"[A-Za-z0-9][A-Za-z0-9 _.\-]{0,127}")
    if not re.fullmatch(valid_board, board):
        raise ValueError("ATS URL has no valid board token.")
    configured = ats.strip().lower()
    recognized = [name for name in ("greenhouse", "lever", "ashby", "workday", "icims", "adp", "paylocity", "taleo", "bamboohr") if name in configured]
    if recognized and name.lower() not in recognized:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    return name, board, root


def _json(url: str, transport: Any, payload: dict | None = None) -> Any:
    _safe_api_url(url)
    response = transport.get(url) if payload is None else transport.post(url, payload)
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Transport must return HTTPResponse.")
    if _challenge(response):
        raise FetchError("blocked", "Human verification detected; manual review required.")
    if response.status in (401, 403):
        raise FetchError("blocked", f"HTTP {response.status}: access denied; manual review, no automatic retry.")
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
        job_url = _url(item.get("absolute_url"))
        # Iron Bow's public module serves Greenhouse metadata with a stale
        # HubSpot sandbox host.  The observed corporate module publishes the
        # same gh_jid under ironbow.com/job-details; canonicalize only this
        # exact board/company/ID shape to preserve existing history URLs.
        if company_id == "COMP-0315" and company.casefold() == "iron bow technologies" and board == "ironbowtechnologies":
            parsed_job = urlsplit(job_url)
            query = parse_qs(parsed_job.query, keep_blank_values=True)
            if (parsed_job.hostname == "ironbow-com.sandbox.hs-sites.com"
                    and parsed_job.path == "/job-details"):
                jid = query.get("gh_jid", [""])[0]
                if (parsed_job.scheme != "https" or parsed_job.username or parsed_job.password
                        or parsed_job.port not in (None, 443) or parsed_job.fragment
                        or set(query) != {"gh_jid"} or len(query["gh_jid"]) != 1
                        or not jid.isascii() or not jid.isdigit() or int(jid) <= 0
                        or str(item.get("id")) != jid):
                    raise ValueError("Malformed Iron Bow Greenhouse sandbox job URL.")
                job_url = "https://ironbow.com/job-details?gh_jid=" + query["gh_jid"][0]
            elif parsed_job.hostname == "ironbow.com" and parsed_job.path == "/job-details":
                jid = query.get("gh_jid", [""])[0]
                if (parsed_job.scheme != "https" or parsed_job.username or parsed_job.password
                        or parsed_job.port not in (None, 443) or parsed_job.fragment
                        or set(query) != {"gh_jid"} or len(query["gh_jid"]) != 1
                        or not jid.isascii() or not jid.isdigit() or int(jid) <= 0
                        or str(item.get("id")) != jid):
                    raise ValueError("Malformed Iron Bow Greenhouse corporate job URL.")
        row.update(title=text(item.get("title")), location=text(location.get("name")),
                   req_id=str(item.get("requisition_id") or ""),
                   url=job_url, description=text(item.get("content")),
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
        path = [unquote(x) for x in job_url.path.split("/") if x]
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
                    transport: Any = None, *, discovery_transport: Any = None, progress_factory=None) -> Inventory:
    from .company_sources import repair_source
    ats, careers_url, note = repair_source(ats, careers_url, company_id, company)
    result = _fetch_inventory(ats, careers_url, company_id, company, transport,
                              discovery_transport=discovery_transport, progress_factory=progress_factory)
    if note:
        result.reason = note + result.reason
    return result


def _fetch_inventory(ats: str, careers_url: str, company_id: str, company: str,
                    transport: Any = None, *, discovery_transport: Any = None, progress_factory=None) -> Inventory:
    """Retrieve official board data using an injectable public-source transport.

    Validate the source before company-specific dispatch so a missing URL
    produces an actionable inventory result instead of an attribute error.
    Ashby unlisted postings remain present with is_listed=False, preventing
    false disappearance counts; callers must not discover/review those rows.
    """
    if not isinstance(careers_url, str) or not careers_url.strip():
        return Inventory(
            "unsupported",
            reason="Missing Official Careers URL; add the employer's careers page or ATS board URL.",
        )

    # These first-party HTML adapters precede generic ATS discovery. Keep the
    # caller's HTML transport when supplied, including for fixture replays.
    html_transport = discovery_transport if discovery_transport is not None else transport
    if careers_url.rstrip("/") == "https://www.kuka.com/en-us/company/careers":
        from .kuka import fetch_kuka
        return fetch_kuka(careers_url, company_id, company, html_transport)
    if careers_url.rstrip("/") == "https://grexdefense.com/careers":
        from .grex_defense import fetch_grex_defense
        return fetch_grex_defense(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0424" and company.casefold() == "wolf advanced technology":
        from .wolf import fetch_wolf
        return fetch_wolf(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0448" and company.casefold() == "hx5":
        from .hx5 import fetch_hx5
        return fetch_hx5(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0428" and company.casefold() == "aitech systems":
        from .aitech import fetch_aitech
        return fetch_aitech(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0427" and company.casefold() == "annapolis micro systems":
        from .annapolis_micro import fetch_annapolis_micro
        return fetch_annapolis_micro(careers_url, company_id, company, html_transport)
    if careers_url == "https://www.haivision.com/about/careers/":
        from .haivision import fetch_haivision
        return fetch_haivision(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0166" and company.casefold() == "black river systems company":
        from .black_river import fetch_black_river
        return fetch_black_river(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0171" and company.casefold() == "freefly systems":
        from .freefly import fetch_freefly
        return fetch_freefly(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0183" and company.casefold() == "anra technologies":
        from .anra import fetch_anra
        return fetch_anra(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0362" and company.casefold() == "atlas space operations":
        from .atlas_space import fetch_atlas_space
        return fetch_atlas_space(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0430" and company.casefold() == "cp technologies":
        from .cp_technologies import fetch_cp_technologies
        return fetch_cp_technologies(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0227" and company.casefold() == "foretellix":
        from .foretellix import fetch_foretellix
        return fetch_foretellix(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0277" and company.casefold() == "losant":
        from .losant import fetch_losant
        return fetch_losant(careers_url, company_id, company, html_transport)
    if company_id == "COMP-0194" and company.casefold() == "parallel flight technologies":
        from .parallel_flight import fetch_parallel_flight
        return fetch_parallel_flight(careers_url, company_id, company, html_transport)

    discovery_note = ""
    if company_id == "COMP-0287" and company.casefold() == "one stop systems":
        from .shopify_jobs import fetch_shopify_jobs
        return fetch_shopify_jobs(careers_url, company_id, company, discovery_transport or transport or HTTPTransport())
    if company_id == "COMP-0262" and company.casefold() == "kvh industries":
        from .kvh import fetch_kvh
        return fetch_kvh(careers_url, company_id, company, discovery_transport or transport or HTTPTransport())
    if company_id == "COMP-0296" or company.casefold() == "panasonic connect":
        from .panasonic import fetch_panasonic
        return fetch_panasonic(company_id, company, transport or HTTPTransport())
    from .taleo_tbe import fetch_tbe, supports_tbe
    if supports_tbe(careers_url):
        from .taleo_tbe import TaleoTbeTransport
        candidate = transport
        if candidate is None or isinstance(candidate, HTTPTransport):
            candidate = TaleoTbeTransport()
        return fetch_tbe(careers_url, company_id, company, candidate)
    from .brightmove import fetch_brightmove, supports_brightmove
    if supports_brightmove(careers_url):
        from .brightmove import BrightMoveTransport
        candidate = transport
        if candidate is None or isinstance(candidate, HTTPTransport):
            candidate = BrightMoveTransport()
        return fetch_brightmove(careers_url, company_id, company, candidate)
    from .amentum import supports_amentum
    if careers_url == 'https://primertechnology.careers.hibob.com/':
        from .hibob import fetch_hibob
        return fetch_hibob(careers_url, company_id, company, transport)
    if supports_amentum(ats, careers_url):
        from .amentum import fetch_amentum
        return fetch_amentum(careers_url, company_id, company, transport)
    if ats.casefold() == 'gdms careers' or careers_url == 'https://gdmissionsystems.com/careers/job-search':
        from .gdms import fetch_gdms
        return fetch_gdms(careers_url, company_id, company, transport)
    if ats.casefold() == 'psi careers' or careers_url == 'https://www.psicorp.com/careers/open-positions/':
        from .psi import fetch_psi
        return fetch_psi(careers_url, company_id, company, transport, discovery_transport)
    if ats.casefold() == 'kratos careers' or careers_url == 'https://kratosdefense.submit4jobs.com/':
        from .kratos import fetch_kratos
        return fetch_kratos(careers_url, company_id, company, transport)
    if ats.casefold() == 'sempre careers' or careers_url == 'https://sempre.ai/careers':
        from .sempre import fetch_sempre
        return fetch_sempre(careers_url, company_id, company, discovery_transport or transport)
    if ats.casefold() == 'blacktree careers' or careers_url == 'https://blacktree.com.au/careers/':
        from .blacktree import fetch_blacktree
        return fetch_blacktree(careers_url, company_id, company, discovery_transport or transport)
    if careers_url in {'https://www.hughes.com/careers','https://www.hughes.com/careers/','https://www.hughes.com/who-we-are/life-at-hughes-echostar'}:
        from .hughes import fetch_hughes
        return fetch_hughes(careers_url, company_id, company, transport or HTTPTransport())
    if careers_url in {'https://jobs.kbr.com/', 'https://jobs.kbr.com/jobs.html'}:
        from .kbr import fetch_kbr, SOURCE
        return fetch_kbr(SOURCE, company_id, company, discovery_transport, transport)
    if careers_url == 'https://careers.wabtec.com/jobs':
        from .attrax import fetch_attrax
        return fetch_attrax(careers_url, company_id, company, discovery_transport or transport)
    if careers_url == 'https://jobs.exail.com/en/annonces':
        from .digitalrecruiters import fetch_digitalrecruiters
        return fetch_digitalrecruiters(careers_url, company_id, company, discovery_transport or transport)
    if company_id == "COMP-0289" and company.casefold() == "kontron":
        from .kontron import fetch_kontron
        return fetch_kontron(careers_url, company_id, company, transport or HTTPTransport())
    if company_id == "COMP-0308" and company.casefold() == "telos corporation":
        from .telos import fetch_telos
        return fetch_telos(careers_url, company_id, company, transport or HTTPTransport())
    if company_id == "COMP-0336" and company.casefold() == "advanced simulation technology inc. (asti)":
        from .asti import fetch_asti
        return fetch_asti(careers_url, company_id, company, discovery_transport or transport or HTTPTransport())
    if company_id == "COMP-0344" and company.casefold() == "mass virtual":
        from .massvirtual import fetch_massvirtual
        return fetch_massvirtual(careers_url, company_id, company, discovery_transport or transport or HTTPTransport())
    if company_id == "COMP-0328" and company.casefold() == "exyn technologies":
        from .exyn import fetch_exyn
        return fetch_exyn(careers_url, company_id, company, discovery_transport or transport or HTTPTransport())
    if company_id == "COMP-0325" and company.casefold() == "radd":
        from .radd import fetch_radd
        return fetch_radd(careers_url, company_id, company, discovery_transport or transport or HTTPTransport())
    if company_id == "COMP-0258" and company.casefold() == "vectornav technologies":
        from .vectornav import fetch_vectornav
        return fetch_vectornav(careers_url, company_id, company, transport or HTTPTransport())
    if company_id == "COMP-0250" and company.casefold() == "jr automation":
        from .jr_automation import fetch_jr_automation
        return fetch_jr_automation(careers_url, company_id, company, discovery_transport or transport)
    if careers_url == 'https://theapplicantmanager.com/careers?co=e1':
        from .applicant_manager import ApplicantManagerTransport, fetch_applicant_manager
        candidate = discovery_transport or transport
        if candidate is None or isinstance(candidate, HTTPTransport):
            candidate = ApplicantManagerTransport()
        return fetch_applicant_manager(careers_url, company_id, company, candidate)
    from .dayforce import fetch_dayforce, supports_dayforce
    if supports_dayforce(ats, careers_url):
        from .dayforce import SOURCE as DAYFORCE_ESA_SOURCE, DayforceSession
        candidate = transport
        if candidate is None:
            candidate = DayforceSession(careers_url) if careers_url == DAYFORCE_ESA_SOURCE else HTTPTransport()
        return fetch_dayforce(ats, careers_url, company_id, company, candidate)
    if careers_url in {'https://www.ycombinator.com/companies/surtr-defense-systems/jobs', 'https://www.ycombinator.com/companies/polymath-robotics/jobs'}:
        from .ycombinator import fetch_ycombinator
        return fetch_ycombinator(careers_url, company_id, company, discovery_transport or transport)
    if careers_url == 'https://app.trinethire.com/companies/32235-uhnder-inc/jobs':
        from .trinet import fetch_trinet
        return fetch_trinet(careers_url, company_id, company, discovery_transport or transport)
    if careers_url == 'https://mobilicom.com/careers/':
        from .mobilicom import fetch_mobilicom
        return fetch_mobilicom(careers_url, company_id, company, discovery_transport or transport)
    if careers_url in {'https://greenseaiq.com/careers/', 'https://searobotics.com/careers/', 'https://www.jaia.tech/careers/', 'https://airspan.com/careers/airspan-careers/', 'https://xtend.me/careers/'}:
        from .wordpress_jobs import fetch_wordpress_careers
        return fetch_wordpress_careers(careers_url, company_id, company, discovery_transport)
    if careers_url == 'https://martacsystems.com/careers/':
        from .martac import fetch_martac
        return fetch_martac(careers_url, company_id, company, discovery_transport)
    if careers_url == 'https://www.comrod.com/about/careers/':
        from .comrod import fetch_comrod
        return fetch_comrod(careers_url, company_id, company, discovery_transport)
    if careers_url in {'https://careers.ses.com/search/?createNewAlert=false&q=&locationsearch=&optionsFacetsDD_customfield3=&optionsFacetsDD_customfield5=', 'https://careers.belden.com/search/?q=', 'https://jobs.hii-tsd.com/search/?q=&sortColumn=referencedate&sortDirection=desc', 'https://careers.leonardodrs.com/go/All-Jobs/8131200/', 'https://careers.thalesdsi.com/search/?q=', 'https://jobs.ametek.com/go/Abaco/8908500/?q=&sortColumn=referencedate&sortDirection=desc', 'https://jobs.deere.com/successfactors/search/?q=&locationsearch=', 'https://jobs.deere.com/search/?q=&sortColumn=referencedate&sortDirection=desc', 'https://jobs.teradyne.com/Universal-Robots/search/?q=&sortColumn=referencedate&sortDirection=desc'}:
        from .successfactors import fetch_successfactors
        return fetch_successfactors(careers_url, company_id, company, discovery_transport)
    if careers_url in {'https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5310', 'https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5313'}:
        from .brassring import fetch_brassring
        return fetch_brassring(careers_url, company_id, company, transport)
    if careers_url == 'https://careers.mantech.com/en_US/careers/':
        from .avature import fetch_avature
        return fetch_avature(careers_url, company_id, company, discovery_transport)
    if careers_url == 'https://jobs.saic.com/search/jobs':
        from .saic import fetch_saic
        return fetch_saic(careers_url, company_id, company, transport)
    # Eightfold boards are rendered applications whose tenant and public API
    # scope must be established by the browser adapter.  Keep them out of
    # generic HTML/board discovery; with_browser_fallback will route this
    # explicit result to fetch_browser_inventory.
    try:
        is_eightfold = ats.casefold() == 'eightfold' or urlsplit(careers_url).hostname.endswith('.eightfold.ai')
    except (AttributeError, ValueError):
        is_eightfold = False
    if is_eightfold:
        return Inventory('unsupported', reason='Eightfold public boards require the verified browser adapter.',
                         source_url=careers_url, ats='Eightfold')
    if ats.casefold() == 'acquiretm' or careers_url.startswith('https://amphenol-aerospace.acquiretm.com/'):
        from .acquiretm import fetch_acquiretm
        return fetch_acquiretm(careers_url, company_id, company)
    from .adp_myjobs import fetch_adp_myjobs, supports_adp_myjobs
    if supports_adp_myjobs(ats, careers_url):
        return fetch_adp_myjobs(ats, careers_url, company_id, company, transport or HTTPTransport())
    from .oracle import fetch_oracle, supports_oracle
    if supports_oracle(ats, careers_url):
        return fetch_oracle(ats, careers_url, company_id, company, transport or HTTPTransport(), discovery_transport)
    if ats.casefold() == 'teamtailor' or careers_url.startswith('https://careers.mildef.com/'):
        from .teamtailor import fetch_teamtailor
        return fetch_teamtailor(careers_url, company_id, company, transport)
    if ats.casefold() == 'trakstar hire' and urlsplit(careers_url).hostname == 'jobsatseptentrio.hire.trakstar.com':
        from .trakstar import fetch_trakstar
        return fetch_trakstar(careers_url, company_id, company, transport or HTTPTransport(), discovery_transport)
    if ats.casefold() == 'applicantstack' or '.applicantstack.com/' in careers_url:
        from .applicantstack import fetch_applicantstack
        return fetch_applicantstack(careers_url, company_id, company, transport)
    if ats.casefold() == 'gem' or careers_url.startswith('https://jobs.gem.com/'):
        from .gem import fetch_gem
        return fetch_gem(careers_url, company_id, company, transport)
    if ats.casefold() == 'salesforce-hosted recruiting' or careers_url == 'https://www.u-blox.com/en/job-openings':
        from .ublox import fetch_ublox
        return fetch_ublox(ats, careers_url, company_id, company, transport)
    from .shared_boards import known_host, fetch_shared, FAMILIES
    try:
        shared_host = known_host(urlsplit(careers_url).hostname)
    except ValueError:
        return Inventory("unsupported", reason="Malformed careers URL.", source_url=careers_url)
    if shared_host or ats in FAMILIES:
        return fetch_shared(ats, careers_url, company_id, company, transport, discovery_transport)
    from .ukg import is_ukg_host, fetch_ukg
    try:
        ukg_host = is_ukg_host(urlsplit(careers_url).hostname)
    except ValueError:
        ukg_host = False
    if ukg_host:
        return fetch_ukg(ats, careers_url, company_id, company, transport)
    from .northrop import supports_northrop
    if supports_northrop(careers_url):
        return Inventory("unsupported", reason="Northrop public jobs require the verified browser board adapter.", source_url=careers_url, ats="Eightfold")
    from .paycom import fetch_paycom
    try:
        paycom_host = urlsplit(careers_url).hostname == "www.paycomonline.net"
    except ValueError:
        paycom_host = False
    if paycom_host:
        return fetch_paycom(ats, careers_url, company_id, company, transport, discovery_transport)
    from .bamboohr import fetch_bamboohr, is_bamboohr_host
    try:
        bamboohr = "bamboohr" in ats.casefold() or is_bamboohr_host(urlsplit(careers_url).hostname)
    except (ValueError, AttributeError):
        bamboohr = False
    if bamboohr:
        return fetch_bamboohr(ats, careers_url, company_id, company, transport, discovery_transport)
    from .phenom import fetch_phenom, supports_phenom
    if supports_phenom(ats, careers_url):
        return fetch_phenom(ats, careers_url, company_id, company, discovery_transport,
                            progress=progress_factory(careers_url) if progress_factory is not None else None)
    if careers_url == 'https://www.peplink.com/company/career/' and company_id == 'COMP-0149' and company.strip().casefold() == 'peplink':
        from .peplink import fetch_peplink
        return fetch_peplink(careers_url, company_id, company, discovery_transport)
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
    if name in FAMILIES:
        return fetch_shared(ats, careers_url, company_id, company, transport, discovery_transport)
    if name == "UKG":
        result = fetch_ukg(ats, root + board, company_id, company, transport)
        result.reason = discovery_note + result.reason
        return result
    if name == "Paycom":
        result = fetch_paycom(ats, root + board, company_id, company, transport, discovery_transport)
        result.reason = discovery_note + result.reason
        return result
    transport = transport or HTTPTransport()
    if name == "BambooHR":
        return fetch_bamboohr(ats, careers_url, company_id, company, transport, discovery_transport)
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
    source_url = root + quote(board, safe="")
    location_scope = lever_location_scope(careers_url) if name == "Lever" else ""
    if name == "Greenhouse":
        source_url += "/jobs?content=true"
    elif name == "Ashby":
        source_url += "?includeCompensation=true"
    if location_scope:
        source_url += "?" + urlencode({"location": location_scope})
    try:
        for page in range(MAX_PAGES if name == "Lever" else 1):
            url = source_url
            if name == "Lever":
                url += ("&" if location_scope else "?") + urlencode({"mode": "json", "skip": page * PAGE_SIZE, "limit": PAGE_SIZE})
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
                if company_id == "COMP-0399" and company.casefold() == "re:build optimation":
                    # Re:Build's Greenhouse board is shared across subsidiaries;
                    # the exact office name is the verified Optimation partition.
                    allowed_office = "Re:Build Optimation Technology"
                    def scoped(rows):
                        return [raw for raw in rows if any(isinstance(o, dict) and o.get("name") == allowed_office for o in (raw.get("offices") or []))]
                    first_scope = scoped(entries)
                    reread = _json(url, transport)
                    reread_rows = reread.get("jobs") if isinstance(reread, dict) else None
                    if not isinstance(reread_rows, list):
                        raise FetchError("partial", "Re:Build reread returned an unexpected Greenhouse schema.")
                    second_scope = scoped(reread_rows)
                    def fingerprints(rows):
                        return {str(x.get("id")): (text(x.get("title")), tuple(sorted(str(o.get("name")) for o in (x.get("offices") or []) if isinstance(o, dict)))) for x in rows}
                    if fingerprints(first_scope) != fingerprints(second_scope):
                        issues.append("Re:Build Optimation office-scoped inventory changed during reread.")
                    if not first_scope:
                        issues.append("Re:Build Optimation office partition is empty.")
                    entries = first_scope
                elif company_id == "COMP-0158" and company.casefold() == "dedrone by axon":
                    # Axon's board is shared, but its structured department fields
                    # expose the complete Dedrone partition.  Never use keyword
                    # matches: only these four exact department labels are in scope.
                    allowed = {"2024 Dedrone R&D", "3042 Dedrone Sales",
                               "3043 Dedrone Customer Support", "1026 Dedrone HW Operations COGS"}
                    def scoped(rows):
                        out = []
                        for raw in rows:
                            depts = raw.get("departments") if isinstance(raw, dict) else None
                            names = {d.get("name") for d in depts if isinstance(d, dict)} if isinstance(depts, list) else set()
                            if names & allowed:
                                out.append(raw)
                        return out
                    first_scope = scoped(entries)
                    reread = _json(url, transport)
                    reread_rows = reread.get("jobs") if isinstance(reread, dict) else None
                    if not isinstance(reread_rows, list):
                        raise FetchError("partial", "Dedrone reread returned an unexpected Greenhouse schema.")
                    second_scope = scoped(reread_rows)
                    def fingerprints(rows):
                        return {str(x.get("id")): (text(x.get("title")), tuple(sorted(str(d.get("name")) for d in (x.get("departments") or []) if isinstance(d, dict)))) for x in rows}
                    if fingerprints(first_scope) != fingerprints(second_scope):
                        issues.append("Dedrone department-scoped inventory changed during reread.")
                    if not {d for x in first_scope for d in (x.get("departments") or []) if isinstance(d, dict) for d in [d.get("name")]} >= allowed:
                        issues.append("Dedrone department partition is missing one or more verified departments.")
                    entries = first_scope
                elif not isinstance(total, int) or isinstance(total, bool) or total != len(entries):
                    issues.append("Greenhouse meta.total missing or inconsistent with inventory size.")
            if name == "Lever" and len(entries) > PAGE_SIZE:
                raise FetchError("partial", "Lever returned more records than requested; pagination is untrusted.")
            if name == "Lever" and not entries:
                break
            duplicate = False
            for item_index, item in enumerate(entries):
                try:
                    if location_scope:
                        categories = item.get("categories") if isinstance(item, dict) else None
                        if not isinstance(categories, dict) or not isinstance(categories.get("allLocations", []), list):
                            raise ValueError("Lever location scope could not be verified.")
                        locations = [categories.get("location"), *categories.get("allLocations", [])]
                        if not all(isinstance(x, str) for x in locations if x is not None) or not any(
                            isinstance(x, str) and x.strip().casefold() == location_scope.casefold() for x in locations
                        ):
                            raise ValueError("Lever posting does not confirm the requested location scope.")
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
                    next_url = source_url + ("&" if location_scope else "?") + urlencode({"mode": "json", "skip": page * PAGE_SIZE + len(entries), "limit": PAGE_SIZE})
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


# Optional durable progress protocol used by the local pipeline and browser wrapper.
fetch_inventory.fetch_with_progress = fetch_inventory
