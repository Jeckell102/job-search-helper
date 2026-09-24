import copy
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from job_search_helper.repository import (
    ALLOWED_TABS, GoogleRepository, MemoryRepository, RepositoryError, SCHEMAS,
    authorize, PROTECTED_BACKUP_ID,
)


def operation(tab="Job History", key="job-1", values=None, **kwargs):
    return {"tab": tab, "identity": {"Job Key": key}, "values": values or {}, **kwargs}


class MemoryRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = MemoryRepository({"Job History": [{"Job Key": "job-1", "Company": "Acme"}]})

    def test_default_schema_and_empty_tabs(self):
        self.assertTrue(self.repo.validate_schema())
        self.assertEqual(set(self.repo.tables), set(ALLOWED_TABS))

    def test_allowlist_does_not_read_prompt_library(self):
        with self.assertRaises(RepositoryError):
            self.repo.read("Prompt Library — Reference Only")
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(tab="Prompt Library — Reference Only")])

    def test_read_returns_detached_copy(self):
        rows = self.repo.read("Job History")
        rows[0]["Company"] = "Changed"
        self.assertEqual(self.repo.read("Job History")[0]["Company"], "Acme")

    def test_cell_updates_preserve_other_fields(self):
        self.repo.commit([operation(values={"Review Notes": "review"})])
        row = self.repo.read("Job History")[0]
        self.assertEqual(row["Company"], "Acme")
        self.assertEqual(row["Review Notes"], "review")

    def test_insert_requires_flag(self):
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(key="missing", values={"Company": "Acme"})])

    def test_insert_is_idempotent_and_on_insert_not_reapplied(self):
        op = operation(key="new", values={"Review Notes": "one"},
                       append_if_missing=True, on_insert={"Company": "Acme"})
        self.repo.commit([op])
        self.repo.commit([operation(key="new", values={"Company": "Changed"})])
        self.repo.commit([op])
        rows = self.repo.read("Job History")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["Company"], "Changed")

    def test_entire_batch_rolls_back_on_later_failure(self):
        before = self.repo.tables
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Review Notes": "unsafe"}),
                              operation(key="missing", values={"Company": "oops"})])
        self.assertEqual(before, self.repo.tables)

    def test_unknown_header_rejected(self):
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Title": "wrong header"})])

    def test_empty_identity_rejected(self):
        for identity in ({}, {"Job Key": ""}, {"Job Key": "   "}):
            with self.subTest(identity=identity), self.assertRaises(RepositoryError):
                self.repo.commit([{"tab": "Job History", "identity": identity}])

    def test_identity_cannot_change_itself(self):
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Job Key": "different"})])

    def test_ambiguous_rows_rejected(self):
        repo = MemoryRepository({"Job History": [{"Job Key": "x"}, {"Job Key": "x"}]})
        with self.assertRaises(RepositoryError):
            repo.commit([operation(key="x", values={"Review Notes": "ambiguous"})])

    def test_company_matching_case_insensitive(self):
        self.repo.commit([{"tab": "Job History", "identity": {"Company": " ACME "},
                           "values": {"Review Notes": "matched"}}])
        self.assertEqual(self.repo.read("Job History")[0]["Review Notes"], "matched")

    def test_url_tracking_match_preserves_job_identifier(self):
        repo = MemoryRepository({"Opportunities": [{"Company": "Acme", "Job URL":
            "https://example.com/job?gh_jid=12&utm_source=x", "Notes": "mine"}]})
        repo.commit([{"tab": "Opportunities", "identity": {"Company": "acme", "Job URL":
            "https://example.com/job?gh_jid=12"}, "append_notes": {"Notes": "Update"}}])
        self.assertIn("mine", repo.read("Opportunities")[0]["Notes"])
        with self.assertRaises(RepositoryError):
            repo.commit([{"tab": "Opportunities", "identity": {"Company": "Acme", "Job URL":
                "https://example.com/job?gh_jid=13"}, "values": {"Location": "Ohio"}}])

    def test_user_application_fields_and_notes_preserved(self):
        repo = MemoryRepository({"Opportunities": [{"Company": "Acme", "Job URL": "https://example.com/job",
            "Application Status": "Applied", "Date Applied": "2026-01-01", "Notes": "My private note"}]})
        base = {"tab": "Opportunities", "identity": {"Job URL": "https://example.com/job"}}
        for field, value in (("Application Status", "Not Reviewed"), ("Date Applied", ""), ("Notes", "overwrite")):
            with self.subTest(field=field), self.assertRaises(RepositoryError):
                repo.commit([{**base, "values": {field: value}}])
        op = {**base, "append_notes": {"Notes": "Reviewed change #1"}}
        repo.commit([op, op])
        row = repo.read("Opportunities")[0]
        self.assertEqual(row["Notes"], "My private note\n\nReviewed change #1")
        self.assertEqual(row["Application Status"], "Applied")

    def test_append_cannot_be_used_to_replace_notes(self):
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Review Notes": "replacement"},
                                       append_notes={"Review Notes": "append"})])

    def test_formula_like_text_remains_literal(self):
        text = '=IMPORTDATA("https://example.invalid")'
        self.repo.commit([operation(values={"Review Notes": text})])
        sheet = self.repo._sheets["Job History"]
        cell = sheet.cells[(1, sheet.headers.index("Review Notes"))]
        self.assertEqual(cell["userEnteredValue"], {"stringValue": text})

    def test_existing_formula_unchanged(self):
        sheet = self.repo._sheets["Job History"]
        col = sheet.headers.index("Review Notes")
        sheet.cells[(1, col)] = {"userEnteredValue": {"formulaValue": '=IF(1,"kept","")'},
                                "effectiveValue": {"stringValue": "kept"}}
        self.repo.commit([operation(values={"Review Notes": "kept"})])
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Review Notes": "lost formula"})])
        self.assertIn("formulaValue", self.repo._sheets["Job History"].cells[(1, col)]["userEnteredValue"])

    def test_duplicate_and_empty_headers_rejected(self):
        for headers in (["Job Key", "job key"], ["Job Key", ""]):
            repo = MemoryRepository({}, schemas={"Job History": headers})
            with self.assertRaises(RepositoryError):
                repo.validate_schema()

    def test_nested_values_and_oversized_cells_rejected(self):
        for value in ({"json": "not serialized"}, ["list"], float("nan"), "x" * 45_001):
            with self.subTest(type=type(value)), self.assertRaises(RepositoryError):
                self.repo.commit([operation(values={"Review Notes": value})])

    def test_checkbox_and_dropdown_validation(self):
        sheet = self.repo._sheets["Job History"]
        col = sheet.headers.index("Reconsideration Status")
        sheet.cells[(1, col)] = {"dataValidation": {"strict": True,
            "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Eligible"}]}}}
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Reconsideration Status": "Active"})])
        self.repo.commit([operation(values={"Reconsideration Status": "Eligible"})])


