"""Official Quantum Systems USA WordPress jobs feed."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .ats import FetchError, HTTPTransport, Inventory, _base, text

CAREERS_URL = "https://quantum-systems.com/us/jobs-quantum-usa/"
ENDPOINT = "https://quantum-systems.com/us/wp-json/wp/v2/posts?categories=75&per_page=100&page="
HOST = "quantum-systems.com"
PATH_PREFIX = "/us/jobs/"


def _header(headers, name):
    return next((value for key, value in headers.items() if key.casefold() == name.casefold()), None)


def _page(transport, number):
    response = transport.get(ENDPOINT + str(number))
    if response.status != 200:
        status = "blocked" if response.status in (401, 403, 429) else "partial"
        raise FetchError(status, f"Quantum Systems USA WordPress jobs API returned HTTP {response.status}.")
    try:
        records = json.loads(response.body.decode("utf-8"))
        total = int(_header(response.headers, "X-WP-Total"))
        pages = int(_header(response.headers, "X-WP-TotalPages"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "Quantum Systems USA jobs API returned an invalid schema.") from None
    if (type(records) is not list or total < 0 or pages < 1 or pages > 100
            or len(records) > 100 or (not records and total)):
        raise FetchError("partial", "Quantum Systems USA jobs API returned inconsistent pagination.")
    return records, total, pages


def _posting(record, company_id, company):
    if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] <= 0:
        raise ValueError("Quantum Systems USA job has no stable ID.")
    link = record.get("link")
    parsed = urlsplit(link if isinstance(link, str) else "")
    if (parsed.scheme != "https" or parsed.hostname != HOST or not parsed.path.startswith(PATH_PREFIX)
            or parsed.query or parsed.fragment):
        raise ValueError("Quantum Systems USA job is outside the verified USA careers scope.")
    title = text((record.get("title") or {}).get("rendered") if isinstance(record.get("title"), dict) else "")
    description = text((record.get("content") or {}).get("rendered") if isinstance(record.get("content"), dict) else "")
    if not title or not description:
        raise ValueError("Quantum Systems USA job lacks a title or full description.")
    row = _base({"id": str(record["id"])}, "Quantum Systems USA careers", company_id, company)
    row.update(title=title, description=description, url=link, created_at=text(record.get("date")))
    return row


def fetch_quantum_systems(careers_url, company_id, company, transport=None):
    client = transport or HTTPTransport()
    jobs, ids = [], set()
    try:
        first, total, pages = _page(client, 1)
        records = list(first)
        for number in range(2, pages + 1):
            current, current_total, current_pages = _page(client, number)
            if current_total != total or current_pages != pages:
                raise FetchError("partial", "Quantum Systems USA jobs count changed during pagination.")
            records.extend(current)
        if len(records) != total:
            raise FetchError("partial", "Quantum Systems USA job records do not match the published total.")
        for record in records:
            row = _posting(record, company_id, company)
            if row["posting_id"] in ids:
                raise FetchError("partial", "Quantum Systems USA jobs API has duplicate posting IDs.")
            ids.add(row["posting_id"])
            jobs.append(row)
        check, check_total, check_pages = _page(client, 1)
        check_ids = {str(item.get("id")) for item in check if isinstance(item, dict)}
        if check_total != total or check_pages != pages or check_ids != {row["posting_id"] for row in jobs[:len(first)]}:
            raise FetchError("partial", "Quantum Systems USA job inventory changed during the scan.")
        return Inventory("complete", jobs,
                         f"Quantum Systems USA WordPress jobs: retrieved and rechecked {len(jobs)} postings.",
                         careers_url or CAREERS_URL, "Quantum Systems USA careers")
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, careers_url or CAREERS_URL, "Quantum Systems USA careers")
    except (AttributeError, KeyError, TypeError, ValueError):
        return Inventory("partial", jobs, "Quantum Systems USA jobs schema validation failed.",
                         careers_url or CAREERS_URL, "Quantum Systems USA careers")
