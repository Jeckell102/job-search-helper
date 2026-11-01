"""Bounded public WordPress careers listings for verified employer sites."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from .ats import FetchError, HTTPTransport, Inventory, _base, text


ROOT = "https://greenseaiq.com"
SOURCE = ROOT + "/careers/"
ENDPOINT = ROOT + "/wp-json/wp/v2/career?per_page=100&page="
SITES = {
    "https://xtend.me/careers/": (
        "xtend.me", "https://xtend.me/wp-json/wp/v2/career?per_page=100&page=", "/careers/"),
    "https://airspan.com/careers/airspan-careers/": (
        "airspan.com", "https://airspan.com/wp-json/wp/v2/jobs?per_page=100&page=", "/jobs/"),
    SOURCE: ("greenseaiq.com", ENDPOINT, "/career/"),
    "https://searobotics.com/careers/": (
        "searobotics.com", "https://searobotics.com/wp-json/wp/v2/career?per_page=100&page=", "/career/"),
    "https://www.jaia.tech/careers/": (
        "www.jaia.tech", "https://www.jaia.tech/wp-json/wp/v2/posts?categories=23&per_page=100&page=", "/"),
}


def _header(headers, name):
    return next((v for k, v in headers.items() if k.casefold() == name.casefold()), None)


def _page(transport, endpoint, number):
    response = transport.get(endpoint + str(number))
    if response.status != 200:
        raise FetchError("blocked" if response.status in (401, 403, 429) else "partial",
                         "WordPress public careers listing was unavailable.")
    try:
        records = json.loads(response.body.decode("utf-8"))
        total, pages = int(_header(response.headers, "X-WP-Total")), int(_header(response.headers, "X-WP-TotalPages"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "WordPress public careers listing returned an invalid schema.") from None
    if (type(records) is not list or total < 0 or pages < 1 or pages > 100
            or len(records) > 100 or (not records and total)):
        raise FetchError("partial", "WordPress public careers listing has inconsistent pagination.")
    return records, total, pages


def _posting(record, company_id, company, host, path_prefix):
    if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] <= 0:
        raise ValueError("WordPress career record has no stable ID.")
    link = record.get("link")
    parsed = urlsplit(link if isinstance(link, str) else "")
    if (parsed.scheme != "https" or parsed.hostname != host or not parsed.path.startswith(path_prefix)
            or parsed.query or parsed.fragment):
        raise ValueError("WordPress career record is outside the verified careers scope.")
    title = text((record.get("title") or {}).get("rendered") if isinstance(record.get("title"), dict) else "")
    description = text((record.get("content") or {}).get("rendered") if isinstance(record.get("content"), dict) else "")
    if not title or not description:
        raise ValueError("WordPress career record lacks a title or full description.")
    row = _base({"id": str(record["id"])}, "WordPress careers", company_id, company)
    row.update(title=title, description=description, url=link, created_at=text(record.get("date")))
    return row

def _xtend_posting(record, company_id, company, transport):
    if not isinstance(record, dict) or type(record.get("id")) is not int or record["id"] <= 0:
        raise ValueError("XTEND career record has no stable ID.")
    link = record.get("link")
    parsed = urlsplit(link if isinstance(link, str) else "")
    if parsed.scheme != "https" or parsed.hostname != "xtend.me" or not parsed.path.startswith("/careers/") or parsed.query or parsed.fragment:
        raise ValueError("XTEND career record is outside the verified careers scope.")
    response = transport.get(link)
    if response.status != 200:
        raise ValueError("XTEND career detail was unavailable.")
    title = text((record.get("title") or {}).get("rendered") if isinstance(record.get("title"), dict) else "")
    description = text(response.body.decode("utf-8", "replace"))
    if not title or len(description) < 500:
        raise ValueError("XTEND career detail lacks a full description.")
    row = _base({"id": str(record["id"])}, "WordPress careers", company_id, company)
    row.update(title=title, description=description, url=link, created_at=text(record.get("date")))
    return row


def fetch_wordpress_careers(careers_url, company_id, company, transport=None):
    site = SITES.get(careers_url)
    if site is None:
        return Inventory("unsupported", reason="WordPress careers adapter requires a verified unfiltered employer careers page.",
                         source_url=careers_url, ats="WordPress careers")
    host, endpoint, path_prefix = site
    client = transport or HTTPTransport()
    jobs, identifiers = [], set()
    try:
        first, total, pages = _page(client, endpoint, 1)
        records = list(first)
        for number in range(2, pages + 1):
            current, current_total, current_pages = _page(client, endpoint, number)
            if current_total != total or current_pages != pages:
                raise FetchError("partial", "WordPress careers count changed during pagination.")
            records.extend(current)
        if len(records) != total:
            raise FetchError("partial", "WordPress careers records do not match the published total.")
        for record in records:
            title = text((record.get("title") or {}).get("rendered") if isinstance(record, dict) and isinstance(record.get("title"), dict) else "")
            if company_id == "COMP-0411" and title.casefold() == "interest in future openings":
                continue
            row = (_xtend_posting(record, company_id, company, client)
                   if company_id == "COMP-0175" else _posting(record, company_id, company, host, path_prefix))
            if row["posting_id"] in identifiers:
                raise FetchError("partial", "WordPress careers listing has duplicate posting IDs.")
            identifiers.add(row["posting_id"])
            jobs.append(row)
        check, check_total, check_pages = _page(client, endpoint, 1)
        check_ids = {str(item.get("id")) for item in check if isinstance(item, dict) and not (company_id == "COMP-0411" and text((item.get("title") or {}).get("rendered") if isinstance(item.get("title"), dict) else "").casefold() == "interest in future openings")}
        if check_total != total or check_pages != pages or check_ids != {row["posting_id"] for row in jobs[:len(first)]}:
            raise FetchError("partial", "WordPress careers inventory changed during the scan.")
        return Inventory("complete", jobs, f"WordPress careers: retrieved {len(jobs)} complete postings and rechecked the public inventory.",
                         careers_url, "WordPress careers")
    except FetchError as error:
        return Inventory(error.status, jobs, error.reason, careers_url, "WordPress careers")
    except (AttributeError, KeyError, TypeError, ValueError):
        return Inventory("partial", jobs, "WordPress careers schema validation failed.", careers_url, "WordPress careers")


def fetch_greensea_jobs(careers_url, company_id, company, transport=None):
    return fetch_wordpress_careers(careers_url, company_id, company, transport)
