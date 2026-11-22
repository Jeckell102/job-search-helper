"""Focused tests for the source-only Crown failure witness."""

import unittest

from crown_inventory_regression import CrownBoard, HOST
from job_search_helper.ats import CROWN_LISTING_RANGE_CODE, HTTPResponse, fetch_inventory
from job_search_helper.successfactors import CROWN_SOURCE


class CrownAdmissionEvidenceTest(unittest.TestCase):
    def test_exact_crown_listing_produces_a_typed_partial(self):
        board = CrownBoard()
        result = fetch_inventory(
            "SuccessFactors", HOST + "/", "COMP-0588", "Crown Equipment",
            discovery_transport=board,
        )
        failure = result.outcome_failure
        self.assertEqual("partial", result.status)
        self.assertEqual([], result.jobs)
        self.assertEqual("pagination_regression", failure["category"])
        self.assertEqual(CROWN_LISTING_RANGE_CODE, failure["evidence_code"])
        self.assertEqual(2, failure["evidence"]["listing_count"])
        self.assertEqual({CROWN_SOURCE: 1}, dict(board.calls))

    def test_foreign_missing_or_unavailable_inventory_produces_no_witness(self):
        cases = (
            (200, b"<body>No listings</body>"),
            (200, b'<a class="jobTitle-link" href="https://example.com/job/Test/10001/">Role</a>'),
            (403, b'<a class="jobTitle-link" href="/job/Test/10001/">Role</a>'),
        )
        for status, body in cases:
            with self.subTest(status=status, body=body):
                class Board:
                    def get(self, url):
                        if url != CROWN_SOURCE:
                            raise AssertionError(f"Unexpected read: {url}")
                        return HTTPResponse(status, body)

                result = fetch_inventory(
                    "SuccessFactors", HOST + "/", "COMP-0588", "Crown Equipment",
                    discovery_transport=Board(),
                )
                self.assertIsNone(result.outcome_failure)

    def test_matching_markup_from_wrong_company_produces_no_witness(self):
        result = fetch_inventory(
            "SuccessFactors", CROWN_SOURCE, "COMP-9999", "Different Company",
            discovery_transport=CrownBoard(),
        )
        self.assertEqual("partial", result.status)
        self.assertIsNone(result.outcome_failure)


if __name__ == "__main__":
    unittest.main()
