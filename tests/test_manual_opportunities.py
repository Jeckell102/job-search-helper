import unittest

from job_search_helper.engine import Engine, State
from job_search_helper.repository import MemoryRepository


class ManualOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository({
            "Companies": [],
            "Job History": [{
                "Company": "Acme", "Job Title": "Field Engineer",
                "Added to Opportunities?": "Yes",
                "Official Job URL": "https://jobs.example.com/123?utm_source=sheet",
                "Location": "Boston, MA", "Last Checked": "2026-09-25",
                "Fit Level": "strong", "Salary / Range": "$150,000",
                "Work Arrangement": "Hybrid",
            }],
            "Job Evidence": [], "Opportunities": [], "Scan Cycles": [],
        })
        self.state = State()
        self.addCleanup(self.state.close)
        self.engine = Engine(self.repo, self.state)

    def test_yes_adds_missing_opportunity_and_is_idempotent(self):
        self.assertEqual(self.engine.sync_manual_opportunities(), {"added": 1, "skipped": 0})
        opportunity = self.repo.read("Opportunities")[0]
        self.assertEqual(opportunity["Company"], "Acme")
        self.assertEqual(opportunity["Job Title"], "Field Engineer")
        self.assertEqual(opportunity["Application Status"], "Not Reviewed")
        self.assertEqual(opportunity["Fit Review"], "Strong Potential Fit")

        self.assertEqual(self.engine.sync_manual_opportunities(), {"added": 0, "skipped": 0})
        self.assertEqual(len(self.repo.read("Opportunities")), 1)

    def test_existing_opportunity_preserves_user_owned_fields(self):
        self.repo.commit([{
            "tab": "Opportunities",
            "identity": {"Company": "Acme", "Job URL": "https://jobs.example.com/123"},
            "values": {}, "append_if_missing": True,
            "on_insert": {
                "Job Title": "Field Engineer", "Application Status": "Applied",
                "Date Applied": "2026-09-24", "Date Found": "2026-09-20",
            },
        }])

        self.assertEqual(self.engine.sync_manual_opportunities(), {"added": 0, "skipped": 0})
        opportunity = self.repo.read("Opportunities")[0]
        self.assertEqual(opportunity["Application Status"], "Applied")
        self.assertEqual(opportunity["Date Applied"], "2026-09-24")


if __name__ == "__main__":
    unittest.main()
