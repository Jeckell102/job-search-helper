"""SkySafe's first-party careers/contact source.

SkySafe does not expose a public employer-scoped ATS on its official site.
The queue's careers URL currently resolves to the company's contact page.  Do
not turn that page, or a transport failure, into a false empty inventory.
"""
from __future__ import annotations

from .ats import FetchError, Inventory
from .discovery import CareersTransport

SOURCE = "https://www.skysafe.io/contact"
CAREERS_SOURCE = "https://www.skysafe.io/careers"


def fetch_skysafe(careers_url, company_id, company, transport=None):
    if (company_id != "COMP-0169" or company.casefold() != "skysafe"
            or careers_url.rstrip("/") not in {SOURCE, CAREERS_SOURCE}):
        return Inventory("unsupported", [], "SkySafe adapter received an unexpected company or source.", careers_url, "SkySafe official site", browser_fallback_allowed=False)
    client = transport or CareersTransport()
    try:
        response = client.get(careers_url)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"SkySafe official careers source HTTP {response.status}; public inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"SkySafe official careers source HTTP {response.status}; inventory completeness is unknown.")
        body = response.body.decode("utf-8", "replace").casefold()
        if any(token in body for token in ("greenhouse", "lever.co", "ashby", "workday", "jobvite", "smartrecruiters")):
            raise FetchError("partial", "SkySafe source references a possible ATS, but employer-scoped postings could not be verified safely.")
        raise FetchError("partial", "SkySafe's official source does not expose a public employer-scoped ATS or verifiable job links; inventory completeness is unknown.")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, careers_url, "SkySafe official site", browser_fallback_allowed=False)
    except Exception as exc:
        return Inventory("partial", [], f"SkySafe official careers source transport failed ({type(exc).__name__}); inventory completeness is unknown.", careers_url, "SkySafe official site", browser_fallback_allowed=False)
