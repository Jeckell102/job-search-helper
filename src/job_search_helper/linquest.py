"""LinQuest's employer-scoped view of KBR's public Workday board.

KBR owns LinQuest, but the public KBR board is shared.  A free-text query is
not sufficient by itself, so this adapter accepts a result only when every
normalized posting also carries provider-supplied LinQuest employer/legal
entity/organization metadata.
"""
from __future__ import annotations

from urllib.parse import urlsplit, parse_qsl

from .ats import FetchError, Inventory
from .workday import fetch_workday, resolve_workday

SOURCE_HOST = "kbr.wd5.myworkdayjobs.com"
SOURCE_SITE = "KBR_Careers"
QUERY = "LinQuest"


def _scoped_url(url: str) -> bool:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != SOURCE_HOST
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or parsed.fragment):
        return False
    parts = [p for p in parsed.path.split("/") if p]
    if parts != ["en-US", SOURCE_SITE]:
        return False
    query = parse_qsl(parsed.query, keep_blank_values=False)
    return query == [("q", QUERY)]


def _linquest_metadata(row: dict) -> bool:
    values = [row.get("employer", ""), row.get("legal_entity", ""), row.get("organization", "")]
    return any("linquest" in str(value).casefold() for value in values if value)


def fetch_linquest(url: str, company_id: str, company: str, transport=None) -> Inventory:
    if company_id != "COMP-0016" or company.casefold() != "linquest":
        return Inventory("unsupported", reason="LinQuest adapter requires the exact company identity.", source_url=url, ats="Workday", browser_fallback_allowed=False)
    if not _scoped_url(url):
        return Inventory("unsupported", reason="LinQuest requires the verified KBR Workday URL with q=LinQuest.", source_url=url, ats="Workday", browser_fallback_allowed=False)
    _, board, root = resolve_workday("Workday (LinQuest scoped)", url)
    result = fetch_workday(board, root, company_id, company, transport)
    result.browser_fallback_allowed = False
    # Partial inventories are still ingested. Every returned row must prove
    # employer scope, independently of whether enumeration finished.
    scoped = [job for job in result.jobs if _linquest_metadata(job)]
    if len(scoped) != len(result.jobs) or (result.status == "complete" and not scoped):
        result.jobs = scoped
        if result.status != "blocked":
            result.status = "partial"
        result.reason = ("LinQuest scope is unproven for one or more postings: "
                         "provider-supplied LinQuest employer metadata is required. " + result.reason)
    elif result.status == "complete":
        result.reason = "LinQuest: verified complete employer-scoped Workday inventory with provider metadata."
    return result
