"""Offline sparse scraper commits retain identity and append safeguards."""
import copy
import re
import unittest

from job_search_helper.batching import PlanningRepository
from job_search_helper.repository import GoogleRepository, RepositoryError
from sheets_fixture import RangeSheets, column


def operation(tab, identity, values, **options):
    return {"tab": tab, "identity": identity, "values": values, **options}


class SheetReadOptimizationTests(unittest.TestCase):
    def make(self, count=40):
        tables = {
            "Companies": [{"Company": f"Company {i}", "Company ID": f"c-{i}",
                           "Scan State": "Queued", "Notes": "Personal company notes. " * 600}
                          for i in range(count)],
            "Job History": [{"Company": f"Company {i}", "Job Key": f"j-{i}",
                             "Official Job URL": f"https://example.test/jobs/{i}",
                             "Current Snapshot": "Saved job snapshot. " * 600,
                             "Job Description": "Full history description. " * 600}
                            for i in range(count)],
            "Job Evidence": [{"Job Key": f"j-{i}", "Source Hash": "h1",
                              "Company": f"Company {i}", "Captured At": "before",
                              "Job Description": "Full evidence description. " * 600}
                             for i in range(count)],
        }
        service = RangeSheets(tables)
        return service, GoogleRepository(service, "fixture", min_request_interval=0)

    def bounds(self, service, area):
        title, span = area.split("!", 1)
        title = title.strip("'").replace("''", "'")
        grid = service.sheet(title)["properties"]["gridProperties"]
        first, last = span.split(":") if ":" in span else (span, span)
        start = re.fullmatch(r"([A-Z]*)(\d*)", first)
        end = re.fullmatch(r"([A-Z]*)(\d*)", last)
        return (title, int(start[2]) - 1 if start[2] else 0,
                int(end[2]) if end[2] else grid["rowCount"],
                column(start[1]) if start[1] else 0,
                column(end[1]) + 1 if end[1] else grid["columnCount"])

    def requested(self, service):
        return [self.bounds(service, area) for call in service.get_calls
                for area in call.get("ranges", [])]

    def assert_cell_not_read(self, service, tab, row, header):
        col = service.schemas[tab].index(header)
        self.assertFalse(any(name == tab and r0 <= row < r1 and c0 <= col < c1
                             for name, r0, r1, c0, c1 in self.requested(service)),
                         f"Unrelated {tab}.{header} at row {row + 1} was downloaded")

    def assert_no_full_grid(self, service):
        for tab, r0, r1, c0, c1 in self.requested(service):
            grid = service.sheet(tab)["properties"]["gridProperties"]
            self.assertFalse(r0 == 0 and r1 >= grid["rowCount"] and c0 == 0
                             and c1 >= len(service.schemas[tab]),
                             f"Downloaded the full {tab} grid")

    def assert_smaller_than_full_commit(self, service, ops, count=40):
        full_service, full_repo = self.make(count)
        full_repo._load_commit = lambda operations: full_repo._load(
            sorted({op["tab"] for op in operations}))
        full_repo.commit(copy.deepcopy(ops))
        self.assertLess(service.response_bytes, full_service.response_bytes / 5)

    def on_second_identity_scan(self, service, tab, header, change):
        scans = 0
        col = service.schemas[tab].index(header)
        rows = service.sheet(tab)["properties"]["gridProperties"]["rowCount"]

        def before_read(kwargs):
            nonlocal scans
            for area in kwargs.get("ranges", []):
                name, r0, r1, c0, c1 = self.bounds(service, area)
                if name == tab and r0 == 1 and r1 >= rows and c0 <= col < c1:
                    scans += 1
                    if scans == 2:
                        change()
                    break
        service.before_read = before_read

    def swap_columns(self, service, tab, first, second):
        rows = service.sheet(tab)["data"][0]["rowData"]
        headers = [cell["effectiveValue"]["stringValue"] for cell in rows[0]["values"]]
        left, right = headers.index(first), headers.index(second)
        for row in rows:
            while len(row["values"]) <= max(left, right):
                row["values"].append({})
            row["values"][left], row["values"][right] = row["values"][right], row["values"][left]

    def test_stable_existing_batches_use_one_fresh_read_and_half_the_identity_bytes(self):
        service, repo = self.make(300)
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'first'})])
        before_calls, before_bytes = len(service.get_calls), service.response_bytes
        repo.commit([operation('Job History', {'Job Key': 'j-2'}, {'Last Checked': 'second'})])
        cached_calls = len(service.get_calls) - before_calls
        cached_bytes = service.response_bytes - before_bytes
        baseline_service, baseline_repo = self.make(300)
        baseline_repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'first'})])
        baseline_repo._identity_hints.clear()
        before_calls, before_bytes = len(baseline_service.get_calls), baseline_service.response_bytes
        baseline_repo.commit([operation('Job History', {'Job Key': 'j-2'}, {'Last Checked': 'second'})])
        baseline_calls = len(baseline_service.get_calls) - before_calls
        baseline_bytes = baseline_service.response_bytes - before_bytes
        self.assertEqual(cached_calls, 1)
        self.assertEqual(baseline_calls, 2)
        self.assertLess(cached_bytes, baseline_bytes * 0.7)
        self.assert_cell_not_read(service, 'Job History', 20, 'Job Description')
        self.assertEqual(repo.read_row('Job History', 4)['Last Checked'], 'second')

    def test_cached_existing_update_rediscovers_moved_rows(self):
        service, repo = self.make()
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'first'})])
        rows = service.sheet('Job History')['data'][0]['rowData']
        rows[2], rows[3] = rows[3], rows[2]
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'second'})])
        self.assertEqual(repo.read_row('Job History', 4)['Job Key'], 'j-1')
        self.assertEqual(repo.read_row('Job History', 4)['Last Checked'], 'second')
        self.assertNotEqual(repo.read_row('Job History', 3)['Last Checked'], 'second')

    def test_cached_existing_update_still_rejects_new_duplicate_identity(self):
        service, repo = self.make()
        op = operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'first'})
        repo.commit([op])
        service.set_cell('Job History', 20, 'Job Key', 'j-1')
        before = len(service.batches)
        with self.assertRaises(RepositoryError):
            repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'second'})])
        self.assertEqual(len(service.batches), before)

    def test_cached_existing_update_preserves_new_formula_protection(self):
        service, repo = self.make()
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'first'})])
        service.set_cell('Job History', 2, 'Last Checked', cell={
            'userEnteredValue': {'formulaValue': '=TODAY()'},
            'effectiveValue': {'stringValue': 'first'}})
        before = len(service.batches)
        with self.assertRaises(RepositoryError):
            repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'second'})])
        self.assertEqual(len(service.batches), before)

    def test_cached_existing_update_preserves_manual_choice_guard(self):
        service, repo = self.make()
        repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'first'})])
        service.set_cell('Job History', 2, 'Added to Opportunities?', 'No')
        before = len(service.batches)
        with self.assertRaises(RepositoryError):
            repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'second'},
                                   expected={'Added to Opportunities?': ''})])
        self.assertEqual(len(service.batches), before)
        self.assertEqual(repo.read_row('Job History', 3)['Added to Opportunities?'], 'No')

    def test_unrelated_manual_controls_are_omitted_but_target_controls_remain_fresh(self):
        service, repo = self.make()
        service.set_cell('Job History', 2, 'Review Status', 'In Progress')
        result = repo.commit([operation('Job History', {'Job Key': 'j-1'}, {'Last Checked': 'second'})])
        self.assertEqual(result['updated'], 0)
        self.assert_cell_not_read(service, 'Job History', 20, 'Added to Opportunities?')
        self.assert_cell_not_read(service, 'Job History', 20, 'Review Status')
        self.assertNotEqual(repo.read_row('Job History', 3)['Last Checked'], 'second')

    def test_evidence_update_omits_other_descriptions(self):
        service, repo = self.make()
        ops = [operation("Job Evidence", {"Job Key": "j-1", "Source Hash": "h1"},
                         {"Captured At": "after"}, append_if_missing=True)]
        repo.commit(ops)
        self.assert_no_full_grid(service)
        self.assert_cell_not_read(service, "Job Evidence", 20, "Job Description")
        self.assert_smaller_than_full_commit(service, ops)
        self.assertEqual(repo.read_row("Job Evidence", 3)["Captured At"], "after")

    def test_company_control_update_omits_other_large_notes(self):
        service, repo = self.make()
        ops = [operation("Companies", {"Company ID": "c-1"},
                         {"Last Checked": "today", "Scan State": "Complete"})]
        repo.commit(ops)
        self.assert_no_full_grid(service)
        self.assert_cell_not_read(service, "Companies", 20, "Notes")
        self.assert_smaller_than_full_commit(service, ops)
        row = repo.read_row("Companies", 3)
        self.assertEqual(row["Scan State"], "Complete")
        self.assertEqual(row["Notes"], "Personal company notes. " * 600)

    def test_mixed_evidence_update_and_new_job_remain_sparse(self):
        service, repo = self.make()
        ops = [operation("Job Evidence", {"Job Key": "j-1", "Source Hash": "h1"},
                         {"Captured At": "after"}, append_if_missing=True),
               operation("Job History", {"Job Key": "new"},
                         {"Company": "New Company", "Job Title": "Engineer",
                          "Official Job URL": "https://example.test/jobs/new"},
                         append_if_missing=True)]
        result = repo.commit(ops)
        self.assertEqual(result["inserted"], 1)
        self.assert_no_full_grid(service)
        for tab in ("Job History", "Job Evidence"):
            self.assert_cell_not_read(service, tab, 20, "Job Description")
        self.assert_smaller_than_full_commit(service, ops)
        self.assertEqual(repo.read_row("Job History", 42)["Job Key"], "new")

    def test_evidence_append_replay_does_not_duplicate(self):
        service, repo = self.make(2)
        ops = [operation("Job Evidence", {"Job Key": "new", "Source Hash": "h2"},
                         {"Company": "New Company", "Job Description": "Verified evidence"},
                         append_if_missing=True)]
        self.assertEqual(repo.commit(ops)["inserted"], 1)
        self.assertEqual(repo.commit(ops)["inserted"], 0)
        self.assert_no_full_grid(service)
        matches = [row for row in repo.read("Job Evidence") if row["Job Key"] == "new"]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["Job Description"], "Verified evidence")

    def test_duplicate_evidence_identity_is_rejected_on_replay(self):
        service, repo = self.make(3)
        ops = [operation("Job Evidence", {"Job Key": "j-1", "Source Hash": "h1"},
                         {"Captured At": "after"}, append_if_missing=True)]
        repo.commit(ops)
        service.set_cell("Job Evidence", 3, "Job Key", "j-1")
        before = len(service.batches)
        with self.assertRaisesRegex(RepositoryError, "multiple rows"):
            repo.commit(ops)
        self.assertEqual(len(service.batches), before)

    def test_new_identity_appearing_between_reads_aborts(self):
        service, repo = self.make(2)

        def insert():
            service.set_cell("Job Evidence", 3, "Job Key", "new")
            service.set_cell("Job Evidence", 3, "Source Hash", "h2")
            service.set_cell("Job Evidence", 3, "Job Description", "Human-added evidence")
        self.on_second_identity_scan(service, "Job Evidence", "Job Key", insert)
        with self.assertRaises(RepositoryError):
            repo.commit([operation("Job Evidence", {"Job Key": "new", "Source Hash": "h2"},
                                   {"Job Description": "Scraper evidence"}, append_if_missing=True)])
        self.assertEqual(service.batches, [])

    def test_new_job_cannot_duplicate_existing_url_alias(self):
        service, repo = self.make(2)
        with self.assertRaisesRegex(RepositoryError, "another identity"):
            repo.commit([operation("Job History", {"Job Key": "new"},
                                   {"Company": "Company 1",
                                    "Official Job URL": "https://example.test/jobs/1?utm_source=x"},
                                   append_if_missing=True)])
        self.assertEqual(service.batches, [])

    def test_append_preserves_orphan_notes_formulas_and_destination_validation(self):
        service, repo = self.make(1)
        service.set_cell("Job History", 3, "Review Notes", "Manual orphan")
        formula = {"userEnteredValue": {"formulaValue": '=IF(TRUE,"","")'},
                   "effectiveValue": {"stringValue": ""}}
        service.set_cell("Job History", 4, "Job Title", cell=copy.deepcopy(formula))
        rule = {"strict": True, "condition": {"type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": "Open"}]}}
        service.set_cell("Job History", 5, "Job Status", cell={"dataValidation": copy.deepcopy(rule)})
        bad = operation("Job History", {"Job Key": "new"}, {"Job Status": "Invalid"},
                        append_if_missing=True)
        with self.assertRaises(RepositoryError):
            repo.commit([bad])
        self.assertEqual(service.batches, [])
        good = {**bad, "values": {"Job Status": "Open"}}
        self.assertEqual(repo.commit([good])["inserted"], 1)
        self.assert_no_full_grid(service)
        rows = service.sheet("Job History")["data"][0]["rowData"]
        self.assertEqual(rows[4]["values"][service.schemas["Job History"].index("Job Title")], formula)
        self.assertEqual(rows[5]["values"][service.schemas["Job History"].index("Job Status")]["dataValidation"], rule)
        self.assertEqual(repo.read_row("Job History", 4)["Review Notes"], "Manual orphan")
        self.assertEqual(repo.read_row("Job History", 6)["Job Key"], "new")

    def test_committed_headers_are_reused_by_following_column_read(self):
        service, repo = self.make(2)
        repo.commit([operation("Companies", {"Company ID": "c-1"}, {"Last Checked": "first"})])
        self.swap_columns(service, "Companies", "Last Checked", "Notes")
        repo.commit([operation("Companies", {"Company ID": "c-1"}, {"Last Checked": "second"})])
        service.get_calls.clear()
        records = repo.read_columns("Companies", ["Company ID", "Last Checked"])
        self.assertEqual(dict(records)[3], {"Company ID": "c-1", "Last Checked": "second"})
        self.assertFalse(any(r0 == 0 for _, r0, _, _, _ in self.requested(service)),
                         "Column read fetched headers already validated by the preceding commit")

    def test_header_reorder_between_identity_and_final_reads_aborts(self):
        service, repo = self.make(2)
        self.on_second_identity_scan(service, "Companies", "Company ID",
                                     lambda: self.swap_columns(service, "Companies", "Last Checked", "Notes"))
        with self.assertRaises(RepositoryError):
            repo.commit([operation("Companies", {"Company ID": "c-1"}, {"Last Checked": "after"})])
        self.assertEqual(service.batches, [])

    def test_warm_mapping_uses_one_grid_read_and_reresolves_moved_target(self):
        service, repo = self.make(3)
        def change(value):
            return operation("Companies", {"Company ID": "c-1"}, {"Last Checked": value})
        repo.commit([change("first")])
        service.get_calls.clear()
        repo.commit([change("second")])
        grids = [call for call in service.get_calls if call.get("includeGridData")]
        self.assertEqual(len(grids), 1)

        service.set_cell("Companies", 2, "Notes", "Human note added after cached read")
        formula = {"userEnteredValue": {"formulaValue": '=IF(TRUE,"Manual","")'},
                   "effectiveValue": {"stringValue": "Manual"}}
        service.set_cell("Companies", 2, "Category", cell=copy.deepcopy(formula))
        rows = service.sheet("Companies")["data"][0]["rowData"]
        rows[2], rows[3] = rows[3], rows[2]
        service.get_calls.clear()
        repo.commit([change("third")])
        self.assert_no_full_grid(service)
        moved = repo.read_row("Companies", 4)
        self.assertEqual(moved["Company ID"], "c-1")
        self.assertEqual(moved["Last Checked"], "third")
        self.assertEqual(moved["Notes"], "Human note added after cached read")
        self.assertEqual(repo.read_row("Companies", 3)["Last Checked"], "")
        cells = service.sheet("Companies")["data"][0]["rowData"][3]["values"]
        self.assertEqual(cells[service.schemas["Companies"].index("Category")], formula)

    def test_warm_upsert_rejects_duplicate_below_cached_tail(self):
        service, repo = self.make(2)
        ops = [operation("Job Evidence", {"Job Key": "j-1", "Source Hash": "h1"},
                         {"Captured At": "after"}, append_if_missing=True)]
        repo.commit(ops)
        service.set_cell("Job Evidence", 20, "Job Key", "j-1")
        service.set_cell("Job Evidence", 20, "Source Hash", "h1")
        service.set_cell("Job Evidence", 20, "Job Description", "Manually inserted duplicate")
        before = len(service.batches)
        with self.assertRaisesRegex(RepositoryError, "multiple rows"):
            repo.commit(ops)
        self.assertEqual(len(service.batches), before)

    def test_planning_cache_keeps_untouched_snapshot_notes_and_application_status(self):
        service, repo = self.make(2)
        service.set_cell("Job History", 2, "Review Notes", "Existing review note")
        for header, value in {"Company": "Company 1", "Job URL": "https://example.test/jobs/1",
                              "Application Status": "Applied", "Notes": "Application note"}.items():
            service.set_cell("Opportunities", 1, header, value)
        planner = PlanningRepository(repo)
        ops = [operation("Job History", {"Job Key": "j-1"}, {"Last Checked": "today"},
                         append_if_missing=True),
               operation("Opportunities", {"Company": "Company 1", "Job URL": "https://example.test/jobs/1"},
                         {"Location": "Ohio"}, append_if_missing=True),
               operation("Job Evidence", {"Job Key": "j-1", "Source Hash": "h1"},
                         {"Captured At": "today"}, append_if_missing=True)]
        planner.commit(ops)
        service.set_cell("Job History", 2, "Current Snapshot", "Newer saved snapshot")
        service.set_cell("Job History", 2, "Review Notes", "Human note after planning")
        service.set_cell("Opportunities", 1, "Application Status", "Interviewing")
        service.set_cell("Opportunities", 1, "Notes", "Human application note after planning")
        repo.commit(ops)
        planner.accept_commit()
        history = next(row for row in planner.read("Job History") if row["Job Key"] == "j-1")
        self.assertEqual(history["Current Snapshot"], "Newer saved snapshot")
        self.assertEqual(history["Review Notes"], "Human note after planning")
        self.assertEqual(history["Last Checked"], "today")
        opportunity = planner.read("Opportunities")[0]
        self.assertEqual(opportunity["Application Status"], "Interviewing")
        self.assertEqual(opportunity["Notes"], "Human application note after planning")
        self.assertEqual(opportunity["Location"], "Ohio")

    def test_sequential_evidence_insert_then_update_in_one_batch(self):
        service, repo = self.make(2)
        identity = {"Job Key": "new", "Source Hash": "h2"}
        ops = [operation("Job Evidence", identity,
                         {"Captured At": "first", "Job Description": "Initial evidence"},
                         append_if_missing=True),
               operation("Job Evidence", identity, {"Captured At": "second"},
                         expected={"Captured At": "first"})]
        result = repo.commit(ops)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(service.batches), 1)
        rows = [row for row in repo.read("Job Evidence") if row["Job Key"] == "new"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Captured At"], "second")
        self.assertEqual(rows[0]["Job Description"], "Initial evidence")

    def test_warm_upsert_checks_fresh_target_formula(self):
        service, repo = self.make(2)
        identity = {"Job Key": "j-1", "Source Hash": "h1"}
        repo.commit([operation("Job Evidence", identity, {"Captured At": "warm"}, append_if_missing=True)])
        formula = {"userEnteredValue": {"formulaValue": '=IF(TRUE,"Manual","")'},
                   "effectiveValue": {"stringValue": "Manual"}}
        service.set_cell("Job Evidence", 2, "Captured At", cell=copy.deepcopy(formula))
        before = len(service.batches)
        with self.assertRaisesRegex(RepositoryError, "existing formula"):
            repo.commit([operation("Job Evidence", identity, {"Captured At": "changed"}, append_if_missing=True)])
        self.assertEqual(len(service.batches), before)
        cells = service.sheet("Job Evidence")["data"][0]["rowData"][2]["values"]
        self.assertEqual(cells[service.schemas["Job Evidence"].index("Captured At")], formula)

    def test_warm_upsert_checks_fresh_target_validation(self):
        service, repo = self.make(2)
        identity = {"Job Key": "j-1", "Source Hash": "h1"}
        repo.commit([operation("Job Evidence", identity, {"Captured At": "warm"}, append_if_missing=True)])
        rule = {"strict": True, "condition": {"type": "ONE_OF_LIST",
                "values": [{"userEnteredValue": "Allowed"}]}}
        service.set_cell("Job Evidence", 2, "Captured At", cell={
            "userEnteredValue": {"stringValue": "Allowed"},
            "effectiveValue": {"stringValue": "Allowed"}, "dataValidation": copy.deepcopy(rule)})
        before = len(service.batches)
        with self.assertRaises(RepositoryError):
            repo.commit([operation("Job Evidence", identity, {"Captured At": "Forbidden"}, append_if_missing=True)])
        self.assertEqual(len(service.batches), before)
        cells = service.sheet("Job Evidence")["data"][0]["rowData"][2]["values"]
        self.assertEqual(cells[service.schemas["Job Evidence"].index("Captured At")]["dataValidation"], rule)


if __name__ == "__main__":
    unittest.main()
