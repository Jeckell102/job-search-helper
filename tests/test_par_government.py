import unittest

from job_search_helper.ats import Inventory
from job_search_helper.par_government import (
    ATS, COMPANY, COMPANY_ID, SOURCE, fetch_par_government, supports,
)


class ParGovernmentTests(unittest.TestCase):
    def test_exact_official_source_is_supported(self):
        self.assertTrue(supports(SOURCE, COMPANY_ID, COMPANY))

    def test_other_company_or_parent_board_is_rejected(self):
        self.assertFalse(supports(SOURCE, "COMP-OTHER", COMPANY))
        self.assertFalse(supports("https://bah.wd1.myworkdayjobs.com/BAH_Jobs", COMPANY_ID, COMPANY))
        result = fetch_par_government("https://bah.wd1.myworkdayjobs.com/BAH_Jobs", COMPANY_ID, COMPANY)
        self.assertEqual(result.status, "unsupported")

    def test_shared_parent_handoff_fails_closed(self):
        result = fetch_par_government(SOURCE, COMPANY_ID, COMPANY)
        self.assertIsInstance(result, Inventory)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.ats, ATS)
        self.assertIn("shared Booz Allen parent", result.reason)
        self.assertIn("Parent-board", result.reason)


if __name__ == "__main__":
    unittest.main()
