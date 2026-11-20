"""XOCEAN official-source routing and browser-only validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0354"
COMPANY = "XOCEAN"
OFFICIAL_CAREERS = "https://www.xocean.com/careers/"


def repair_xocean_source(ats="Browser", url=OFFICIAL_CAREERS):
    return repair_source(ats, url, COMPANY_ID, COMPANY)


def validate_xocean_source():
    """Run the installed browser route without inferring zero jobs."""
    return fetch_inventory("Browser", OFFICIAL_CAREERS, COMPANY_ID, COMPANY)


__all__ = [
    "COMPANY_ID", "COMPANY", "OFFICIAL_CAREERS", "REPAIRS",
    "repair_xocean_source", "validate_xocean_source",
]
