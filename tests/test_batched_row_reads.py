"""Exact sparse review rows use bounded value requests; entirely offline."""
import copy
import unittest

from job_search_helper.repository import GoogleRepository, MemoryRepository, RepositoryError
from sheets_fixture import RangeSheets


SCHEMAS = {"Job History": ["Company", "Job Key", "Review Status"]}


class RecordingSheets(RangeSheets):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.batch_get_calls = []
        self.omit_last_range = False

    def values(self):
        inner = super().values()
        outer = self

        class Values:
            def get(self, **kwargs):
                return inner.get(**kwargs)

            def batchGet(self, **kwargs):
                outer.batch_get_calls.append(copy.deepcopy(kwargs))
                request = inner.batchGet(**kwargs)

                class Response:
                    def execute(self, num_retries=0):
                        result = request.execute(num_retries=num_retries)
                        if outer.omit_last_range:
                            result["valueRanges"].pop()
                        return result

                return Response()

        return Values()


class BatchedRowReadsTests(unittest.TestCase):
    def make(self, count=700):
        service = RecordingSheets({"Job History": [
            {"Company": "Fixture", "Job Key": str(index)} for index in range(count)
        ]}, schemas=SCHEMAS)
        return service, GoogleRepository(service, "fixture", schemas=SCHEMAS,
                                         min_request_interval=0)

    def test_100_sparse_rows_use_one_bounded_batch(self):
        service, repo = self.make()
        requested = [2 + index * 7 for index in range(100)]
        rows = repo.read_rows("Job History", requested)
        self.assertEqual(list(rows), requested)
        self.assertEqual(len(service.batch_get_calls), 1)
        self.assertEqual(service.batch_get_calls[0]["ranges"],
                         [f"'Job History'!A{row}:C{row}" for row in requested])
        for row in requested:
            self.assertEqual(rows[row], {"Company": "Fixture", "Job Key": str(row - 2),
                                         "Review Status": ""})

    def test_duplicates_are_read_once_and_blank_rows_are_padded(self):
        service, repo = self.make(1)
        rows = repo.read_rows("Job History", [1000, 2, 1000, 2])
        self.assertEqual(list(rows), [1000, 2])
        self.assertEqual(rows[1000], dict.fromkeys(SCHEMAS["Job History"], ""))
        self.assertEqual(rows[2]["Review Status"], "")
        self.assertEqual(service.batch_get_calls[0]["ranges"],
                         ["'Job History'!A1000:C1000", "'Job History'!A2:C2"])

    def test_more_than_100_rows_are_chunked(self):
        service, repo = self.make()
        rows = repo.read_rows("Job History", range(2, 103))
        self.assertEqual(len(rows), 101)
        self.assertEqual([len(call["ranges"]) for call in service.batch_get_calls], [100, 1])

    def test_empty_request_uses_no_service_calls(self):
        service, repo = self.make(1)
        self.assertEqual(repo.read_rows("Job History", []), {})
        self.assertEqual(service.get_calls, [])
        self.assertEqual(service.batch_get_calls, [])

    def test_invalid_row_numbers_are_rejected_before_data_requests(self):
        for row in (0, 1, -2, True, 2.0, "2", None, 1001):
            with self.subTest(row=row):
                service, repo = self.make(1)
                with self.assertRaises(RepositoryError):
                    repo.read_rows("Job History", [2, row])
                self.assertEqual(service.batch_get_calls, [])

    def test_native_grid_bound_is_used(self):
        service, repo = self.make(1)
        service.sheet("Job History")["properties"]["gridProperties"]["rowCount"] = 8
        with self.assertRaises(RepositoryError):
            repo.read_rows("Job History", [9])
        self.assertEqual(service.batch_get_calls, [])

    def test_omitted_response_range_is_rejected(self):
        service, repo = self.make(2)
        service.omit_last_range = True
        with self.assertRaisesRegex(RepositoryError, "omitted"):
            repo.read_rows("Job History", [2, 3])


class MemoryRowReadsTests(unittest.TestCase):
    def make(self):
        return MemoryRepository({"Job History": [{"Company": "Fixture", "Job Key": "one"}]},
                                schemas=SCHEMAS)

    def test_matches_single_reads_and_returns_detached_values(self):
        repo = self.make()
        rows = repo.read_rows("Job History", [3, 2, 3])
        self.assertEqual(list(rows), [3, 2])
        self.assertEqual(rows[2], repo.read_row("Job History", 2))
        self.assertEqual(rows[3], dict.fromkeys(SCHEMAS["Job History"], ""))
        rows[2]["Company"] = "Changed"
        self.assertEqual(repo.read_row("Job History", 2)["Company"], "Fixture")
        self.assertEqual(repo.read_rows("Job History", []), {})

    def test_invalid_rows_and_grid_bounds_are_rejected(self):
        repo = self.make()
        for row in (0, 1, -2, True, 2.0, "2", None, 1001):
            with self.subTest(row=row), self.assertRaises(RepositoryError):
                repo.read_rows("Job History", [row])


if __name__ == "__main__":
    unittest.main()
