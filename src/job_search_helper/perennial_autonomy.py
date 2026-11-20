"""Perennial Autonomy's official site when no public recruiting source exists.

The company site is authoritative for identity, but the current public site
does not expose a careers page, ATS, feed, or canonical job postings.  This
adapter deliberately returns ``partial`` so an unreachable or non-inventory
marketing page cannot be mistaken for a verified zero-job inventory.
"""
from __future__ import annotations

from .ats import FetchError, Inventory
from .discovery import CareersTransport

SOURCE = "https://www.perennialautonomy.com/"
COMPANY_ID = "COMP-0167"
COMPANY = "Perennial Autonomy"


def fetch_perennial_autonomy(careers_url, company_id, company, transport=None):
    if (company_id != COMPANY_ID or company.casefold() != COMPANY.casefold()
            or careers_url.rstrip("/") not in {SOURCE.rstrip("/"), "https://www.perennialautonomy.com/careers"}):
        return Inventory("unsupported", [], "Perennial Autonomy adapter received an unexpected company or source.", careers_url, "Perennial Autonomy careers", browser_fallback_allowed=False)

    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Perennial Autonomy official site HTTP {response.status}; public inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"Perennial Autonomy official site HTTP {response.status}; inventory completeness is unknown.")
        body = response.body.decode("utf-8", "replace")
        lowered = body.casefold()
        if "perennial autonomy" not in lowered:
            raise FetchError("partial", "Perennial Autonomy source changed; official company identity could not be verified.")
        if any(token in lowered for token in ("greenhouse", "lever", "ashby", "workday", "jobvite", "careers", "open positions", "job openings")):
            raise FetchError("partial", "Perennial Autonomy source changed; a recruiting destination requires fresh employer-scoped verification.")
        raise FetchError("partial", "Perennial Autonomy's official site exposes no public careers page, ATS, or verifiable job-posting inventory; completeness is unknown.")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, "Perennial Autonomy careers", browser_fallback_allowed=False)
    except Exception as exc:
        return Inventory("partial", [], f"Perennial Autonomy official-site transport failed ({type(exc).__name__}); inventory completeness is unknown.", SOURCE, "Perennial Autonomy careers", browser_fallback_allowed=False)
