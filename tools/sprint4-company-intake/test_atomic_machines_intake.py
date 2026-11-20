import copy
from dataclasses import replace
from hashlib import sha256
import json

import pytest

from atomic_machines_intake import IntakeScope, TAB, intake
from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.repository import GoogleRepository, RepositoryError, UncertainWriteError
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS
from job_search_helper.sqlite_repository import SQLiteRepository
from sheets_fixture import RangeSheets


WORKBOOK = "test-only-atomic-machines-intake"
HEADER_DIGEST = sha256(json.dumps(COMPACT_SCHEMAS[TAB], separators=(",", ":")).encode()).hexdigest()
SCOPE = IntakeScope("COMP-6490E67245BA", "2026-11-20", sha256(WORKBOOK.encode()).hexdigest(),
                    1, "fixture-table", HEADER_DIGEST)
EXISTING = {"Company": "Existing Company", "Company ID": "COMP-8123EF5720DD",
            "Official Careers URL": "https://example.com/careers", "Notes": "manual note"}


class NativeAppendFixture(RangeSheets):
    """Model only the supported native-table append. Existing rows stay in place."""

    def get(self, **kwargs):
        response = super().get(**kwargs)
        if kwargs.get("fields") != "sheets(properties(sheetId,title),tables(tableId,range))":
            return response

        class Metadata:
            def execute(self, num_retries=0):
                data = response.execute(num_retries=num_retries)
                for sheet in data["sheets"]:
                    sheet["properties"].pop("gridProperties")
                return data

        return Metadata()

    def append_with_values(self, values):
        sheet = self.sheet(TAB)
        rows = sheet["data"][0]["rowData"]
        table = sheet["tables"][0]
        rows.append({"values": values})
        table["range"]["endRowIndex"] = len(rows)

    def append_dict(self, row):
        self.append_with_values([
            {"userEnteredValue": {"stringValue": row[header]}} if header in row else {}
            for header in COMPACT_SCHEMAS[TAB]
        ])

    def batchUpdate(self, **kwargs):
        outer = self
        self.batches.append(copy.deepcopy(kwargs))

        class Appended:
            def execute(self):
                if outer.before_write:
                    outer.before_write()
                request, = kwargs["body"]["requests"]
                append = request["appendCells"]
                assert kwargs["spreadsheetId"] == WORKBOOK
                assert set(append) == {"tableId", "fields", "rows"}
                assert append["tableId"] == SCOPE.table_id
                assert append["fields"] == "userEnteredValue"
                row, = append["rows"]
                outer.append_with_values(row["values"])
                if outer.lose_response:
                    raise TimeoutError("committed, response lost")
                return {"replies": [{}]}

        return Appended()


@pytest.fixture
def stores(tmp_path):
    custody = tmp_path / "custody"
    custody.mkdir(mode=0o700)
    local = SQLiteRepository(tmp_path / "jobs.sqlite3", WORKBOOK, initialize=True)
    local.set_meta("ready", "yes")
    local.set_meta("sheets_profile", COMPACT_PROFILE)
    local.import_rows(TAB, [(2, EXISTING)])
    local.bootstrap_company_event_reconciliation()
    service = NativeAppendFixture({TAB: [EXISTING]}, schemas=COMPACT_SCHEMAS)
    service.sheet(TAB)["tables"] = [{
        "tableId": SCOPE.table_id,
        "range": {"sheetId": SCOPE.sheet_id, "endRowIndex": 2,
                  "endColumnIndex": len(COMPACT_SCHEMAS[TAB])},
    }]
    remote = GoogleRepository(service, WORKBOOK, schemas=COMPACT_SCHEMAS, min_request_interval=0)
    yield local, remote, custody, service
    local.close()


def run(stores, scope=SCOPE):
    local, remote, custody, _ = stores
    return intake(local, remote, scope, custody_directory=custody)


