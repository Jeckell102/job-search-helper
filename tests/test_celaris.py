from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0322"
COMPANY = "Celaris Industries"
SOURCE = "https://www.celaris.us/careers/"


def test_celaris_repair_uses_parent_linked_official_careers_route():
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE
    assert repair_source("Browser", "https://celarisindustries.com/careers/", COMPANY_ID, COMPANY) == (
        "Browser", "https://celarisindustries.com/careers/", ""
    )
    assert repair_source("Browser", SOURCE, COMPANY_ID, COMPANY)[:2] == ("Browser", SOURCE)
    assert repair_source("Browser", "", COMPANY_ID, COMPANY)[:2] == ("Browser", "")
    assert repair_source("Browser", SOURCE, COMPANY_ID, "Other Employer") == (
        "Browser", SOURCE, ""
    )


def test_celaris_browser_route_stays_incomplete_when_public_site_is_unreachable():
    with patch("job_search_helper.ats.HTTPTransport", side_effect=OSError("DNS failure")):
        result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY)
    assert result.status in {"failed", "unsupported", "blocked", "partial"}
    assert result.jobs == []
