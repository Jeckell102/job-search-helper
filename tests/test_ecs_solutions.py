from urllib.parse import urlsplit

from job_search_helper.ats import fetch_inventory, resolve_board
from job_search_helper.company_sources import REPAIRS, repair_source


COMPANY_ID = "COMP-0405"
COMPANY = "ECS Solutions"
OFFICIAL = "https://magnumsystems.com/about/careers/"
BOARD = "https://magnumsystems.isolvedhire.com/jobs/"


def test_ecs_source_is_pinned_to_official_isolved_board():
    ats, url, note = repair_source("isolved", OFFICIAL, COMPANY_ID, COMPANY)
    assert ats == "isolved"
    assert url == BOARD
    assert "Verified company source repair" in note
    assert REPAIRS[COMPANY_ID]["company"] == COMPANY


def test_ecs_board_routing_is_employer_scoped():
    ats, path, root = resolve_board("isolved", BOARD)
    assert ats == "isolved"
    assert path == "/jobs/"
    assert root == "https://magnumsystems.isolvedhire.com"
    assert urlsplit(BOARD).hostname == "magnumsystems.isolvedhire.com"


def test_ecs_does_not_infer_empty_or_unreachable_inventory():
    class Blocked:
        def get(self, url):
            from job_search_helper.ats import HTTPResponse
            return HTTPResponse(503, b"", {})

    result = fetch_inventory("isolved", OFFICIAL, COMPANY_ID, COMPANY,
                            discovery_transport=Blocked())
    assert result.status in {"partial", "blocked", "failed"}
    assert not result.jobs
