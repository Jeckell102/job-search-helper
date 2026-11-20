"""RBC Signals official-source routing and fail-closed validation."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0363"
COMPANY = "RBC Signals"
OFFICIAL_SOURCE = "https://rbcsignals.com/"


def test_rbc_signals_repairs_stale_careers_route_to_official_homepage():
    ats, url, note = repair_source(
        "Browser", "https://rbcsignals.com/careers/", COMPANY_ID, COMPANY
    )

    assert (ats, url) == ("Browser", OFFICIAL_SOURCE)
    assert REPAIRS[COMPANY_ID]["url"] == OFFICIAL_SOURCE
    assert "no employer-scoped ATS" in REPAIRS[COMPANY_ID]["evidence"]
    assert "Verified company source repair" in note


def test_rbc_signals_browser_route_fails_closed_when_live_source_is_unavailable():
    result = fetch_inventory("Browser", OFFICIAL_SOURCE, COMPANY_ID, COMPANY)

    assert result.status in {"failed", "partial", "blocked", "unsupported"}
    assert not result.jobs
    reason = result.reason.casefold()
    assert any(token in reason for token in ("network", "dns", "board discovery", "playwright", "timeout"))
