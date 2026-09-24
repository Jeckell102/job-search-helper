import unittest

from job_search_helper.efficiency import (
    classify_title,
    parse_annual_base_max_usd,
    strip_job_boilerplate,
)
from job_search_helper.repository import MemoryRepository


class EfficiencyV32Tests(unittest.TestCase):
    def test_python_title_routing(self):
        self.assertEqual(classify_title("Systems Engineer"), "reject")
        self.assertEqual(classify_title("Senior Staff Engineer, Survivability Materials"), "reject")
        self.assertEqual(classify_title("Electrical Engineer"), "reject")
        self.assertEqual(classify_title("Staff Solutions Engineer"), "reject")
        self.assertEqual(classify_title("Field Applications Engineer"), "review")
        self.assertEqual(classify_title("Technical Program Manager"), "ambiguous")

    def test_salary_parser_is_conservative(self):
        self.assertEqual(parse_annual_base_max_usd("Base salary $120,000 - $165,000"), 165000)
        self.assertEqual(parse_annual_base_max_usd("$90k-$115k annual base"), 115000)
        self.assertIsNone(parse_annual_base_max_usd("$80/hour"))
        self.assertIsNone(parse_annual_base_max_usd("OTE $190,000"))
        self.assertIsNone(parse_annual_base_max_usd("EUR 150,000"))

    def test_boilerplate_strip_preserves_requirements(self):
        source = "Responsibilities\nDeploy systems.\nQualifications\nNo clearance required.\nEqual Opportunity Employer\nLegal boilerplate"
        cleaned = strip_job_boilerplate(source)
        self.assertIn("Deploy systems", cleaned)
        self.assertIn("No clearance required", cleaned)
        self.assertNotIn("Legal boilerplate", cleaned)

    def test_memory_repo_targeted_reads(self):
        repo = MemoryRepository({
            "Companies": [],
            "Opportunities": [],
            "Scan Cycles": [],
            "Job History": [{
                "Company": "Demo", "Job Title": "TPM", "Job Key": "k1",
                "Review Status": "Needs Review", "Review Started At": "",
            }],
        })
        rows = repo.read_columns("Job History", ["Job Key", "Review Status"])
        self.assertEqual(rows[0][0], 2)
        self.assertEqual(rows[0][1]["Job Key"], "k1")
        self.assertEqual(repo.read_row("Job History", 2)["Review Status"], "Needs Review")


if __name__ == "__main__":
    unittest.main()
