"""Public ADP MyJobs career sites, using their browser-visible listing API."""
from __future__ import annotations

import re
from urllib.parse import urlencode, urlsplit

from .ats import FetchError, Inventory, _base, _json, text


SITE = "https://myjobs.adp.com"
API = "https://my.adp.com/myadp_prefix/mycareer/public/staffing/v1/job-requisitions"
PAGE_SIZE = 20
MAX_PAGES = 200
SLUG = r"[a-z0-9][a-z0-9-]{0,127}"
IDENT = r"[0-9A-Za-z_-]{1,128}"
LARGE_PAGE_SLUGS = frozenset({"mercurysystemscareers", "kearfott", "jt4currentopeningscx3", "fanuc"})


def supports_adp_myjobs(ats: str, url: str) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    return p.scheme == "https" and p.hostname == "myjobs.adp.com" and bool(re.fullmatch(r"/" + SLUG + "/?", p.path))


def resolve_adp_myjobs(ats: str, url: str) -> str:
    p = urlsplit(url)
    if not supports_adp_myjobs(ats, url) or p.query or p.fragment or p.username or p.password or p.port not in (None, 443):
        raise ValueError("Provide a verified public ADP MyJobs career-site URL.")
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "workday", "icims", "paylocity")) and "adp" not in configured:
        raise ValueError("ATS / Source disagrees with the verified ADP MyJobs URL.")
    return p.path.strip("/")


def posting_url(slug: str, ident: str) -> str:
    if not re.fullmatch(SLUG, slug) or not re.fullmatch(IDENT, str(ident)):
        raise ValueError("ADP MyJobs requires a valid site and requisition ID.")
    return f"{SITE}/{slug}/cx/job-details?" + urlencode({"reqId": str(ident)})


def repair_saved_urls(payload):
    """Normalize legacy board-only links without changing saved evidence or IDs."""
    source = payload.get('source_url', '')
    if not supports_adp_myjobs('', source):
        return payload
    try:
        slug = resolve_adp_myjobs('', source)
    except ValueError:
        return payload
    jobs = []
    for job in payload.get('jobs', []):
        if (job.get('ats') == 'ADP MyJobs'
                and job.get('url', '').rstrip('/') == f'{SITE}/{slug}'
                and re.fullmatch(IDENT, str(job.get('posting_id', '')))):
            job = dict(job, url=posting_url(slug, job['posting_id']))
        jobs.append(job)
    return dict(payload, jobs=jobs)


def _headers(token: str) -> dict[str, str]:
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_+=./-]{32,4096}", token):
        raise FetchError("partial", "ADP MyJobs public site did not provide a valid transient listing token.")
    return {"myJobsToken": token, "rolecode": "manager", "Referer": SITE + "/", "Accept-Language": "en-US"}


def _request(transport, url: str, headers: dict[str, str]):
    method = getattr(transport, "get_with_headers", None)
    if method is None:
        raise FetchError("failed", "Transport does not support public ADP MyJobs request headers.")
    response = method(url, headers)
    return _json(url, type("Transport", (), {"get": lambda self, value: response})())


def _listing(data, offset: int, page_size: int = PAGE_SIZE):
    if not isinstance(data, dict) or type(data.get("count")) is not int or data["count"] < 0 or not isinstance(data.get("jobRequisitions"), list):
        raise FetchError("partial", "ADP MyJobs listing returned an unexpected schema.")
    rows = data["jobRequisitions"]
    if len(rows) != min(page_size, max(0, data["count"] - offset)):
        raise FetchError("partial", "ADP MyJobs page size does not match its reported inventory.")
    return data["count"], rows


