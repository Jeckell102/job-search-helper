import json

from job_search_helper.ats import HTTPResponse, fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY = 'Allen Control Systems'
COMPANY_ID = 'COMP-0164'
STALE_BOARD = 'https://job-boards.greenhouse.io/allencontrolsystems'
BOARD = 'https://jobs.ashbyhq.com/allen-control-systems'
API = 'https://api.ashbyhq.com/posting-api/job-board/allen-control-systems?includeCompensation=true'


def test_saved_allen_source_uses_the_exact_ashby_board():
    description = 'Allen Control Systems fixture role with a complete public description.'

    class ExactBoard:
        def get(self, url):
            assert url == API
            response = {'jobs': [{
                'id': '66a1259b-ec2d-462b-8722-4fd239e8f6d0',
                'title': 'Field Applications Engineer',
                'jobUrl': BOARD + '/66a1259b-ec2d-462b-8722-4fd239e8f6d0',
                'descriptionPlain': description,
                'isListed': True,
            }]}
            return HTTPResponse(200, json.dumps(response).encode(), {})

    result = fetch_inventory('Greenhouse', STALE_BOARD, COMPANY_ID, COMPANY, ExactBoard())
    assert result.status == 'complete'
    assert len(result.jobs) == 1
    assert result.jobs[0]['description'] == description


def test_source_change_and_other_companies_are_respected():
    manual = 'https://example.invalid/manually-selected-careers'
    assert repair_source('Greenhouse', manual, COMPANY_ID, COMPANY) == ('Greenhouse', manual, '')
    assert repair_source('Greenhouse', STALE_BOARD, 'COMP-9999', COMPANY) == ('Greenhouse', STALE_BOARD, '')
    assert repair_source('Greenhouse', STALE_BOARD, COMPANY_ID, 'Another Company') == (
        'Greenhouse', STALE_BOARD, '')
    assert repair_source('Ashby', BOARD, COMPANY_ID, COMPANY) == ('Ashby', BOARD, '')
