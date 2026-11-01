"""Public ADP Workforce Now listings and full requisition details.

Endpoint and one-based offsets verified on public boards on 2026-09-23.
Only the public job-requisitions GET endpoint is used.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit

from .ats import FetchError, Inventory, _base, _json, text


HOST = "workforcenow.adp.com"
LEGACY_HOST = "workforcenow.cloud.adp.com"
HOSTS = frozenset({HOST, LEGACY_HOST})
CAREERS_PATH = "/mascsr/default/mdf/recruitment/recruitment.html"
API_PATH = "/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
API = f"https://{HOST}{API_PATH}"
PAGE_SIZE = 20
MAX_PAGES = 200
TOKEN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
CID = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
DISPLAY_PARAMS = frozenset({"jobId", "selectedMenuKey", "type", "source", "hsCtaAttrib"})


def _parameters(query, *, api=False):
    values = {}
    for key, value in parse_qsl(query, keep_blank_values=True, max_num_fields=50):
        if not api and (key in DISPLAY_PARAMS or key.startswith("utm_")):
            continue
        allowed = {"cid", "ccId", "lang", "userQuery"} | ({"locale", "$skip", "$top"} if api else set())
        if key not in allowed or len(value) > 512 or any(ord(c) < 32 for c in value):
            raise ValueError("Unsupported ADP URL parameter or filter; verify the public career-center URL.")
        if key in values and values[key] != value:
            raise ValueError("Conflicting ADP company or career-center parameters.")
        values[key] = value
    if not re.fullmatch(CID, values.get("cid", "")) or not re.fullmatch(TOKEN, values.get("ccId", "")):
        raise ValueError("ADP Workforce Now URL requires explicit valid cid and ccId values; no company or center ID is guessed.")
    lang = values.get("lang") or values.get("locale") or "en_US"
    if not re.fullmatch(r"[a-z]{2}_[A-Z]{2}", lang) or values.get("locale", lang) != lang:
        raise ValueError("ADP language/locale is unsupported or inconsistent.")
    for key in ("$skip", "$top"):
        if key in values and not re.fullmatch(r"[0-9]{1,6}", values[key]):
            raise ValueError("Invalid ADP pagination parameter.")
    result = {"cid": values["cid"].lower(), "ccId": values["ccId"], "lang": lang}
    if values.get("userQuery", "").strip():
        result["userQuery"] = values["userQuery"].strip()
    return result


def safe_api_path(parsed):
    if parsed.fragment:
        return False
    if parsed.path != API_PATH and not re.fullmatch(re.escape(API_PATH) + "/" + TOKEN, parsed.path):
        return False
    try:
        _parameters(parsed.query, api=True)
        return True
    except ValueError:
        return False


def resolve_adp(ats, url):
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 443)):
        raise ValueError("Provide a verified public ADP Workforce Now HTTPS URL.")
    api = p.path == API_PATH or bool(re.fullmatch(re.escape(API_PATH) + "/" + TOKEN, p.path))
    if p.path != CAREERS_PATH and not api:
        raise ValueError("Unsupported ADP URL; use the public Workforce Now recruitment page.")
    params = _parameters(p.query, api=api)
    configured = ats.casefold()
    if any(name in configured for name in ("greenhouse", "lever", "ashby", "workday", "icims", "paylocity")) and "adp" not in configured:
        raise ValueError("ATS / Source disagrees with the verified ATS URL.")
    if any(marker in configured for marker in ("shared", "parent")) and not params.get("userQuery"):
        raise ValueError("Shared/parent ADP board requires an explicit company search; verify its career center and userQuery.")
    return "ADP", urlencode(params), f"https://{p.hostname}{API_PATH}?"


def _token(value, name):
    if not isinstance(value, str) or not re.fullmatch(TOKEN, value):
        raise FetchError("partial", f"ADP posting lacks a valid {name}.")
    return value


def _fields(item, group):
    custom = item.get("customFieldGroup") or {}
    if not isinstance(custom, dict) or not isinstance(custom.get(group, []), list):
        raise FetchError("partial", "ADP posting has malformed custom fields.")
    fields = {}
    for field in custom.get(group, []):
        if not isinstance(field, dict) or not isinstance(field.get("nameCode"), dict):
            raise FetchError("partial", "ADP posting has malformed named custom fields.")
        name = field["nameCode"].get("codeValue")
        if not isinstance(name, str) or name in fields:
            raise FetchError("partial", "ADP posting has missing or duplicate custom-field names.")
        fields[name] = field
    return fields


def _external_id(item):
    return _token(_fields(item, "stringFields").get("ExternalJobID", {}).get("stringValue"), "ExternalJobID")


def _posting(item, ident, external_id, params, company_id, company, host=HOST):
    if not isinstance(item, dict) or item.get("itemID") != ident:
        raise FetchError("partial", "ADP job detail ID does not match its listing.")
    if _external_id(item) != external_id:
        raise FetchError("partial", "ADP external posting ID changed during the scan.")
    if any(not isinstance(item.get(key), str) or not item[key].strip()
           for key in ("requisitionTitle", "requisitionDescription")):
        raise FetchError("partial", "ADP job detail is missing its title or full description.")
    if _fields(item, "indicatorFields").get("InternalPostingFlag", {}).get("indicatorValue") is True:
        raise FetchError("partial", "ADP returned an internal-only posting; verify the public career center.")
    locations = item.get("requisitionLocations") or []
    if not isinstance(locations, list):
        raise FetchError("partial", "ADP job detail has malformed locations.")
    places = []
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("nameCode", {}), dict):
            raise FetchError("partial", "ADP job detail has malformed location data.")
        label = text(location.get("nameCode", {}).get("shortName"))
        if not label:
            address = location.get("address") or {}
            if not isinstance(address, dict):
                raise FetchError("partial", "ADP job detail has malformed address data.")
            region = address.get("countrySubdivisionLevel1") or {}
            if not isinstance(region, dict):
                raise FetchError("partial", "ADP job detail has malformed region data.")
            label = ", ".join(filter(None, (text(address.get("cityName")), text(region.get("codeValue")), text(address.get("countryCode")))))
        if label:
            places.append(label)
    strings = _fields(item, "stringFields")
    codes = _fields(item, "codeFields")
    salary = item.get("payGradeRange")
    compensation = ""
    if salary:
        if not isinstance(salary, dict):
            raise FetchError("partial", "ADP job detail has malformed salary data.")
        # Preserve the pay period with the amounts; never assume annual USD.
        compensation = text({"range": salary, "period": codes.get("SalaryType", {}).get("shortName", "")})
    public_params = {key: params[key] for key in ("cid", "ccId", "lang")}
    public_params["jobId"] = external_id
    row = _base({"id": ident}, "ADP", company_id, company)
    row.update(title=text(item["requisitionTitle"]), description=text(item["requisitionDescription"]),
               req_id=text(item.get("clientRequisitionID")), url=f"https://{host}{CAREERS_PATH}?" + urlencode(public_params),
               location="; ".join(dict.fromkeys(places)), department=text(strings.get("HomeDepartment", {}).get("stringValue")),
               compensation=compensation, created_at=text(item.get("postDate")))
    if not row["title"] or not row["description"]:
        raise FetchError("partial", "ADP job detail has empty normalized content.")
    return row


def _page(data, offset, *, search=False):
    if not isinstance(data, dict) or not isinstance(data.get("jobRequisitions"), list) or not isinstance(data.get("meta"), dict):
        raise FetchError("partial", "ADP returned an unexpected listing schema.")
    total, start = data["meta"].get("totalNumber"), data["meta"].get("startSequence")
    if (type(total) is not int or total < 0 or type(start) is not int
            or (start != offset and not (total == 0 and start == 0))):
        raise FetchError("partial", "ADP listing total or start position is missing or inconsistent.")
    entries = data["jobRequisitions"]
    # Keyword search uses a separate zero-based service that can return the
    # entire result set regardless of $top. Accept only a verified full set.
    if search:
        if len(entries) != total or len(entries) > MAX_PAGES * PAGE_SIZE:
            raise FetchError("partial", "ADP keyword search did not return its complete reported result set within the size limit.")
        return total, entries
    if len(entries) != min(PAGE_SIZE, max(0, total - offset + 1)):
        raise FetchError("partial", "ADP page size does not match the reported inventory count.")
    return total, entries


def fetch_adp(board, root, company_id, company, transport):
    source = root + board
    origin = urlsplit(source)
    if (origin.scheme != "https" or origin.hostname not in HOSTS or origin.path != API_PATH
            or origin.username or origin.password or origin.port not in (None, 443) or origin.fragment):
        return Inventory("unsupported", reason="ADP requires a verified public API origin.", source_url=source)
    api = f"https://{origin.hostname}{API_PATH}"
    params = dict(parse_qsl(board))
    request_params = {**params, "locale": params["lang"]}
    # Unfiltered $skip is one-based; keyword searches start at zero.
    search = bool(params.get("userQuery"))
    offset = 0 if search else 1
    jobs, seen = [], set()
    expected, first_ids = None, []
    context = "ADP listing"
    try:
        for page in range(MAX_PAGES):
            context = f"ADP listing page {page + 1}"
            url = api + "?" + urlencode({**request_params, "$skip": offset, "$top": PAGE_SIZE})
            total, entries = _page(_json(url, transport), offset, search=search)
            if expected is None:
                expected = total
            elif total != expected:
                raise FetchError("partial", "ADP listing count changed during pagination.")
            page_ids = []
            for item in entries:
                if not isinstance(item, dict):
                    raise FetchError("partial", "ADP listing contains a malformed posting.")
                ident = _token(item.get("itemID"), "itemID")
                if ident in seen:
                    raise FetchError("partial", "ADP repeated a posting or results page.")
                seen.add(ident)
                page_ids.append(ident)
                external_id = _external_id(item)
                context = f"ADP job detail {ident}"
                detail_params = {key: request_params[key] for key in ("cid", "ccId", "lang", "locale")}
                detail = _json(api + "/" + ident + "?" + urlencode(detail_params), transport)
                jobs.append(_posting(detail, ident, external_id, params, company_id, company, origin.hostname))
            if page == 0:
                first_ids = page_ids
            offset += len(entries)
            print(json.dumps({"event": "inventory_page", "provider": "ADP", "company_id": company_id,
                              "page": page + 1, "postings_fetched": len(jobs), "expected": expected}), file=sys.stderr)
            if len(jobs) == expected:
                break
        else:
            raise FetchError("partial", "ADP page cap reached before the inventory ended.")
        if not search and expected > PAGE_SIZE:
            context = "ADP final listing check"
            url = api + "?" + urlencode({**request_params, "$skip": 1, "$top": PAGE_SIZE})
            total, entries = _page(_json(url, transport), 1)
            current = [item.get("itemID") for item in entries if isinstance(item, dict)]
            if total != expected or current != first_ids:
                raise FetchError("partial", "ADP board changed during the scan; retry for a complete inventory.")
        return Inventory("complete", jobs, f"ADP: retrieved {len(jobs)} full postings in {page + 1} listing pages.", source)
    except FetchError as error:
        status = "blocked" if error.status == "blocked" else ("partial" if jobs else error.status)
        return Inventory(status, jobs, context + ": " + error.reason, source)
    except (OSError, ValueError, TypeError, AttributeError):
        return Inventory("partial" if jobs else "failed", jobs, context + ": unexpected transport or schema failure; inventory incomplete.", source)
