import json

import pytest

from job_search_helper.ats import HTTPResponse, resolve_board
from job_search_helper.company_sources import repair_source
from job_search_helper.ukg import FetchError, SEARCH, _listing, resolve_ukg


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


DIGI_ID = BOARD.rsplit("/", 1)[-1]


def _job(number):
    return {
        "Id": f"00000000-0000-0000-0000-{number:012d}",
        "Title": f"Digi role {number}",
        "RequisitionNumber": f"DIGI-{number}",
    }


class _Transport:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.payloads = []

    def post(self, url, payload):
        assert url == BOARD + SEARCH
        self.payloads.append(payload)
        return self.bodies.pop(0)


def _listing_response(jobs, total=None):
    return HTTPResponse(200, json.dumps({
        "opportunities": jobs,
        "totalCount": len(jobs) if total is None else total,
    }).encode())


def test_digi_scope_is_exact_tenant_and_board_not_a_parent_search():
    name, path, root = resolve_ukg("UKG / UltiPro", BOARD)
    assert (name, root + path) == ("UKG", BOARD)
    with pytest.raises(ValueError):
        resolve_ukg("UKG shared parent", BOARD)


def test_digi_pagination_and_duplicate_identity_are_strict():
    first = [_job(i) for i in range(1, 51)]
    transport = _Transport([_listing_response(first, 51), _listing_response([_job(51)], 51)])
    assert len(_listing(transport, BOARD)) == 51
    assert [p["opportunitySearch"]["Skip"] for p in transport.payloads] == [0, 50]

    duplicate = _Transport([_listing_response([_job(1), _job(1)], 2)])
    with pytest.raises(FetchError):
        _listing(duplicate, BOARD)
