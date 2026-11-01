"""Anonymous public Dayforce candidate-portal job feeds."""
from __future__ import annotations

import re
import http.cookiejar
import json
from html.parser import HTMLParser
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _NoRedirect, _base, _json, text
from .phenom_session import _PublicHTTPS

SOURCE = "https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE/jobs"
SEARCH = "https://jobs.dayforcehcm.com/api/geo/esa/jobposting/search"
MULTITECH_SOURCE = "https://us231.dayforcehcm.com/CandidatePortal/en-US/multitech"
MULTITECH_SEARCH = "https://jobs.dayforcehcm.com/api/geo/multitech/jobposting/search"
PAGE_SIZE = 25
MAX_PAGES = 200


class DayforceSession:
    """Anonymous cookie-backed session used by the current ESA portal."""
    def __init__(self, source):
        parsed = urlsplit(source)
        if source != SOURCE:
            raise FetchError("unsupported", "Dayforce session host is outside the verified public portal.")
        self.host = parsed.hostname
        self.source = source
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}), _PublicHTTPS(), _NoRedirect(), HTTPCookieProcessor(self.cookies))
        self.csrf = ""
        self.last_request = 0.0
        self.ready = False

    def _request(self, url, payload=None):
        parsed = urlsplit(url)
        allowed_get = {"/api/auth/session", "/api/auth/csrf", "/esa/ESACAREERSITE"}
        detail_prefix = "/en-US/esa/ESACAREERSITE/jobs/"
        if (parsed.scheme != "https" or parsed.hostname != self.host or parsed.query or parsed.fragment
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise FetchError("unsupported", "Dayforce session request left the verified host.")
        if payload is None and not (parsed.path in allowed_get or re.fullmatch(re.escape(detail_prefix) + r"[0-9]{1,20}", parsed.path)):
            raise FetchError("unsupported", "Dayforce session GET left the verified public paths.")
        if payload is not None:
            if (not isinstance(payload, dict) or parsed.path != "/api/geo/esa/jobposting/search" or set(payload) != {"clientNamespace", "jobBoardCode", "cultureCode", "distanceUnit", "exactLocationOnly", "paginationStart"}):
                raise FetchError("unsupported", "Dayforce session POST left the verified public search contract.")
            if ((payload["clientNamespace"], payload["jobBoardCode"], payload["cultureCode"]) != ("esa", "ESACAREERSITE", "en-US")
                    or type(payload["distanceUnit"]) is not int or payload["distanceUnit"] != 0
                    or payload["exactLocationOnly"] is not False
                    or type(payload["paginationStart"]) is not int or not 0 <= payload["paginationStart"] < PAGE_SIZE * MAX_PAGES
                    or payload["paginationStart"] % PAGE_SIZE):
                raise FetchError("unsupported", "Dayforce session POST had an invalid public search scope.")
            if not self.ready:
                self._bootstrap()
        time.sleep(max(0.0, 0.4 - (time.monotonic() - self.last_request))); self.last_request = time.monotonic()
        headers = {
            "User-Agent": "JobSearchHelper/1.0 (public job-board inventory; read-only)",
            "Accept": "application/json" if parsed.path.startswith("/api/") else "text/html",
            "Accept-Encoding": "identity",
            "Origin": "https://jobs.dayforcehcm.com",
            "Referer": self.source,
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            if self.csrf:
                headers["X-CSRF-Token"] = self.csrf
            data = json.dumps(payload).encode()
        try:
            response = self.opener.open(Request(url, data=data, headers=headers, method="POST" if data else "GET"), timeout=25)
            with response:
                body = response.read(16 * 1024 * 1024 + 1)
                if len(body) > 16 * 1024 * 1024:
                    raise FetchError("partial", "Dayforce public response exceeded the safe size limit.")
                return HTTPResponse(response.status, body, dict(response.headers))
        except HTTPError as error:
            return HTTPResponse(error.code, error.read(8192), dict(error.headers))
        except (URLError, OSError):
            raise FetchError("failed", "Dayforce public session network failure.") from None

    def _bootstrap(self):
        session = self._request("https://jobs.dayforcehcm.com/api/auth/session")
        csrf = self._request("https://jobs.dayforcehcm.com/api/auth/csrf")
        if session.status in (401, 403, 429) or csrf.status in (401, 403, 429):
            raise FetchError("blocked", "Dayforce anonymous session bootstrap was denied.")
        if session.status != 200 or csrf.status != 200:
            raise FetchError("partial", "Dayforce anonymous session bootstrap was unavailable.")
        try:
            token = json.loads(csrf.body).get("csrfToken")
            if not isinstance(token, str) or not 1 <= len(token) <= 1024:
                raise ValueError("Missing public session token")
        except (ValueError, TypeError, AttributeError):
            raise FetchError("partial", "Dayforce anonymous session omitted its CSRF state.") from None
        self.csrf = token
        self.ready = True

    def get(self, url):
        response = self._request(url)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Dayforce public page returned HTTP {response.status}.")
        if not 200 <= response.status < 300:
            raise FetchError("failed", f"Dayforce public page returned HTTP {response.status}.")
        return response

    def post(self, url, payload, headers=None):
        if headers:
            raise FetchError("unsupported", "Dayforce public session does not accept caller authentication headers.")
        response = self._request(url, payload)
        return response


def supports_dayforce(ats: str, url: str) -> bool:
    return isinstance(url, str) and url in (SOURCE, MULTITECH_SOURCE)


def _rows(data):
    if not isinstance(data, dict):
        raise FetchError("partial", "Dayforce search returned an unexpected schema.")
    rows = data.get("jobPostings")
    if not isinstance(rows, list):
        rows = data.get("JobPostings")
    total = data.get("maxCount", data.get("MaxCount"))
    if not isinstance(rows, list) or type(total) is not int or total < 0:
        raise FetchError("partial", "Dayforce search omitted its public inventory count.")
    return rows, total


def _page(data, offset, scoped_esa):
    rows, total = _rows(data)
    if scoped_esa and (data.get("offset") != offset or data.get("count") != len(rows)
                       or len(rows) != min(PAGE_SIZE, max(0, total - offset))
                       or total > PAGE_SIZE * MAX_PAGES):
        raise FetchError("partial", "Dayforce search did not confirm its complete requested page slice.")
    return rows, total


def _location(item):
    values = item.get("postingLocations", item.get("PostingLocations", []))
    if isinstance(values, dict):
        values = [values]
    if not isinstance(values, list):
        return ""
    out = []
    for value in values:
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            formatted = text(value.get("formattedAddress"))
            if formatted:
                out.append(formatted)
                continue
            out.append(", ".join(filter(None, (
                text(value.get("city", value.get("City"))),
                text(value.get("state", value.get("State"))),
                text(value.get("country", value.get("Country"))),
            ))))
    return "; ".join(dict.fromkeys(filter(None, out)))


def _posting(item, company_id, company, config):
    if not isinstance(item, dict):
        raise FetchError("partial", "Dayforce search contains a malformed posting.")
    if config["client"] == "esa" and (item.get("clientNamespace") != "esa" or item.get("jobBoardId") != 4):
        raise FetchError("partial", "Dayforce posting belongs to a different employer board.")
    ident = text(item.get("jobPostingId", item.get("JobPostingId", item.get("id", item.get("Id")))))
    req_id = text(item.get("jobReqId", item.get("JobReqId", item.get("reqId", item.get("ReqId", ident)))))
    title = text(item.get("jobTitle", item.get("JobTitle", item.get("Title"))))
    description = text(item.get("jobDescription", item.get("JobDescription", item.get("Description"))))
    detail = text(item.get("jobDetailsUrl", item.get("JobDetailsUrl")))
    if not detail and config["client"] == "esa" and ident:
        detail = f"https://jobs.dayforcehcm.com/en-US/esa/ESACAREERSITE/jobs/{ident}"
    if not ident or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", ident) or not title or not description or not detail:
        raise FetchError("partial", "Dayforce posting lacks a stable ID, title, description, or detail URL.")
    parsed = urlsplit(detail)
    if (parsed.scheme != "https" or parsed.hostname != config["detail_host"]
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.path.rstrip("/") != config["detail_prefix"] + ident or parsed.query or parsed.fragment):
        raise FetchError("partial", "Dayforce posting detail is outside the verified employer portal scope.")
    row = _base({"id": ident}, "Dayforce", company_id, company)
    row.update(req_id=req_id or ident, title=title, description=description, url=detail,
               location=_location(item), created_at=text(item.get("postingStartTimestampUTC", item.get("DatePosted"))))
    return row


class _NextData(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=False)
        self.count = 0
        self.active = False
        self.closed = False
        self.parts = []
        self.feed(body)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("id") == "__NEXT_DATA__":
            self.count += 1
            self.active = attrs.get("type") == "application/json"

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.active = False
            self.closed = True


def _esa_detail(client, row, config):
    """Refresh ESA rows from the public SSR detail document."""
    response = client.get(row["url"])
    if not isinstance(response, HTTPResponse) or response.status != 200:
        raise FetchError("partial", "Dayforce ESA detail was unavailable.")
    body = response.body.decode("utf-8", "replace")
    embedded = _NextData(body)
    if embedded.count != 1 or not embedded.closed:
        raise FetchError("partial", "Dayforce ESA detail omitted its public job data.")
    try:
        page = json.loads("".join(embedded.parts))
        props = page["props"]["pageProps"]
        job = props["jobData"]
        content = job["jobPostingContent"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise FetchError("partial", "Dayforce ESA detail had malformed public job data.") from None
    query = urlsplit(row["url"])
    routing = page.get("query")
    if (not isinstance(routing, dict) or routing.get("clientNamespace") != "esa"
            or routing.get("careerSiteXRefCode") != "ESACAREERSITE" or str(routing.get("id")) != row["posting_id"]
            or page.get("locale") != "en-US"
            or props.get("jobUrl") not in {"https://jobs.dayforcehcm.com/esa/ESACAREERSITE/jobs/" + row["posting_id"], row["url"]}):
        raise FetchError("partial", "Dayforce ESA detail route did not match the verified employer posting.")
    if (str(job.get("jobPostingId")) != row["posting_id"] or
            text(job.get("jobTitle")) != row["title"] or job.get("isInternal") is not False or
            str(job.get("jobReqId")) != row["req_id"] or
            query.hostname != config["detail_host"] or
            query.path != f"/en-US/esa/ESACAREERSITE/jobs/{row['posting_id']}" or
            not isinstance(content, dict)):
        raise FetchError("partial", "Dayforce ESA detail identity did not match its listing.")
    dehydrated = props.get("dehydratedState", {})
    site_records = [q.get("state", {}).get("data") for q in dehydrated.get("queries", [])
                    if isinstance(q, dict) and isinstance(q.get("queryKey"), list)
                    and q["queryKey"] and q["queryKey"][0] == "site-info"]
    site_info = site_records[0] if len(site_records) == 1 and isinstance(site_records[0], dict) else {}
    if (site_info.get("jobBoardId") != 4 or site_info.get("clientId") != 54055 or
                      site_info.get("clientNamespace") != "esa" or site_info.get("jobBoardCode", "").casefold() != "esacareersite"):
        raise FetchError("partial", "Dayforce ESA detail board identity did not match the verified tenant.")
    sections = [content.get(key) for key in ("jobDescriptionHeader", "jobDescription", "jobDescriptionFooter")]
    if any(not isinstance(value, str) for value in sections) or not text(sections[1]).strip():
        raise FetchError("partial", "Dayforce ESA detail omitted a complete public description section.")
    row["description"] = "\n\n".join(text(value) for value in sections)
    return row


def fetch_dayforce(ats, source, company_id, company, transport):
    if not supports_dayforce(ats, source):
        return Inventory("unsupported", reason="Dayforce adapter requires a verified employer-scoped public portal.", source_url=source, ats="Dayforce")
    config = ({"search": SEARCH, "client": "esa", "board": "ESACAREERSITE", "detail_host": "jobs.dayforcehcm.com", "detail_prefix": "/en-US/esa/ESACAREERSITE/jobs/"}
              if source == SOURCE else
              {"search": MULTITECH_SEARCH, "client": "multitech", "board": "CANDIDATEPORTAL", "detail_host": "jobs.dayforcehcm.com", "detail_prefix": "/en-US/multitech/CANDIDATEPORTAL/jobs/"})
    jobs = []
    try:
        records = []
        expected = None
        for page in range(MAX_PAGES):
            # Match the anonymous portal's current public search contract.
            # The API rejects the legacy string distance unit; the browser
            # sends numeric zero and an explicit exact-location flag.
            payload = {"clientNamespace": config["client"], "jobBoardCode": config["board"], "cultureCode": "en-US", "distanceUnit": 0 if source == SOURCE else "miles", "paginationStart": page * PAGE_SIZE}
            if source == SOURCE:
                payload["exactLocationOnly"] = False
            rows, total = _page(_json(config["search"], transport, payload=payload), page * PAGE_SIZE, source == SOURCE)
            if expected is None:
                expected = total
            elif total != expected:
                raise FetchError("partial", "Dayforce inventory count changed during pagination.")
            records.extend(rows)
            if len(records) >= expected:
                break
            if not rows:
                raise FetchError("partial", "Dayforce pagination ended before its published inventory.")
        else:
            raise FetchError("partial", "Dayforce page cap reached before the inventory ended.")
        if len(records) != expected:
            raise FetchError("partial", "Dayforce records do not match its published inventory.")
        initial_fingerprints = {text(item.get("jobPostingId", item.get("JobPostingId", item.get("id", item.get("Id"))))): json.dumps(item, sort_keys=True, separators=(",", ":")) for item in records}
        seen = set()
        for item in records:
            row = _posting(item, company_id, company, config)
            if source == SOURCE:
                row = _esa_detail(transport, row, config)
            if row["posting_id"] in seen:
                raise FetchError("partial", "Dayforce inventory contains duplicate posting IDs.")
            seen.add(row["posting_id"])
            jobs.append(row)
        check_records = []
        for page in range(MAX_PAGES):
            check_payload = {"clientNamespace": config["client"], "jobBoardCode": config["board"], "cultureCode": "en-US", "distanceUnit": 0 if source == SOURCE else "miles", "paginationStart": page * PAGE_SIZE}
            if source == SOURCE:
                check_payload["exactLocationOnly"] = False
            check_rows, check_total = _page(_json(config["search"], transport, payload=check_payload), page * PAGE_SIZE, source == SOURCE)
            if check_total != expected:
                raise FetchError("partial", "Dayforce inventory count changed during the final recheck.")
            check_records.extend(check_rows)
            if len(check_records) >= expected:
                break
            if not check_rows:
                raise FetchError("partial", "Dayforce final recheck ended before its published inventory.")
        check_fingerprints = {text(item.get("jobPostingId", item.get("JobPostingId", item.get("id", item.get("Id"))))): json.dumps(item, sort_keys=True, separators=(",", ":")) for item in check_records}
        if len(check_records) != expected or check_fingerprints != initial_fingerprints:
            raise FetchError("partial", "Dayforce inventory changed during the final recheck.")
        return Inventory("complete", jobs, f"Dayforce: retrieved {len(jobs)} full postings and rechecked the public inventory.", source, "Dayforce")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, source, "Dayforce")
    except (TypeError, ValueError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs, "Dayforce public schema validation failed.", source, "Dayforce")
