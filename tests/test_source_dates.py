import unittest

from job_search_helper.dates import normalize_source_date, readable_timestamp
from job_search_helper.models import JobPosting


class SourceDateTests(unittest.TestCase):
    def test_dates_preserve_precision_and_normalize_known_timezones(self):
        cases = {
            "2026-09-25": "2026-09-25",
            "2026-09-25T08:30:12-04:00": "2026-09-25T12:30:12Z",
            "2026-09-25T08:30:12.125-0400": "2026-09-25T12:30:12.125000Z",
            "2026-09-25 08:30": "2026-09-25T08:30:00",
            "September 25, 2026": "2026-09-25",
            "25 Sep 2026": "2026-09-25",
            "2026-02-30": None,
            "09/10/2026": None,
            "3 days ago": None,
            "taleo-job-id:987": None,
            "": None,
            "20260925": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_source_date(raw), expected)

    def test_epoch_conversion_is_provider_specific_and_raw_value_survives(self):
        row = {"posting_id": "001", "ats": "Lever", "created_at": "1704067200000"}
        posting = JobPosting.from_adapter(row)
        self.assertEqual(posting.source_created_at, "2024-01-01T00:00:00Z")
        self.assertEqual(posting.source_created_raw, "1704067200000")
        self.assertIsNone(JobPosting.from_adapter(dict(row, ats="Unknown")).source_created_at)

    def test_text_display_labels_utc_without_changing_date_only_values(self):
        self.assertEqual(readable_timestamp("2026-09-25T12:30:00Z"), "2026-09-25 12:30:00 UTC")
        self.assertEqual(readable_timestamp("2026-09-25"), "2026-09-25")
