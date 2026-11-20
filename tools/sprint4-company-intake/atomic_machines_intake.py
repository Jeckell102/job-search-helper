"""One-shot, spreadsheet-first intake for the approved Atomic Machines pilot."""

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from job_search_helper.ats import resolve_board
from job_search_helper.cli import writer_lock
from job_search_helper.company_events import canonical_company_fact, source_revision
from job_search_helper.repository import (
    MAX_ROWS, PROTECTED_BACKUP_ID, RepositoryError, _Sheet, _column_name, _effective,
)
from job_search_helper.sheet_profile import COMPACT_PROFILE, COMPACT_SCHEMAS


TAB = "Companies"
NAME = "Atomic Machines"
CAREERS = "https://job-boards.greenhouse.io/atomicmachines"
IDENTITY_FIELDS = ("Company", "Company ID", "Official Careers URL")


@dataclass(frozen=True)
class IntakeScope:
    company_id: str
    added_on: str
    workbook_sha256: str
    sheet_id: int
    table_id: str
    headers_sha256: str

    def row(self):
        if not re.fullmatch(r"COMP-[A-F0-9]{12}", self.company_id):
            raise RepositoryError("Expected the privately enrolled Company ID.")
        if not re.fullmatch(r"[a-f0-9]{64}", self.workbook_sha256):
            raise RepositoryError("Expected the independently enrolled workbook digest.")
        if (type(self.sheet_id) is not int or self.sheet_id < 0
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.table_id)
                or not re.fullmatch(r"[a-f0-9]{64}", self.headers_sha256)):
            raise RepositoryError("Expected independently enrolled native table and header identities.")
        if date.fromisoformat(self.added_on).isoformat() != self.added_on:
            raise RepositoryError("Expected an ISO Date Added.")
        return {
            "Company": NAME,
            "Company ID": self.company_id,
            "Company Status": "Active",
            "Official Careers URL": CAREERS,
            "ATS / Source": "Greenhouse",
            "Date Added": self.added_on,
        }


