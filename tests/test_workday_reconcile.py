import copy
import unittest
from unittest.mock import patch

from job_search_helper.ats import HTTPResponse, fetch_inventory
from test_ats import Transport, response
from test_workday import BOARD, WorkdayTransport, detail, listing, page


class WorkdayReconcileTests(unittest.TestCase):
    def fetch(self, responses):
        transport = WorkdayTransport(responses)
        result = fetch_inventory("Workday", BOARD, "COMP-0154", "Analog Devices", transport,
                                 discovery_transport=Transport([]))
        return result, transport

    def test_count_change_cannot_false_complete(self):
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, _ = self.fetch([
                page(2, [listing(1)]), page(2, [listing(2)]),
                page(3, [listing(2)]),
                response(detail(1)), response(detail(2)),
            ])
        self.assertEqual(result.status, "partial")
        self.assertNotEqual(result.status, "complete")

    def test_same_count_membership_change_cannot_false_complete(self):
        changed = copy.deepcopy(listing(2))
        changed["externalPath"] = "/job/Remote/Replacement_REQ3"
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, _ = self.fetch([
                page(2, [listing(1)]), page(2, [listing(2)]),
                response(detail(1)), response(detail(2)),
                page(2, [listing(1)]), page(2, [changed]),
                response(detail(3)),
                page(2, [listing(1)]), page(2, [listing(4)]),
            ])
        self.assertEqual(result.status, "partial")
        self.assertNotEqual(result.status, "complete")

    def test_failing_new_detail_keeps_verified_jobs_partial(self):
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, _ = self.fetch([
                page(2, [listing(1)]), page(2, [listing(2)]),
                response(detail(1)), HTTPResponse(404, b"missing"),
                page(2, [listing(1)]), page(2, [listing(2)]),
            ])
        self.assertEqual(result.status, "partial")
        self.assertEqual([job["req_id"] for job in result.jobs], ["REQ1"])

    def test_stable_fresh_replacement_cohort_can_complete(self):
        """A changed board is accepted only after two identical full rechecks."""
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, _ = self.fetch([
                page(2, [listing(1)]), page(2, [listing(2)]),
                response(detail(1)), response(detail(2)),
                # The initial final check observes the replacement cohort.
                page(2, [listing(3)]), page(2, [listing(4)]),
                # Reconciliation validates the new details before closure.
                response(detail(3)), response(detail(4)),
                page(2, [listing(3)]), page(2, [listing(4)]),
            ])
        self.assertEqual(result.status, "complete", result.reason)
        self.assertEqual({job["req_id"] for job in result.jobs}, {"REQ3", "REQ4"})

    def test_nonfirst_page_drift_cannot_false_complete(self):
        """A first-page match is insufficient when a later page changed."""
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, _ = self.fetch([
                page(2, [listing(1)]), page(2, [listing(2)]),
                response(detail(1)), response(detail(2)),
                # The first final cohort differs on page two, then changes
                # again after its newly fetched detail.
                page(2, [listing(1)]), page(2, [listing(3)]),
                response(detail(3)),
                page(2, [listing(1)]), page(2, [listing(4)]),
            ])
        self.assertEqual(result.status, "partial", result.reason)

    def test_listing_metadata_change_during_detail_fetch_cannot_complete(self):
        """Stable paths are not enough when a listing's advertised metadata moves."""
        changed = copy.deepcopy(listing(1))
        changed["title"] = "Replacement title"
        changed_again = copy.deepcopy(changed)
        changed_again["title"] = "Replacement title (updated)"
        with patch("job_search_helper.workday.PAGE_SIZE", 1):
            result, _ = self.fetch([
                page(2, [listing(1)]), page(2, [listing(2)]),
                response(detail(1)), response(detail(2)),
                page(2, [changed]), page(2, [listing(2)]),
                response(detail(1)),
                page(2, [changed_again]), page(2, [listing(2)]),
            ])
        self.assertEqual(result.status, "partial", result.reason)


if __name__ == "__main__":
    unittest.main()
