"""Guarded adapter for Aethercomm's Frontgrade shared careers portal."""
from __future__ import annotations

from .ats import FetchError, Inventory
from .discovery import CareersTransport

SOURCE = "https://careers.frontgrade.com/fg-locations"
COMPANY_ID = "COMP-0128"
COMPANY = "Aethercomm"


def fetch_aethercomm(careers_url, company_id, company, transport=None):
    accepted = {
        SOURCE,
        "https://www.aethercomm.com/careers",
        "https://www.aethercomm.com/careers/",
    }
    if (company_id != COMPANY_ID or company.casefold() != COMPANY.casefold()
            or careers_url.rstrip("/") not in {url.rstrip("/") for url in accepted}):
        return Inventory("unsupported", [], "Aethercomm adapter received an unexpected company or source.", careers_url, "Frontgrade shared careers", browser_fallback_allowed=False)

    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in (401, 403, 429):
            raise FetchError("blocked", f"Frontgrade shared careers source HTTP {response.status}; Aethercomm inventory is unavailable.")
        if response.status != 200:
            raise FetchError("partial", f"Frontgrade shared careers source HTTP {response.status}; inventory completeness is unknown.")
        body = response.body.decode("utf-8", "replace").casefold()
        if "aethercomm" not in body or "frontgrade" not in body:
            raise FetchError("partial", "Frontgrade source changed; Aethercomm identity could not be verified.")
        raise FetchError(
            "partial",
            "Aethercomm is represented as FG Aethercomm inside Frontgrade's shared parent board; no standalone employer-scoped public inventory was established.",
        )
    except FetchError as exc:
        return Inventory(exc.status, [], exc.reason, SOURCE, "Frontgrade shared careers", browser_fallback_allowed=False)
    except Exception as exc:
        return Inventory("partial", [], f"Frontgrade shared careers transport failed ({type(exc).__name__}); inventory completeness is unknown.", SOURCE, "Frontgrade shared careers", browser_fallback_allowed=False)
