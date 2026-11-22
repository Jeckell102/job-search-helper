from xml.etree import ElementTree

import pytest

from job_search_helper.ats import Inventory, text
from job_search_helper.successfactors import _Page, fetch_successfactors
from crown_inventory_regression import CrownBoard, HOST, JOBS
from qualify_crown import BOARD, COMPANY, COMPANY_ID, PROVIDER, SITEMAP, RecordingTransport, validate_result


def capture():
    return RecordingTransport(CrownBoard(), _Page, text)


def captured_inventory(observed):
    observed.get(BOARD)
    observed.get(SITEMAP)
    jobs = []
    for path in JOBS:
        url = HOST + path
        page = _Page(observed.get(url).body.decode())
        jobs.append({
            'company_id': COMPANY_ID, 'company': COMPANY, 'url': url,
            'posting_id': path.strip('/').rsplit('/', 1)[1],
            'description': text(''.join(page.description)),
        })
    observed.get(SITEMAP)
    return Inventory('complete', jobs, source_url=BOARD, ats=PROVIDER)


def test_exact_complete_coverage_and_final_membership():
    observed = capture()
    result = captured_inventory(observed)
    assert validate_result(result, observed)['complete_descriptions'] == 3
    result.jobs[1]['description'] = 'Truncated'
    with pytest.raises(ValueError, match='matching descriptions'):
        validate_result(result, observed)


def test_pre_repair_dispatch_remains_unqualified():
    observed = capture()
    result = fetch_successfactors(BOARD, COMPANY_ID, COMPANY, transport=observed)
    with pytest.raises(ValueError, match='stable official-board result'):
        validate_result(result, observed)


def test_final_membership_change_fails_before_any_replay():
    board = CrownBoard()
    original = board.get

    def changing_board(url):
        response = original(url)
        if url == SITEMAP and board.calls[url] == 2:
            root = ElementTree.fromstring(response.body)
            root.remove(root[-1])
            response.body = ElementTree.tostring(root)
        return response

    board.get = changing_board
    observed = RecordingTransport(board, _Page, text)
    with pytest.raises(ValueError, match='membership changed'):
        captured_inventory(observed)
    with pytest.raises(ValueError, match='qualification stopped'):
        observed.get(BOARD)
