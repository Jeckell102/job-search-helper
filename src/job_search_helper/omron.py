"""OMRON Industrial Automation Business regional careers manifest.

OMRON's global careers page is a router, not one global job board.  Keep the
regional sources explicit so an Americas-only result can never be reported as
global completion.  The two regional handoffs are deliberately fail-closed:
their sites use different public applications and must expose a validated
inventory before they can contribute jobs.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .adp_myjobs import fetch_adp_myjobs
from .ats import FetchError, HTTPTransport, Inventory
from .discovery import CareersTransport
from .successfactors import fetch_successfactors

COMPANY_ID = "COMP-0247"
COMPANY = "Omron Automation"
MANIFEST_SOURCE = "https://careers.omron.com/content/Job-Opportunities/?locale=en_US"
ADP_SOURCE = "https://myjobs.adp.com/omroncareerexternal"
SF_SOURCE = (
    "https://careers.omron.com/search/?createNewAlert=false&locationsearch="
    "&optionsFacetsDD_department=Industrial+Automation+Business+(IAB)&q="
)
JAPAN_HANDOFF = "https://job.axol.jp/qd/c/omron/public/"
CHINA_HANDOFF = "https://www.fa.omron.com.cn/hr/position"


@dataclass(frozen=True)
class Region:
    name: str
    source: str
    provider: str
    kind: str


REGIONAL_MANIFEST = (
    Region("Americas / Industrial Automation", ADP_SOURCE, "ADP MyJobs", "adp"),
    Region("Asia Pacific / IAB", SF_SOURCE, "SuccessFactors", "successfactors"),
    # OMRON currently exposes the same IAB-filtered SuccessFactors endpoint
    # for the EMEA tile.  Dedupe by canonical URL when the tiles overlap.
    Region("EMEA / IAB", SF_SOURCE, "SuccessFactors", "successfactors"),
    Region("Japan / IAB", JAPAN_HANDOFF, "OMRON Japan handoff", "handoff"),
    Region("Greater China / IAB", CHINA_HANDOFF, "OMRON China handoff", "handoff"),
)


def _validate_manifest():
    if len({r.name for r in REGIONAL_MANIFEST}) != len(REGIONAL_MANIFEST):
        raise ValueError("OMRON regional manifest contains duplicate scopes.")
    if not any(r.kind == "adp" for r in REGIONAL_MANIFEST):
        raise ValueError("OMRON manifest has no Americas ADP delegation.")
    if sum(r.kind == "successfactors" for r in REGIONAL_MANIFEST) != 2:
        raise ValueError("OMRON manifest must contain Asia Pacific and EMEA IAB delegations.")
    for region in REGIONAL_MANIFEST:
        parsed = urlsplit(region.source)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("OMRON manifest contains a non-public HTTPS source.")
    return True


def _canonical_key(job):
    url = str(job.get("url", "")).split("#", 1)[0].rstrip("/")
    if url:
        return url.casefold()
    return f"{job.get('ats','')}:{job.get('posting_id','')}".casefold()


def _merge(region_results):
    """Merge delegated inventories, rejecting scope leakage and duplicates."""
    jobs = []
    seen = set()
    for region, inventory in region_results:
        if inventory.status != "complete":
            raise FetchError(inventory.status, f"{region.name}: {inventory.reason or 'delegated inventory incomplete.'}")
        for job in inventory.jobs:
            if not job.get("title") or not job.get("description") or not job.get("url"):
                raise FetchError("partial", f"{region.name}: delegated job lacks a full description or URL.")
            key = _canonical_key(job)
            if key in seen:
                continue
            seen.add(key)
            row = dict(job)
            row["omron_region"] = region.name
            jobs.append(row)
    return jobs


def _handoff(region):
    raise FetchError(
        "blocked",
        f"{region.name} is an official regional handoff ({region.source}); no validated public inventory adapter is available.",
    )


def fetch_omron(careers_url, company_id, company, transport=None):
    _validate_manifest()
    if company_id != COMPANY_ID or company.strip().casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="OMRON adapter requires the exact Omron Automation company mapping.",
                         source_url=MANIFEST_SOURCE, ats="OMRON IAB regional manifest")
    if careers_url.rstrip("/") != MANIFEST_SOURCE.rstrip("/"):
        return Inventory("unsupported", reason="OMRON adapter requires the official regional manifest landing page.",
                         source_url=MANIFEST_SOURCE, ats="OMRON IAB regional manifest")
    results = []
    try:
        adp_transport = transport if hasattr(transport, "get_with_headers") else HTTPTransport()
        sf_transport = transport or CareersTransport()
        for region in REGIONAL_MANIFEST:
            if region.kind == "adp":
                result = fetch_adp_myjobs(region.provider, region.source, company_id, company, adp_transport)
            elif region.kind == "successfactors":
                result = fetch_successfactors(region.source, company_id, company, sf_transport)
            else:
                result = _handoff(region)
            results.append((region, result))
        jobs = _merge(results)
        return Inventory("complete", jobs,
                         f"OMRON: retrieved {len(jobs)} full postings across all delegated regional scopes and deduplicated overlaps.",
                         MANIFEST_SOURCE, "OMRON IAB regional manifest")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, MANIFEST_SOURCE, "OMRON IAB regional manifest")
    except (AttributeError, TypeError, ValueError, OSError):
        return Inventory("partial", [], "OMRON regional manifest validation failed.", MANIFEST_SOURCE,
                         "OMRON IAB regional manifest")
