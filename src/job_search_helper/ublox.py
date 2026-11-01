"""Pinned public u-blox Algolia and Salesforce careers inventory."""
from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from .ats import FetchError, HTTPResponse, Inventory, _base, _challenge
from .core import plain_text


CAREERS = "https://www.u-blox.com/en/job-openings"
SEARCH = "https://l87m8knomj-dsn.algolia.net/1/indexes/open_positions_en-US/query"
DETAIL_HOST = "fs-4627.my.salesforce-sites.com"
DETAIL_PATH = "/recruit/fRecruit__ApplyJob"
JSON_LD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def supports_ublox(ats: str, url: str) -> bool:
    return url == CAREERS and (not ats.strip() or ats.casefold() == "salesforce-hosted recruiting")


def _json(response: HTTPResponse) -> dict:
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "u-blox transport must return HTTPResponse.")
    if response.status in (401, 403) or _challenge(response):
        raise FetchError("blocked", "u-blox public job inventory is access denied or requires human verification.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"u-blox public inventory returned HTTP {response.status}.")
    try:
        data = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise FetchError("partial", "u-blox public inventory returned non-JSON data.") from None
    if not isinstance(data, dict):
        raise FetchError("partial", "u-blox public inventory schema changed.")
    return data


def _detail_url(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise ValueError("u-blox posting lacks a public detail URL.")
    parsed = urlsplit(value)
    query = parse_qs(parsed.query, keep_blank_values=True)
    vacancy = query.get("vacancyNo", [])
    if (parsed.scheme != "https" or parsed.hostname != DETAIL_HOST or parsed.path != DETAIL_PATH
            or set(query) != {"vacancyNo"} or len(vacancy) != 1 or not re.fullmatch(r"VN[0-9]{1,20}", vacancy[0])):
        raise ValueError("u-blox posting has an unexpected public detail URL.")
    return value, vacancy[0]


def _description(response: HTTPResponse, title: str) -> str:
    if not isinstance(response, HTTPResponse):
        raise FetchError("failed", "u-blox detail transport must return HTTPResponse.")
    if response.status in (401, 403) or _challenge(response, expect_html=True):
        raise FetchError("blocked", "u-blox public job detail is access denied or requires human verification.")
    if not 200 <= response.status < 300:
        raise FetchError("failed", f"u-blox public job detail returned HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    for raw in JSON_LD.findall(body):
        try:
            data = json.loads(unescape(raw))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting" and plain_text(data.get("title", "")) == title:
            description = plain_text(data.get("description", ""))
            if description:
                return description
    raise FetchError("partial", "u-blox public detail lacks a matching nonempty job description.")


def _posting(entry: object, company_id: str, company: str, transport) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("u-blox posting is not an object.")
    posting_id = entry.get("id")
    title = plain_text(entry.get("name", ""))
    url, vacancy = _detail_url(entry.get("link_https"))
    locations = entry.get("locations_legacy") or []
    if (not isinstance(posting_id, str) or not re.fullmatch(r"[A-Za-z0-9]{10,40}", posting_id)
            or not title or not isinstance(locations, list) or any(not isinstance(x, str) or not plain_text(x) for x in locations)):
        raise ValueError("u-blox posting schema changed.")
    row = _base({"id": posting_id}, "Salesforce-hosted recruiting", company_id, company)
    row.update(req_id=vacancy, title=title, url=url, location="; ".join(dict.fromkeys(plain_text(x) for x in locations)),
               work_arrangement="", compensation=plain_text(entry.get("percentage", "")),
               description=_description(transport.get(url), title), department=plain_text(entry.get("department", "")),
               created_at="", updated_at="", is_listed=True)
    return row


def fetch_ublox(ats: str, careers_url: str, company_id: str, company: str, transport=None) -> Inventory:
    if not supports_ublox(ats, careers_url):
        return Inventory("unsupported", reason="u-blox requires its verified public job-openings page.", source_url=careers_url)
    from .ats import HTTPTransport
    transport = transport or HTTPTransport()
    try:
        data = _json(transport.post(SEARCH, {"params": "query=&hitsPerPage=1000&page=0"}))
        hits, total = data.get("hits"), data.get("nbHits")
        if (not isinstance(hits, list) or not isinstance(total, int) or isinstance(total, bool)
                or total != len(hits) or data.get("page") != 0 or data.get("nbPages") != 1 or total > 1000):
            raise FetchError("partial", "u-blox public inventory pagination or count is incomplete.")
        jobs = []
        ids = set()
        for entry in hits:
            row = _posting(entry, company_id, company, transport)
            if row["posting_id"] in ids:
                raise FetchError("partial", "u-blox public inventory repeated a posting ID.")
            ids.add(row["posting_id"])
            jobs.append(row)
        check = _json(transport.post(SEARCH, {"params": "query=&hitsPerPage=1000&page=0"}))
        check_ids = {item.get("id") for item in check.get("hits", []) if isinstance(item, dict)}
        if check.get("nbHits") != total or check_ids != ids:
            raise FetchError("partial", "u-blox public inventory changed during the scan.")
        return Inventory("complete", jobs, f"u-blox public careers: retrieved {len(jobs)} full postings.", CAREERS, ats="Salesforce-hosted recruiting")
    except FetchError as exc:
        retained = locals().get("jobs", [])
        return Inventory("partial" if retained else exc.status, retained, exc.reason, CAREERS, ats="Salesforce-hosted recruiting")
    except (OSError, TypeError, ValueError, AttributeError):
        return Inventory("partial" if 'jobs' in locals() and jobs else "failed", locals().get("jobs", []),
                         "u-blox public careers schema changed; inventory is incomplete.", CAREERS, ats="Salesforce-hosted recruiting")
