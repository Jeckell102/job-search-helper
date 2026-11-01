"""Bounded public IBM BrassRing careers boards."""
from __future__ import annotations

import json
import socket
import ssl
from html import unescape
from http.client import HTTPSConnection, HTTPException
from urllib.parse import parse_qs, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, text
from .discovery import _public_addresses, public_careers_url


SITES = {
    # The public General Atomics site links these distinct, scoped boards.
    "https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5310": ("25539", "5310"),
    "https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5313": ("25539", "5313"),
}
# These are not keyword matches.  The General Atomics public U.S. board
# publishes a department value with every result; GA-ASI is the exact value
# shown for its own postings.  We still enumerate the entire published board
# before filtering, so a missing department is a completeness failure rather
# than an opportunity to silently omit a posting.
SCOPES = {
    ("COMP-0072", "https://sjobs.brassring.com/TGNewUI/Search/Home/Home?partnerid=25539&siteid=5313"):
        "General Atomics Aeronautical Systems",
}
HOST = "sjobs.brassring.com"
PAGE_SIZE, MAX_PAGES = 50, 100


class _Client:
    """Minimal cookie-scoped client for an exact public BrassRing host."""
    def __init__(self, timeout=25):
        self.timeout = timeout
        self.cookies = []
        self.context = ssl.create_default_context()

    def _request(self, method, path, body=None, headers=None):
        headers = dict(headers or {})
        if self.cookies:
            headers["Cookie"] = "; ".join(self.cookies)
        headers.setdefault("User-Agent", "JobSearchHelper/1.0 (public careers-board retrieval; read-only)")
        headers.setdefault("Accept-Encoding", "identity")
        try:
            addresses = _public_addresses(HOST)
            for family, kind, protocol, _, address in addresses[:4]:
                connection = HTTPSConnection(HOST, timeout=self.timeout)
                raw = socket.socket(family, kind, protocol)
                try:
                    raw.settimeout(self.timeout)
                    raw.connect(address)
                    connection.sock = self.context.wrap_socket(raw, server_hostname=HOST)
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    body = response.read(16 * 1024 * 1024 + 1)
                    if len(body) > 16 * 1024 * 1024:
                        raise FetchError("partial", "BrassRing response exceeded the safe retrieval limit.")
                    for name, value in response.getheaders():
                        if name.lower() == "set-cookie":
                            cookie = value.split(";", 1)[0]
                            if "=" in cookie:
                                self.cookies = [item for item in self.cookies if item.split("=", 1)[0] != cookie.split("=", 1)[0]] + [cookie]
                    return HTTPResponse(response.status, body, dict(response.getheaders()))
                except (OSError, HTTPException):
                    continue
                finally:
                    connection.close()
                    raw.close()
        except OSError:
            pass
        raise FetchError("failed", "BrassRing public board network request failed.")

    def get(self, source):
        parsed = urlsplit(public_careers_url(source))
        if parsed.hostname != HOST:
            raise FetchError("unsupported", "BrassRing adapter requires the verified public board host.")
        return self._request("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), headers={"Accept": "text/html"})

    def post(self, endpoint, data, token):
        if endpoint not in {"MatchedJobs", "ProcessSortAndShowMoreJobs"}:
            raise FetchError("unsupported", "Only public BrassRing listing endpoints are allowed.")
        return self._request("POST", "/TgNewUI/Search/Ajax/" + endpoint,
                             json.dumps(data).encode(), {"RFT": token, "Content-Type": "application/json", "Accept": "application/json"})


def _input(body, name):
    marker = 'id="' + name + '"'
    pos = body.find(marker)
    if pos < 0:
        marker = 'name="' + name + '"'; pos = body.find(marker)
    if pos < 0:
        return ""
    end = body.find(">", pos)
    field = body[pos:end]
    value = field.split('value="', 1)
    return unescape(value[1].split('"', 1)[0]) if len(value) == 2 else ""


def _fields(job):
    return {item.get("QuestionName", "").casefold(): item.get("Value", "") for item in job.get("Questions", [])}


def _signature(entries):
    return [(text(_fields(entry).get("reqid")), text(_fields(entry).get("jobtitle"))) for entry in entries]


def _listing(client, source, partner, site, page, token, session):
    common = {"partnerId": partner, "siteId": site, "keyword": "", "location": "", "keywordCustomSolrFields": "",
              "locationCustomSolrFields": "", "linkId": "", "Latitude": 0, "Longitude": 0,
              "facetfilterfields": {"Facet": []}, "powersearchoptions": {"PowerSearchOption": []},
              "SortType": "", "encryptedSessionValue": session}
    if page == 1:
        payload = {key[0].upper() + key[1:]: value for key, value in common.items()}
        payload["TurnOffHttps"] = False
        response = client.post("MatchedJobs", payload, token)
    else:
        common.update(sortby=None, pageNumber=page)
        response = client.post("ProcessSortAndShowMoreJobs", common, token)
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial", "BrassRing public listings were unavailable.")
    try:
        data = json.loads(response.body)
        total = data["JobsCount"]; jobs = data["Jobs"]["Job"]
        if not isinstance(total, int) or total < 0 or not isinstance(jobs, list):
            raise ValueError
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise FetchError("partial", "BrassRing listing schema validation failed.") from None
    return total, jobs


def fetch_brassring(url, company_id, company, transport=None):
    board = SITES.get(url)
    if not board:
        return Inventory("unsupported", reason="BrassRing adapter requires a verified employer board.", source_url=url, ats="BrassRing")
    client = transport or _Client(); partner, site = board; jobs = []; matched = 0
    department_scope = SCOPES.get((company_id, url))
    try:
        response = client.get(url)
        if response.status != 200:
            raise FetchError("blocked" if response.status in (401, 403, 429) else "partial", "BrassRing public board was unavailable.")
        body = response.body.decode("utf-8", "replace")
        token, session = _input(body, "__RequestVerificationToken"), _input(body, "CookieValue")
        if not token or not session:
            raise FetchError("partial", "BrassRing board did not expose its public search session.")
        total, first = _listing(client, url, partner, site, 1, token, session)
        pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
        if pages > MAX_PAGES:
            raise FetchError("partial", "BrassRing inventory exceeds the safe page limit.")
        seen = set()
        for page in range(1, pages + 1):
            current_total, entries = (total, first) if page == 1 else _listing(client, url, partner, site, page, token, session)
            if current_total != total or len(entries) != min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE):
                raise FetchError("partial", "BrassRing page count disagrees with its published inventory.")
            for entry in entries:
                fields = _fields(entry); ident = text(fields.get("reqid")); title = text(fields.get("jobtitle")); description = text(fields.get("jobdescription")); department = text(fields.get("department")).strip()
                if not ident or not title or not department:
                    raise FetchError("partial", "BrassRing listing lacks a unique ID, title, or published department.")
                if department_scope and department != department_scope:
                    continue
                matched += 1
                if not description or ident in seen:
                    raise FetchError("partial", "BrassRing scoped listing lacks a unique ID, title, or full description.")
                seen.add(ident)
                row = _base({"id": ident}, "BrassRing", company_id, company)
                location = ", ".join(part for part in (text(fields.get("formtext5")), text(fields.get("formtext4"))) if part)
                row.update(title=title, description=description, url=text(entry.get("Link")), location=location, department=department)
                if not row["url"].startswith("https://" + HOST + "/"):
                    raise FetchError("partial", "BrassRing listing had an invalid public detail URL.")
                jobs.append(row)
        check_total, check = _listing(client, url, partner, site, 1, token, session)
        check_ids = {ident for ident, _ in _signature(check)}
        first_ids = {ident for ident, _ in _signature(first)}
        if (check_total != total or check_ids != first_ids
                or len(jobs) != (matched if department_scope else total)):
            raise FetchError("partial", "BrassRing inventory changed during retrieval.")
        scope_note = f" for published department {department_scope}" if department_scope else ""
        return Inventory("complete", jobs, f"BrassRing: retrieved {len(jobs)} complete postings{scope_note} and rechecked the public inventory.", url, "BrassRing")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, url, "BrassRing")
    except (ValueError, TypeError, AttributeError):
        return Inventory("partial", jobs, "BrassRing public schema validation failed.", url, "BrassRing")
