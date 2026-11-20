import unittest
from unittest.mock import patch

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source


COMPANY_ID = 'COMP-0542'
COMPANY = 'Serve Robotics'
SOURCE = 'https://www.serverobotics.com/careers/'
BOARD = 'https://jobs.ashbyhq.com/serverobotics'


class ServeRoboticsRouteTests(unittest.TestCase):
    def test_exact_source_repair_reaches_employer_ashby_board(self):
        ats, url, note = repair_source('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual((ats, url), ('Ashby', BOARD))
        self.assertTrue(note)
        self.assertEqual(
            repair_source('Official careers', SOURCE + '?locale=en', COMPANY_ID, COMPANY),
            ('Official careers', SOURCE + '?locale=en', ''),
        )
        self.assertEqual(
            repair_source('Official careers', SOURCE, 'OTHER', COMPANY),
            ('Official careers', SOURCE, ''),
        )
        self.assertEqual(
            repair_source('Official careers', SOURCE, COMPANY_ID, 'Other employer'),
            ('Official careers', SOURCE, ''),
        )

    def test_normal_dispatch_uses_the_ashby_inventory_with_full_content(self):
        payload = {'jobs': [{
            'id': 'serve-1',
            'title': 'Autonomy Engineer',
            'jobUrl': BOARD + '/serve-1',
            'descriptionPlain': 'Build and operate autonomous delivery robotics.',
            'location': 'Los Angeles, CA',
            'isListed': True,
        }]}
        with patch('job_search_helper.ats._json', return_value=payload) as api:
            result = fetch_inventory('Official careers', SOURCE, COMPANY_ID, COMPANY)
        self.assertEqual(result.status, 'complete', result.reason)
        self.assertEqual(result.ats, 'Ashby')
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual(result.jobs[0]['description'], payload['jobs'][0]['descriptionPlain'])
        self.assertEqual(api.call_args.args[0], BOARD.replace('https://jobs.ashbyhq.com/', 'https://api.ashbyhq.com/posting-api/job-board/') + '?includeCompensation=true')

