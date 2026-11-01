"""CymSTAR source repair and ADP routing acceptance checks."""

from unittest.mock import patch

from job_search_helper.ats import Inventory, fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0333"
COMPANY = "CymSTAR"


def test_cymstar_repair_pins_official_adp_tenant():
    entry = REPAIRS[COMPANY_ID]
    ats, url, note = repair_source("Browser", "https://www.cymstar.com/careers", COMPANY_ID, COMPANY)
    assert (ats, url) == (entry["ats"], entry["url"])
    assert "Verified company source repair" in note


def test_cymstar_repaired_source_routes_to_adp_adapter():
    entry = REPAIRS[COMPANY_ID]
    with patch("job_search_helper.adp.fetch_adp", return_value=Inventory("blocked", ats="ADP")) as fetch:
        result = fetch_inventory("Browser", "https://cymstar.com/careers/", COMPANY_ID, COMPANY)
    assert result.status == "blocked"
    assert fetch.call_args.args[2:4] == (COMPANY_ID, COMPANY)
    assert fetch.call_args.args[1].startswith("https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions?")
    assert "Verified company source repair" in result.reason
