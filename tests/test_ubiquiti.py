import unittest
from unittest.mock import patch

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0749'
COMPANY = 'Ubiquiti'
SOURCE = 'https://careers.ui.com/'
BOARD = 'https://job-boards.greenhouse.io/ubiquiti'


class UbiquitiRouteTests(unittest.TestCase):
    def test_exact_source_repair_reaches_employer_greenhouse_board(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Greenhouse', BOARD))
        self.assertTrue(note)
        self.assertEqual(
            repair_source('Official careers', SOURCE + '?team=engineering', COMPANY_ID, COMPANY),
            ('Official careers', SOURCE + '?team=engineering', ''),
        )
        self.assertEqual(
            repair_source('Official careers', SOURCE, 'OTHER', COMPANY),
            ('Official careers', SOURCE, ''),
        )
        self.assertEqual(
            repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'),
            ('Official careers', SOURCE, ''),
        )

    def test_normal_dispatch_uses_greenhouse_full_content(self):
        payload = {'jobs': [{
            'id': 123,
            'title': 'Software Engineer',
            'absolute_url': BOARD + '/jobs/123',
            'content': '<p>Build reliable networking products.</p>',
            'location': {'name': 'New York, NY'},
            'departments': [{'name': 'Engineering'}],
        }], 'meta': {'total': 1}}
        with patch('job_search_helper.ats._json', return_value=payload) as api:
            result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.ats, 'Greenhouse')
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['posting_id'], '123')
        self.assertEqual(result.jobs[0]['description'], 'Build reliable networking products.')
        self.assertEqual(api.call_args.args[0], 'https://boards-api.greenhouse.io/v1/boards/ubiquiti/jobs?content=true')

