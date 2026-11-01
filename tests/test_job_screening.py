from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from job_search_helper.ats import Inventory
from job_search_helper.efficiency import classify_title, parse_annual_base_max_usd
from job_search_helper.screening import screen_posting
import test_v33_pro_work as workflow

posting = workflow.posting


class PreferenceTests(unittest.TestCase):
    def screen(self, **changes):
        return screen_posting({**posting(salary=""), **changes})

    def test_shortlist_is_a_hint_and_never_an_allowlist(self):
        preferred = (
            "Field Applications Engineer", "Field Application Engineer", "Applications Engineer",
            "Product Applications Engineer", "Customer Applications Engineer", "Product Manager",
            "Assistant Product Manager", "Associate Product Manager", "Technical Product Manager",
            "Product Owner", "Product Line Manager", "Solutions Engineer", "Pre-Sales Engineer",
            "Sales Engineer", "Customer Engineer", "Product Engineer", "Product Specialist",
            "Technical Product Specialist", "Field Support Engineer", "Field Service Engineer",
            "Senior Product Manager", "Lead Field Applications Engineer", "Technical Program Manager",
            "Technical Project Manager", "Staff Field Solutions Engineer", "Network Deployment Engineer",
        )
        for title in preferred:
            with self.subTest(title=title):
                result = self.screen(title=title)
                self.assertIsNone(result.reason)
                self.assertIn("shortlist match", result.review_note)
        for title in ("Integration Engineer", "Operations Manager",
                      "Product Marketing Manager", "Support Engineer", "Unusual Customer Role"):
            with self.subTest(title=title):
                result = self.screen(title=title)
                self.assertIsNone(result.reason)
                self.assertIn("retained for AI", result.review_note)

    def test_existing_hard_blacklist_still_wins_and_saas_is_added(self):
        for title in ("Principal Applications Engineer", "SaaS Product Manager",
                      "Product Manager, Software-as-a-Service", "Senior Engineer, Field Service",
                      "Lead Engineer, Field Support", "Product Manager, Research",
                      "Software Engineer / Solutions Engineer", "Systems Engineer - Mission Integration"):
            with self.subTest(title=title):
                self.assertEqual(classify_title(title), "reject")

    def test_recovered_opportunity_title_families_are_not_blacklisted(self):
        for title in ("Staff Product Manager", "Staff Field Solutions Engineer", "Director of Product",
                      "Director of Field Engineering", "Product Manager, Development",
                      "Senior Field Engineer - Electrical/Mechanical Integration",
                      "Field Test Engineer, Maritime", "Senior System Test Engineer",
                      "Applications Engineer, Learning & Development", "Senior Business Development Engineer"):
            with self.subTest(title=title):
                self.assertNotEqual(classify_title(title), "reject")

    def test_salary_floor_is_inclusive_and_missing_pay_survives(self):
        for compensation in ("", "$120,000 annual base", "$95,000 - $120,000", "$110k - 160k",
                             "USD 120000-150000 annual base", "OTE $180,000", "CAD 100000",
                             "$90 per hour", "$10,000 per month", "Competitive salary"):
            with self.subTest(compensation=compensation):
                self.assertIsNone(self.screen(compensation=compensation).reason)
        for compensation in ("$95,000-$119,999 annual base", "USD 90000-110000 annual base",
                             "Base salary $100,000; OTE $180,000", "Base $110k plus $60k commission"):
            with self.subTest(compensation=compensation):
                self.assertIn("Compensation exclusion", self.screen(compensation=compensation).reason)

    def test_salary_description_and_multiple_regions(self):
        self.assertIn("Compensation exclusion", self.screen(description="Annual base salary is $90k-$110k.").reason)
        self.assertIn("Compensation exclusion", self.screen(compensation="OTE $180k", description="Annual base salary is $90k-$110k.").reason)
        self.assertIsNone(self.screen(description="US annual base salary is $90k-$110k. CA annual base salary is $130k-$160k.").reason)
        self.assertIsNone(self.screen(description=(
            "Estimated Starting Salary Range: USD $75,650.00/Yr. - "
            "USD $126,050.00/Yr. Salary depends on experience."
        )).reason)
        self.assertIsNone(self.screen(description="Our equipment costs $100,000.").reason)
        self.assertIsNone(self.screen(description="Salary range is CAD $90,000-$110,000.").reason)
        self.assertIsNone(self.screen(compensation="See location-specific ranges", description="Annual base salary is $90k-$110k.").reason)

    def test_base_parser_does_not_use_bonus_to_cross_floor(self):
        self.assertEqual(parse_annual_base_max_usd("Base $110,000 + bonus $50,000 + equity $200,000"), 110000)
        self.assertEqual(parse_annual_base_max_usd("OTE $200,000; base $100,000"), 100000)
        self.assertIsNone(parse_annual_base_max_usd("Total compensation $110,000"))
        self.assertIsNone(parse_annual_base_max_usd("$100,000 base and commission combined"))
        self.assertIsNone(parse_annual_base_max_usd("Annual base salary EUR 100000"))

    def test_base_label_applies_to_all_location_ranges(self):
        for compensation in ("Base salary $90k-$110k in Ohio and $130k-$160k in California",
                             "USD base salary 90000-110000 in Ohio and 130000-160000 in California",
                             "Base $110k in Ohio; $150k in California; OTE $250k"):
            with self.subTest(compensation=compensation):
                self.assertIsNone(self.screen(compensation=compensation).reason)
        self.assertEqual(parse_annual_base_max_usd("Base $110k in Ohio; $150k in California; OTE $250k"), 150000)

    def test_travel_limits_and_unrelated_percentages(self):
        for description in ("Travel up to 50%.", "Travel: 25-50%.", "Travel as needed.",
                            "Travel is optional, up to 75%.", "No travel required. Bonus up to 75%.",
                            "Travel reimbursement covers 75% of meals.", "Travel 25%; 75% office work.",
                            "Work on hardware 75% of the time; occasional travel."):
            with self.subTest(description=description):
                self.assertIsNone(self.screen(description=description).reason)
        for description in ("Travel up to 75%.", "Travel: 60%.", "Requires 75% travel.",
                            "Travel 25-75%.", "Ability to travel more than 50%.",
                            "Travel is required up to 80%.", "Travel no more than 75%.",
                            "Travel not to exceed 75%."):
            with self.subTest(description=description):
                self.assertIn("Travel exclusion", self.screen(description=description).reason)

    def test_permanent_only_without_confusing_customer_contracts(self):
        for description in ("This is a contract position.", "Employment type: Temporary.",
                            "This position is a 12-month contract.", "This is a seasonal role.",
                            "This role is fixed-term."):
            with self.subTest(description=description):
                self.assertIn("Employment exclusion", self.screen(description=description).reason)
        for title in ("Field Support Engineer (Contract)", "Temporary Product Manager",
                      "Product Manager - Contract-to-hire", "Field Service Engineer - Seasonal"):
            with self.subTest(title=title):
                self.assertIn("Employment exclusion", self.screen(title=title).reason)
        for description in ("Permanent, full-time position.", "Manage customer contracts.",
                            "We are a government contractor.", "Negotiate a 12-month contract with suppliers.",
                            "This role is not temporary.", "Support temporary installations."):
            with self.subTest(description=description):
                self.assertIsNone(self.screen(description=description).reason)
        self.assertIsNone(self.screen(title="Product Manager, Temporary Power").reason)
        self.assertIsNone(self.screen(title="Temporary Power Product Manager").reason)
        self.assertIsNone(self.screen(title="Contract Manager").reason)
        self.assertIsNone(self.screen(description="This role is a contract specialist working with customers.").reason)

    def test_saas_product_scope_and_incidental_mentions(self):
        for description in ("You will own our SaaS product.", "You will manage the software-as-a-service platform.",
                            "Own the roadmap for our SaaS platform.", "This role focuses on SaaS products."):
            with self.subTest(description=description):
                self.assertIn("Product exclusion", self.screen(description=description).reason)
        for description in ("Use SaaS tools to track hardware deployments.", "SaaS experience preferred.",
                            "Integrate our sensors with customer SaaS systems.", "We offer both hardware and SaaS products.",
                            "You will not manage the SaaS platform.", "Build a software roadmap.",
                            "Support mixed hardware and software."):
            with self.subTest(description=description):
                self.assertIsNone(self.screen(description=description).reason)

    def test_location_and_work_arrangement_never_exclude(self):
        for arrangement in ("Onsite", "Hybrid", "Remote", ""):
            self.assertIsNone(self.screen(location="Anywhere", work_arrangement=arrangement).reason)


class ScreeningIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.company, self.repo, self.state, self.engine = workflow.V33ProWorkTests().make()
        self.addCleanup(self.state.close)

    def stage(self, **changes):
        with redirect_stdout(StringIO()):
            self.engine._stage_posting({"id": "CYC"}, self.company, {**posting(salary=""), **changes})
        return self.repo.read("Job History")

    def test_ambiguous_job_reaches_ai_with_all_evidence(self):
        row = self.stage(title="Implementation Manager", description="Unusual but potentially relevant work.")[0]
        self.assertEqual(row["Review Status"], "Needs Review")
        self.assertEqual(row["Added to Opportunities?"], "Pending")
        self.assertIn("retained for AI", row["Review Notes"])
        self.assertTrue(row["Job Description"].startswith("See Job Evidence tab:"))

    def test_explicit_exclusion_is_auditable_and_idempotent(self):
        row = self.stage(description="Travel up to 75%.")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Status"], "Reviewed")
        self.assertIn("Travel exclusion", row["Rejection Reason"])
        rows = self.stage(description="Travel up to 75%.")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Added to Opportunities?"], "No")

    def test_existing_manual_choice_notes_and_review_lock_survive(self):
        row = self.stage()[0]
        self.repo.commit([{"tab": "Job History", "identity": {"Job Key": row["Job Key"]},
                           "values": {"Added to Opportunities?": "No", "Review Notes": "My decision"}}])
        row = self.stage(description="Travel up to 75%.")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Notes"], "My decision")
        self.assertEqual(row["Review Status"], "Needs Review")
        self.repo.commit([{"tab": "Job History", "identity": {"Job Key": row["Job Key"]},
                           "values": {"Review Status": "In Progress"}}])
        before = self.repo.read("Job History")
        self.assertEqual(self.stage(description="This is a contract position."), before)

    def test_saas_title_never_enters_queue(self):
        self.assertEqual(self.stage(title="SaaS Product Manager"), [])

    def test_restart_refetches_and_replays_without_losing_ambiguous_jobs(self):
        jobs = [{**posting(title=title, salary=""), "posting_id": str(index),
                 "url": f"https://boards.greenhouse.io/demo/jobs/{index}"}
                for index, title in enumerate(("Product Manager", "SaaS Product Manager", "Integration Engineer"))]
        self.engine.fetcher = lambda *args: Inventory(status="complete", jobs=jobs, reason="ok",
                                                     source_url=self.company["Official Careers URL"])
        self.engine.batch_size = 1
        cycle = self.engine.start_cycle([self.company["Company ID"]])
        original_stage = self.engine._stage_posting

        def interrupt(current_cycle, company, job):
            if job["posting_id"] == "1":
                raise KeyboardInterrupt()
            return original_stage(current_cycle, company, job)

        with redirect_stdout(StringIO()):
            with patch.object(self.engine, "_stage_posting", side_effect=interrupt), self.assertRaises(KeyboardInterrupt):
                self.engine.resume(cycle)
            self.assertEqual(len(self.repo.read("Job History")), 1)
            self.engine.resume(cycle)
        rows = self.repo.read("Job History")
        self.assertEqual({row["Job Title"] for row in rows}, {"Product Manager", "Integration Engineer"})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["Review Status"] == "Needs Review" for row in rows))

    def test_blacklisted_listing_does_not_count_as_a_missing_job(self):
        row = self.stage()[0]
        self.stage(title="SaaS Product Manager")
        with redirect_stdout(StringIO()):
            self.engine._reconcile_absences({"id": "CYC"}, self.company, [posting(title="SaaS Product Manager")])
        after = self.repo.read("Job History")[0]
        self.assertEqual(after["Consecutive Missing Scans"], 0)
        self.assertEqual(after["Job Status"], row["Job Status"])


if __name__ == "__main__":
    unittest.main()
