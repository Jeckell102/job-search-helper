"""BAE Systems' verified employer-scoped Phenom contract."""

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source
from job_search_helper.phenom import supports_phenom


COMPANY_ID = "COMP-0073"
COMPANY = "BAE Systems, Inc."
OFFICIAL = "https://jobs.baesystems.com/global/en/"
BOARD = "https://jobs.baesystems.com/global/en/search-results"


def test_bae_routes_to_verified_search_results_board():
    ats, url, note = repair_source("Browser", OFFICIAL, COMPANY_ID, COMPANY)
    assert ats == "Phenom"
    assert url == BOARD
    assert "Verified company source repair" in note


def test_bae_board_is_recognized_as_phenom_scope():
    assert supports_phenom("Phenom", BOARD)
    assert supports_phenom("Phenom", "https://jobs.example.com/global/en/search-results")


def test_bae_live_contract_is_scoped_and_never_claims_failure_as_complete():
    result = fetch_inventory("Phenom", BOARD, COMPANY_ID, COMPANY)
    assert result.ats == "Phenom"
    assert result.source_url == BOARD or result.status in {"failed", "blocked", "partial"}
    if result.status == "complete":
        assert result.jobs
        assert all(job["company_id"] == COMPANY_ID for job in result.jobs)
        assert all(job.get("description", "").strip() for job in result.jobs)