def _job(detail, ident: str, company_id: str, company: str, slug: str):
    if not isinstance(detail, dict) or not isinstance(detail.get("jobRequisitions"), list) or len(detail["jobRequisitions"]) != 1:
        raise FetchError("partial", "ADP MyJobs detail returned an unexpected schema.")
    row = detail["jobRequisitions"][0]
    if not isinstance(row, dict) or str(row.get("itemID", "")) != ident:
        raise FetchError("partial", "ADP MyJobs detail does not match its listing.")
    title, description = text(row.get("requisitionTitle")), text(row.get("requisitionDescription"))
    if not title or not description:
        raise FetchError("partial", "ADP MyJobs detail is missing a title or full description.")
    locations = row.get("requisitionLocations") or []
    if not isinstance(locations, list):
        raise FetchError("partial", "ADP MyJobs detail has malformed locations.")
    places = []
    for place in locations:
        if not isinstance(place, dict):
            raise FetchError("partial", "ADP MyJobs detail has malformed location data.")
        label = text((place.get("nameCode") or {}).get("shortName"))
        if label:
            places.append(label)
    result = _base({"id": ident}, "ADP MyJobs", company_id, company)
    result.update(title=title, description=description, req_id=text(row.get("clientRequisitionID")),
                  url=posting_url(slug, ident), location="; ".join(dict.fromkeys(places)))
    return result


def fetch_adp_myjobs(ats: str, url: str, company_id: str, company: str, transport) -> Inventory:
    slug = resolve_adp_myjobs(ats, url)
    source = f"{SITE}/{slug}"
    # These verified ADP boards support a 200-row page; their default 20-row
    # ordering moves tied posting dates between pages. Other ADP sites retain
    # the default page size20 until independently verified.
    page_size = 200 if slug in LARGE_PAGE_SLUGS else PAGE_SIZE
    jobs = []
    try:
        config = _json(f"{SITE}/public/staffing/v1/career-site/{slug}", transport)
        headers = _headers(config.get("myJobsToken") if isinstance(config, dict) else "")
        seen, expected, first, snapshots = set(), None, [], []
        for page in range(MAX_PAGES):
            offset = page * page_size
            query = {"$orderby": "postingDate desc", "$top": page_size, "$skip": offset, "tz": "America/New_York"}
            listing_url = API + "/apply-custom-filters?" + urlencode(query)
            total, rows = _listing(_request(transport, listing_url, headers), offset, page_size)
            if expected is None:
                expected = total
            elif total != expected:
                raise FetchError("partial", "ADP MyJobs inventory changed during pagination.")
            ids = []
            for listing in rows:
                ident = str(listing.get("reqId", "")) if isinstance(listing, dict) else ""
                if not re.fullmatch(IDENT, ident) or ident in seen:
                    raise FetchError("partial", "ADP MyJobs listing has missing or repeated requisitions.")
                seen.add(ident); ids.append(ident)
                jobs.append(_job(_request(transport, API + "/search-meta/" + ident, headers), ident, company_id, company, slug))
            if page == 0:
                first = ids
            snapshots.append(ids)
            if len(jobs) == expected:
                if slug in LARGE_PAGE_SLUGS:
                    reread_ids = []
                    for check_page, original_ids in enumerate(snapshots):
                        check_query = {"$orderby": "postingDate desc", "$top": page_size,
                                       "$skip": check_page * page_size, "tz": "America/New_York"}
                        check_total, check_rows = _listing(_request(transport, API + "/apply-custom-filters?" + urlencode(check_query), headers), check_page * page_size, page_size)
                        check_ids = [str(x.get("reqId", "")) for x in check_rows]
                        if check_total != expected or len(set(check_ids)) != len(check_ids):
                            raise FetchError("partial", "ADP MyJobs inventory changed during the scan.")
                        reread_ids.extend(check_ids)
                    if set(reread_ids) != set(seen) or len(reread_ids) != expected:
                        raise FetchError("partial", "ADP MyJobs inventory changed during the scan.")
                else:
                    query["$skip"] = 0
                    check_total, check_rows = _listing(_request(transport, API + "/apply-custom-filters?" + urlencode(query), headers), 0, page_size)
                    check_ids = [str(x.get("reqId", "")) for x in check_rows]
                    if check_total != expected or check_ids != first:
                        raise FetchError("partial", "ADP MyJobs inventory changed during the scan.")
                return Inventory("complete", jobs, f"ADP MyJobs: retrieved {len(jobs)} full postings in {page + 1} listing pages.", source)
        raise FetchError("partial", "ADP MyJobs page cap reached before the inventory ended.")
    except FetchError as error:
        return Inventory("partial" if jobs else error.status, jobs, error.reason, source)
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs, "ADP MyJobs public API returned an unexpected response; inventory incomplete.", source)
