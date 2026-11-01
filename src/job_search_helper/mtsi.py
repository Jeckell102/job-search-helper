"""Modern Technology Solutions, Inc.'s official public Eightfold board."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from .ats import FetchError, Inventory


COMPANY_ID = "COMP-0017"
COMPANY = "Modern Technology Solutions, Inc. (MTSI)"
BOARD = "https://talent.mtsi-va.com/careers"
_HOSTS = frozenset({"careers.mtsi-va.com", "talent.mtsi-va.com", "mtsi-va.eightfold.ai"})


def supports_mtsi(url: str) -> bool:
    try:
        return urlsplit(url).hostname in _HOSTS
    except (TypeError, ValueError):
        return False


def _source(url: str) -> str:
    """Accept only the verified corporate page or the unfiltered public board."""
    parsed = urlsplit(url)
    if (not supports_mtsi(url) or parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443) or parsed.fragment or "\\" in url
            or any(ord(char) <= 32 for char in url)
            or any(not key.startswith("utm_") for key, _ in parse_qsl(parsed.query, keep_blank_values=True))):
        raise FetchError("unsupported", "MTSI requires its unfiltered, verified public careers board.")
    path = parsed.path.rstrip("/")
    if parsed.hostname == "careers.mtsi-va.com" and path:
        raise FetchError("unsupported", "MTSI corporate careers source must be its canonical landing page.")
    if parsed.hostname in {"talent.mtsi-va.com", "mtsi-va.eightfold.ai"} and path != "/careers":
        raise FetchError("unsupported", "MTSI Eightfold source must be the unfiltered careers board.")
    return BOARD


def fetch_mtsi(url: str, company_id: str, company: str):
    """Route only MTSI's exact scope through the bounded Eightfold adapter."""
    if company_id != COMPANY_ID or company.strip().casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="MTSI Eightfold adapter is restricted to COMP-0017.", source_url=url, ats="Eightfold")
    try:
        source = _source(url)
    except FetchError as error:
        return Inventory(error.status, reason=error.reason, source_url=url, ats="Eightfold")
    from .eightfold import fetch_eightfold
    # The verified MTSI landing URL carries sort_by=hot; preserve that
    # public UI ordering when rebuilding every paginated API request.
    return fetch_eightfold(source, company_id, company, "Eightfold", sort_by="hot", listing_first=True)
