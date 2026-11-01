import tempfile
import unittest
from pathlib import Path

from job_search_helper.repository import MemoryRepository
from job_search_helper.review_queue import build_review_queues, export_review_queues


class ReviewQueueTests(unittest.TestCase):
    def make_repo(self):
        history = [
            {
                "Company": "Alpha", "Job Title": "Staff Field Solutions Engineer",
                "Added to Opportunities?": "Pending", "Job Key": "a",
                "Review Status": "Needs Review", "Source Hash": "ha",
                "Job Status": "Open and verified", "Salary / Range": "$180,000 annual base",
            },
            {
                "Company": "Beta", "Job Title": "Operations Coordinator",
                "Added to Opportunities?": "Pending", "Job Key": "b",
                "Review Status": "Needs Review", "Source Hash": "hb",
                "Job Status": "Open and verified", "Salary / Range": "$150,000 annual base",
            },
            {
                "Company": "Gamma", "Job Title": "Software Engineer",
                "Added to Opportunities?": "Pending", "Job Key": "c",
                "Review Status": "Needs Review", "Source Hash": "hc",
                "Job Status": "Open and verified", "Salary / Range": "$180,000 annual base",
            },
            {
                "Company": "Delta", "Job Title": "Field Service Engineer",
                "Added to Opportunities?": "Pending", "Job Key": "d",
                "Review Status": "Needs Review", "Source Hash": "hd",
                "Job Status": "Open and verified",
                "Salary / Range": "$90,000-$110,000 annual base",
            },
            {
                "Company": "Echo", "Job Title": "Technical Program Manager",
                "Added to Opportunities?": "Pending", "Job Key": "e",
                "Review Status": "Needs Review", "Source Hash": "he",
                "Job Status": "Open and verified", "Salary / Range": "",
            },
        ]
        evidence = [
            {
                "Job Key": "a", "Source Hash": "ha",
                "Job Description": (
                    "Customer-facing field deployment and systems integration for defense "
                    "hardware and mission systems, including technical training."
                ),
            },
            {
                "Job Key": "b", "Source Hash": "hb",
                "Job Description": "Coordinate internal calendars, vendors, and office activities.",
            },
            {
                "Job Key": "c", "Source Hash": "hc",
                "Job Description": "Author production software for a web platform.",
            },
            {
                "Job Key": "d", "Source Hash": "hd",
                "Job Description": "Provide customer field support and troubleshooting.",
            },
        ]
        return MemoryRepository({"Job History": history, "Job Evidence": evidence})

    def test_partition_is_read_only_and_keeps_low_scores_for_rescue(self):
        repo = self.make_repo()
        before = repo.read("Job History")
        result = build_review_queues(repo, threshold=17)
        self.assertEqual(repo.read("Job History"), before)
        self.assertEqual([x["job_key"] for x in result["second_pass"]], ["a"])
        audit = {x["job_key"]: x for x in result["first_pass"]}
        self.assertIn("b", audit)
        self.assertIn("c", audit)
        self.assertIn("e", audit)
        self.assertTrue(audit["e"]["evidence_missing"])
        self.assertEqual(audit["c"]["band"], "FIRST_PASS_TITLE_FILTER_AUDIT")
        self.assertNotIn("job_description", audit["b"])
        self.assertNotIn("company", audit["b"])
        self.assertNotIn("company", result["second_pass"][0])
        filtered = {x["job_key"]: x["reason"] for x in result["deterministic_filtered"]}
        self.assertIn("Title exclusion", filtered["c"])
        self.assertIn("Compensation exclusion", filtered["d"])
    def test_export_writes_three_auditable_queues_and_summary(self):
        repo = self.make_repo()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "queue"
            summary = export_review_queues(repo, output, threshold=17)
            self.assertEqual(summary["second_pass"], 1)
            self.assertEqual(summary["first_pass"], 3)
            self.assertEqual(summary["deterministic_filtered"], 2)
            self.assertEqual(summary["band_counts"]["FIRST_PASS_TITLE_FILTER_AUDIT"], 1)
            self.assertTrue((output / "summary.json").exists())
            self.assertTrue((output / "second-pass.jsonl").exists())
            self.assertTrue((output / "first-pass.jsonl").exists())
            self.assertTrue((output / "deterministic-filtered.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
