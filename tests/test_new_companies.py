import unittest
from job_search_helper.company_sources import repair_source
from job_search_helper.shared_boards import board_link
from job_search_helper.workday import resolve_workday
from job_search_helper.ats import resolve_board

CASES = [
    ('COMP-0512', 'Tarana Wireless', 'https://taranawireless.com/careers/', 'JazzHR', 'https://taranawireless.applytojob.com/'),
    ('COMP-0516', 'Wisk Aero', 'https://wisk.aero/careers', 'Workday', 'https://wisk.wd108.myworkdayjobs.com/Wisk_Careers'),
    ('COMP-0520', 'Verkada', 'https://www.verkada.com/careers/', 'Greenhouse', 'https://job-boards.greenhouse.io/verkada'),
    ('COMP-0522', 'Arista Networks', 'https://www.arista.com/en/careers', 'SmartRecruiters', 'https://careers.smartrecruiters.com/AristaNetworks'),
]

class NewCompanyRoutes(unittest.TestCase):
    def test_exact_sheet_identity_and_override_guards(self):
        for cid, name, old_url, provider, target in CASES:
            with self.subTest(cid=cid):
                self.assertEqual(repair_source('Official careers page', old_url, cid, name)[:2], (provider, target))
                for bad_id, bad_name, bad_url in [('other', name, old_url), (cid, 'Other', old_url), (cid, name, 'https://new.example/jobs')]:
                    self.assertEqual(repair_source('Official careers page', bad_url, bad_id, bad_name), ('Official careers page', bad_url, ''))
    def test_provider_parses_verified_board(self):
        board = board_link(CASES[0][4])
        self.assertEqual((board.name, board.slug, board.url), ('JazzHR', 'taranawireless', 'https://taranawireless.applytojob.com/apply'))
        self.assertEqual(resolve_workday('Workday', CASES[1][4]), ('Workday', 'Wisk_Careers', 'https://wisk.wd108.myworkdayjobs.com/wday/cxs/wisk/'))
        self.assertEqual(resolve_board('Greenhouse', CASES[2][4])[:2], ('Greenhouse', 'verkada'))
        board = board_link(CASES[3][4])
        self.assertEqual((board.name, board.slug), ('SmartRecruiters', 'AristaNetworks'))

if __name__ == '__main__':
    unittest.main()
