"""Guard the exact official Booz Allen careers-to-Workday repair."""
import unittest
import json
from unittest.mock import patch

from job_search_helper.ats import HTTPResponse, Inventory, fetch_inventory
from job_search_helper.company_sources import repair_source


class BoozAllenSourceTests(unittest.TestCase):
    def test_official_careers_source_routes_to_unfiltered_bah_workday_board(self):
        expected = 'https://bah.wd1.myworkdayjobs.com/BAH_Jobs'
        for source in ('https://careers.boozallen.com', 'https://careers.boozallen.com/'):
            with self.subTest(source=source):
                ats, board, note = repair_source('', source, 'COMP-0623', 'Booz Allen Hamilton')
                self.assertEqual((ats, board), ('Workday', expected))
                self.assertTrue(note)

    def test_repair_does_not_override_changed_source_or_identity(self):
        original = 'https://careers.boozallen.com?manual=1'
        self.assertEqual(repair_source('', original, 'COMP-0623', 'Booz Allen Hamilton'), ('', original, ''))
        self.assertEqual(repair_source('', 'https://careers.boozallen.com', 'OTHER', 'Booz Allen Hamilton'),
                         ('', 'https://careers.boozallen.com', ''))

    def test_capped_bah_board_uses_verified_job_family_partitions(self):
        class Transport:
            def post(self, url, payload):
                body = {
                    'total': 2000,
                    'jobPostings': [],
                    'facets': [{'facetParameter': 'jobFamilyGroup', 'values': [
                        {'id': 'consulting', 'count': 1100}, {'id': 'technology', 'count': 1013},
                    ]}],
                }
                return HTTPResponse(200, json.dumps(body).encode(), {})

        complete = Inventory('complete', [], 'partitioned', 'https://example.test')
        with patch('job_search_helper.workday._fetch_leidos_partitions', return_value=complete) as partition:
            result = fetch_inventory('', 'https://careers.boozallen.com', 'COMP-0623',
                                     'Booz Allen Hamilton', Transport())
        self.assertIs(result, complete)
        self.assertEqual(partition.call_args.kwargs['provider'], 'Booz Allen')
        self.assertEqual(repair_source('', 'https://careers.boozallen.com', 'COMP-0623', 'Other Employer'),
                         ('', 'https://careers.boozallen.com', ''))


if __name__ == '__main__':
    unittest.main()
