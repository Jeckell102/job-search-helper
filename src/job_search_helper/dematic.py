"""Dematic's employer-scoped KION Workday inventory."""

from urllib.parse import urlsplit

from .ats import HTTPTransport, Inventory
from .workday import fetch_workday


SOURCE = "https://kiongroup.wd3.myworkdayjobs.com/en-US/KION_SCS"
ROOT = "https://kiongroup.wd3.myworkdayjobs.com/wday/cxs/kiongroup/"
BOARD = "KION_SCS"
HOST = "kiongroup.wd3.myworkdayjobs.com"
COMPANY_ID = "COMP-0248"
COMPANY = "Dematic"


def _is_demantic_board(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == HOST
        and parsed.path.rstrip("/") in {
            "/en-US/KION_SCS",
            "/wday/cxs/kiongroup/KION_SCS",
        }
        and not parsed.query
        and not parsed.fragment
    )


def fetch_dematic(careers_url, company_id, company, transport=None):
    """Fetch only the Dematic-scoped KION SCS Workday board."""
    if company_id != COMPANY_ID or company.casefold() != COMPANY.casefold():
        return Inventory("unsupported", reason="Dematic adapter received the wrong company identity.", source_url=careers_url)
    if not _is_demantic_board(careers_url):
        return Inventory("unsupported", reason="Dematic source is not the verified KION SCS Workday board.", source_url=careers_url)
    result = fetch_workday(BOARD, ROOT, company_id, company, transport or HTTPTransport())
    result.ats = "Workday"
    return result
