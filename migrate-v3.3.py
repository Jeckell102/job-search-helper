#!/usr/bin/env python3
"""One-time v3.3 workbook migration for ChatGPT Work review."""
from __future__ import annotations

import os
from pathlib import Path

from job_search_helper.cli import PROJECT_ROOT, load_environment, project_path
from job_search_helper.core import material_hash, unpack_snapshot
from job_search_helper.efficiency import strip_job_boilerplate
from job_search_helper.repository import authorize, PROTECTED_BACKUP_ID
from job_search_helper.cli import get_repository, state_path
from job_search_helper.repair_v33_validation import repair

NEW_HEADERS = ["Source Hash", "Salary / Range", "Work Arrangement", "Job Description"]


def main() -> int:
    load_environment(PROJECT_ROOT / ".env")
    for variable, default in (
        ("GOOGLE_CREDENTIALS_FILE", "credentials.json"),
        ("GOOGLE_TOKEN_READ_FILE", ".secrets/token-readonly.json"),
        ("GOOGLE_TOKEN_WRITE_FILE", ".secrets/token-write.json"),
    ):
        os.environ[variable] = str(project_path(os.environ.get(variable, default)))

    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    if not spreadsheet_id:
        raise SystemExit("SPREADSHEET_ID is missing from .env")

    if spreadsheet_id == PROTECTED_BACKUP_ID:
        raise SystemExit("Refusing to modify the protected backup spreadsheet.")

    service = authorize(write=True, interactive=False)
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        includeGridData=False,
        fields="sheets(properties(sheetId,title,gridProperties),basicFilter)",
    ).execute()
    sheet = next((s for s in meta.get("sheets", []) if s.get("properties", {}).get("title") == "Job History"), None)
    if not sheet:
        raise SystemExit("Job History sheet not found")
    props = sheet["properties"]
    sheet_id = props["sheetId"]
    row_count = int(props.get("gridProperties", {}).get("rowCount", 1000))

    header_result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="'Job History'!1:1",
    ).execute()
    headers = (header_result.get("values") or [[]])[0]

    present = [h for h in NEW_HEADERS if h in headers]
    if present and present != NEW_HEADERS:
        raise SystemExit(f"Partial/out-of-order v3.3 headers found: {present}. Reconcile manually before migration.")

    if not present:
        old_count = len(headers)
        requests = [
            {"appendDimension": {"sheetId": sheet_id, "dimension": "COLUMNS", "length": len(NEW_HEADERS)}},
            {"updateCells": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                          "startColumnIndex": old_count, "endColumnIndex": old_count + len(NEW_HEADERS)},
                "rows": [{"values": [{"userEnteredValue": {"stringValue": h}} for h in NEW_HEADERS]}],
                "fields": "userEnteredValue",
            }},
            {"copyPaste": {
                "source": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": row_count,
                           "startColumnIndex": old_count - 1, "endColumnIndex": old_count},
                "destination": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": row_count,
                                "startColumnIndex": old_count, "endColumnIndex": old_count + len(NEW_HEADERS)},
                "pasteType": "PASTE_FORMAT",
                "pasteOrientation": "NORMAL",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": old_count, "endIndex": old_count + 1},
                "properties": {"pixelSize": 180}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": old_count + 1, "endIndex": old_count + 3},
                "properties": {"pixelSize": 150}, "fields": "pixelSize",
            }},
            {"updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": old_count + 3, "endIndex": old_count + 4},
                "properties": {"pixelSize": 600}, "fields": "pixelSize",
            }},
            {"setBasicFilter": {"filter": {"range": {
                "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": row_count,
                "startColumnIndex": 0, "endColumnIndex": old_count + len(NEW_HEADERS),
            }}}},
        ]
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()
        headers = headers + NEW_HEADERS
        print("Added Job History columns: " + ", ".join(NEW_HEADERS))
    else:
        print("v3.3 Job History columns already exist")

    # Formatting copied by older migrations can carry dropdown validation.
    repair(get_repository(write=True, interactive=False), state_path().parent)

    # Backfill the Work-readable fields from the helper's existing snapshot.
    end_col = "AF"  # 32 columns after v3.3 migration.
    rows_result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"'Job History'!A2:{end_col}{row_count}",
        majorDimension="ROWS",
    ).execute()
    rows = rows_result.get("values", [])
    index = {name: i for i, name in enumerate(headers)}
    updates = []
    backfilled = 0
    for offset, row in enumerate(rows, start=2):
        def cell(name):
            i = index[name]
            return row[i] if i < len(row) else ""
        if not cell("Job Key") or not cell("Current Snapshot"):
            continue
        try:
            snap = unpack_snapshot(cell("Current Snapshot"))
        except Exception:
            continue
        posting = snap.get("pending") or snap.get("evaluated")
        if not isinstance(posting, dict):
            continue
        desc = strip_job_boilerplate(posting.get("description", ""))
        if len(desc) > 44_000:
            desc = desc[:43_900] + "\n[TRUNCATED — open Official Job URL for the remainder]"
        values = [[
            material_hash(posting),
            posting.get("compensation", ""),
            posting.get("work_arrangement", ""),
            desc,
        ]]
        updates.append({"range": f"'Job History'!AC{offset}:AF{offset}", "values": values})
        backfilled += 1
        if len(updates) >= 200:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"valueInputOption": "RAW", "data": updates},
            ).execute()
            updates = []
    if updates:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()
    print(f"Backfilled Work-readable source fields for {backfilled} Job History rows")

    # Keep Search Config aligned with the new no-API workflow.
    config = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range="'Search Config'!A1:D100",
    ).execute().get("values", [])
    for rownum, row in enumerate(config, start=1):
        if len(row) > 1 and row[1] == "Hard Title Filter":
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=f"'Search Config'!C{rownum}:D{rownum}",
                valueInputOption="RAW",
                body={"values": [[
                    "Python deterministic + Work title triage",
                    "Scraper rejects clear title families and clear below-floor salary at $0. ChatGPT Work reviews remaining Needs Review jobs one at a time, checking the title before reading the description.",
                ]]},
            ).execute()
            break

    print("Migration complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
