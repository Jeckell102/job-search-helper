"""Norseman Defense Technologies' guarded careers-source adapter.

Norseman's official site currently sends applicants to a LinkedIn company
jobs search.  LinkedIn returns an authenticated guest shell rather than a
complete, enumerable employer-scoped inventory, so this adapter must remain
fail-closed and never infer a zero-job result.
"""
from __future__ import annotations

from .ats import FetchError, Inventory
from .discovery import CareersTransport

SOURCE = "https://www.norseman.com/"
LINKEDIN_SOURCE = "https://www.linkedin.com/jobs/search?geoId=92000000&f_C=744258&company=Norseman+Defense+Technologies"
COMPANY_ID = "COMP-0303"
COMPANY = "Norseman Defense Technologies"


def fetch_norseman_defense(careers_url, company_id, company, transport=None):
    accepted = {SOURCE.rstrip("/"), "https://www.norseman.com", "https://norseman.tech/", "https://norseman.tech"}
    if (company_id != COMPANY_ID or company.casefold() != COMPANY.casefold()
            or careers_url.rstrip("/") not in {url.rstrip("/") for url in accepted}):
        return Inventory("unsupported", [], "Norseman adapter received an unexpected company or source.", careers_url, "Norseman Defense careers", browser_fallback_allowed=False)

    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Norseman official careers source HTTP {response.status}; public inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"Norseman official careers source HTTP {response.status}; inventory completeness is unknown.")
        body = response.body.decode("utf-8", "replace").casefold()
        if "norseman" not in body or "linkedin.com" not in body:
            raise FetchError("partial", "Norseman source changed; official identity or the LinkedIn recruiting destination could not be verified.")
        raise FetchError("partial", "Norseman's official source is LinkedIn-only; the public guest response exposes no complete employer-scoped inventory or full descriptions.")
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, "Norseman Defense careers", browser_fallback_allowed=False)
    except Exception as exc:
        return Inventory("partial", [], f"Norseman official careers source transport failed ({type(exc).__name__}); inventory completeness is unknown.", SOURCE, "Norseman Defense careers", browser_fallback_allowed=False)
