from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0354"
COMPANY = "XOCEAN"
SOURCE = "https://www.xocean.com/careers/"


def test_xocean_repairs_legacy_careers_routes_to_canonical_source():
    ats, url, note = repair_source(
        "Browser", "https://xocean.com/careers", COMPANY_ID, COMPANY
    )
    assert (ats, url) == ("Browser", SOURCE)
    assert REPAIRS[COMPANY_ID]["url"] == SOURCE
    assert "LinkedIn opportunities" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_xocean_browser_route_does_not_infer_zero_jobs():
    result = fetch_inventory("Browser", SOURCE, COMPANY_ID, COMPANY)
    assert result.status in {"complete", "failed", "partial", "blocked", "unsupported"}
    if result.status != "complete":
        assert not result.jobs
        reason = result.reason.casefold()
        assert any(token in reason for token in ("network", "dns", "inventory", "playwright", "timeout", "supported"))
