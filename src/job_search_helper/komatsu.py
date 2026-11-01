"""Public Komatsu SuccessFactors inventory adapter.

Komatsu's branded board renders results through its first-party recruiting JSON
endpoint rather than server-side job links.  Keep the endpoint and detail URL
construction pinned to the official komatsu.jobs host.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

from .ats import FetchError, HTTPResponse, HTTPTransport, Inventory, _base, text
from .successfactors import _Page

SOURCE = "https://komatsu.jobs/viewalljobs/"
SEARCH = "https://komatsu.jobs/services/recruiting/v1/jobs"
PAGE_SIZE = 10
MAX_PAGES = 100


def _json(transport, payload):
    response = transport.post(SEARCH, payload, headers={"Content-Type": "application/json"})
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "Komatsu transport returned an invalid response.")
    if response.status in (401, 403, 429):
        raise FetchError("blocked", f"Komatsu public recruiting API returned HTTP {response.status}.")
    if response.status != 200:
        raise FetchError("partial", f"Komatsu public recruiting API returned HTTP {response.status}.")
    import json
    try:
        return json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "Komatsu recruiting API returned non-JSON data.") from None


def fetch_komatsu(url, company_id, company, transport=None):
    if url != SOURCE:
        return Inventory("unsupported", reason="Komatsu adapter requires the verified komatsu.jobs source.", source_url=url, ats="SuccessFactors")
    client = transport or HTTPTransport()
    jobs = []
    seen = set()
    try:
        total = None
        for page in range(MAX_PAGES):
            data = _json(client, {"keywords": "", "locale": "en_US", "location": "", "pageNumber": page, "sortBy": "recent"})
            rows = data.get("jobSearchResult")
            current_total = data.get("totalJobs")
            if not isinstance(rows, list) or not isinstance(current_total, int) or current_total < 0:
                raise FetchError("partial", "Komatsu API returned an invalid inventory envelope.")
            if total is None:
                total = current_total
            elif current_total != total:
                raise FetchError("partial", "Komatsu inventory total changed during pagination.")
            if not rows:
                if len(seen) != total:
                    raise FetchError("partial", "Komatsu API ended before publishing the advertised inventory.")
                break
            for wrapper in rows:
                record = wrapper.get("response") if isinstance(wrapper, dict) else None
                ident = record.get("id") if isinstance(record, dict) else None
                slug = record.get("urlTitle") if isinstance(record, dict) else None
                title = record.get("unifiedStandardTitle") if isinstance(record, dict) else None
                if not (isinstance(ident, str) and re.fullmatch(r"[1-9][0-9]{2,15}", ident)
                        and isinstance(slug, str) and slug and isinstance(title, str) and title.strip()):
                    raise FetchError("partial", "Komatsu API published a job result without a stable requisition identity.")
                if ident in seen:
                    raise FetchError("partial", "Komatsu API repeated a requisition during pagination.")
                seen.add(ident)
                detail_url = f"https://komatsu.jobs/job/{slug}/{ident}-en_US"
                jobs.append((ident, title.strip(), detail_url))
            if len(seen) >= total:
                break
        else:
            raise FetchError("partial", "Komatsu API exceeded the bounded page limit.")
        if total is None or len(jobs) != total:
            raise FetchError("partial", "Komatsu API record count disagreed with totalJobs.")

        def detail(entry):
            ident, title, detail_url = entry
            response = client.get(detail_url)
            if response.status != 200:
                raise FetchError("partial", f"Komatsu posting {ident} detail returned HTTP {response.status}.")
            page = _Page(response.body.decode("utf-8", "replace"))
            detail_title = text("".join(page.title))
            description = text("".join(page.description))
            if not detail_title or not description:
                raise FetchError("partial", f"Komatsu posting {ident} lacks a full public title or description.")
            row = _base({"id": ident}, "SuccessFactors", company_id, company)
            row.update(title=title, url=detail_url, description=description, req_id=ident)
            return row

        with ThreadPoolExecutor(max_workers=12) as pool:
            complete_jobs = list(pool.map(detail, jobs))
        if len(complete_jobs) != total:
            raise FetchError("partial", "Komatsu detail count disagreed with the public inventory.")
        return Inventory("complete", complete_jobs, f"Komatsu: retrieved {len(complete_jobs)} complete postings and rechecked the public inventory.", SOURCE, "SuccessFactors")
    except FetchError as exc:
        return Inventory(exc.status if not jobs else "partial", [], exc.reason, SOURCE, "SuccessFactors")
    except (AttributeError, TypeError, ValueError):
        return Inventory("partial", [], "Komatsu public schema validation failed.", SOURCE, "SuccessFactors")
