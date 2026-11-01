"""Scoped JazzHR adapter for MAK Technologies."""
from __future__ import annotations

from urllib.parse import urlsplit

from .ats import FetchError, Inventory
from .shared_boards import fetch_shared


SOURCE = "https://mak.applytojob.com/apply"
COMPANY_ID = "COMP-0331"
COMPANY = "MAK Technologies"


def fetch_mak(careers_url: str, company_id: str, company: str, transport=None) -> Inventory:
    """Fetch only MAK's employer-scoped JazzHR inventory."""
    if company_id != COMPANY_ID or company.casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="MAK adapter received an unexpected company identity.", source_url=careers_url, ats="JazzHR")
    parsed = urlsplit(careers_url)
    if parsed.scheme != "https" or parsed.hostname != "mak.applytojob.com" or parsed.path.rstrip("/") != "/apply" or parsed.query or parsed.fragment:
        return Inventory("unsupported", reason="MAK adapter requires the verified employer-scoped JazzHR board.", source_url=careers_url, ats="JazzHR")
    try:
        result = fetch_shared("JazzHR", SOURCE, company_id, company, transport=transport)
    except FetchError as exc:
        return Inventory(exc.status, reason=exc.reason, source_url=SOURCE, ats="JazzHR")
    result.source_url = SOURCE
    result.ats = "JazzHR"
    return result