def _claim_bytes(scope, row, database):
    return (json.dumps({
        "version": 1,
        "workbook_sha256": scope.workbook_sha256,
        "database": [database.st_dev, database.st_ino],
        "row": row,
        "sheet_id": scope.sheet_id,
        "table_id": scope.table_id,
        "headers_sha256": scope.headers_sha256,
    }, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _require_private(info, mode):
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != mode:
        raise RepositoryError("Expected owner-private pilot custody.")


def _read_claim(directory_fd, expected):
    try:
        fd = os.open("append-claim.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory_fd)
    except FileNotFoundError:
        return False
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        _require_private(info, 0o600)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or stream.read(len(expected) + 1) != expected):
            raise RepositoryError("Pilot append custody differs from the approved scope.")
    return True


def _create_claim(directory_fd, payload):
    fd = os.open("append-claim.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(directory_fd)
    if not _read_claim(directory_fd, payload):
        raise RepositoryError("Pilot append custody could not be read back.")


def _key(value):
    return str(value or "").strip().casefold()


def _same_board(url):
    url = str(url or "").strip()
    if url.lower().startswith("http://"):
        url = "https://" + url[7:]
    try:
        provider, board, _ = resolve_board("", url)
    except ValueError:
        return False
    return provider == "Greenhouse" and board.casefold() == "atomicmachines"


def _match(records, row):
    candidates = [
        (number, found) for number, found in records
        if (_key(found["Company"]) == NAME.casefold()
            or _key(found["Company ID"]) == row["Company ID"].casefold()
            or _same_board(found["Official Careers URL"]))
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise RepositoryError("Multiple rows match the enrolled Company identity or provider board.")
    number, found = candidates[0]
    if any(found[key] != row[key] for key in IDENTITY_FIELDS):
        raise RepositoryError("A Company row collides with the enrolled identity or provider board.")
    return number, found


def _local_match(local, row):
    hit = _match(local.read_columns(TAB, IDENTITY_FIELDS), row)
    if hit is None:
        return None
    number, _ = hit
    return _require_enrolled_values(number, local.read_row(TAB, number), row)


def _require_enrolled_values(number, recorded, row):
    if any(recorded.get(key) != value for key, value in row.items()):
        raise RepositoryError("A selected Company row changed or differs from enrollment.")
    return number, recorded


def _remote_view(remote, scope, row):
    """Read the native table, order, and identity from the same grid response."""
    width = len(COMPACT_SCHEMAS[TAB])
    api = remote.service.spreadsheets()
    snapshot = remote._execute(api.get(
        spreadsheetId=remote.spreadsheet_id,
        ranges=[f"'Companies'!A1:{_column_name(width)}"],
        includeGridData=True,
        fields=("sheets(properties(sheetId,title,gridProperties(rowCount)),tables(tableId,range,rowsProperties(footerColorStyle)),"
                "data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,"
                "formattedValue,hyperlink,textFormatRuns))))"),
    ), "read")
    sheets = snapshot.get("sheets", [])
    if len(sheets) != 1:
        raise RepositoryError("The Companies worksheet was not uniquely returned.")
    raw = sheets[0]
    properties = raw.get("properties", {})
    if properties.get("title") != TAB or properties.get("sheetId") != scope.sheet_id:
        raise RepositoryError("The Companies worksheet identity differs from enrollment.")
    tables = raw.get("tables", [])
    if len(tables) != 1 or tables[0].get("tableId") != scope.table_id:
        raise RepositoryError("The Companies native table identity differs from enrollment.")
    bounds = tables[0].get("range", {})
    grid_rows = properties.get("gridProperties", {}).get("rowCount", 0)
    table_end = bounds.get("endRowIndex")
    if (bounds.get("sheetId") != scope.sheet_id
            or bounds.get("startRowIndex", 0) != 0
            or bounds.get("startColumnIndex", 0) != 0
            or bounds.get("endColumnIndex") != width
            or type(grid_rows) is not int or type(table_end) is not int
            or not 2 <= table_end <= grid_rows <= MAX_ROWS):
        raise RepositoryError("The Companies native table does not span the enrolled compact columns.")
    blocks = raw.get("data", [])
    if (len(blocks) != 1 or blocks[0].get("startRow", 0) != 0
            or blocks[0].get("startColumn", 0) != 0):
        raise RepositoryError("The Companies grid snapshot did not begin with its headers.")
    raw_rows = blocks[0].get("rowData", [])
    if not raw_rows or len(raw_rows) > grid_rows:
        raise RepositoryError("The Companies grid snapshot did not return its bounded rows.")
    header_cells = raw_rows[0].get("values", [])
    headers = [_effective(cell) for cell in header_cells]
    if (len(headers) != width or any(not isinstance(header, str) for header in headers)
            or any("formulaValue" in cell.get("userEnteredValue", {}) for cell in header_cells)):
        raise RepositoryError("The Companies headers are outside the approved compact layout.")
    encoded = json.dumps(headers, separators=(",", ":"), ensure_ascii=False).encode()
    if (set(headers) != set(COMPACT_SCHEMAS[TAB])
            or hashlib.sha256(encoded).hexdigest() != scope.headers_sha256):
        raise RepositoryError("The Companies header order differs from enrollment.")
    sheet = _Sheet(headers)
    for index, entry in enumerate(raw_rows[1:], start=1):
        values = entry.get("values", [])
        if len(values) > width:
            raise RepositoryError("The Companies grid returned columns outside the approved width.")
        sheet.cells.update({(index, col): cell for col, cell in enumerate(values) if cell})
    hit = _match(((number + 1, found) for number, found in sheet.records()), row)
    if hit is None:
        return headers, None
    number, recorded = hit
    footer = "footerColorStyle" in tables[0].get("rowsProperties", {})
    if number > table_end or (footer and number == table_end):
        raise RepositoryError("The confirmed Company row is outside the enrolled native table body.")
    _require_enrolled_values(number, recorded, row)
    for column, header in enumerate(headers):
        if header in row and sheet.cells.get((number - 1, column), {}).get("userEnteredValue") != {
            "stringValue": row[header],
        }:
            raise RepositoryError("The selected Company row is not the enrolled literal input.")
    return headers, hit


def _append_table_row(remote, scope, headers, row):
    cells = [{"userEnteredValue": {"stringValue": row[header]}} if header in row else {}
             for header in headers]
    request = {"appendCells": {"tableId": scope.table_id, "fields": "userEnteredValue",
                               "rows": [{"values": cells}]}}
    remote._execute(remote.service.spreadsheets().batchUpdate(
        spreadsheetId=remote.spreadsheet_id, body={"requests": [request]},
    ), "write")


def _require_event(local, row, origin):
    records = local.db.execute(
        "SELECT event_id,revision,source_revision,kind,payload FROM company_event_outbox "
        "WHERE company_id=? ORDER BY revision", (row["Company ID"],)
    ).fetchall()
    revisions = local.db.execute(
        "SELECT revision,source_revision,eligible,fact FROM company_revisions "
        "WHERE company_id=? ORDER BY revision", (row["Company ID"],)
    ).fetchall()
    fact = canonical_company_fact(row)
    digest = source_revision(row)
    if (len(records) != 1 or len(revisions) != 1
            or revisions[0][:3] != (1, digest, 1)
            or json.loads(revisions[0][3]) != fact):
        raise RepositoryError("The selected Company lacks one matching intake revision and event.")
    event_id, revision, recorded_digest, kind, payload = records[0]
    event = json.loads(payload)
    if (not re.fullmatch(r"CEV-[a-f0-9]{32}", event_id)
            or (revision, recorded_digest, kind) != (1, digest, "company.eligible")
            or event != {"event_id": event_id, "revision": revision, "source_revision": digest,
                         "kind": kind, "fact": fact, "origin": origin,
                         "company_id": row["Company ID"], "company": NAME}):
        raise RepositoryError("The selected outbox event differs from the exact enrollment.")
    return event


def _has_revision(local, row):
    return local.db.execute(
        "SELECT 1 FROM company_revisions WHERE lower(company_id)=lower(?)",
        (row["Company ID"],)
    ).fetchone() is not None


def _confirm_local(local, remote_hit, row, claim_digest):
    remote_number, remote_row = remote_hit
    receipt_key = "scoped_pilot_intake:" + claim_digest
    origin = "sheets-reconciliation"
    with local.transaction():
        local_hit = _local_match(local, row)
        receipt = local.get_meta(receipt_key)
        if local_hit is None:
            if receipt is not None or _has_revision(local, row):
                raise RepositoryError("The enrolled Company ID already has intake or revision history.")
            imported, events = local._import_rows_in_transaction(
                TAB, [(remote_number, remote_row)], event_origin=origin,
            )
            if imported != 1 or len(events) != 1:
                raise RepositoryError("The one scoped import did not create one event.")
            local_hit = _local_match(local, row)
            receipt = events[0]["event_id"]
            local.set_meta(receipt_key, receipt)
        if local_hit is None:
            raise RepositoryError("The selected Company was not read back from the local store.")
        local_number, local_row = local_hit
        baseline = local.baseline(TAB, local_number - 1)
        if (baseline is None or any(baseline.get(key) != value or local_row.get(key) != value
                                    for key, value in remote_row.items())):
            raise RepositoryError("The confirmed Sheet row differs from the scoped local baseline.")
        event = _require_event(local, row, origin)
        if receipt != event["event_id"]:
            raise RepositoryError("The selected event is not bound to this durable append claim.")
    return {"state": "COMPANY_INTAKE_CONFIRMED", "event_id": event["event_id"],
            "company_id": event["company_id"], "source_revision": event["source_revision"]}


def _intake(local, remote, scope, directory_fd, payload, row):
    claimed = _read_claim(directory_fd, payload)
    headers, remote_hit = _remote_view(remote, scope, row)
    if not claimed:
        if remote_hit or _local_match(local, row) or _has_revision(local, row):
            raise RepositoryError("Company identity was already present before this intake.")
        _create_claim(directory_fd, payload)
        _append_table_row(remote, scope, headers, row)
        _, remote_hit = _remote_view(remote, scope, row)
    if remote_hit is None:
        raise RepositoryError("The claimed Company is absent in Sheets; automatic append replay is held.")
    return _confirm_local(local, remote_hit, row, hashlib.sha256(payload).hexdigest())


def intake(local, remote, scope, *, custody_directory):
    """Confirm exactly one approved append and durable event under both existing leases."""
    row = scope.row()
    if (local.readonly or local.get_meta("ready") != "yes"
            or local.get_meta("sheets_profile") != COMPACT_PROFILE
            or local.get_meta("company_event_external_baseline") != "yes"
            or remote.schemas.get(TAB) != COMPACT_SCHEMAS[TAB]
            or remote.spreadsheet_id == PROTECTED_BACKUP_ID
            or local.spreadsheet_id != remote.spreadsheet_id
            or hashlib.sha256(remote.spreadsheet_id.encode()).hexdigest() != scope.workbook_sha256):
        raise RepositoryError("The working workbook or its completed local baseline is outside scope.")
    state_dir = local.path.parent
    with writer_lock(state_dir / "scraper.lock"), writer_lock(state_dir / "writer.lock"):
        directory_fd = os.open(Path(custody_directory), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _require_private(os.fstat(directory_fd), 0o700)
            payload = _claim_bytes(scope, row, local.path.stat())
            return _intake(local, remote, scope, directory_fd, payload, row)
        finally:
            os.close(directory_fd)
