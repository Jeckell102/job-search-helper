"""Employer-scoped Panasonic Connect jobs from the public Jibe feed."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from .ats import FetchError, Inventory, HTTPTransport, _base, text

SOURCE = "https://careers.na.panasonic.com/connect"
API = "https://careers.na.panasonic.com/api/jobs"
TAGS = (
    "PCONA Panasonic Connect North America",
    "PSG Panasonic Connect North America Professional Services",
)


def _json(transport, url):
    response = transport.get(url)
    if response.status in (401, 403, 429):
        raise FetchError("blocked", f"Panasonic public jobs API HTTP {response.status}: access denied or rate limited.")
    if response.status != 200:
        raise FetchError("failed", f"Panasonic public jobs API HTTP {response.status}.")
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FetchError("partial", "Panasonic public jobs API returned invalid JSON.") from exc
    if not isinstance(value, dict):
        raise FetchError("partial", "Panasonic public jobs API returned an invalid payload.")
    return value


def _listing(transport, tag):
    entries = []
    expected = None
    for page in range(1, 101):
        query = urlencode({"page": page, "limit": 100, "tags3": tag})
        payload = _json(transport, API + "?" + query)
        total = payload.get("totalCount")
        count = payload.get("count")
        rows = payload.get("jobs")
        if not isinstance(total, int) or not isinstance(count, int) or not isinstance(rows, list):
            raise FetchError("partial", "Panasonic Connect inventory metadata is malformed.")
        if expected is None:
            expected = total
        if total != expected or count != len(rows) or len(rows) != min(100, total - len(entries)):
            raise FetchError("partial", "Panasonic Connect inventory counts or pagination changed.")
        for row in rows:
            data = row.get("data") if isinstance(row, dict) else None
            if not isinstance(data, dict) or data.get("tags3") != [tag]:
                raise FetchError("partial", "Panasonic Connect employer scope changed in the public feed.")
            ident = str(data.get("slug") or "")
            if not ident or any(str(old.get("slug")) == ident for old in entries):
                raise FetchError("partial", "Panasonic Connect inventory has duplicate or missing job IDs.")
            entries.append(data)
        if len(entries) == expected:
            return entries
        if not rows:
            raise FetchError("partial", "Panasonic Connect inventory ended before its advertised count.")
    raise FetchError("partial", "Panasonic Connect inventory page bound reached.")


def fetch_panasonic(company_id, company, transport=None):
    transport = transport or HTTPTransport()
    entries = []
    for tag in TAGS:
        entries.extend(_listing(transport, tag))
    ids = set()
    jobs = []
    for data in entries:
        ident = str(data["slug"])
        if ident in ids:
            raise FetchError("partial", "Panasonic Connect employer filters overlap.")
        ids.add(ident)
        title = text(data.get("title"))
        description = "\n\n".join(
            text(data.get(key)) for key in ("description", "responsibilities", "qualifications") if data.get(key)
        ).strip()
        if not title or not description or len(description) < 40:
            raise FetchError("partial", "Panasonic Connect posting lacks a complete title or description.")
        row = _base({"id": ident}, "Jibe", company_id, company)
        row.update(
            title=title,
            description=description,
            url=f"https://careers.na.panasonic.com/jobs/{ident}?lang=en-us",
            req_id=text(data.get("req_id")),
            location=text(data.get("full_location")),
            department=text(data.get("category")),
            created_at=data.get("posted_date", ""),
            compensation=" ".join(str(data.get(k) or "") for k in ("salary_value", "salary_min_value", "salary_max_value")).strip(),
        )
        jobs.append(row)
    return Inventory("complete", jobs, f"Panasonic Connect: retrieved {len(jobs)} full postings across two employer-scoped Jibe filters and rechecked each filter inventory.", SOURCE, "Jibe")