def test_one_append_and_one_event_survive_replay(stores):
    local, remote, custody, service = stores
    old_local = copy.deepcopy(local.read(TAB)[0])
    old_remote = copy.deepcopy(remote.read(TAB)[0])
    first = run(stores)
    assert first == run(stores)
    assert first["state"] == "COMPANY_INTAKE_CONFIRMED"
    assert len(service.batches) == 1
    assert local.read(TAB)[0] == old_local
    assert remote.read(TAB)[0] == old_remote
    assert len(local.read(TAB)) == len(remote.read(TAB)) == 2
    assert local.pending_company_events("bridge")[0]["event_id"] == first["event_id"]
    assert local.db.execute("SELECT count(*) FROM dirty").fetchone() == (0,)
    assert (custody / "append-claim.json").stat().st_mode & 0o777 == 0o600


def test_reconcile_after_lost_write_ack(stores):
    local, remote, _, service = stores
    service.lose_response = True
    with pytest.raises(UncertainWriteError):
        run(stores)
    assert len(local.read(TAB)) == 1
    assert len(remote.read(TAB)) == 2
    first = run(stores)
    assert run(stores) == first
    assert len(service.batches) == 1


def test_lost_attempt_without_row_cannot_retry(stores):
    local, remote, _, service = stores
    def fail_before_append():
        raise TimeoutError("the server outcome is unknown")
    service.before_write = fail_before_append
    with pytest.raises(UncertainWriteError):
        run(stores)
    with pytest.raises(RepositoryError, match="automatic append replay is held"):
        run(stores)
    assert len(service.batches) == 1 and len(remote.read(TAB)) == len(local.read(TAB)) == 1


def test_unrelated_concurrent_appender_retains_row(stores):
    _, remote, _, service = stores
    other = {"Company": "Concurrent Company", "Company ID": "COMP-700000000001",
             "Official Careers URL": "https://example.com/other", "Notes": "own this row"}
    service.before_write = lambda: service.append_dict(other)
    assert run(stores)["state"] == "COMPANY_INTAKE_CONFIRMED"
    assert remote.read(TAB)[1]["Notes"] == "own this row"


def test_selected_duplicate_holds_local_and_leaves_both_remote_rows(stores):
    local, remote, _, service = stores
    other = {**SCOPE.row(), "Company ID": "COMP-700000000001"}
    service.before_write = lambda: service.append_dict(other)
    for _ in range(2):
        with pytest.raises(RepositoryError, match="Multiple rows"):
            run(stores)
    assert len(service.batches) == 1 and len(remote.read(TAB)) == 3
    assert len(local.read(TAB)) == 1 and not local.pending_company_events("bridge")


def test_exact_row_already_present_without_claim_is_not_adopted(stores):
    local, _, custody, service = stores
    service.append_dict(SCOPE.row())
    with pytest.raises(RepositoryError, match="already present"):
        run(stores)
    assert not service.batches and not list(custody.iterdir())
    assert len(local.read(TAB)) == 1


def test_old_board_alias_blocks_before_append(stores):
    _, _, _, service = stores
    service.append_dict({**EXISTING, "Official Careers URL": "https://boards.greenhouse.io/atomicmachines/"})
    with pytest.raises(RepositoryError, match="collides"):
        run(stores)
    assert not service.batches


def test_wrong_native_table_is_rejected(stores):
    _, _, custody, service = stores
    with pytest.raises(RepositoryError, match="table identity"):
        run(stores, replace(SCOPE, table_id="wrong-table"))
    assert not service.batches and not list(custody.iterdir())


def test_changed_headers_after_dispatch_hold_on_restart(stores):
    local, _, _, service = stores
    def move_headers():
        headers = service.sheet(TAB)["data"][0]["rowData"][0]["values"]
        headers[0], headers[1] = headers[1], headers[0]
    service.before_write = move_headers
    for _ in range(2):
        with pytest.raises(RepositoryError, match="header order"):
            run(stores)
    assert len(service.batches) == 1 and len(local.read(TAB)) == 1


def test_local_scraper_contention_never_creates_claim(stores):
    local, _, custody, service = stores
    with writer_lock(local.path.parent / "scraper.lock"):
        with pytest.raises(WriterLockBusy):
            run(stores)
    assert not service.batches and not list(custody.iterdir())


def test_claim_substitution_holds_before_write(stores):
    _, _, custody, service = stores
    (custody / "append-claim.json").write_text("substituted")
    (custody / "append-claim.json").chmod(0o600)
    with pytest.raises(RepositoryError, match="custody differs"):
        run(stores)
    assert not service.batches


