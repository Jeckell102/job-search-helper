"""Guard Power Integrations' official Jobvite routing and embed normalization."""
import unittest

from job_search_helper.company_sources import repair_source
from job_search_helper.shared_boards import board_link


class PowerIntegrationsSourceTests(unittest.TestCase):
    def test_official_source_routes_to_unfiltered_jobvite_board(self):
        expected = 'https://jobs.jobvite.com/power-integrations/jobs'
        for source in ('https://www.power.com/company/careers',
                       'https://www.power.com/company/careers/'):
            with self.subTest(source=source):
                ats, board, note = repair_source('', source, 'COMP-0791', 'Power Integrations')
                self.assertEqual((ats, board), ('Jobvite', expected))
                self.assertTrue(note)

    def test_known_embed_display_flags_canonicalize_without_scope(self):
        board = board_link('https://jobs.jobvite.com/power-integrations/?nl=1&fr=true')
        self.assertEqual((board.name, board.slug, board.url),
                         ('Jobvite', 'power-integrations', 'https://jobs.jobvite.com/power-integrations/jobs'))
        with self.assertRaises(ValueError):
            board_link('https://jobs.jobvite.com/power-integrations/?nl=2')

    def test_repair_preserves_changed_source_and_identity(self):
        changed = 'https://www.power.com/company/careers?manual=1'
        self.assertEqual(repair_source('', changed, 'COMP-0791', 'Power Integrations'), ('', changed, ''))
        self.assertEqual(repair_source('', 'https://www.power.com/company/careers', 'OTHER', 'Power Integrations'),
                         ('', 'https://www.power.com/company/careers', ''))


if __name__ == '__main__':
    unittest.main()
