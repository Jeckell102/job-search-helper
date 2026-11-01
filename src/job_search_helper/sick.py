"""Company-scoped SICK USA SuccessFactors careers inventory."""
from __future__ import annotations

import json
from urllib.parse import quote

from .ats import FetchError, HTTPTransport, Inventory, _base, text
from .successfactors import _Page

SOURCE = "https://jobs.sick.com/usa?locale=en_US"
SEARCH = "https://jobs.sick.com/services/recruiting/v1/jobs"
PAGE_SIZE = 10


def _search(client, page):
    # ``recent`` is the UI default but its order can move while the board is
    # paginated.  The public ``date`` sort is stable for the scan window.
    response = client.post(SEARCH, {"keywords": "", "locale": "en_US", "location": "", "pageNumber": page, "sortBy": "date"})
    if response.status != 200:
        raise FetchError("blocked" if response.status in {401, 403, 429} else "partial", "SICK SuccessFactors search was unavailable.")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "SICK SuccessFactors search returned invalid JSON.") from None
    total, records = payload.get("totalJobs"), payload.get("jobSearchResult")
    if not isinstance(total, int) or not 0 <= total <= 1000 or not isinstance(records, list):
        raise FetchError("partial", "SICK SuccessFactors search returned an invalid inventory shape.")
    if len(records) != min(PAGE_SIZE, max(0, total - page * PAGE_SIZE)):
        raise FetchError("partial", "SICK SuccessFactors page size disagreed with the published total.")
    entries, seen = [], set()
    for record in records:
        row = record.get("response") if isinstance(record, dict) else None
        ident, title, slug = (row or {}).get("id"), (row or {}).get("unifiedStandardTitle"), (row or {}).get("unifiedUrlTitle")
        if (row.get("brandUrl") != "usa" or "en_US" not in (row.get("supportedLocales") or [])):
            continue
        if (not isinstance(ident, str) or not ident.isdigit() or ident in seen or not isinstance(title, str) or not title.strip() or not isinstance(slug, str) or not slug.strip()):
            raise FetchError("partial", "SICK SuccessFactors returned an invalid posting identity.")
        seen.add(ident); entries.append((ident, title.strip(), slug.strip()))
    return total, entries


def fetch_sick(url, company_id, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="SICK adapter requires the official USA careers page.", source_url=url, ats="SuccessFactors")
    client = transport or HTTPTransport(); jobs = []
    try:
        total, first = _search(client, 0); entries = list(first)
        for page in range(1, (total + PAGE_SIZE - 1) // PAGE_SIZE):
            current, page_entries = _search(client, page)
            if current != total: raise FetchError("partial", "SICK inventory changed during pagination.")
            entries.extend(page_entries)
        if len({x[0] for x in entries}) != len(entries) or not entries:
            raise FetchError("partial", "SICK pagination did not produce a USA inventory.")
        for ident, title, slug in entries:
            detail_url = f"https://jobs.sick.com/usa/job/{quote(slug, safe='-%()')}/{ident}-en_US/"
            response = client.get(detail_url)
            if response.status != 200: raise FetchError("blocked" if response.status in {401,403,429} else "partial", "SICK posting detail was unavailable.")
            page = _Page(response.body.decode("utf-8", "replace")); detail_title = text("".join(page.title)).strip(); description = text("".join(page.description)).strip()
            if detail_title != title or not description: raise FetchError("partial", f"SICK posting {ident} lacked a complete matching detail body.")
            row = _base({"id": ident}, "SuccessFactors", company_id, company); row.update(title=title, url=detail_url, description=description, req_id=ident); jobs.append(row)
        check_total, check_first = _search(client, 0)
        if check_total != total or check_first != first: raise FetchError("partial", "SICK inventory changed during the installed reread.")
        return Inventory("complete", jobs, f"SICK SuccessFactors: retrieved and rechecked {len(jobs)} complete postings.", url, "SuccessFactors")
    except FetchError as exc:
        return Inventory(exc.status if not jobs else "partial", jobs, exc.reason, url, "SuccessFactors")
    except (KeyError, TypeError, UnicodeDecodeError):
        return Inventory("partial", jobs, "SICK SuccessFactors public schema validation failed.", url, "SuccessFactors")
