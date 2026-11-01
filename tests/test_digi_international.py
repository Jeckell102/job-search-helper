from job_search_helper.ats import resolve_board
from job_search_helper.company_sources import repair_source


CAREERS = "https://www.digi.com/company/careers"
BOARD = "https://recruiting2.ultipro.com/DIG1008DIGI/JobBoard/bf7d79dc-5bb9-447e-be77-bc5713185792"


def test_digi_repair_uses_official_ultipro_board():
    ats, url, note = repair_source("Browser", CAREERS, "COMP-0141", "Digi International")
    assert ats == "UKG / UltiPro"
    assert url == BOARD
    assert note.startswith("Verified company source repair:")


def test_digi_board_resolves_to_pinned_ukg_route():
    name, path, root = resolve_board("UKG / UltiPro", BOARD + "/?q=&o=postedDateDesc")
    assert name == "UKG"
    assert root + path == BOARD