class _Result:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def execute(self):
        if self.error:
            raise self.error
        return copy.deepcopy(self.value)


class FakeSheets:
    def __init__(self, tabs=None, *, schemas=None):
        self.schemas = SCHEMAS if schemas is None else schemas
        self.sheets = []
        self.get_calls = []
        self.batches = []
        self.write_error = None
        for sheet_id, (tab, headers) in enumerate(self.schemas.items(), 1):
            rows = [{"values": [{"userEnteredValue": {"stringValue": h},
                                  "effectiveValue": {"stringValue": h}} for h in headers]}]
            for record in (tabs or {}).get(tab, []):
                rows.append({"values": [{"userEnteredValue": {"stringValue": str(record.get(h, ""))},
                                          "effectiveValue": {"stringValue": str(record.get(h, ""))}}
                                         for h in headers]})
            self.sheets.append({"properties": {"sheetId": sheet_id, "title": tab,
                "gridProperties": {"rowCount": 1000, "columnCount": max(26, len(headers))}},
                "data": [{"rowData": rows}], "tables": []})

    def spreadsheets(self):
        return self

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        sheets = self.sheets
        if kwargs.get("ranges"):
            selected = {r.split("!")[0].strip("'") for r in kwargs["ranges"]}
            sheets = [s for s in sheets if s["properties"]["title"] in selected]
        return _Result({"sheets": sheets})

    def batchUpdate(self, **kwargs):
        self.batches.append(copy.deepcopy(kwargs))
        return _Result({}, self.write_error)

    def sheet(self, title):
        return next(s for s in self.sheets if s["properties"]["title"] == title)


class GoogleRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.service = FakeSheets({"Job History": [{"Job Key": "job-1", "Company": "Acme"}],
                                  "Opportunities": [{"Company": "Acme", "Job URL": "https://example.com/job",
                                                     "Application Status": "Applied", "Notes": "Mine"}]})
        self.repo = GoogleRepository(self.service, "test-spreadsheet-id", min_request_interval=0)

    def test_validate_required_headers(self):
        self.assertTrue(self.repo.validate_schema())
        self.service.sheet("Job History")["data"][0]["rowData"][0]["values"][10] = {}
        with self.assertRaises(RepositoryError):
            self.repo.validate_schema()

    def test_ranges_bounded_and_prompt_cells_not_read(self):
        self.repo.read("Job History")
        call = self.service.get_calls[-1]
        self.assertEqual(call["ranges"], ["'Job History'!A1:AF1000"])
        self.assertNotIn("Prompt Library", json.dumps(call))
        for request in self.service.get_calls:
            fields = request["fields"]
            self.assertEqual(fields.count("("), fields.count(")"))

    def test_oversized_grid_not_silently_truncated(self):
        self.service.sheet("Job History")["properties"]["gridProperties"]["rowCount"] = 100001
        with self.assertRaises(RepositoryError):
            self.repo.read("Job History")

    def test_two_sheet_job_commit_uses_one_atomic_batch(self):
        self.repo.commit([
            operation(values={"Review Notes": "Evaluated"}),
            {"tab": "Opportunities", "identity": {"Company": "Acme", "Job URL": "https://example.com/job"},
             "values": {"Location": "Ohio"}, "append_notes": {"Notes": "Scanner update"}},
        ])
        self.assertEqual(len(self.service.batches), 1)
        requests = self.service.batches[0]["body"]["requests"]
        self.assertEqual(len(requests), 3)
        for request in requests:
            update = request["updateCells"]
            self.assertEqual(update["fields"], "userEnteredValue")
            self.assertEqual(len(update["rows"][0]["values"]), 1)
        serialized = json.dumps(self.service.batches)
        self.assertNotIn("clear", serialized)
        self.assertNotIn("USER_ENTERED", serialized)
        self.assertNotIn("Applied", serialized)

    def test_google_validation_failure_has_zero_writes(self):
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(values={"Review Notes": "first"}), operation(key="missing")])
        self.assertEqual(self.service.batches, [])

    def test_hyperlink_cell_used_instead_of_display_text(self):
        cells = self.service.sheet("Opportunities")["data"][0]["rowData"][1]["values"]
        cells[2] = {"userEnteredValue": {"formulaValue": '=HYPERLINK("https://example.com/job", "Apply")'},
                    "effectiveValue": {"stringValue": "Apply"}, "hyperlink": "https://example.com/job"}
        self.assertEqual(self.repo.read("Opportunities")[0]["Job URL"], "https://example.com/job")
        self.repo.commit([{"tab": "Opportunities", "identity": {"Job URL": "https://example.com/job"},
                           "values": {"Job URL": "https://example.com/job", "Location": "Remote"}}])
        requests = self.service.batches[0]["body"]["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["updateCells"]["start"]["columnIndex"], 3)

    def test_formula_hyperlink_fallback_and_ambiguous_links(self):
        cells = self.service.sheet("Opportunities")["data"][0]["rowData"][1]["values"]
        cells[2] = {"userEnteredValue": {"formulaValue": '=HYPERLINK("https://example.com/job"; "Apply")'},
                    "effectiveValue": {"stringValue": "Apply"}}
        self.assertEqual(self.repo.read("Opportunities")[0]["Job URL"], "https://example.com/job")
        cells[2] = {"textFormatRuns": [{"format": {"link": {"uri": "https://example.com/a"}}},
                                       {"format": {"link": {"uri": "https://example.com/b"}}}]}
        with self.assertRaises(RepositoryError):
            self.repo.read("Opportunities")

    def test_native_table_expands_in_same_batch(self):
        sheet = self.service.sheet("Job History")
        sheet["properties"]["gridProperties"]["rowCount"] = 2
        sheet["tables"] = [{"tableId": "history-table", "range": {"sheetId": 3,
            "startRowIndex": 0, "endRowIndex": 2, "startColumnIndex": 0,
            "endColumnIndex": len(SCHEMAS["Job History"])}}]
        self.repo.commit([operation(key="new", values={"Company": "Acme"}, append_if_missing=True)])
        requests = self.service.batches[0]["body"]["requests"]
        self.assertEqual(requests[0]["appendDimension"]["length"], 1)
        self.assertEqual(requests[1]["updateTable"]["table"]["range"]["endRowIndex"], 3)

    def test_table_dropdown_rejects_unsupported_fit_label(self):
        sheet = self.service.sheet("Opportunities")
        sheet["tables"] = [{"tableId": "opportunities", "range": {"sheetId": 2,
            "startRowIndex": 0, "endRowIndex": 1000, "startColumnIndex": 0, "endColumnIndex": 12},
            "columnProperties": [{"columnIndex": 6, "dataValidationRule": {"condition": {
                "type": "ONE_OF_LIST", "values": [{"userEnteredValue": "Potential Fit"}]}}}]}]
        with self.assertRaises(RepositoryError):
            self.repo.commit([{"tab": "Opportunities", "identity": {"Job URL": "https://example.com/job"},
                               "values": {"Fit Review": "Stretch"}}])
        self.assertEqual(self.service.batches, [])

    def test_footer_table_append_fails_closed(self):
        self.service.sheet("Job History")["tables"] = [{"tableId": "x", "rowsProperties": {
            "footerColorStyle": {}}, "range": {"endColumnIndex": 24, "endRowIndex": 2}}]
        with self.assertRaises(RepositoryError):
            self.repo.commit([operation(key="new", append_if_missing=True)])
        self.assertEqual(self.service.batches, [])

    def test_server_failure_not_claimed_success_or_automatically_retried(self):
        self.service.write_error = TimeoutError("Connection interrupted")
        with self.assertRaisesRegex(RepositoryError, "No successful write is confirmed"):
            self.repo.commit([operation(values={"Review Notes": "reviewed"})])
        self.assertEqual(len(self.service.batches), 1)

    def test_unexpected_field_no_writes(self):
        with self.assertRaises(RepositoryError):
            self.repo.commit([{**operation(), "delete": True}])
        self.assertEqual(self.service.batches, [])

    def test_numeric_header_fails_closed(self):
        header = self.service.sheet("Job History")["data"][0]["rowData"][0]["values"][0]
        header["effectiveValue"] = {"numberValue": 1}
        with self.assertRaises(RepositoryError):
            self.repo.read("Job History")

    def test_known_backup_can_be_read_but_not_written(self):
        backup = GoogleRepository(self.service, PROTECTED_BACKUP_ID, min_request_interval=0)
        self.assertEqual(backup.read("Job History")[0]["Job Key"], "job-1")
        with self.assertRaisesRegex(RepositoryError, "protected Job Search Master"):
            backup.commit([operation(values={"Review Notes": "do not touch backup"})])
        self.assertEqual(self.service.batches, [])

    def test_default_api_pacing_applies_to_all_requests(self):
        repo = GoogleRepository(self.service, "test-id")
        with patch("job_search_helper.repository.time.monotonic", return_value=100.0), \
                patch("job_search_helper.repository.time.sleep") as sleep:
            repo.read("Job History")
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args[0][0], 1.1)


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.secret = self.directory / "secrets"
        self.secret.mkdir(mode=0o700)
        self.read = self.secret / "read.json"
        self.write = self.secret / "write.json"
        self.credential_file = self.directory / "credentials.json"
        self.environment = {
            "GOOGLE_TOKEN_READ_FILE": str(self.read),
            "GOOGLE_TOKEN_WRITE_FILE": str(self.write),
            "GOOGLE_CREDENTIALS_FILE": str(self.credential_file),
        }
        self.scope = "https://www.googleapis.com/auth/spreadsheets.readonly"
        self.interactions = []
        modules = {name: types.ModuleType(name) for name in (
            "google", "google.auth", "google.auth.transport", "google.auth.transport.requests",
            "google.oauth2", "google.oauth2.credentials", "google_auth_oauthlib",
            "google_auth_oauthlib.flow", "googleapiclient", "googleapiclient.discovery")}
        owner = self

        class Credentials:
            valid = True
            expired = False
            refresh_token = "not-a-real-token"

            @classmethod
            def from_authorized_user_info(cls, saved, scopes):
                owner.interactions.append(("load", scopes))
                result = cls()
                result.scopes = scopes
                return result

            def to_json(self):
                return json.dumps({"scopes": self.scopes, "token": "not-real"})

        class Flow:
            @classmethod
            def from_client_secrets_file(cls, path, scopes):
                owner.interactions.append(("flow", scopes))
                result = cls()
                result.scopes = scopes
                return result

            def run_local_server(self, **kwargs):
                owner.interactions.append(("browser", kwargs))
                credentials = Credentials()
                credentials.scopes = self.scopes
                return credentials

        modules["google.auth.transport.requests"].Request = lambda: None
        modules["google.oauth2.credentials"].Credentials = Credentials
        modules["google_auth_oauthlib.flow"].InstalledAppFlow = Flow
        modules["googleapiclient.discovery"].build = lambda *args, **kwargs: "sheets-service"
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.env_patch = patch.dict(os.environ, self.environment)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def token(self, path, scope=None):
        path.write_text(json.dumps({"scopes": [scope or self.scope]}), encoding="utf-8")
        path.chmod(0o600)

    def test_no_implicit_browser_authentication(self):
        with self.assertRaisesRegex(RepositoryError, "explicit authenticate"):
            authorize(write=False, interactive=False)
        self.assertEqual(self.interactions, [])
        self.assertFalse(self.read.exists())

    def test_existing_read_token_uses_readonly_scope(self):
        self.token(self.read)
        self.assertEqual(authorize(write=False), "sheets-service")
        self.assertEqual(self.interactions, [("load", [self.scope])])

    def test_read_token_cannot_be_reused_for_writes(self):
        self.token(self.read)
        with self.assertRaisesRegex(RepositoryError, "explicit authenticate"):
            authorize(write=True)
        self.assertFalse(self.write.exists())

    def test_shared_token_path_rejected(self):
        with patch.dict(os.environ, {"GOOGLE_TOKEN_WRITE_FILE": str(self.read)}):
            with self.assertRaisesRegex(RepositoryError, "different token files"):
                authorize(write=False)

    def test_excess_token_scopes_rejected(self):
        self.token(self.read, "https://www.googleapis.com/auth/spreadsheets")
        with self.assertRaisesRegex(RepositoryError, "scopes do not exactly match"):
            authorize(write=False)

    def test_world_readable_token_rejected(self):
        self.token(self.read)
        self.read.chmod(0o644)
        with self.assertRaisesRegex(RepositoryError, "permissions must be 0600"):
            authorize(write=False)

    def test_explicit_authentication_saves_private_token(self):
        self.credential_file.write_text("{}", encoding="utf-8")
        self.assertEqual(authorize(write=False, interactive=True), "sheets-service")
        self.assertEqual(self.read.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.secret.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.write.exists())
        self.assertEqual(self.interactions[1][0], "browser")


if __name__ == "__main__":
    unittest.main()
