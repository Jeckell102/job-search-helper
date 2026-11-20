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
        skip_title_filter = changes.pop("skip_title_filter", False)
        return screen_posting({**posting(salary=""), **changes}, skip_title_filter=skip_title_filter)

    def test_shortlist_is_a_hint_and_never_an_allowlist(self):
        preferred = (
            "Field Applications Engineer", "Field Application Engineer", "Applications Engineer",
            "Product Applications Engineer", "Customer Applications Engineer", "Product Manager",
            "Assistant Product Manager", "Associate Product Manager", "Technical Product Manager",
            "Product Owner", "Product Line Manager", "Solutions Engineer",
            "Customer Engineer", "Product Engineer", "Field Support Engineer", "Field Service Engineer",
            "Senior Product Manager", "Principal Product Manager", "Principal Applications Engineer",
            "Lead Field Applications Engineer", "Technical Program Manager",
            "Staff Field Solutions Engineer", "Network Deployment Engineer",
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

    def test_hourly_base_is_annualized_including_starting_rates_and_shifts(self):
        for compensation in ("$32/hr", "$32-$34/hour", "USD 32 to 34 per hour",
                             "Hourly base pay: $32-$34.", "$57.69 per hour"):
            with self.subTest(compensation=compensation):
                result = self.screen(compensation=compensation)
                self.assertIn("Compensation exclusion", result.reason)
                self.assertIn("2,080 hours/year", result.reason)
        result = self.screen(description="The US base salary range for this full-time position starts at $32/hr for day shift, $34/hr for night shift.")
        self.assertIn("$70,720", result.reason)

    def test_hourly_unknown_currency_units_and_qualifying_alternatives_survive(self):
        for compensation in ("$57.70/hr", "$32-$60/hr", "$34/hr day; $65/hr night",
                             "CAD $32/hr", "C$32/hr", "EUR 32 per hour", "$32/hr plus uncapped commission",
                             "$32/hr or $140,000 annually", "$32/hr; another location pays $65",
                             "$32/hr including overtime and bonus", "Hourly pay is competitive"):
            with self.subTest(compensation=compensation):
                self.assertIsNone(self.screen(compensation=compensation).reason)
        self.assertIsNone(self.screen(description="Our equipment rental costs $32/hr.").reason)
        self.assertIsNone(self.screen(description="Base pay is $32/hr in Ohio. Annual base salary is $140,000 in California.").reason)

    def test_spelled_duration_and_fixed_term_agreement_are_employment_exclusions(self):
        for description in (
            "This is a six-month fixed-term agreement, with potential for longer-term opportunities depending on your contributions and interests.",
            "This is a six-month fixed-term role.", "This is a fixed-term agreement.",
            "The position is a 6-month fixed-term agreement.", "This is an eighteen-month contract position."):
            with self.subTest(description=description):
                self.assertIn("Employment exclusion", self.screen(description=description).reason)
        for description in ("Negotiate a six-month fixed-term agreement with suppliers.",
                            "This role manages fixed-term customer agreements.",
                            "This is not a six-month fixed-term agreement."):
            with self.subTest(description=description):
                self.assertIsNone(self.screen(description=description).reason)

    def test_existing_hard_blacklist_still_wins_and_saas_is_added(self):
        for title in ("Principal Software Engineer", "SaaS Product Manager",
                      "Product Manager, Software-as-a-Service", "Senior Engineer, Field Service",
                      "Lead Engineer, Field Support", "Product Manager, Research",
                      "Software Engineer / Solutions Engineer", "Systems Engineer - Mission Integration",
                      "Sales Engineer", "Pre-Sales Engineer", "Product Specialist", "Technical Product Specialist",
                      "Technical Project Manager", "Senior Business Development Engineer"):
            with self.subTest(title=title):
                self.assertEqual(classify_title(title), "reject")

    def test_recovered_opportunity_title_families_are_not_blacklisted(self):
        for title in ("Staff Product Manager", "Staff Field Solutions Engineer", "Director of Product",
                      "Director of Field Engineering", "Product Manager, Development",
                      "Senior Field Engineer - Electrical/Mechanical Integration",
                      "Field Test Engineer, Maritime", "Senior System Test Engineer",
                      "Applications Engineer, Learning & Development"):
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
                self.assertIn("Employment exclusion", self.screen(title=title, skip_title_filter=True).reason)
        for description in ("Permanent, full-time position.", "Manage customer contracts.",
                            "We are a government contractor.", "Negotiate a 12-month contract with suppliers.",
                            "This role is not temporary.", "Support temporary installations."):
            with self.subTest(description=description):
                self.assertIsNone(self.screen(description=description).reason)
        self.assertIsNone(self.screen(title="Product Manager, Temporary Power").reason)
        self.assertIsNone(self.screen(title="Temporary Power Product Manager").reason)
        self.assertIsNone(self.screen(title="Contract Manager", skip_title_filter=True).reason)
        self.assertIsNone(self.screen(description="This role is a contract specialist working with customers.").reason)

    def test_travel_coverage_and_speed_are_not_employee_time(self):
        for description in (
            "Our platform collects data from vehicles that travel 99.9% of U.S. roads.",
            "Our robots travel 75% of warehouse aisles.",
            "Sensors travel 80% of the route autonomously.",
            "Our vehicles travel 90% farther on a charge.",
            "Travel covers 75% of operating costs.",
        ):
            with self.subTest(description=description):
                self.assertIsNone(self.screen(description=description).reason)
        for description in (
            "You will travel up to 75% of your working time.",
            "Travel: 50-75% of the year.",
            "Travel up to 75% of scheduled work days.",
            "75% of your time travel is required.",
            "Our vehicles travel 99.9% of U.S. roads. This role requires 60% travel.",
            "Our robots travel 75% of aisles; travel up to 80% to customer sites.",
        ):
            with self.subTest(description=description):
                self.assertIn("Travel exclusion", self.screen(description=description).reason)

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

    def test_unknown_location_and_work_arrangement_require_review(self):
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

    def test_vehicle_coverage_enters_review_with_evidence(self):
        description = "Our vehicles travel 99.9% of U.S. roads. Own our device roadmap."
        row = self.stage(title="Lead Product Manager", description=description)[0]
        self.assertEqual(row["Added to Opportunities?"], "Pending")
        self.assertEqual(row["Review Status"], "Needs Review")
        self.assertEqual(row.get("Rejection Reason", ""), "")
        self.assertEqual(len(self.repo.read("Job Evidence")), 1)

    def test_overseas_location_is_rejected_before_ai_and_evidence_is_retained(self):
        row = self.stage(location="Hachioji, Japan")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Status"], "Reviewed")
        self.assertEqual(row["Decision"], "Reject")
        self.assertIn("Hachioji, Japan", row["Rejection Reason"])
        self.assertTrue(row["Job Description"].startswith("See Job Evidence tab:"))
        self.assertEqual(len(self.stage(location="Hachioji, Japan")), 1)

    def test_overseas_primary_with_us_alternative_stays_in_review(self):
        row = self.stage(location="Hachioji, Japan; Austin, TX")[0]
        self.assertEqual(row["Added to Opportunities?"], "Pending")
        self.assertEqual(row["Review Status"], "Needs Review")

    def test_existing_pending_overseas_job_is_rechecked_without_changing_first_seen(self):
        row = self.stage(location="Austin, TX")[0]
        self.repo.commit([{"tab": "Job History", "identity": {"Job Key": row["Job Key"]},
                           "values": {"First Seen": "2026-01-01", "Review Notes": "Keep my notes"}}])
        row = self.stage(location="Hachioji, Japan")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["First Seen"], "2026-01-01")
        self.assertEqual(row["Review Notes"], "Keep my notes")
        self.assertIn("Japan", row["Rejection Reason"])

    def test_existing_pending_job_receives_new_pay_or_employment_screen(self):
        for changes in ({"compensation": "$32/hr"}, {"description": "This is a six-month fixed-term agreement."}):
            self.setUp()
            row = self.stage()[0]
            self.repo.commit([{"tab": "Job History", "identity": {"Job Key": row["Job Key"]},
                "values": {"First Seen": "2026-01-01", "Review Notes": "Keep my notes"}}])
            after = self.stage(**changes)[0]
            self.assertEqual(after["Added to Opportunities?"], "No")
            self.assertEqual(after["Review Status"], "Reviewed")
            self.assertEqual(after["First Seen"], "2026-01-01")
            self.assertEqual(after["Review Notes"], "Keep my notes")

    def test_pending_rescreen_does_not_touch_a_managed_claim(self):
        row = self.stage()[0]
        self.state.path = "/fixture/state.db"
        before = self.repo.read("Job History")
        with patch("job_search_helper.location_cleanup.active_review_keys", return_value={row["Job Key"]}):
            self.assertEqual(self.stage(compensation="$32/hr"), before)

    def test_existing_manual_choice_and_review_claim_are_preserved_for_overseas_job(self):
        row = self.stage(location="Austin, TX")[0]
        self.repo.commit([{"tab": "Job History", "identity": {"Job Key": row["Job Key"]},
                           "values": {"Added to Opportunities?": "No", "Review Notes": "My decision"}}])
        row = self.stage(location="Hachioji, Japan")[0]
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Notes"], "My decision")
        self.assertEqual(row["Decision"], "")

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
