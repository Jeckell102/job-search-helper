"""Kratos Defense's employer-owned Submit4Jobs public inventory."""
from __future__ import annotations

import json

from .ats import FetchError, HTTPTransport, Inventory, _base, text


SOURCE = "https://kratosdefense.submit4jobs.com/"
SEARCH = "https://apps3.pereless.com/templates/magnetolive/api/?action=getJobs"
CID = 85347
MAX_JOBS = 2_000


def _filters(jid: int | None = None) -> dict:
    filters = {"buid": "", "intranet": 0, "city": "", "mystate": [],
               "country": "", "title": "", "zipcode": "", "department": "",
               "businessname": "", "language": "en", "jobtype": "", "keyword": "",
               "jobcapability": [], "jobcategory": []}
    if jid is not None:
        filters["jid"] = jid
    return {"filters": filters}


def _request(client, jid: int | None = None) -> list[dict]:
    response = client.post(SEARCH, _filters(jid), headers={"cid": str(CID)})
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial",
                         "Kratos public job API was unavailable.")
    try:
        rows = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "Kratos public job API returned invalid JSON.") from None
    if not isinstance(rows, list):
        raise FetchError("partial", "Kratos public job API returned an invalid inventory schema.")
    return rows


def _listing_row(value: object) -> tuple[int, str]:
    if not isinstance(value, dict):
        raise FetchError("partial", "Kratos public job API returned an invalid posting.")
    jid, title = value.get("jid"), text(value.get("job_title"))
    if (not isinstance(jid, int) or isinstance(jid, bool) or jid <= 0 or not title
            or value.get("cid") != CID or text(value.get("companyname")).casefold() != "kratos defense"):
        raise FetchError("partial", "Kratos public job API returned a posting outside its employer scope.")
    return jid, title


def fetch_kratos(careers_url: str, company_id: str, company: str, transport=None) -> Inventory:
    if (careers_url != SOURCE or company_id != "COMP-0068"
            or company.strip().casefold() != "kratos defense & security solutions"):
        return Inventory("unsupported", reason="Kratos adapter requires its verified unfiltered public careers portal.", source_url=careers_url, ats="Kratos careers")
    client = transport or HTTPTransport()
    jobs: list[dict] = []
    try:
        listing = _request(client)
        if len(listing) > MAX_JOBS:
            raise FetchError("partial", "Kratos public inventory exceeded the safe complete-inventory limit.")
        rows = [_listing_row(item) for item in listing]
        identifiers = [jid for jid, _ in rows]
        if len(identifiers) != len(set(identifiers)):
            raise FetchError("partial", "Kratos public inventory contains duplicate posting IDs.")
        for jid, listed_title in rows:
            detail = _request(client, jid)
            if len(detail) != 1:
                raise FetchError("partial", "Kratos public job detail did not resolve exactly one posting.")
            detail_jid, detail_title = _listing_row(detail[0])
            description = text(detail[0].get("jobdescription"))
            if detail_jid != jid or detail_title != listed_title or len(description) < 80:
                raise FetchError("partial", "Kratos public job detail lacks a matching title or full description.")
            row = _base({"id": str(jid)}, "Kratos careers", company_id, company)
            row.update(title=listed_title, description=description,
                       url=f"{SOURCE}#/jobDescription/{jid}/")
            jobs.append(row)
        recheck = _request(client)
        if [_listing_row(item) for item in recheck] != rows:
            raise FetchError("partial", "Kratos public inventory changed during the scan.")
        return Inventory("complete", jobs,
                         f"Kratos careers: retrieved {len(jobs)} complete public postings and rechecked the inventory.",
                         SOURCE, "Kratos careers")
    except FetchError as error:
        return Inventory(error.status if not jobs else "partial", jobs, error.reason, SOURCE, "Kratos careers")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", jobs, "Kratos public careers schema validation failed.", SOURCE, "Kratos careers")
