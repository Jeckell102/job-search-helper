"""RapidDeploy's official Motorola Solutions Workday handoff.

RapidDeploy is now a Motorola Solutions product line.  The public board is a
shared tenant, so the adapter uses the official RapidDeploy search handoff and
requires every returned detail to carry authoritative RapidDeploy wording.
It fails closed when the shared board cannot establish that scope.
"""
from __future__ import annotations

from .ats import FetchError, Inventory
from .workday import fetch_workday

SOURCE = "https://motorolasolutions.wd5.myworkdayjobs.com/Careers?q=RapidDeploy"
OFFICIAL_CAREERS = "https://www.motorolasolutions.com/en_us/about/careers.html"
ATS = "Workday (RapidDeploy scoped)"
COMPANY_ID = "COMP-0470"
COMPANY = "RapidDeploy"


def _valid_source(url, company_id, company):
    return (company_id == COMPANY_ID and isinstance(company, str)
            and company.strip().casefold() == COMPANY.casefold()
            and url == SOURCE)


def _rapiddeploy_marker(job):
    text = " ".join(str(job.get(key, "")) for key in
                    ("title", "description", "employer", "legal_entity", "organization"))
    folded = text.casefold()
    return "rapiddeploy" in folded or "rapid deploy" in folded


def fetch_rapiddeploy(careers_url, company_id, company, transport=None):
    if not _valid_source(careers_url, company_id, company):
        return Inventory("unsupported", reason=(
            "RapidDeploy requires the verified official Motorola Workday "
            "RapidDeploy-scoped source."), source_url=careers_url, ats=ATS, browser_fallback_allowed=False)
    result = fetch_workday("Careers?q=RapidDeploy",
                           "https://motorolasolutions.wd5.myworkdayjobs.com/wday/cxs/motorolasolutions/",
                           company_id, company, transport)
    result.ats = ATS
    result.browser_fallback_allowed = False
    scoped = [job for job in result.jobs if _rapiddeploy_marker(job)]
    if len(scoped) != len(result.jobs):
        result.jobs = scoped
        if result.status != "blocked":
            result.status = "partial"
        result.reason = ("RapidDeploy Workday query returned unscoped details; "
                         "inventory is not complete. " + result.reason)
    elif result.status == "complete":
        result.reason = ("RapidDeploy-scoped Workday inventory: verified "
                         f"{len(result.jobs)} full postings with RapidDeploy attribution.")
    elif result.reason:
        result.reason = "RapidDeploy Workday validation: " + result.reason
    result.source_url = careers_url
    return result
