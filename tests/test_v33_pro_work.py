import unittest

from job_search_helper.core import unpack_snapshot
from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository


def company():
    return {
        "Company": "Demo Co", "Company ID": "COMP-1", "Company Status": "Active",
        "ATS / Source": "Greenhouse", "Official Careers URL": "https://boards.greenhouse.io/demo",
    }


def posting(title="Solutions Engineer", salary="$150,000-$190,000", description="Deploy and integrate systems."):
    return {
        "company_id": "COMP-1", "company": "Demo Co", "ats": "Greenhouse",
        "posting_id": "1", "req_id": "1", "url": "https://boards.greenhouse.io/demo/jobs/1",
        "title": title, "location": "Remote", "work_arrangement": "Remote",
        "compensation": salary, "description": description, "department": "Solutions",
        "created_at": "", "updated_at": "1", "is_listed": True,
    }


class V33ProWorkTests(unittest.TestCase):
    def make(self):
        c = company()
        repo = MemoryRepository({"Companies": [c], "Job History": [], "Opportunities": [], "Scan Cycles": []})
        state = State()
        engine = Engine(repo, state)
        return c, repo, state, engine

    def test_excluded_titles_are_skipped_before_insertion(self):
        c, repo, state, engine = self.make()
        for title in ("Systems Engineer", "Principal Field Applications Engineer"):
            with self.subTest(title=title):
                engine._stage_posting({"id": "CYC"}, c, posting(title=title))
                self.assertEqual(repo.read("Job History"), [])
                self.assertEqual(repo.read("Opportunities"), [])
                self.assertEqual(state.reviews("CYC"), [])
        state.close()

    def test_staff_and_director_target_roles_reach_review(self):
        for title in ("Staff Solutions Engineer", "Director of Field Engineering", "Technical Support Director"):
            c, repo, state, engine = self.make()
            with self.subTest(title=title):
                engine._stage_posting({"id": "CYC"}, c, posting(title=title))
                self.assertEqual(repo.read("Job History")[0]["Review Status"], "Needs Review")
            state.close()

    def test_below_floor_salary_reject_is_completed_without_ai(self):
        c, repo, state, engine = self.make()
        engine._stage_posting({"id": "CYC"}, c, posting(title="Technical Program Manager", salary="$95,000-$115,000 annual base"))
        row = repo.read("Job History")[0]
        self.assertEqual(row["Decision"], "Reject")
        self.assertIn("$115,000", row["Rejection Reason"])
        state.close()

    def test_survivor_is_work_readable_needs_review(self):
        c, repo, state, engine = self.make()
        engine._stage_posting({"id": "CYC"}, c, posting())
        row = repo.read("Job History")[0]
        self.assertEqual(row["Review Status"], "Needs Review")
        self.assertEqual(row["Salary / Range"], "$150,000-$190,000")
        self.assertEqual(row["Work Arrangement"], "Remote")
        self.assertIn("Deploy and integrate", row["Job Description"])
        self.assertTrue(row["Source Hash"])
        self.assertEqual(row["Description Hash"], "")
        state.close()

    def test_in_progress_lock_prevents_scraper_change(self):
        c, repo, state, engine = self.make()
        first = posting(description="VERSION ONE")
        engine._stage_posting({"id": "CYC"}, c, first)
        row = repo.read("Job History")[0]
        key = row["Job Key"]
        repo.commit([{"tab": "Job History", "identity": {"Job Key": key}, "values": {
            "Review Status": "In Progress", "Review Started At": "2026-09-17T01:00:00+00:00"
        }}])
        engine._stage_posting({"id": "CYC"}, c, posting(description="VERSION TWO"))
        after = repo.read("Job History")[0]
        self.assertEqual(after["Job Description"], "VERSION ONE")
        self.assertEqual(after["Review Status"], "In Progress")
        state.close()

    def test_changed_previously_reviewed_job_returns_to_work_queue(self):
        c, repo, state, engine = self.make()
        p = posting()
        engine._stage_posting({"id": "CYC"}, c, p)
        row = repo.read("Job History")[0]
        key = row["Job Key"]
        # Simulate a completed Work review by making Source Hash the reviewed baseline.
        repo.commit([{"tab": "Job History", "identity": {"Job Key": key}, "values": {
            "Review Status": "Reviewed", "Decision": "Accept", "Fit Level": "Strong",
            "Description Hash": row["Source Hash"], "Added to Opportunities?": "Yes"
        }}])
        engine._stage_posting({"id": "CYC"}, c, posting(description="Materially changed responsibilities"))
        after = repo.read("Job History")[0]
        self.assertEqual(after["Review Status"], "Needs Review")
        self.assertEqual(after["Decision"], "")
        self.assertNotEqual(after["Source Hash"], after["Description Hash"])
        state.close()


if __name__ == "__main__":
    unittest.main()
