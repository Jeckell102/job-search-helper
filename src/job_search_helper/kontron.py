"""Kontron's public CMS Softgarden + Paylocity composite job feeds."""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from urllib.parse import urlsplit

from .ats import FetchError, Inventory, _base, _json, text

SOURCE = "https://www.kontron.com/en/group/careers"
HOST = "www.kontron.com"
SOFTGARDEN = "https://www.kontron.com/api/cms/softgarden/jobs?locale=en"
PAYLOCITY = "https://www.kontron.com/api/paylocity/jobs"
CHANNELS = "https://www.kontron.com/api/cms/softgarden/channels"
DETAIL_PREFIX = "https://www.kontron.com/en/group/careers/jobs/"


def _date(value):
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        raise FetchError("partial", "Kontron posting has an invalid date.")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0:
            raise FetchError("partial", "Kontron posting has an invalid date.")
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            raise FetchError("partial", "Kontron posting has an invalid date.") from None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            raise FetchError("partial", "Kontron posting has an invalid date.") from None
    raise FetchError("partial", "Kontron posting has an invalid date.")


def _locations(raw):
    values = []
    primary = raw.get("fullLocation") or raw.get("geo_name")
    if primary:
        if not isinstance(primary, str):
            raise FetchError("partial", "Kontron posting has malformed location metadata.")
        values.append(primary)
    extra = raw.get("additionalLocations") or []
    if not isinstance(extra, list):
        raise FetchError("partial", "Kontron posting has malformed additional locations.")
    for value in extra:
        if isinstance(value, str):
            label = value
        elif isinstance(value, dict):
            label = value.get("geo_name") or value.get("fullLocation")
            if label is not None and not isinstance(label, str):
                raise FetchError("partial", "Kontron posting has malformed additional locations.")
        else:
            raise FetchError("partial", "Kontron posting has malformed additional locations.")
        if label:
            values.append(label)
    return "; ".join(dict.fromkeys(v.strip() for v in values if v.strip()))


def _workplace(value):
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise FetchError("partial", "Kontron posting has malformed work arrangement.")
    known = {"REMOTE": "Remote", "REMOTE_FLEXIBLE": "Remote / Flexible",
             "FULLY_REMOTE": "Remote", "NOT_REMOTE": "On-site",
             "HYBRID": "Hybrid", "ONSITE": "On-site", "ON_SITE": "On-site"}
    return known.get(value.upper(), value.replace("_", " ").title())


def _salary(raw):
    value = raw.get("salaryFormatted") or raw.get("salary")
    if isinstance(value, dict):
        value = value.get("formatted") or value.get("description") or ""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise FetchError("partial", "Kontron posting has malformed salary metadata.")
    value = value.strip()
    if not value or re.fullmatch(r"(?:[A-Z]{3}\s*)?0(?:\.0+)?\s*[-–]\s*(?:[A-Z]{3}\s*)?0(?:\.0+)?(?:\s*/\s*\w+)?", value):
        return ""
    return value


def _rows(data, source):
    if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), list):
        raise FetchError("partial", f"Kontron {source} feed returned an invalid response.")
    if source == "softgarden" and (type(data.get("count")) is not int or data["count"] != len(data["data"])):
        raise FetchError("partial", "Kontron Softgarden count does not match its feed.")
    return data["data"]


def _normalize(raw, source, company_id, company):
    if not isinstance(raw, dict):
        raise FetchError("partial", "Kontron feed contains a malformed posting.")
    ident = raw.get("jobDbId")
    if source == "softgarden":
        if type(ident) is not int or ident <= 0:
            raise FetchError("partial", "Kontron Softgarden posting lacks a valid integer jobDbId.")
    else:
        if not isinstance(ident, str) or not re.fullmatch(r"pl-[0-9]+", ident):
            raise FetchError("partial", "Kontron Paylocity posting lacks a valid public ID.")
    ident = str(ident)
    title = text(raw.get("externalPostingName") or raw.get("internalPostingName"))
    body = text(raw.get("jobAdText"))
    if not title or not body:
        raise FetchError("partial", "Kontron posting lacks a full public jobAdText body.")
    if source == "paylocity" and raw.get("source") != "paylocity":
        raise FetchError("partial", "Kontron Paylocity posting has invalid source metadata.")
    if not isinstance(raw.get("company_name"), str) or not raw["company_name"].strip():
        raise FetchError("partial", "Kontron posting has invalid company metadata.")
    if source == "softgarden":
        channel = raw.get("channel")
        if (not isinstance(channel, dict) or channel.get("id") != "147418_extern"
                or channel.get("accessible") is not True
                or not isinstance(raw.get("company_id"), str) or not raw["company_id"].strip()):
            raise FetchError("partial", "Kontron Softgarden posting has invalid public channel/company metadata.")
    url = DETAIL_PREFIX + ident
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.query or parsed.fragment:
        raise FetchError("partial", "Kontron posting has an unsafe canonical URL.")
    row = _base({"id": ident}, "Kontron", company_id, company)
    row.update(title=title, description=body, url=url,
               location=_locations(raw),
               created_at=_date(raw.get("jobStartDate")),
               updated_at=_date(raw.get("postingLastUpdatedDate")),
               req_id=text(raw.get("internal_reference_id")),
               work_arrangement=_workplace(raw.get("remote_status")),
               compensation=_salary(raw))
    return row


