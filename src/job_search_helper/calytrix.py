"""Calytrix official-source routing and fail-closed browser validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0339"
COMPANY = "Calytrix Technologies"
OFFICIAL_SITE = "https://www.calytrix.com/"
LEGACY_CAREERS = "https://calytrix.com/careers/"


def repair_calytrix_source(ats="Browser", url=LEGACY_CAREERS):
    return repair_source(ats, url, COMPANY_ID, COMPANY)


def validate_calytrix_source():
    """Run the installed browser route without treating access failure as zero jobs."""
    return fetch_inventory("Browser", OFFICIAL_SITE, COMPANY_ID, COMPANY)


__all__ = [
    "COMPANY_ID", "COMPANY", "OFFICIAL_SITE", "LEGACY_CAREERS", "REPAIRS",
    "repair_calytrix_source", "validate_calytrix_source",
]
