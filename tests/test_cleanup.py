import argparse
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from job_search_helper import cli
from job_search_helper.cleanup import cleanup_blacklisted_history, plan_blacklist_cleanup
from job_search_helper.repository import GoogleRepository, MemoryRepository, RepositoryError, SCHEMAS


def rejected(title):
    return "reject" if any(word in title.casefold() for word in ("software", "director", "duplicate", "locked")) else "review"


class BlacklistCleanupTests(unittest.TestCase):
    def rows(self):
        return [
            {"Company": "Acme", "Job Title": "Software Engineer", "Added to Opportunities?": "Yes",
             "Job Key": "one", "Official Job URL": "https://example.com/1", "Review Status": "Reviewed",
             "Review Notes": "preserve me"},
            {"Company": "Acme", "Job Title": "Field Applications Engineer", "Added to Opportunities?": "Yes",
             "Job Key": "two", "Official Job URL": "https://example.com/2"},
            {"Company": "Beta", "Job Title": "Director of Sales", "Added to Opportunities?": "No",
             "Job Key": "three", "Official Job URL": "https://example.com/3"},
            {"Company": "Gamma", "Job Title": "Locked Engineer", "Added to Opportunities?": "Pending",
             "Job Key": "four", "Official Job URL": "https://example.com/4", "Review Status": "In Progress"},
            {"Company": "Same", "Job Title": "Duplicate Role", "Added to Opportunities?": "Yes"},
            {"Company": "Same", "Job Title": "Duplicate Role", "Added to Opportunities?": "Pending"},
        ]

    @patch("job_search_helper.cleanup.classify_title", side_effect=rejected)
    @patch("job_search_helper.cleanup.load_title_blacklist")
    def test_plan_updates_only_identifiable_unlocked_matches(self, _load, _classify):
        repo = MemoryRepository({"Job History": self.rows()})
        operations, summary = plan_blacklist_cleanup(repo)
        self.assertEqual(summary["rows_scanned"], 6)
        self.assertEqual(summary["blacklisted_titles"], 5)
        self.assertEqual(summary["already_no"], 1)
        self.assertEqual(summary["proposed_updates"], 1)
        self.assertEqual(summary["locked_in_progress"], 1)
        self.assertEqual(summary["unresolved_identity"], 2)
        self.assertEqual(operations[0]["values"], {"Added to Opportunities?": "No"})
        self.assertEqual(operations[0]["identity"]["Job Title"], "Software Engineer")

    @patch("job_search_helper.cleanup.classify_title", side_effect=rejected)
    @patch("job_search_helper.cleanup.load_title_blacklist")
    def test_dry_run_is_read_only_and_apply_preserves_other_cells(self, _load, _classify):
        repo = MemoryRepository({"Job History": self.rows()})
        preview = cleanup_blacklisted_history(repo)
        self.assertEqual(preview["spreadsheet_changes"], 0)
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"], "Yes")
        applied = cleanup_blacklisted_history(repo, apply=True)
        row = repo.read("Job History")[0]
        self.assertEqual(applied["spreadsheet_changes"], 1)
        self.assertEqual(row["Added to Opportunities?"], "No")
        self.assertEqual(row["Review Notes"], "preserve me")

    @patch("job_search_helper.cleanup.classify_title", side_effect=rejected)
    @patch("job_search_helper.cleanup.load_title_blacklist")
    def test_stale_title_aborts_instead_of_updating_wrong_row(self, _load, _classify):
        repo = MemoryRepository({"Job History": self.rows()})
        operations, _ = plan_blacklist_cleanup(repo)
        repo.commit([{"tab": "Job History", "identity": {"Job Key": "one"},
                      "values": {"Job Title": "Changed Role"}}])
        with self.assertRaises(RepositoryError):
            repo.commit([{key: value for key, value in operation.items() if key != "row_number"}
                         for operation in operations])
        self.assertEqual(repo.read("Job History")[0]["Added to Opportunities?"], "Yes")

    def google_repo(self, *, value="Yes", formula=False):
        service = MagicMock()
        grid = {"sheets": [{"data": [{"startRow": 1, "startColumn": 2, "rowData": [
            {"values": [{"userEnteredValue": ({"formulaValue": "=TRUE"} if formula else {"stringValue": value}),
                         "dataValidation": {"strict": True, "condition": {"type": "ONE_OF_LIST",
                             "values": [{"userEnteredValue": "Yes"}, {"userEnteredValue": "No"},
                                        {"userEnteredValue": "Pending"}]}}}]}
        ]}]}]}
        service.spreadsheets.return_value.get.return_value.execute.return_value = grid
        service.spreadsheets.return_value.batchUpdate.return_value.execute.return_value = {}
        repo = GoogleRepository(service, "working-sheet", min_request_interval=0)
        headers = SCHEMAS["Job History"]
        repo._headers = MagicMock(return_value=(headers, {header: index for index, header in enumerate(headers)}))
        repo._metadata = MagicMock(return_value={"sheets": [{"properties": {"title": "Job History",
            "sheetId": 123, "gridProperties": {"rowCount": 20_694, "columnCount": 32}}}]})
        row = {header: "" for header in headers}
        row.update({"Company": "Acme", "Job Title": "Software Engineer", "Added to Opportunities?": value,
                    "Job Key": "one", "Official Job URL": "https://example.com/1", "Review Status": "Reviewed"})
        repo.read_columns = MagicMock(return_value=[(2, row)])
        operation = {"tab": "Job History", "row_number": 2,
                     "identity": {"Job Key": "one", "Job Title": "Software Engineer", "Review Status": "Reviewed"},
                     "values": {"Added to Opportunities?": "No"}}
        return repo, service, operation

    def test_targeted_google_commit_accepts_large_empty_grid_and_updates_only_column_c(self):
        repo, service, operation = self.google_repo()
        result = repo.commit_existing_job_history_flags([operation])
        self.assertEqual(result["updated"], 1)
        request = service.spreadsheets.return_value.batchUpdate.call_args.kwargs["body"]["requests"][0]
        self.assertEqual(request["updateCells"]["start"], {"sheetId": 123, "rowIndex": 1, "columnIndex": 2})
        self.assertEqual(request["updateCells"]["fields"], "userEnteredValue")
        read = service.spreadsheets.return_value.get.call_args.kwargs
        self.assertEqual(read["ranges"], ["'Job History'!C2:C20694"])
        self.assertNotIn("Job Description", str(read))

    def test_targeted_google_commit_rejects_stale_identity_formula_and_review_lock(self):
        repo, service, operation = self.google_repo()
        repo.read_columns.return_value[0][1]["Job Title"] = "Changed"
        with self.assertRaisesRegex(RepositoryError, "changed after cleanup planning"):
            repo.commit_existing_job_history_flags([operation])
        service.spreadsheets.return_value.batchUpdate.assert_not_called()

        repo, service, operation = self.google_repo(formula=True)
        with self.assertRaisesRegex(RepositoryError, "formula"):
            repo.commit_existing_job_history_flags([operation])
        service.spreadsheets.return_value.batchUpdate.assert_not_called()

        repo, service, operation = self.google_repo()
        repo.read_columns.return_value[0][1]["Review Status"] = "In Progress"
        operation["identity"].pop("Review Status")
        with self.assertRaisesRegex(RepositoryError, "entered review"):
            repo.commit_existing_job_history_flags([operation])
        service.spreadsheets.return_value.batchUpdate.assert_not_called()

    def test_cli_parser_defaults_to_dry_run_and_apply_requires_lock(self):
        args = cli.parser().parse_args(["cleanup-blacklist"])
        self.assertFalse(args.apply)
        with self.assertRaises(ValueError):
            cli.require_single_writer(cli.parser().parse_args(["cleanup-blacklist", "--apply"]))

    @patch("job_search_helper.cleanup.classify_title", return_value="reject")
    @patch("job_search_helper.cleanup.load_title_blacklist")
    def test_malformed_url_falls_back_to_unique_company_and_title(self, _load, _classify):
        repo = MemoryRepository({"Job History": [{"Company": "Acme", "Job Title": "Software Engineer",
            "Added to Opportunities?": "Yes", "Official Job URL": "not a URL"}]})
        operations, summary = plan_blacklist_cleanup(repo)
        self.assertEqual(summary["proposed_updates"], 1)
        self.assertEqual(operations[0]["identity"]["Company"], "Acme")

    @patch("job_search_helper.cli.get_repository")
    @patch("job_search_helper.cli.cleanup_blacklisted_history", return_value={"proposed_updates": 2})
    def test_cli_dry_run_uses_read_only_repository(self, cleanup, repository):
        repository.return_value.validate_schema.return_value = True
        args = cli.parser().parse_args(["cleanup-blacklist"])
        with redirect_stdout(StringIO()) as output:
            cli.execute_cleanup(args)
        repository.assert_called_once_with(write=False, interactive=False)
        cleanup.assert_called_once_with(repository.return_value, apply=False)
        self.assertIn('"proposed_updates": 2', output.getvalue())


if __name__ == "__main__":
    unittest.main()
