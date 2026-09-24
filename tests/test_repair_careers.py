import unittest

from job_search_helper.ats import FetchError, Inventory
from job_search_helper.repair import CANDIDATE_COLUMN, repair_careers_urls
from job_search_helper.repository import MemoryRepository, SCHEMAS


def schemas_with_candidate():
    schemas = {tab: list(headers) for tab, headers in SCHEMAS.items()}
    if CANDIDATE_COLUMN not in schemas["Companies"]:
        schemas["Companies"].append(CANDIDATE_COLUMN)
    return schemas


def company(**overrides):
    row = {
        "Company": "Acme",
        "Company ID": "C-1",
        "Company Status": "Active",
        "ATS / Source": "",
        "Official Careers URL": "https://acme.example/careers",
        "Scan State": "Blocked / Manual Review",
        "Blocked Reason": "Careers redirect has no destination.",
        "Next Action": "Verify official careers URL / inspect manually; retry only on request",
        "Automatic Retry?": "No",
        "Coverage Status": "Incomplete inventory",
    }
    row.update(overrides)
    return row


class RepairCareersUrlsTests(unittest.TestCase):
    def repo(self, rows):
        return MemoryRepository({"Companies": rows}, schemas=schemas_with_candidate())

    def test_dry_run_reports_validated_update_without_mutating_sheet(self):
        repo = self.repo([company()])

        def discoverer(ats, url, transport=None):
            return ("Greenhouse", "acme", "https://boards-api.greenhouse.io/v1/boards/"), url

        def fetcher(ats, url, company_id, company_name):
            self.assertEqual(url, "https://boards-api.greenhouse.io/v1/boards/acme")
            return Inventory("complete", jobs=[{"title": "Program Manager"}], source_url=url, ats="Greenhouse")

        result = repair_careers_urls(repo, fetcher=fetcher, discoverer=discoverer)
        self.assertEqual(result["validated_updates"], 1)
        self.assertEqual(result["spreadsheet_changes"], 0)
        self.assertEqual(repo.read("Companies")[0]["Scan State"], "Blocked / Manual Review")
        self.assertEqual(result["findings"][0]["proposed_url"], "https://boards-api.greenhouse.io/v1/boards/acme")

    def test_apply_updates_validated_url_and_requeues_company(self):
        repo = self.repo([company()])

        def discoverer(ats, url, transport=None):
            return ("Lever", "acme", "https://api.lever.co/v0/postings/"), url

        def fetcher(ats, url, company_id, company_name):
            return Inventory("complete", jobs=[{"title": "Systems Engineer"}], source_url=url, ats="Lever")

        result = repair_careers_urls(repo, apply=True, fetcher=fetcher, discoverer=discoverer)
        self.assertEqual(result["spreadsheet_changes"], 1)
        row = repo.read("Companies")[0]
        self.assertEqual(row["Official Careers URL"], "https://api.lever.co/v0/postings/acme")
        self.assertEqual(row["ATS / Source"], "Lever")
        self.assertEqual(row["Scan State"], "Queued")
        self.assertEqual(row["Blocked Reason"], "")
        self.assertEqual(row["Automatic Retry?"], "")
        self.assertEqual(row["Coverage Status"], "")
        self.assertEqual(row["Last Inventory Count"], 1)

    def test_unvalidated_candidate_goes_to_manual_review_column(self):
        repo = self.repo([company()])

        def discoverer(ats, url, transport=None):
            return ("Greenhouse", "acme", "https://boards-api.greenhouse.io/v1/boards/"), url

        def fetcher(ats, url, company_id, company_name):
            return Inventory("complete", jobs=[], source_url=url, ats="Greenhouse")

        result = repair_careers_urls(repo, apply=True, fetcher=fetcher, discoverer=discoverer)
        self.assertEqual(result["validated_updates"], 0)
        self.assertEqual(result["manual_review_candidates"], 1)
        row = repo.read("Companies")[0]
        self.assertEqual(row[CANDIDATE_COLUMN], "https://boards-api.greenhouse.io/v1/boards/acme")
        self.assertEqual(row["Scan State"], "Blocked / Manual Review")
        self.assertIn("Review candidate careers URL", row["Next Action"])

    def test_writer_conflicts_are_not_treated_as_careers_url_repairs(self):
        repo = self.repo([company(**{"Blocked Reason": "Job History: review fields changed since planning; replan from fresh rows."})])
        result = repair_careers_urls(repo, apply=True, fetcher=lambda *args: self.fail("should not fetch"))
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["spreadsheet_changes"], 0)

    def test_direct_valid_board_can_be_requeued_without_url_change(self):
        repo = self.repo([company(**{"ATS / Source": "Greenhouse", "Official Careers URL": "https://boards.greenhouse.io/acme"})])

        def fetcher(ats, url, company_id, company_name):
            self.assertEqual(url, "https://boards.greenhouse.io/acme")
            return Inventory("complete", jobs=[{"title": "Analyst"}], source_url=url, ats="Greenhouse")

        result = repair_careers_urls(repo, apply=True, fetcher=fetcher)
        self.assertEqual(result["validated_updates"], 1)
        self.assertEqual(repo.read("Companies")[0]["Scan State"], "Queued")


if __name__ == "__main__":
    unittest.main()
