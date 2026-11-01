"""Garmin's employer-scoped public Jibe inventory."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://careers.garmin.com/jobs"
API = "https://careers.garmin.com/api/jobs"
HOST = "careers.garmin.com"
APPLY_HOSTS = {"careers-garmin.icims.com", "canada-garmin.icims.com"}
ATS = "Garmin Jibe"
COMPANY_ID = "COMP-0437"
COMPANY = "Garmin"


def _verified_source(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and isinstance(company, str)
                and company.strip().casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == HOST
                and p.path.rstrip("/") == "/jobs" and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _page(client, page):
    response = client.get(f"{API}?page={page}&limit=100")
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Garmin public job feed blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Garmin public job feed HTTP {response.status}.")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise FetchError("partial", "Garmin public job feed returned invalid JSON.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise FetchError("partial", "Garmin public job feed shape changed.")
    total = payload.get("totalCount")
    if (type(total) is not int or not 0 <= total <= 10000
            # Jibe's `count` is the complete matching-result count, not the
            # number returned on this page.
            or payload.get("count") != total
            or len(payload["jobs"]) != min(100, total - (page - 1) * 100)):
        raise FetchError("partial", "Garmin public job feed pagination metadata is inconsistent.")
    return total, payload["jobs"]


def _jobs(client):
    total, first = _page(client, 1)
    entries = list(first)
    for page in range(2, (total + 99) // 100 + 1):
        page_total, values = _page(client, page)
        if page_total != total:
            raise FetchError("partial", "Garmin public job count changed during pagination.")
        entries.extend(values)
    if len(entries) != total:
        raise FetchError("partial", "Garmin public job feed is truncated.")

    result = []
    seen = set()
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
            raise FetchError("partial", "Garmin posting record is malformed.")
        data = item["data"]
        ident = data.get("slug")
        title = text(data.get("title"))
        description = text(data.get("description"))
        apply_url = data.get("apply_url")
        if (not isinstance(ident, str) or not ident.strip() or ident in seen
                or not title or len(description) < 100
                or not isinstance(apply_url, str)
                or urlsplit(apply_url).hostname not in APPLY_HOSTS):
            raise FetchError("partial", "Garmin posting identity, scope, or full description is invalid.")
        seen.add(ident)
        row = _base({"id": ident}, ATS, COMPANY_ID, COMPANY)
        row.update(title=title, description=description, url=apply_url,
                   req_id=text(data.get("req_id")),
                   location=text(data.get("full_location")),
                   department=text(data.get("category")),
                   created_at=data.get("posted_date", ""))
        result.append(row)
    return sorted(result, key=lambda row: (row["title"].casefold(), row["posting_id"]))


def fetch_garmin(careers_url, company_id, company, transport=None):
    if not _verified_source(careers_url, company_id, company):
        return Inventory("unsupported", reason="Garmin requires its verified public Jibe board.",
                         source_url=SOURCE, ats=ATS)
    client = transport or CareersTransport(accept="application/json")
    try:
        first = _jobs(client)
        second = _jobs(client)
        signature = lambda jobs: [(j["posting_id"], j["title"], j["description"]) for j in jobs]
        if signature(first) != signature(second):
            raise FetchError("partial", "Garmin job inventory changed during the reread.")
        return Inventory("complete", first,
                         f"Garmin: retrieved {len(first)} full public postings and passed a stable reread.",
                         SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError, json.JSONDecodeError):
        return Inventory("partial", [], "Garmin public job feed validation failed.", SOURCE, ATS)
