import unittest

from job_search_helper.ats import fetch_inventory
from job_search_helper.company_sources import repair_source
from job_search_helper.linquest import _linquest_metadata, _scoped_url


URL = "https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers?q=LinQuest"


class LinQuestTests(unittest.TestCase):
    def test_exact_source_repair(self):
        self.assertEqual(repair_source("Workday (shared parent board)",
                                       "https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers",
                                       "COMP-0016", "LinQuest")[:2],
                         ("Workday (LinQuest scoped)", URL))

    def test_scope_is_exact_and_tls_bound(self):
        self.assertTrue(_scoped_url(URL))
        self.assertFalse(_scoped_url(URL.replace("q=LinQuest", "q=KBR")))
        self.assertFalse(_scoped_url(URL.replace("https://", "http://")))

    def test_plain_parent_board_is_rejected(self):
        result = fetch_inventory("Workday (LinQuest scoped)",
                                 "https://kbr.wd5.myworkdayjobs.com/en-US/KBR_Careers",
                                 "COMP-0016", "LinQuest")
        self.assertNotEqual(result.status, "complete")
        self.assertTrue("q=LinQuest" in result.reason or "scope" in result.reason.casefold())

    def test_provider_metadata_required(self):
        self.assertTrue(_linquest_metadata({"employer": "LinQuest Corporation"}))
        self.assertFalse(_linquest_metadata({"title": "LinQuest engineer", "description": ""}))


if __name__ == "__main__":
    unittest.main()
