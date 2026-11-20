"""ABB must fetch only its official Robotics division, including on resume."""
from copy import deepcopy
import json
from unittest.mock import patch
import pytest
from test_phenom import html, APP, entry, detail
from job_search_helper.ats import FetchError, HTTPResponse
from job_search_helper.phenom import fetch_phenom, supports_phenom
from job_search_helper.phenom_session import PhenomSession
from job_search_helper.browser_progress import BrowserProgress
from job_search_helper.company_sources import repair_source

CID = 'COMP-0242'
COMPANY = 'ABB Robotics'
SOURCE = 'https://careers.abb/global/en/'
BOARD = SOURCE + 'search-results'
FILTER = {'businessSegment': ['Robotics']}
ABB_APP = dict(APP, refNum='ABB1GLOBAL', baseUrl=SOURCE, locale='en_global',
               widgetApiEndpoint='https://careers.abb/widgets')


def abb_entry(n):
    return entry(n, jobSeqNo=f'ABB1GLOBAL{n}EXTERNALENGLOBAL', businessSegment='Robotics')


class Board:
    def __init__(self, count=3, change=None):
        self.items = [abb_entry(i) for i in range(1, count+1)]
        self.searches = []
        self.details = []
        self.change = change

    def get(self, url):
        if '/job/' not in url:
            return html(app=ABB_APP)
        n = int(url.rsplit('/', 1)[-1])
        self.details.append(n)
        job = json.loads(detail(n).body.decode().split('phApp.ddo = ')[1].split('; phApp.sessionParams')[0])['jobDetail']['data']['job']
        job.update(abb_entry(n), refNum='ABB1GLOBAL')
        if self.change == 'detail':
            job['businessSegment'] = 'Electrification'
        return html({'jobDetail': {'status': 200, 'data': {'job': job}}}, app=ABB_APP)

    def search(self, app, params, offset, *, selected_fields=None):
        assert selected_fields == FILTER
        self.searches.append(offset)
        result = {'status': 200, 'hits': len(self.items[offset:offset+2]),
                  'totalHits': len(self.items), 'eid': {'searchType': 'allJobs'},
                  'data': {'jobs': deepcopy(self.items[offset:offset+2]), 'ui_selections': deepcopy(FILTER)}}
        if self.change == 'echo' or (self.change == 'later_echo' and len(self.searches)>1):
            result['data']['ui_selections'] = {}
        if self.change == 'row' and result['data']['jobs']:
            result['data']['jobs'][0]['businessSegment'] = 'Motion'
        return result


def fetch(board, progress=None):
    return fetch_phenom('Phenom', BOARD, CID, COMPANY, board, progress=progress)


def test_repair_routes_abb_to_verified_phenom_board():
    ats, url, note = repair_source('Browser', SOURCE, CID, COMPANY)
    assert ats == 'Phenom'
    assert url == BOARD
    assert 'careers.abb' in note


def test_phenom_support_recognizes_abb_host():
    assert supports_phenom('Phenom', BOARD)


def test_filtered_pagination_and_reconciliation_fetch_only_robotics():
    board = Board()
    result = fetch(board)
    assert result.status == 'complete', result.reason
    assert len(result.jobs) == 3
    assert board.searches == [0, 2, 0, 2]
    assert board.details == [1, 2, 3]
    assert 'businessSegment=Robotics' in result.reason
    assert all(j['description'] for j in result.jobs)


@pytest.mark.parametrize('change', ['echo', 'row', 'later_echo', 'detail'])
def test_lost_filter_or_wrong_division_never_reports_complete(change):
    board = Board(change=change)
    result = fetch(board)
    assert result.status != 'complete', result.reason
    if change in {'echo', 'row'}:
        assert board.details == []


def test_unscoped_cache_cannot_bypass_scoped_detail_validation():
    progress = BrowserProgress()
    assert fetch(Board(1), progress).status == 'complete'
    cache = progress._read('phenom_detail_v1')['1']
    cache.pop('scope_filters')
    progress._write('phenom_detail_v1', '1', cache)
    board = Board(1)
    assert fetch(board, progress).status == 'complete'
    assert board.details == [1]
    resumed = Board(1)
    assert fetch(resumed, progress).status == 'complete'
    assert resumed.details == []


def test_empty_filtered_inventory_is_reconciled_twice():
    board = Board(0)
    result = fetch(board)
    assert result.status == 'complete', result.reason
    assert result.jobs == []
    assert board.searches == [0, 0]


def test_html_only_transport_cannot_fall_back_to_parent_inventory():
    class HTMLOnly:
        def get(self, url):
            return html(app=ABB_APP)
    result = fetch(HTMLOnly())
    assert result.status == 'unsupported'
    assert not result.jobs


@pytest.mark.parametrize('echo', [FILTER, {}, {'businessSegment': ['Motion']}])
def test_session_sends_filter_and_requires_exact_response_echo(echo):
    session = PhenomSession(BOARD)
    jobs = [abb_entry(1)]
    response = HTTPResponse(200, json.dumps({'refineSearch': {
        'status': 200, 'totalHits': 1, 'hits': 1,
        'data': {'jobs': jobs, 'ui_selections': echo}}}).encode())
    with patch.object(session, '_request', return_value=response) as request:
        if echo == FILTER:
            session.search(ABB_APP, {}, 0, selected_fields=FILTER)
        else:
            with pytest.raises(FetchError):
                session.search(ABB_APP, {}, 0, selected_fields=FILTER)
        payload = request.call_args.args[1]
        assert payload['selected_fields'] == FILTER
        assert 'businessSegment' in payload['all_fields']
        assert payload['from'] == 0
