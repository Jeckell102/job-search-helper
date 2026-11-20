"""Geographic exclusions, U.S. alternatives, and ambiguous location safeguards."""
import unittest

from job_search_helper.locations import check_location
from job_search_helper.screening import screen_posting


class LocationTests(unittest.TestCase):
    def test_overseas_bases_are_rejected_including_remote_arrangements(self):
        for location in ("Hachioji, Japan", "Gurgaon, India", "Lonqueuil, Canada",
                         "London, United Kingdom", "Munich, Germany", "Singapore, SG",
                         "AE - Abu Dhabi", "SA - Riyadh", "QA - Doha", "Remote - UK",
                         "Cambridge, GBR", "Remote (Canada)", "Poland; Romania",
                         "Guantanamo Bay, Cuba", "Berlin, Germany / Paris, France",
                         "São Paulo, Brazil", "Japan", "Japan (Hybrid)"):
            with self.subTest(location=location):
                result = check_location(location)
                self.assertEqual(result.status, "non_us")
                self.assertIn(location, result.rejection_reason)
                for arrangement in ("Remote", "Hybrid", "Onsite", ""):
                    self.assertIn("Location exclusion", screen_posting({
                        "title": "Field Service Engineer", "location": location,
                        "work_arrangement": arrangement, "description": "Deploy customer hardware."
                    }).reason)

    def test_states_dc_and_explicit_us_remote_remain_eligible(self):
        for location in ("Austin, TX", "The Colony, TX, US", "Olathe, Kansas",
                         "California", "Washington, DC", "Honolulu, HI", "Anchorage, AK",
                         "USA-VA-Chantilly", "US - AL, Huntsville", "US Remote",
                         "Remote - US", "U.S. Remote", "US - Remote (Any Location)",
                         "United States", "United States of America", "London, OH",
                         "Paris, TX", "Toronto, OH", "India, TX", "Lebanon, OH",
                         "Mexico, MO", "Peru, IN", "Jordan, MN"):
            with self.subTest(location=location):
                # Conflicting labels may require review, but never reject a
                # U.S. state just because its city shares a foreign name.
                self.assertIsNone(check_location(location).rejection_reason)

    def test_a_us_alternative_survives_even_when_first_location_is_foreign(self):
        for location in ("Munich, Germany; Austin, TX", "Canada / United States",
                         "India | San Jose, California, United States",
                         "UK or USA", "Remote - US/Canada"):
            with self.subTest(location=location):
                self.assertEqual(check_location(location).status, "us")

    def test_unknowns_territories_and_conflicting_values_require_review(self):
        for location in ("", None, "Remote", "Worldwide", "Anywhere", "EMEA",
                         "London", "Georgia", "Bangalore, IN", "Berlin, DE",
                         "Andersen Air Force Base, GU, GU", "Guam", "Puerto Rico",
                         "Munich, Germany; Remote", "London, UK; Austin",
                         "Austin, TX, Germany"):
            with self.subTest(location=location):
                self.assertIsNone(check_location(location).rejection_reason)
        for location in (None, "Remote", "Guam", "Worldwide"):
            result = screen_posting({"title": "Field Service Engineer", "location": location})
            self.assertIsNone(result.reason)
            self.assertIn("Verify U.S. location", result.review_note)

    def test_foreign_travel_customers_and_hq_do_not_change_us_job_base(self):
        result = screen_posting({"title": "Field Service Engineer", "location": "Austin, TX",
            "description": "Travel up to 25% to Germany and Japan. Canadian customers. Headquarters in India."})
        self.assertIsNone(result.reason)


if __name__ == "__main__":
    unittest.main()
