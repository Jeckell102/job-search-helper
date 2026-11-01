"""Public Workday CXS listings and full job descriptions.

Verified against Draper, Boeing and Crane public boards on 2026-09-23.
Search POSTs are read-only. No application, login or candidate endpoints.
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit

from .ats import FetchError, Inventory, _base, _json, is_workday_host, text


PAGE_SIZE = 20
MAX_PAGES = 200
# Leidos's public CXS endpoint currently returns this maximum even though its
# public facet counts show a larger board. Preserve fetched postings, but
# never use that truncated result to infer closures.
LEIDOS_RESULT_CAP = 2000
LEIDOS_HOST = "leidos.wd5.myworkdayjobs.com"
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
    # Workday site IDs preserve the board's configured casing (for example
    # Fugro returns ``Careers`` while its public URL uses ``careers``).
    # Treat that provider-owned token case-insensitively while retaining the
    # exact tenant/site path for endpoint and URL validation.
    posting_site = info.get("jobPostingSiteId", site)
    if (not isinstance(posting_site, str) or posting_site.casefold() != site.casefold()
            or info.get("posted") is False):
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


def _job_family_groups(data):
    """Return the exact public Leidos job-family IDs and advertised counts."""
    facets = data.get("facets") if isinstance(data, dict) else []
    family = [facet for facet in facets if isinstance(facet, dict)
              and facet.get("facetParameter") == "jobFamilyGroup"]
    if len(family) != 1 or not isinstance(family[0].get("values"), list):
        return {}
    groups = {}
    for value in family[0]["values"]:
        ident = value.get("id") if isinstance(value, dict) else None
        count = value.get("count") if isinstance(value, dict) else None
        if (not isinstance(ident, str) or not re.fullmatch(TOKEN, ident)
                or (count is not None and (type(count) is not int or count < 0)) or ident in groups):
            return {}
        groups[ident] = count
    return groups if len(groups) > 1 else {}


def _complete_listing_pass(endpoint, payload, expected_hint, transport):
    """Enumerate one complete, duplicate-free Workday listing cohort."""
    expected = None
    offset = 0
    pages = []
    items = {}
    for page_number in range(MAX_PAGES):
        data = _json(endpoint + "/jobs", transport, {**payload, "offset": offset})
        total, entries = _page(data)
        if expected is None:
            expected = total
        elif total not in (0, expected):
            raise FetchError("partial", "Workday refreshed listing count changed during pagination.")
        remaining = expected - offset
        if offset + len(entries) > expected or (not entries and offset < expected):
            raise FetchError("partial", "Workday refreshed pages do not match the inventory count.")
        # Every nonterminal page must be full.  A short page is terminal only
        # when it lands exactly on the advertised total; this prevents a
        # silent skipped range from being mistaken for a complete board.
        if entries and len(entries) < min(PAGE_SIZE, remaining) and offset + len(entries) != expected:
            raise FetchError("partial", "Workday refreshed page ended before the inventory count.")
        page_paths = []
        for item in entries:
            path = _job_path(item.get("externalPath") if isinstance(item, dict) else None)
            if path in items:
                raise FetchError("partial", "Workday refreshed listing repeated a posting.")
            items[path] = item
            page_paths.append(path)
        pages.append(page_paths)
        offset += len(entries)
        if offset == expected:
            return expected, pages, items
    raise FetchError("partial", "Workday refreshed listing reached its page cap before completion.")


def _listing_fingerprint(item):
    if not isinstance(item, dict):
        return ()
    def stable(value):
        if isinstance(value, (list, tuple)):
            return tuple(stable(v) for v in value)
        if isinstance(value, dict):
            return tuple(sorted((str(k), stable(v)) for k, v in value.items()))
        return text(value)
    return tuple(stable(item.get(key)) for key in ("title", "jobReqId", "bulletFields", "locationsText"))


def _cohort_equal(left, right):
    """Compare complete listing cohorts, ignoring harmless ordering changes."""
    left_total, left_pages, left_items = left
    right_total, right_pages, right_items = right
    return (left_total == right_total
            and [len(page) for page in left_pages] == [len(page) for page in right_pages]
            and set(left_items) == set(right_items)
            and all(_listing_fingerprint(left_items[path]) == _listing_fingerprint(right_items[path])
                    for path in left_items))


def _reconcile_changed_workday(endpoint, payload, expected, site, host, company_id,
                                company, transport, existing_jobs, original_items=None,
                                first_cohort=None):
    """Recover one moving final cohort without unioning two board snapshots."""
    try:
        first_cohort = first_cohort or _complete_listing_pass(endpoint, payload, expected, transport)
        first_total, first_pages, first_items = first_cohort
        existing_by_path = {}
        for row in existing_jobs:
            parsed = urlsplit(row.get("url", ""))
            if (parsed.scheme == "https" and parsed.hostname == host and parsed.port in (None, 443)
                    and parsed.query == "" and parsed.fragment == ""
                    and parsed.path.startswith("/" + site + "/")):
                existing_by_path[parsed.path[len(site) + 1:]] = row
        jobs, ids = [], set()
        for path, item in first_items.items():
            old = existing_by_path.get(path)
            listed_title = text(item.get("title")) if isinstance(item, dict) else ""
            listed_req = text(item.get("jobReqId")) if isinstance(item, dict) else ""
            original = (original_items or {}).get(path)
            if (old is not None and original is not None
                    and _listing_fingerprint(original) == _listing_fingerprint(item)
                    and old.get("title") == listed_title
                    and (not listed_req or old.get("req_id") == listed_req)):
                row = old
            else:
                row = _posting(_json(endpoint + path, transport), path, site, host, company_id, company)
            if row["posting_id"] in ids:
                return None, "Workday refreshed details returned duplicate posting IDs."
            ids.add(row["posting_id"])
            jobs.append(row)
        # The board may move while details are being fetched.  Re-read every
        # page after all fresh details, and only accept the cohort if its
        # count, page shape, membership, and listing metadata are unchanged.
        second_cohort = _complete_listing_pass(endpoint, payload, first_total, transport)
        if not _cohort_equal(first_cohort, second_cohort):
            return None, "Workday refreshed listing cohort changed after detail retrieval."
        second_items = second_cohort[2]
        second_total = second_cohort[0]
        if len(jobs) != second_total:
            return None, "Workday refreshed details did not cover the complete listing cohort."
        return jobs, f"Workday reconciled cohort: {len(jobs)} postings across {len(second_cohort[1])} listing pages."
    except FetchError as error:
        if error.status == "blocked":
            raise
        return None, "Workday refreshed cohort could not be verified: " + error.reason
    except (OSError, ValueError, TypeError, AttributeError, StopIteration) as error:
        return None, "Workday refreshed cohort could not be verified: " + str(error)


def _exhaustive_facet_maps(data):
    """Return exact optional exhaustive facet ID/count maps."""
    names = ("workerSubType", "timeType", "Is_Evergreen")
    facets = data.get("facets", []) if isinstance(data, dict) else []
    result = {}
    for name in names:
        matches = [facet for facet in facets
                   if isinstance(facet, dict) and facet.get("facetParameter") == name]
        if not matches:
            continue
        if len(matches) != 1 or not isinstance(matches[0].get("values"), list):
            raise FetchError("partial", "Leidos exhaustive facet schema is malformed.")
        mapped = {}
        for value in matches[0]["values"]:
            ident = value.get("id") if isinstance(value, dict) else None
            count = value.get("count") if isinstance(value, dict) else None
            if (not isinstance(ident, str) or not ident or ident in mapped
                    or type(count) is not int or count < 0):
                raise FetchError("partial", "Leidos exhaustive facet values are malformed.")
            mapped[ident] = count
        result[name] = mapped
    return result


def _validate_exhaustive_facet_maps(data, expected=None):
    actual = _exhaustive_facet_maps(data)
    if expected is not None and actual != expected:
        raise FetchError("partial", "Leidos exhaustive facet counts changed during the capped scan.")
    return actual


def _fetch_leidos_partitions(endpoint, payload, site, host, company_id, company, transport, initial, *, _allow_refresh=True, _detail_cache=None):
    """Fail closed while recovering Leidos's documented 2,000-result cap."""
    groups = _job_family_groups(initial)
    if not groups or any(type(count) is not int or count < 0 for count in groups.values()):
        return None
    advertised_family_total = sum(groups.values())
    # Leidos' global endpoint is capped, so its facet totals may exceed the
    # global result count. Retain exact optional exhaustive maps for every
    # global reread; accepting drift would create hidden membership gaps.
    exhaustive_maps = _validate_exhaustive_facet_maps(initial)
    for facet_map in exhaustive_maps.values():
        if sum(facet_map.values()) != advertised_family_total:
            raise FetchError("partial", "Leidos exhaustive facet counts do not match job-family coverage.")
    paths, jobs, ids = set(), [], set()
    partition_total = 0
    detail_cache = {} if _detail_cache is None else _detail_cache
    cache_hits = 0
    fresh_details = 0

    def enumerate_partition(group):
        """Capture one complete partition; later total=0 pages may omit facets."""
        scoped = {**payload, "appliedFacets": {"jobFamilyGroup": [group]},
                  "searchText": "", "offset": 0}
        expected, offset, pages, items = None, 0, [], {}
        for page_number in range(MAX_PAGES):
            data = _json(endpoint + "/jobs", transport, {**scoped, "offset": offset})
            total, entries = _page(data)
            facet_map = _job_family_groups(data)
            if page_number == 0:
                if facet_map != groups:
                    raise FetchError("partial", "Leidos job-family facets changed during partition scan.")
                expected = total
                if ((groups[group] is not None and expected != groups[group])
                        or expected >= LEIDOS_RESULT_CAP):
                    raise FetchError("partial", "Leidos job-family partition reached the 2,000-result ceiling.")
            else:
                if facet_map and facet_map != groups:
                    raise FetchError("partial", "Leidos job-family facets changed during partition scan.")
                if total not in (0, expected):
                    raise FetchError("partial", "Leidos job-family partition count changed during pagination.")
            remaining = expected - offset
            if offset + len(entries) > expected or (not entries and offset < expected):
                raise FetchError("partial", "Leidos job-family partition pages do not match its inventory count.")
            if entries and len(entries) < min(PAGE_SIZE, remaining) and offset + len(entries) != expected:
                raise FetchError("partial", "Leidos job-family partition ended before its inventory count.")
            page_paths = []
            for item in entries:
                try:
                    path = _job_path(item.get("externalPath") if isinstance(item, dict) else None)
                except ValueError as error:
                    raise FetchError("partial", "Leidos job-family listing has an invalid posting path.") from error
                if path in items:
                    raise FetchError("partial", "Leidos job-family partition repeated a posting.")
                items[path] = item
                page_paths.append(path)
            pages.append(page_paths)
            offset += len(entries)
            if offset == expected:
                return expected, pages, items
        raise FetchError("partial", "Leidos job-family partition page cap reached before completion.")

    cohorts = {}
    detail_issues = []
    details_started = False
    try:
        for group in sorted(groups):
            expected, pages, items = enumerate_partition(group)
            overlap = paths.intersection(items)
            if overlap:
                raise FetchError("partial", "Leidos job-family partitions overlap or repeat a posting.")
            paths.update(items)
            cohorts[group] = (expected, pages, items)
            partition_total += expected
        global_recheck = _json(endpoint + "/jobs", transport, payload)
        global_total, _ = _page(global_recheck)
        _validate_exhaustive_facet_maps(global_recheck, exhaustive_maps)
        advertised = [count for count in groups.values() if count is not None]
        if (global_total != LEIDOS_RESULT_CAP or _job_family_groups(global_recheck) != groups
                or (len(advertised) == len(groups) and partition_total != sum(advertised))
                or partition_total < LEIDOS_RESULT_CAP):
            raise FetchError("partial", "Leidos job-family partitions do not cover the capped global inventory.")
        detail_items = sorted((path, item) for cohort in cohorts.values() for path, item in cohort[2].items())
        detail_issues = []
        def fetch_detail(entry):
            nonlocal cache_hits, fresh_details
            path, item = entry
            cached = detail_cache.get(path)
            if cached is not None and cached[0] == _listing_fingerprint(item):
                row = cached[1]
                reqs = [str(v) for v in (item.get("bulletFields") or [])] if isinstance(item, dict) else []
                if (row.get("title") == text(item.get("title"))
                        and row.get("req_id") and row["req_id"] in reqs
                        and row.get("posting_id")
                        and row.get("url") == f"https://{host}/{site}{path}"):
                    cache_hits += 1
                    return path, row, None
            try:
                row = _posting(_json(endpoint + path, transport), path, site, host, company_id, company)
                detail_cache[path] = (_listing_fingerprint(item), row)
                fresh_details += 1
                return path, row, None
            except FetchError as error:
                if error.status == "blocked":
                    raise
                return path, None, error
            except (OSError, ValueError, TypeError, AttributeError) as error:
                return path, None, error
        details_started = True
        pool = (ThreadPoolExecutor(max_workers=8)
                if transport.__class__.__name__ == "HTTPTransport" else None)
        try:
            detail_iter = pool.map(fetch_detail, detail_items) if pool else map(fetch_detail, detail_items)
            for index, (path, row, error) in enumerate(detail_iter, 1):
                if error is not None:
                    detail_issues.append(f"{path}: {error}")
                    continue
                if row["posting_id"] in ids:
                    raise FetchError("partial", "Leidos job-family partitions returned duplicate posting IDs.")
                ids.add(row["posting_id"]); jobs.append(row)
                if len(jobs) and len(jobs) % 100 == 0:
                    print(f"{company}: Leidos fetched {len(jobs)}/{len(detail_items)} jobs.", flush=True)
        finally:
            if pool:
                pool.shutdown(wait=True, cancel_futures=True)

        if detail_issues:
            return Inventory("partial", jobs,
                             "Leidos Workday listing reached its 2,000-result ceiling; "
                             + "; ".join(detail_issues[:50]), endpoint)

        # Final proof rereads every partition after all details, then checks
        # the global facet map and the complete path/metadata cohort.
        final_paths = set()
        for group in sorted(groups):
            final = enumerate_partition(group)
            original = cohorts[group]
            if (final[0] != original[0]
                    or [len(page) for page in final[1]] != [len(page) for page in original[1]]
                    or set(final[2]) != set(original[2])
                    or any(_listing_fingerprint(original[2][path]) != _listing_fingerprint(final[2][path])
                           for path in original[2])):
                raise FetchError("partial", "Leidos job-family partitions changed after detail retrieval.")
            if final_paths.intersection(final[2]):
                raise FetchError("partial", "Leidos job-family partitions overlap during final recheck.")
            final_paths.update(final[2])
        global_final = _json(endpoint + "/jobs", transport, payload)
        final_total, _ = _page(global_final)
        _validate_exhaustive_facet_maps(global_final, exhaustive_maps)
        if (final_total != global_total or _job_family_groups(global_final) != groups
                or final_paths != paths):
            raise FetchError("partial", "Leidos global listing changed after detail retrieval.")
        return Inventory("complete", jobs, f"Leidos Workday: retrieved {len(jobs)} postings across {len(groups)} rechecked job-family partitions (cached details {cache_hits}, refetched details {fresh_details}).", endpoint)
    except FetchError as error:
        # Access denials are terminal for this run; preserve verified jobs and
        # do not spend another request on reconciliation.
        if error.status == "blocked":
            return Inventory("blocked", jobs,
                             "Leidos Workday listing reached its 2,000-result ceiling; " + error.reason,
                             endpoint)
        # A complete initial cohort can be invalidated by a transient/malformed
        # final reread. Reconcile once against a newly enumerated global cohort;
        # never union cohorts and never retry detail failures.
        if _allow_refresh and details_started and not detail_issues and len(jobs) == partition_total:
            try:
                current = _json(endpoint + "/jobs", transport, payload)
                # The refreshed cohort may add/remove jobs or categories.
                # Its own exhaustive maps and full closure must be stable;
                # requiring the old counts would prevent normal removals.
                refreshed = _fetch_leidos_partitions(
                    endpoint, payload, site, host, company_id, company, transport, current,
                    _allow_refresh=False, _detail_cache=detail_cache)
                if refreshed is not None and refreshed.status == "blocked":
                    return Inventory("blocked", jobs, refreshed.reason, endpoint)
                if refreshed is not None and refreshed.status == "complete":
                    refreshed.reason = (refreshed.reason +
                                        " Reconciled once after final listing drift; "
                                        "reused matching in-run details where possible.")
                    return refreshed
            except FetchError as refresh_error:
                if refresh_error.status == "blocked":
                    return Inventory("blocked", jobs, refresh_error.reason, endpoint)
            except (OSError, ValueError, TypeError, AttributeError, KeyError, StopIteration):
                pass
        return Inventory("partial", jobs,
                         "Leidos Workday listing reached its 2,000-result ceiling; " + error.reason,
                         endpoint)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return Inventory("partial", jobs, "Leidos Workday listing reached its 2,000-result ceiling; job-family partition schema changed; inventory not complete.", endpoint)


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
    listing_items = {}
    listing_pages = []
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
        queued = []
        listing_complete = False
        try:
            for page in range(MAX_PAGES):
                context = f"Workday listing page {page + 1}"
                data = _json(endpoint + "/jobs", transport, payload)
                total, entries = _page(data)
                if expected is None:
                    expected = total
                    if parsed.hostname == LEIDOS_HOST and expected == LEIDOS_RESULT_CAP:
                        issues.append("Leidos Workday listing reached its 2,000-result ceiling; inventory may be truncated.")
                        if (company_id == "COMP-0003" and site == "External" and not query and not facets):
                            partitioned = _fetch_leidos_partitions(endpoint, payload, site, parsed.hostname,
                                                                   company_id, company, transport, data)
                            if partitioned is not None:
                                return partitioned
                elif total not in (0, expected):
                    raise FetchError("partial", "Workday listing count changed during pagination.")
                if payload["offset"] + len(entries) > expected or (not entries and payload["offset"] < expected):
                    raise FetchError("partial", "Workday pages do not match the initial inventory count.")
                page_paths = []
                for index, item in enumerate(entries):
                    try:
                        path = _job_path(item.get("externalPath") if isinstance(item, dict) else None)
                    except ValueError as error:
                        issues.append(str(error))
                        continue
                    if path in paths:
                        raise FetchError("partial", "Workday repeated a posting/page; inventory is incomplete.")
                    paths.add(path)
                    listing_items[path] = item
                    page_paths.append(path)
                    queued.append((path, page + 1, index + 1))
                if page == 0:
                    first_paths = page_paths
                listing_pages.append(page_paths)
                payload["offset"] += len(entries)
                if payload["offset"] == expected:
                    listing_complete = True
                    break
            else:
                raise FetchError("partial", "Workday page cap reached before the inventory ended.")
        except FetchError as error:
            if error.status == "blocked":
                raise
            issues.append(context + ": " + error.reason)
        # Capture the inventory quickly before slow detail requests can reorder pages.
        # A failed enumeration stays partial, but verified details remain useful.
        def detail_result(item):
            path, page_number, item_number = item
            try:
                return item, _posting(_json(endpoint + path, transport), path, site,
                                      parsed.hostname, company_id, company), None
            except (FetchError, OSError, ValueError, TypeError, AttributeError, StopIteration) as error:
                return item, None, error
            except ValueError as error:
                return item, None, error

        # Large public Workday boards can expose thousands of independently
        # addressable detail records.  Keep listing enumeration and final
        # reconciliation serial, while validating details with a bounded pool
        # on the real HTTP transport.  Injected test transports remain serial
        # so deterministic response fixtures keep their ordering semantics.
        pool = (ThreadPoolExecutor(max_workers=8)
                if transport.__class__.__name__ == "HTTPTransport" else None)
        try:
            detail_iter = pool.map(detail_result, queued) if pool else map(detail_result, queued)
            for (path, page_number, item_number), row, error in detail_iter:
                context = f"Workday job detail https://{parsed.hostname}/{site}{path}"
                try:
                    if error is not None:
                        raise error
                    if row["posting_id"] in ids:
                        raise FetchError("partial", "Workday returned duplicate posting IDs.")
                    ids.add(row["posting_id"])
                    jobs.append(row)
                except FetchError as error:
                    if error.status == "blocked":
                        raise
                    issues.append(context + ": " + error.reason)
                except ValueError as error:
                    issues.append(str(error))
                    if len(issues) <= 50:
                        print(json.dumps({"event": "posting_skipped", "provider": "Workday",
                                          "page": page_number, "item_on_page": item_number,
                                          "reason": str(error)}), file=sys.stderr)
                if len(jobs) and len(jobs) % 100 == 0:
                    print(f"{company}: Workday fetched {len(jobs)}/{expected} jobs.", flush=True)
        finally:
            if pool:
                pool.shutdown(wait=True)
        if listing_complete and payload["offset"] > PAGE_SIZE:
            # Recheck every page after detail retrieval. A first-page-only
            # check can miss a later-page replacement and falsely complete.
            context = "Workday final listing check"
            final_cohort = None
            try:
                final_cohort = _complete_listing_pass(endpoint, payload, expected, transport)
                initial_cohort = (expected, listing_pages, listing_items)
                stable = _cohort_equal(initial_cohort, final_cohort)
            except FetchError as error:
                if error.status == "blocked":
                    raise
                stable = False
                final_cohort = None
                final_error = error
            if not stable:
                # If this is the sole issue and every original detail was
                # verified, reconcile the refreshed cohort in two complete
                # passes.  Never union moving snapshots: removed postings are
                # dropped only after the refreshed global set is stable.
                if not issues and len(jobs) == expected:
                    refreshed, refresh_issue = _reconcile_changed_workday(
                        endpoint, payload, expected, site, parsed.hostname,
                        company_id, company, transport, jobs, listing_items,
                        final_cohort)
                    if refreshed is not None:
                        jobs = refreshed
                        ids = {row["posting_id"] for row in jobs}
                        expected = len(jobs)
                        reconciliation_note = refresh_issue
                    else:
                        issues.append(refresh_issue or "Workday board changed during the scan; retry to establish a complete inventory.")
                else:
                    if final_cohort is None:
                        issues.append("Workday final listing check: " + str(final_error))
                    else:
                        issues.append("Workday board changed during the scan; retry to establish a complete inventory.")
        if len(jobs) != expected:
            issues.append("Workday normalized posting count does not match the inventory count.")
        message = " ".join(dict.fromkeys(issues)) if issues else \
                  f"Workday: retrieved {len(jobs)} full postings in {page + 1} listing pages."
        if not issues and 'reconciliation_note' in locals() and reconciliation_note:
            message = reconciliation_note
        return Inventory("partial" if issues else "complete", jobs, message, source)
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source)
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs,
                         "Unexpected Workday transport or schema failure; inventory not complete.", source)