def _feed(transport, url, source):
    return _rows(_json(url, transport), source)


def _channels(transport):
    data = _json(CHANNELS, transport)
    if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), list):
        raise FetchError("partial", "Kontron channels response is invalid.")
    channels = data["data"]
    if len(channels) != 1 or not isinstance(channels[0], dict):
        raise FetchError("partial", "Kontron public channel scope changed.")
    channel = channels[0]
    if channel.get("id") != "147418_extern" or channel.get("accessible") is not True:
        raise FetchError("partial", "Kontron public channel scope changed.")
    return data


def fetch_kontron(careers_url, company_id, company, transport):
    if company_id != "COMP-0289" or company.casefold() != "kontron":
        return Inventory("unsupported", reason="Kontron provider is pinned to COMP-0289/Kontron.", source_url=careers_url, ats="Kontron")
    if careers_url.rstrip("/") != SOURCE.rstrip("/"):
        return Inventory("unsupported", reason="Kontron provider requires the verified corporate careers source.", source_url=careers_url, ats="Kontron")
    jobs = []
    try:
        channel_data = _channels(transport)
        soft = pay = None
        errors = []
        blocked = False
        for source, url in (("softgarden", SOFTGARDEN), ("paylocity", PAYLOCITY)):
            try:
                records = _feed(transport, url, source)
                normalized = []
                for raw in records:
                    try:
                        normalized.append(_normalize(raw, source, company_id, company))
                    except FetchError as error:
                        errors.append(f"{source}: {error.reason}")
                if source == "softgarden":
                    soft = normalized
                else:
                    pay = normalized
            except (FetchError, OSError, ValueError, TypeError) as error:
                if isinstance(error, FetchError) and error.status == "blocked":
                    blocked = True
                errors.append(f"{source}: {getattr(error, 'reason', str(error))}")
        if soft is None and pay is None:
            raise FetchError("blocked" if blocked else "partial", "; ".join(errors) or "both Kontron feeds failed")
        by_id = {}
        for records in (soft or [], pay or []):
            for row in records:
                if row["posting_id"] in by_id:
                    errors.append("duplicate public jobDbId values")
                    continue
                by_id[row["posting_id"]] = row
        jobs = list(by_id.values())
        if errors:
            return Inventory("blocked" if blocked else "partial", jobs, "Kontron composite feed incomplete: " + "; ".join(errors), SOURCE, "Kontron")
        # Re-read both feeds and channel metadata; only a stable complete union closes.
        channel2 = _channels(transport)
        soft2 = [_normalize(raw, "softgarden", company_id, company) for raw in _feed(transport, SOFTGARDEN, "softgarden")]
        pay2 = [_normalize(raw, "paylocity", company_id, company) for raw in _feed(transport, PAYLOCITY, "paylocity")]
        by2 = {}
        for records in (soft2, pay2):
            for row in records:
                if row["posting_id"] in by2:
                    raise FetchError("partial", "Kontron reread contains duplicate public jobDbId values.")
                by2[row["posting_id"]] = row
        if channel2 != channel_data or set(by2) != set(by_id) or any(by2[k] != by_id[k] for k in by_id):
            raise FetchError("partial", "Kontron public feed cohort changed during reread.")
        return Inventory("complete", jobs, f"Kontron composite feeds: {len(jobs)} postings (Softgarden {len(soft)}, Paylocity {len(pay)}), both feeds reread stable.", SOURCE, "Kontron")
    except FetchError as error:
        return Inventory("blocked" if error.status == "blocked" else "partial", jobs,
                         "Kontron composite feed incomplete: " + error.reason, SOURCE, "Kontron")
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
        return Inventory("partial", jobs, "Kontron composite feed incomplete: " + str(error), SOURCE, "Kontron")