def test_conflicting_event_origin_holds_without_repeat_write(stores):
    local, _, _, service = stores
    event_id = run(stores)["event_id"]
    row = local.db.execute("SELECT payload FROM company_event_outbox WHERE event_id=?",
                           (event_id,)).fetchone()
    event = json.loads(row[0])
    event["origin"] = "other"
    local.db.execute("UPDATE company_event_outbox SET payload=? WHERE event_id=?",
                     (json.dumps(event), event_id))
    with pytest.raises(RepositoryError, match="event differs"):
        run(stores)
    assert len(service.batches) == 1


def test_late_local_insert_without_claim_receipt_is_never_adopted(stores):
    local, _, _, service = stores
    service.before_write = lambda: local.import_companies_with_events(
        [(3, SCOPE.row())], origin="sheets-reconciliation")
    for _ in range(2):
        with pytest.raises(RepositoryError, match="not bound"):
            run(stores)
    assert len(service.batches) == 1


def test_failed_local_receipt_rolls_back_row_baseline_and_event(stores, monkeypatch):
    local, _, _, service = stores
    set_meta = local.set_meta

    def fail_receipt(key, value):
        set_meta(key, value)
        raise RuntimeError("interrupted after local receipt insert")

    with monkeypatch.context() as patch:
        patch.setattr(local, "set_meta", fail_receipt)
        with pytest.raises(RuntimeError, match="interrupted after"):
            run(stores)
    assert len(local.read(TAB)) == 1
    assert not local.pending_company_events("bridge")
    assert not local.db.execute("SELECT 1 FROM baseline WHERE tab=? AND row_id=2", (TAB,)).fetchone()
    assert run(stores)["state"] == "COMPANY_INTAKE_CONFIRMED"
    assert len(service.batches) == 1
    assert local.pending_company_events("bridge")[0]["origin"] == "sheets-reconciliation"


def test_rich_board_link_collision_is_visible_in_grid_snapshot(stores):
    _, _, _, service = stores
    service.set_cell(TAB, 1, "Official Careers URL", cell={
        "effectiveValue": {"stringValue": "Careers at this employer"},
        "hyperlink": "https://boards-api.greenhouse.io/v1/boards/atomicmachines/jobs",
    })
    with pytest.raises(RepositoryError, match="collides"):
        run(stores)
    assert not service.batches


def test_post_append_grid_with_replaced_native_table_holds(stores):
    local, _, _, service = stores

    def replace_table(_request):
        if service.batches:
            service.sheet(TAB)["tables"][0]["tableId"] = "replacement-native-table"

    service.before_read = replace_table
    with pytest.raises(RepositoryError, match="table identity"):
        run(stores)
    assert len(service.batches) == 1
    assert len(local.read(TAB)) == 1 and not local.pending_company_events("bridge")


def test_post_append_row_outside_table_holds(stores):
    local, _, _, service = stores

    def shrink_table(_request):
        if service.batches:
            service.sheet(TAB)["tables"][0]["range"]["endRowIndex"] = 2

    service.before_read = shrink_table
    with pytest.raises(RepositoryError, match="outside the enrolled native table"):
        run(stores)
    assert len(service.batches) == 1
    assert len(local.read(TAB)) == 1 and not local.pending_company_events("bridge")


def test_post_append_row_in_current_footer_holds(stores):
    local, _, _, service = stores

    def mark_footer(_request):
        if service.batches:
            service.sheet(TAB)["tables"][0]["rowsProperties"] = {
                "footerColorStyle": {"rgbColor": {}},
            }

    service.before_read = mark_footer
    with pytest.raises(RepositoryError, match="outside the enrolled native table body"):
        run(stores)
    assert len(service.batches) == 1
    assert not local.pending_company_events("bridge")


def test_formula_cannot_impersonate_enrolled_literal(stores):
    local, _, _, service = stores

    def replace_with_formula(_request):
        if service.batches:
            service.set_cell(TAB, 2, "Company Status", cell={
                "userEnteredValue": {"formulaValue": '= "Active"'},
                "effectiveValue": {"stringValue": "Active"},
            })

    service.before_read = replace_with_formula
    with pytest.raises(RepositoryError, match="not the enrolled literal input"):
        run(stores)
    assert len(service.batches) == 1
    assert not local.pending_company_events("bridge")
