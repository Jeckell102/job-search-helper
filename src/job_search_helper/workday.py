"""Public Workday CXS listings and full job descriptions.

Verified against Draper, Boeing and Crane public boards on 2026-09-23.
Search POSTs are read-only. No application, login or candidate endpoints.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from .ats import FetchError, Inventory, _base, _json, is_workday_host, text


PAGE_SIZE = 20
MAX_PAGES = 200
TOKEN = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"


def _job_path(path):
    if not isinstance(path, str) or not path.startswith("/job/") or len(path) > 2048:
        raise ValueError("Workday posting has no valid job path.")
    decoded = unquote(path)
    if (any(c in decoded for c in "?#\\%") or any(ord(c) <= 32 or ord(c) == 127 for c in decoded)
            or any(part in ("", ".", "..") for part in decoded.split("/")[1:])):
        raise ValueError("Workday posting has no valid job path.")
    return path


def safe_api_path(parsed):
    parts = parsed.path.split("/")
    if (parsed.query or parsed.fragment or len(parts) < 6 or parts[1:3] != ["wday", "cxs"]
            or parts[3] != parsed.hostname.split(".")[0] or not re.fullmatch(TOKEN, parts[4])):
        return False
    if parts[5:] == ["jobs"]:
        return True
    try:
        _job_path("/" + "/".join(parts[5:]))
        return True
    except ValueError:
        return False


def resolve_workday(ats, url):
    p = urlsplit(url)
    if (p.scheme != "https" or not is_workday_host(p.hostname) or p.username or p.password
            or p.port not in (None, 443)):
        raise ValueError("Provide a verified public Workday HTTPS board URL.")
    parts = [part for part in p.path.split("/") if part]
    tenant = p.hostname.split(".")[0]
    if parts[:2] == ["wday", "cxs"]:
        if len(parts) < 4 or parts[2] != tenant:
            raise ValueError("Workday tenant does not match the board hostname.")
        parts = parts[3:]
    elif parts and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", parts[0]):
        parts = parts[1:]
    if not parts or not re.fullmatch(TOKEN, parts[0]) or parts[0] in {"job", "jobs", "login", "wday"}:
        raise ValueError("Workday URL is missing a valid careers site name.")
    site = parts[0]
    if parts[1:] and parts[1:] != ["jobs"]:
        _job_path("/" + "/".join(parts[1:]))
    scope = {}
    for key, value in parse_qsl(p.query, keep_blank_values=True, max_num_fields=80):
        if key.startswith("utm_") or key == "source":
            continue
        if not re.fullmatch(TOKEN, key) or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise ValueError("Workday URL has an unsupported search/filter parameter.")
        if not value.strip():
            if key == "q":
                continue
            raise ValueError("Workday URL has an empty filter; verify its company scope.")
        scope.setdefault(key, set()).add(value.strip())
    if len(scope.get("q", [])) > 1:
        raise ValueError("Workday URL has conflicting search terms.")
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "icims", "adp", "paylocity")) and "workday" not in configured:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    if any(marker in configured for marker in ("shared", "parent")) and not scope:
        raise ValueError("Shared/parent Workday board requires an explicit company search or filter.")
    query = urlencode([(key, value) for key in sorted(scope) for value in sorted(scope[key])])
    return "Workday", site + ("?" + query if query else ""), f"https://{p.hostname}/wday/cxs/{tenant}/"


def _facet_options(facets):
    options = {}
    for facet in facets if isinstance(facets, list) else []:
        if not isinstance(facet, dict):
            continue
        values = facet.get("values", [])
        if not isinstance(values, list):
            continue
        key = facet.get("facetParameter")
        if isinstance(key, str):
            options.setdefault(key, set()).update(v["id"] for v in values
                if isinstance(v, dict) and isinstance(v.get("id"), str))
        for nested_key, nested_values in _facet_options(values).items():
            options.setdefault(nested_key, set()).update(nested_values)
    return options


def _page(data):
    if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
        raise FetchError("partial", "Workday returned an unexpected listing schema.")
    total, entries = data.get("total"), data["jobPostings"]
    if type(total) is not int or total < 0 or len(entries) > PAGE_SIZE:
        raise FetchError("partial", "Workday returned an invalid count or page size.")
    return total, entries


def _posting(data, path, site, host, company_id, company):
    info = data.get("jobPostingInfo") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        raise ValueError("Workday job detail is missing jobPostingInfo.")
    if info.get("jobPostingSiteId", site) != site or info.get("posted") is False:
        raise ValueError("Workday job detail no longer belongs to this public board.")
    posting_id = info.get("id")
    if not isinstance(posting_id, str) or not posting_id.strip():
        raise ValueError("Workday job detail is missing a stable posting ID.")
    if any(not isinstance(info.get(field), str) for field in ("title", "jobDescription")):
        raise ValueError("Workday job detail is missing its title or full description.")
    # Requisition IDs and title-bearing URL slugs can change; use the opaque ID.
    row = _base({"id": posting_id}, "Workday", company_id, company)
    additional = info.get("additionalLocations") or []
    if not isinstance(additional, list) or any(not isinstance(v, str) for v in additional):
        raise ValueError("Workday job detail has malformed additional locations.")
    row.update(title=text(info.get("title")), description=text(info.get("jobDescription")),
               req_id=text(info.get("jobReqId")), url=f"https://{host}/{site}{path}",
               location="; ".join(dict.fromkeys(filter(None, [text(info.get("location")), *map(text, additional)]))),
               work_arrangement=text(info.get("remoteType")), created_at=text(info.get("startDate")))
    if not row["title"] or not row["description"]:
        raise ValueError("Workday job detail is missing its title or full description.")
    return row


def fetch_workday(board, root, company_id, company, transport):
    source = root + board
    parsed = urlsplit(source)
    site = parsed.path.rsplit("/", 1)[-1]
    endpoint = root + site
    query, facets = "", {}
    for key, value in parse_qsl(parsed.query):
        if key == "q":
            query = value
        else:
            facets.setdefault(key, []).append(value)
    payload = {"appliedFacets": facets, "limit": PAGE_SIZE, "offset": 0, "searchText": query}
    jobs, issues = [], []
    paths, ids = set(), set()
    expected = None
    first_paths = []
    context = "Workday filter validation"
    try:
        if facets:
            unfiltered = _json(endpoint + "/jobs", transport,
                               {**payload, "appliedFacets": {}, "searchText": ""})
            _page(unfiltered)
            options = _facet_options(unfiltered.get("facets"))
            if any(key not in options or not set(values) <= options[key] for key, values in facets.items()):
                raise FetchError("unsupported", "Workday URL filter is unavailable or unrecognized; verify the company's filtered board URL.")
        for page in range(MAX_PAGES):
            context = f"Workday listing page {page + 1}"
            total, entries = _page(_json(endpoint + "/jobs", transport, payload))
            if expected is None:
                expected = total
            # Workday commonly sends total=0 after the first page.
            elif total not in (0, expected):
                raise FetchError("partial", "Workday listing count changed during pagination.")
            if payload["offset"] + len(entries) > expected or (not entries and payload["offset"] < expected):
                raise FetchError("partial", "Workday pages do not match the initial inventory count.")
            page_paths = []
            for index, item in enumerate(entries):
                try:
                    path = _job_path(item.get("externalPath") if isinstance(item, dict) else None)
                    if path in paths:
                        raise FetchError("partial", "Workday repeated a posting/page; inventory is incomplete.")
                    paths.add(path)
                    page_paths.append(path)
                    context = f"Workday job detail https://{parsed.hostname}/{site}{path}"
                    row = _posting(_json(endpoint + path, transport), path, site,
                                   parsed.hostname, company_id, company)
                    if row["posting_id"] in ids:
                        raise FetchError("partial", "Workday returned duplicate posting IDs.")
                    ids.add(row["posting_id"])
                    jobs.append(row)
                except ValueError as error:
                    issues.append(str(error))
                    if len(issues) <= 50:
                        print(json.dumps({"event": "posting_skipped", "provider": "Workday",
                                          "page": page + 1, "item_on_page": index + 1,
                                          "reason": str(error)}), file=sys.stderr)
            if page == 0:
                first_paths = page_paths
            payload["offset"] += len(entries)
            print(json.dumps({"event": "inventory_page", "provider": "Workday", "company_id": company_id,
                              "page": page + 1, "postings_fetched": len(jobs), "expected": expected}), file=sys.stderr)
            if payload["offset"] == expected:
                break
        else:
            raise FetchError("partial", "Workday page cap reached before the inventory ended.")
        if payload["offset"] > PAGE_SIZE:
            # Recheck the first page after pagination to detect a moving board.
            context = "Workday final listing check"
            total, entries = _page(_json(endpoint + "/jobs", transport, {**payload, "offset": 0}))
            current = [item.get("externalPath") for item in entries if isinstance(item, dict)]
            if total != expected or current != first_paths:
                issues.append("Workday board changed during the scan; retry to establish a complete inventory.")
        if len(jobs) != expected:
            issues.append("Workday normalized posting count does not match the inventory count.")
        return Inventory("partial" if issues else "complete", jobs,
                         " ".join(dict.fromkeys(issues)) if issues else
                         f"Workday: retrieved {len(jobs)} full postings in {page + 1} listing pages.", source)
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source)
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs,
                         "Unexpected Workday transport or schema failure; inventory not complete.", source)
