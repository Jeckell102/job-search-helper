"""Fail-closed source contract for PAR Government (COMP-0045).

PAR Government's public careers handoff currently lands in the Booz Allen
careers ecosystem.  A parent Workday board is not a PAR Government inventory
unless the page or returned posting carries a verified PAR-only selector.  This
module intentionally refuses to infer that scope from titles, locations, or
aggregator copies.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from .ats import Inventory

COMPANY_ID = "COMP-0045"
COMPANY = "PAR Government"
SOURCE = "https://pargovernment.com/careers/"
ATS = "PAR Government (official browser)"
PAR_HOSTS = {"pargovernment.com", "www.pargovernment.com"}


def supports(url: str, company_id: str, company: str) -> bool:
    return (company_id == COMPANY_ID
            and isinstance(company, str)
            and company.strip().casefold() == COMPANY.casefold()
            and url.rstrip("/") == SOURCE.rstrip("/"))


def _official_host(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme == "https" and parsed.hostname in PAR_HOSTS


def fetch_par_government(url: str, company_id: str, company: str, transport=None) -> Inventory:
    """Return a durable blocker until an employer-published PAR-only board exists."""
    if not supports(url, company_id, company):
        return Inventory("unsupported", reason=(
            "PAR Government adapter requires the exact official careers handoff."),
            source_url=url, ats=ATS, browser_fallback_allowed=False)
    if not _official_host(url):
        return Inventory("unsupported", reason=(
            "PAR Government source left the verified employer domain."),
            source_url=url, ats=ATS, browser_fallback_allowed=False)
    return Inventory("blocked", reason=(
        "Official PAR Government careers currently hands off to the shared "
        "Booz Allen parent careers board; no PAR-only selector or employer "
        "published PAR inventory is verified. Parent-board and aggregator "
        "postings are excluded."), source_url=SOURCE, ats=ATS, browser_fallback_allowed=False)


def fetch_par_government_browser(url: str, company_id: str, company: str, **_kwargs) -> Inventory:
    """Browser reread entry point; retain the same scope guard as direct fetch."""
    return fetch_par_government(url, company_id, company)
