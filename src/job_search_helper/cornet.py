"""Fail-closed official-source contract for Cornet Technology, Inc."""
from __future__ import annotations
from urllib.parse import urlsplit
from .ats import FetchError, Inventory, _base, text
from .discovery import CareersTransport

SOURCE = "https://www.cornet.com/careers/"
HOST = "www.cornet.com"
ATS = "Cornet Technology careers"
COMPANY_ID = "COMP-0304"
COMPANY = "Cornet Technology, Inc."

def _verified_source(url: str, company_id: str, company: str) -> bool:
    try:
        p = urlsplit(url)
        return (company_id == COMPANY_ID and company.strip().casefold() == COMPANY.casefold()
                and p.scheme == "https" and p.hostname == HOST and p.path.rstrip("/") == "/careers"
                and not p.query and not p.fragment)
    except (AttributeError, TypeError, ValueError):
        return False

def fetch_cornet(url=SOURCE, company_id=COMPANY_ID, company=COMPANY, transport=None):
    if not _verified_source(url, company_id, company):
        return Inventory("unsupported", reason="Cornet adapter requires the verified U.S. company careers source.", source_url=SOURCE, ats=ATS, browser_fallback_allowed=False)
    client = transport or CareersTransport()
    try:
        response = client.get(SOURCE)
        if response.status in {401, 403, 429}:
            raise FetchError("blocked", f"Cornet official careers page blocked (HTTP {response.status}).")
        if response.status != 200:
            raise FetchError("partial", f"Cornet official careers page HTTP {response.status}.")
        if not text(response.body.decode("utf-8", "replace")):
            raise FetchError("partial", "Cornet official careers page was blank.")
        raise FetchError("partial", "Cornet official careers page exposes no verified complete public inventory.")
    except FetchError as error:
        return Inventory(error.status, [], error.reason, SOURCE, ATS, browser_fallback_allowed=False)
    except (AttributeError, TypeError, UnicodeError, ValueError, OSError) as error:
        return Inventory("partial", [], f"Cornet official source validation failed: {error}.", SOURCE, ATS, browser_fallback_allowed=False)
