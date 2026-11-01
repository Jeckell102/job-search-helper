import unittest

from job_search_helper.company_sources import REPAIRS, repair_source
from job_search_helper.ats import resolve_board


CASES = [
    ('COMP-0151', 'Rohde & Schwarz USA'), ('COMP-0157', 'D-Fend Solutions'),
    ('COMP-0158', 'Dedrone by Axon'), ('COMP-0159', 'Fortem Technologies'),
    ('COMP-0166', 'Black River Systems Company'), ('COMP-0167', 'Perennial Autonomy'),
    ('COMP-0169', 'SkySafe'), ('COMP-0171', 'Freefly Systems'),
    ('COMP-0172', 'Inspired Flight Technologies'), ('COMP-0173', 'ModalAI'),
    ('COMP-0174', 'Quantum Systems USA'), ('COMP-0175', 'XTEND'),
    ('COMP-0180', 'Ascent AeroSystems'), ('COMP-0182', 'Aero Systems West'),
    ('COMP-0184', 'uAvionix'), ('COMP-0185', 'DroneSense'),
    ('COMP-0200', 'Symbotic'), ('COMP-0221', 'Gatik'),
    ('COMP-0227', 'Foretellix'), ('COMP-0229', 'Polymath Robotics'),
]


class Batch59BRoutes(unittest.TestCase):
    def test_all_routes_are_exact_identity_guarded(self):
        for company_id, company in CASES:
            with self.subTest(company_id=company_id):
                entry = REPAIRS[company_id]
                ats, url, note = repair_source('Existing source', entry['expected_url'], company_id, company)
                self.assertEqual((ats, url), (entry['ats'], entry['url']))
                self.assertIn(entry['url'], note)
                self.assertEqual(repair_source('Existing source', entry['expected_url'], company_id, 'Other Employer'),
                                 ('Existing source', entry['expected_url'], ''))
                self.assertEqual(repair_source('Existing source', entry['expected_url'] + '?changed=1', company_id, company),
                                 ('Existing source', entry['expected_url'] + '?changed=1', ''))

    def test_greenhouse_shared_boards_resolve(self):
        self.assertEqual(resolve_board('Greenhouse', REPAIRS['COMP-0158']['url'])[:2], ('Greenhouse', 'axon'))
        self.assertEqual(resolve_board('Greenhouse', REPAIRS['COMP-0185']['url'])[:2], ('Greenhouse', 'dronesense'))


if __name__ == '__main__':
    unittest.main()
