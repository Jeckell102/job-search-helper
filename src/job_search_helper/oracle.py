"""Public Oracle Fusion Candidate Experience listings and details."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urlsplit

from .ats import FetchError, Inventory, _base, _json, is_oracle_host, text
from .discovery import CareersTransport


PAGE_SIZE = 20
MAX_PAGES = 200
DETAIL_WORKERS = 16
SITE = r"CX_[0-9]{1,12}"
IDENT = r"[0-9]{1,24}"
EXTERNAL_FIELDS = ('ExternalDescriptionStr', 'ExternalResponsibilitiesStr', 'ExternalQualificationsStr')
PUBLIC_BODY_FIELDS = ('CorporateDescriptionStr', 'OrganizationDescriptionStr', *EXTERNAL_FIELDS)
OCEANEERING_SITE = ('ebfr.fa.us2.oraclecloud.com', 'CX_3001')
PORTUGUESE_HEADERS = {'Accept-Language': 'pt-BR', 'Ora-Irc-Language': 'pt-BR'}


def supports_oracle(ats: str, url: str) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    # Oracle Candidate Experience uses both the legacy ``/sites/jobs`` form
    # and site-specific boards such as ``/sites/Aerospace/jobs``.  The latter
    # was previously rejected because the final ``/jobs`` segment was omitted
    # from the allow-list, sending valid Oracle boards through generic
    # discovery instead of the API adapter.
    return (p.scheme == "https" and is_oracle_host(p.hostname) and not p.query and not p.fragment
            and bool(re.fullmatch(r"/hcmUI/CandidateExperience/[a-z]{2}/sites/[A-Za-z0-9_-]+(?:/jobs)?/?", p.path)))


def _site_number(url: str, transport) -> str:
    response = transport.get(url)
    if response.status in (401, 403):
        raise FetchError("blocked", "Oracle public careers page requires human verification.")
    if response.status < 200 or response.status >= 300:
        raise FetchError("failed", f"Oracle public careers page returned HTTP {response.status}.")
    body = response.body.decode("utf-8", "replace")
    values = set(re.findall(r"siteNumber=(CX_[0-9]{1,12})", body))
    if len(values) != 1:
        raise FetchError("unsupported", "Oracle careers page did not expose one verified candidate-site identifier.")
    return values.pop()


def _page(data, offset: int):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or len(data["items"]) != 1:
        raise FetchError("partial", "Oracle listing returned an unexpected schema.")
    result = data["items"][0]
    if not isinstance(result, dict) or type(result.get("TotalJobsCount")) is not int or result["TotalJobsCount"] < 0:
        raise FetchError("partial", "Oracle listing omitted its total inventory count.")
    rows = result.get("requisitionList")
    if not isinstance(rows, list) or len(rows) != min(PAGE_SIZE, max(0, result["TotalJobsCount"] - offset)):
        raise FetchError("partial", "Oracle listing page does not match its reported inventory.")
    return result["TotalJobsCount"], rows


def _detail(data, ident: str, company_id: str, company: str, source: str):
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or len(data["items"]) != 1:
        raise FetchError("partial", "Oracle job detail returned an unexpected schema.")
    item = data["items"][0]
    if not isinstance(item, dict) or str(item.get("Id", "")) != ident:
        raise FetchError("partial", "Oracle job detail does not match its listing.")
    title = text(item.get("Title"))
    external_parts = tuple(filter(None, (text(item.get(field)) for field in EXTERNAL_FIELDS)))
    description_parts = tuple(filter(None, (text(item.get(field)) for field in PUBLIC_BODY_FIELDS)))
    description = "\n".join(description_parts)
    # Some public Oracle postings publish only one of the external sections
    # (usually responsibilities or qualifications).  That is still the full
    # public text Oracle exposes for the posting; reject only records with no
    # role-specific external description at all.
    if not title or not external_parts:
        raise FetchError("partial", "Oracle job detail is missing a title or full public description.")
    locations = [text(item.get("PrimaryLocation"))]
    for field in ("otherWorkLocations", "secondaryLocations"):
        values = item.get(field) or []
        if not isinstance(values, list):
            raise FetchError("partial", "Oracle job detail has malformed locations.")
        locations.extend(text(value.get("Location") if isinstance(value, dict) else value) for value in values)
    row = _base({"id": ident}, "Oracle Fusion", company_id, company)
    row.update(title=title, description=description, req_id=text(item.get("RequisitionId")), url=source + "/job/" + ident,
               location="; ".join(dict.fromkeys(filter(None, locations))), department=text(item.get("Department")),
               created_at=text(item.get("ExternalPostedStartDate")), content_locale=text(item.get('ContentLocale')))
    return row


def _localized_oceaneering(data, ident, url, client, host, site):
    items = data.get('items') if isinstance(data, dict) else None
    if (host, site) != OCEANEERING_SITE or not isinstance(items, list) or len(items) != 1:
        return data
    original = items[0]
    if (not isinstance(original, dict) or str(original.get('Id', '')) != ident
            or original.get('ContentLocale') != 'en' or original.get('PrimaryLocationCountry') != 'BR'
            or not text(original.get('RequisitionId'))
            or any(text(original.get(field)) for field in EXTERNAL_FIELDS)):
        return data
    if not hasattr(client, 'get_with_headers'):
        return data

    class PublicLocale:
        def get(self, endpoint):
            # These are the public site's own locale-selection headers. The
            # API URL, posting ID and verified employer site remain identical.
            return client.get_with_headers(endpoint, PORTUGUESE_HEADERS)

    localized = _json(url, PublicLocale())
    values = localized.get('items') if isinstance(localized, dict) else None
    if not isinstance(values, list) or len(values) != 1:
        raise FetchError('partial', 'Oracle localized detail returned an unexpected schema.')
    item = values[0]
    if (not isinstance(item, dict) or str(item.get('Id', '')) != ident
            or str(item.get('RequisitionId', '')) != str(original['RequisitionId'])
            or item.get('ContentLocale') != 'pt-BR' or item.get('PrimaryLocationCountry') != 'BR'):
        raise FetchError('partial', 'Oracle localized detail does not match the verified requisition and locale.')
    return localized


def fetch_oracle(ats: str, careers_url: str, company_id: str, company: str, transport, discovery_transport=None) -> Inventory:
    if not supports_oracle(ats, careers_url):
        return Inventory("unsupported", reason="Provide a verified public Oracle Candidate Experience site URL.", source_url=careers_url)
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "workday", "icims", "adp", "paylocity")):
        return Inventory("unsupported", reason="ATS / Source disagrees with the verified Oracle URL.", source_url=careers_url)
    p = urlsplit(careers_url)
    source = careers_url.rstrip("/")
    root = f"https://{p.hostname}/hcmRestApi/resources/latest/"
    jobs, issues = [], []
    try:
        site = _site_number(careers_url, discovery_transport or CareersTransport())
        seen, expected, identifiers, page_snapshots = set(), None, [], {}
        for page in range(MAX_PAGES):
            offset = page * PAGE_SIZE
            finder = f"findReqs;siteNumber={site},facetsList=NONE,limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
            listing = root + "recruitingCEJobRequisitions?" + urlencode({"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder})
            total, rows = _page(_json(listing, transport), offset)
            if expected is None:
                expected = total
            elif total != expected:
                raise FetchError("partial", "Oracle inventory changed during pagination.")
            ids = []
            for item in rows:
                ident = str(item.get("Id", "")) if isinstance(item, dict) else ""
                if not re.fullmatch(IDENT, ident) or ident in seen:
                    raise FetchError("partial", "Oracle listing has a missing or repeated job identifier.")
                seen.add(ident); ids.append(ident); identifiers.append(ident)
            page_snapshots[offset] = (total, ids)
            if len(identifiers) == expected:
                break
        else:
            raise FetchError("partial", "Oracle page cap reached before the inventory ended.")
        if len(identifiers) != expected:
            raise FetchError("partial", "Oracle listing did not yield its published inventory count.")

        def detail_for(ident):
            detail_finder = f'ById;Id="{ident}",siteNumber={site}'
            detail = root + "recruitingCEJobRequisitionDetails?" + urlencode({"expand": "all", "onlyData": "true", "finder": detail_finder})
            try:
                data = _json(detail, transport)
                data = _localized_oceaneering(data, ident, detail, transport, p.hostname, site)
                return _detail(data, ident, company_id, company, source), None
            except FetchError as error:
                return None, FetchError(error.status, 'Posting ' + ident + ': ' + error.reason)

        with ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as pool:
            details = list(pool.map(detail_for, identifiers))
        for row, error in details:
            if error is not None:
                if error.status == "blocked":
                    raise error
                issues.append(error.reason)
            elif row is not None:
                jobs.append(row)
        for offset, snapshot in page_snapshots.items():
            finder = f"findReqs;siteNumber={site},facetsList=NONE,limit={PAGE_SIZE},offset={offset},sortBy=POSTING_DATES_DESC"
            check = root + "recruitingCEJobRequisitions?" + urlencode({"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder})
            total, rows = _page(_json(check, transport), offset)
            if (total, [str(row.get('Id', '')) for row in rows]) != snapshot:
                raise FetchError("partial", "Oracle inventory changed during the scan.")
        if issues or len(jobs) != expected:
            return Inventory("partial", jobs, " ".join(dict.fromkeys(issues + ["Oracle normalized posting count does not match the inventory count."])), source)
        return Inventory("complete", jobs, f"Oracle Fusion: retrieved {len(jobs)} full postings in {page + 1} listing pages.", source)
    except FetchError as error:
        return Inventory("partial" if jobs else error.status, jobs, error.reason, source)
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs, "Oracle public API returned an unexpected response; inventory incomplete.", source)
