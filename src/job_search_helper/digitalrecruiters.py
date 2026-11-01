"""Exail's public Cegid/DigitalRecruiters inventory and complete job content."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from urllib.parse import parse_qsl, quote, urlencode

from .ats import FetchError, HTTPTransport, Inventory, _base, _json
from .core import plain_text

HOST = "jobs.exail.com"
SOURCE = "https://jobs.exail.com/en/annonces"
API_HOST = "api.digitalrecruiters.com"
API_PATH = "/public/v1/careers-site/job-ads"
API = "https://" + API_HOST + API_PATH
PAGE_SIZE, MAX_JOBS = 100, 5000


def supports_digitalrecruiters(url):
    return url == SOURCE


def safe_api_path(parsed):
    if parsed.hostname != API_HOST or parsed.fragment:
        return False
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=10)
        query = dict(pairs)
        if len(query) != len(pairs) or query.get("domainName") != HOST or query.get("locale") != "en_GB":
            return False
        if parsed.path == API_PATH:
            return (set(query) == {"domainName", "locale", "limit", "page"}
                    and query["limit"] == str(PAGE_SIZE) and query["page"].isdigit()
                    and 1 <= int(query["page"]) <= MAX_JOBS // PAGE_SIZE)
        return (bool(re.fullmatch(re.escape(API_PATH) + r"/[1-9][0-9]{0,11}", parsed.path))
                and query == {"domainName": HOST, "locale": "en_GB", "external": "0", "withJsonld": "1"})
    except (ValueError, TypeError):
        return False


def _page(client, page):
    url = API + "?" + urlencode({"domainName": HOST, "limit": PAGE_SIZE, "page": page, "locale": "en_GB"})
    data = _json(url, client, {"filters": {}})
    if not isinstance(data, dict) or type(data.get("count")) is not int or not isinstance(data.get("items"), list):
        raise FetchError("partial", "Cegid listing lacks its complete count and items.")
    total, items = data["count"], data["items"]
    if not 0 <= total <= MAX_JOBS or len(items) != min(PAGE_SIZE, max(0, total - (page - 1) * PAGE_SIZE)):
        raise FetchError("partial", "Cegid page size disagrees with the published total.")
    entries = {}
    for item in items:
        if not isinstance(item, dict):
            raise FetchError("partial", "Cegid listing includes a malformed posting.")
        ident, ad_id, slug = item.get("id"), item.get("job_ad_id"), item.get("url")
        title = plain_text(item.get("title", ""))
        if (not isinstance(ident, str) or not re.fullmatch(r"[1-9][0-9]{0,11}-[1-9][0-9]{0,11}", ident)
                or type(ad_id) is not int or str(ad_id) != ident.split("-", 1)[0]
                or not isinstance(slug, str) or not slug.startswith(str(ad_id) + "-")
                or len(slug) <= len(str(ad_id)) + 1 or not all(c.isalnum() or c == "-" for c in slug)
                or ident in entries or not title):
            raise FetchError("partial", "Cegid listing has an invalid or duplicate job identity/title/URL.")
        entries[ident] = {"id": ident, "ad_id": ad_id, "title": title, "slug": slug,
                          "location": plain_text(item.get("location", ""))}
    return total, entries


def _detail(client, entry, company_id, company):
    url = API + "/" + str(entry["ad_id"]) + "?" + urlencode(
        {"domainName": HOST, "locale": "en_GB", "external": 0, "withJsonld": 1})
    data = _json(url, client)
    if not isinstance(data, dict):
        raise FetchError("partial", "Cegid detail has no requisition object.")
    schema = data.get("jsonld")
    if (not isinstance(schema, dict) or schema.get("@type") != "JobPosting"
            or not isinstance(schema.get("identifier"), dict)
            or not isinstance(schema.get("hiringOrganization"), dict)
            or data.get("id") != entry["id"] or data.get("job_ad_id") != entry["ad_id"]
            or data.get("url") != entry["slug"] or data.get("career_domain") != HOST
            or data.get("brand_name", "").casefold() != "exail"
            or data.get("is_external") is not False or data.get("job_ad_status") != 1
            or schema["identifier"].get("value") != entry["id"]
            or schema["hiringOrganization"].get("name", "").casefold() != "exail"
            or plain_text(schema.get("title", "")) != entry["title"]
            or plain_text(data.get("title", "")) != entry["title"]):
        raise FetchError("partial", "Cegid detail does not confirm its listed Exail identity and title.")
    if (not isinstance(data.get("description"), str) or not plain_text(data["description"])
            or not isinstance(data.get("profile"), str)
            or plain_text(schema.get("description", "")) != plain_text(data["description"])):
        raise FetchError("partial", "Cegid detail lacks its full description/profile content.")
    additional = data.get("additional_info") or {}
    if not isinstance(additional, dict) or any(not isinstance(additional.get(k, ""), str) for k in ("title", "text")):
        raise FetchError("partial", "Cegid additional employer description is malformed.")
    parts = [data.get("catch_phrase") or "", data["description"], data["profile"],
             additional.get("title", ""), additional.get("text", "")]
    if any(not isinstance(value, str) for value in parts):
        raise FetchError("partial", "Cegid full description fields are malformed.")
    description = "\n\n".join(plain_text(value) for value in parts if plain_text(value))
    row = _base({"id": entry["id"]}, "Cegid HR", company_id, company)
    row.update(req_id=str(entry["ad_id"]), title=entry["title"], description=description,
               url="https://" + HOST + "/en/annonce/" + quote(entry["slug"], safe="-"),
               location=plain_text(data.get("location", "")) or entry["location"],
               created_at=plain_text(schema.get("datePosted", "")),
               updated_at=plain_text(data.get("republished_at", "")))
    return row


def fetch_digitalrecruiters(source, company_id, company, transport=None):
    if not supports_digitalrecruiters(source) or company_id != "COMP-0357" or company.strip().casefold() != "exail":
        return Inventory("unsupported", reason="Cegid requires Exail's verified employer source.", source_url=source, ats="Cegid HR")
    client, jobs = transport or HTTPTransport(), []
    try:
        total, first = _page(client, 1)
        snapshots, entries = {1: (total, first)}, dict(first)
        for page in range(2, max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE) + 1):
            current, rows = _page(client, page)
            if current != total or set(entries) & set(rows):
                raise FetchError("partial", "Cegid listing changed or repeated IDs during pagination.")
            snapshots[page] = (current, rows)
            entries.update(rows)
        if len(entries) != total:
            raise FetchError("partial", "Cegid full listing does not match its advertised count.")
        errors = []
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_detail, client, entry, company_id, company): ident for ident, entry in entries.items()}
            for future in as_completed(futures):
                try:
                    jobs.append(future.result())
                except (FetchError, ValueError, TypeError, AttributeError) as exc:
                    errors.append(f"{futures[future]}: " + (exc.reason if isinstance(exc, FetchError) else "invalid detail schema"))
        jobs.sort(key=lambda row: row["posting_id"])
        if errors:
            raise FetchError("partial", f"Cegid {len(errors)} full details remain incomplete; " + "; ".join(errors[:3]))
        for page, snapshot in snapshots.items():
            if _page(client, page) != snapshot:
                raise FetchError("partial", "Cegid full listing changed during its final recheck.")
        return Inventory("complete", jobs, f"Cegid: retrieved {len(jobs)} full postings including qualifications and rechecked every listing page.", SOURCE, "Cegid HR")
    except FetchError as exc:
        return Inventory(exc.status if not jobs else "partial", jobs, exc.reason, SOURCE, "Cegid HR")
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial", jobs, "Cegid public API schema validation failed.", SOURCE, "Cegid HR")
