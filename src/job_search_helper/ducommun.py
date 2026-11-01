"""Ducommun's official Cornerstone career-site inventory."""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from .ats import FetchError, HTTPTransport, Inventory, _base, _challenge, text
from .discovery import CareersTransport

SOURCE = "https://www.ducommun.com/careers/CareersHome.aspx/"
BOARD = "https://ducommun.csod.com/ux/ats/careersite/1/home?c=ducommun"
SEARCH = "https://us.api.csod.com/rec-job-search/external/jobs"
ATS = "Cornerstone careers"
COMPANY_ID = "COMP-0440"
COMPANY = "Ducommun"
TOKEN_RE = re.compile(rb'"token":"([^"]+)"')


def _verified_source(url, company_id, company):
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == "www.ducommun.com"
                and p.path.rstrip("/").casefold() == "/careers/careershome.aspx"
                and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False


def _token(client):
    response = client.get(BOARD)
    if response.status in {401, 403, 429} or _challenge(response, expect_html=True):
        raise FetchError("blocked", f"Ducommun careers page blocked (HTTP {response.status}).")
    if response.status != 200 or b"ducommun" not in response.body.lower():
        raise FetchError("partial", "Ducommun Cornerstone board did not identify the Ducommun tenant.")
    match = TOKEN_RE.search(response.body)
    if not match:
        raise FetchError("partial", "Ducommun Cornerstone page did not expose a public search token.")
    return match.group(1).decode("ascii")


def _search(client, token):
    payload = {"careerSiteId": 1, "careerSitePageId": 1, "pageNumber": 1, "pageSize": 100,
               "cultureId": 1, "searchText": "", "cultureName": "en-US", "states": [],
               "countryCodes": [], "cities": [], "placeID": "", "radius": 0,
               "postingsWithinDays": 0, "customFieldCheckboxKeys": [],
               "customFieldDropdowns": [], "customFieldRadios": []}
    response = client.post(SEARCH, payload, headers={"Authorization": "Bearer " + token})
    if response.status in {401, 403, 429}:
        raise FetchError("blocked", f"Ducommun Cornerstone search blocked (HTTP {response.status}).")
    if response.status != 200:
        raise FetchError("partial", f"Ducommun Cornerstone search HTTP {response.status}.")
    try:
        data = json.loads(response.body)["data"]
        rows, total = data["requisitions"], data["totalCount"]
        if not isinstance(rows, list) or not isinstance(total, int) or total < 0 or total != len(rows):
            raise ValueError
        return rows
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise FetchError("partial", "Ducommun Cornerstone search response was malformed or truncated.") from None


def _detail(client, token, row, company_id, company):
    rid = row.get("requisitionId")
    if not isinstance(rid, int) or not 1 <= rid <= 10**10:
        raise FetchError("partial", "Ducommun requisition has an invalid identifier.")
    url = f"https://ducommun.csod.com/services/x/job-requisition/v2/requisitions/{rid}/jobDetails?cultureId=1"
    response = client.get_with_headers(url, {"Authorization": "Bearer " + token})
    if response.status != 200:
        raise FetchError("partial", f"Ducommun requisition detail HTTP {response.status}.")
    try:
        data = json.loads(response.body)["data"]
        title = text(data.get("displayTitle") or row.get("displayJobTitle"))
        description = text(data.get("externalDescription") or data.get("jobAd"))
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        raise FetchError("partial", "Ducommun requisition detail response was malformed.") from None
    if not title or len(description) < 100 or "ducommun" not in description.casefold():
        raise FetchError("partial", "Ducommun requisition detail lacks a complete employer-scoped description.")
    return _base({"id": str(rid)}, ATS, company_id, company) | {
        "title": title, "description": description,
        "url": f"https://ducommun.csod.com/ux/ats/careersite/1/requisition/{rid}?c=ducommun",
    }


def fetch_ducommun(url, company_id, company, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Ducommun adapter requires its verified official careers page.", source_url=SOURCE, ats=ATS)
    page_client = transport or CareersTransport()
    api = transport if all(hasattr(transport, name) for name in ("post", "get_with_headers")) else HTTPTransport()
    try:
        token = _token(page_client)
        first = _search(api, token)
        jobs = [_detail(api, token, row, company_id, company) for row in first]
        token2 = _token(page_client)
        second = _search(api, token2)
        if [row.get("requisitionId") for row in first] != [row.get("requisitionId") for row in second]:
            raise FetchError("partial", "Ducommun Cornerstone inventory changed during the reread.")
        return Inventory("complete", jobs, f"Ducommun Cornerstone: retrieved {len(jobs)} postings and rechecked the public inventory.", SOURCE, ATS)
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS)
    except (AttributeError, OSError, TypeError, ValueError):
        return Inventory("partial", [], "Ducommun careers response validation failed.", SOURCE, ATS)
