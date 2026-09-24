"""Allowlisted, cell-precise persistence. No whole-tab replacement is provided.

A Google commit is one atomic Sheets batchUpdate, after resolving identities
against a fresh read. This is NOT an interprocess lock: the CLI must enforce an
exclusive writer, and users must not sort/insert/delete rows during a commit.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCHEMAS = {
    "Companies": [
        "Company", "Category", "Technology / Focus", "Website", "Why It Fits",
        "Priority", "Company Status", "Last Checked", "Notes", "Company ID",
        "Date Added", "Official Careers URL", "ATS / Source", "Scan State",
        "Active Cycle ID", "Last Successful Scan", "Claimed By", "Claim Expires At",
        "Claim Token", "Blocked Reason", "Next Action", "Automatic Retry?",
        "Coverage Status", "Last Inventory Count", "Last Scan Result", "Record Updated",
    ],
    "Opportunities": [
        "Company", "Job Title", "Job URL", "Location", "Salary / Range",
        "Work Arrangement", "Fit Review", "Application Status", "Date Applied",
        "Date Found", "Last Checked", "Notes",
    ],
    "Job History": [
        "Company", "Job Title", "Added to Opportunities?", "Rejection Reason",
        "Requisition ID", "Official Job URL", "Location", "First Seen", "Last Checked",
        "Job Status", "Job Key", "Review Notes", "Description Hash", "Current Snapshot",
        "Material Change Summary", "Reconsideration Count", "Reconsideration Status",
        "Last Evaluated", "Consecutive Missing Scans", "Last Seen In Inventory",
        "Prior Job Key", "Recheck Limit", "Record Updated", "Source Last Modified",
        "Review Status", "Review Started At", "Decision", "Fit Level",
        "Source Hash", "Salary / Range", "Work Arrangement", "Job Description",
    ],
    "Scan Cycles": [
        "Cycle ID", "Started At", "Completed At", "Cycle Status", "Started By",
        "Companies in Scope", "Companies Complete", "Companies Partial",
        "Companies Blocked", "Companies Remaining", "Last Company ID", "Last Company",
        "Last Checkpoint At", "Notes",
    ],
}
ALLOWED_TABS = frozenset(SCHEMAS)
MAX_ROWS = 100_000
MAX_EXISTING_GRID_ROWS = 100_000
MAX_COLUMNS = 52
MAX_CELL_CHARACTERS = 45_000
MAX_BATCH_UPDATE_BYTES = 2_200_000
MAX_BATCH_UPDATE_MB_LABEL = "2.2 MB"
URL_HEADERS = {"Job URL", "Official Job URL", "Official Careers URL", "Website"}
USER_FIELDS = {"Application Status", "Date Applied", "Date Found"}
PROTECTED_BACKUP_ID = "1avssxbKDXMrKS0oFHNAfhbQ2HWNz3T_jkn4DSUEmqv0"


class RepositoryError(RuntimeError):
    """A schema, identity, permission, or preservation precondition failed."""


def _tab(tab):
    if tab not in ALLOWED_TABS:
        raise RepositoryError(f"Tab is not operationally allowlisted: {tab!r}")


def _scalar(value):
    if value is None:
        return ""
    if not isinstance(value, (str, int, float, bool)):
        raise RepositoryError("Cell values must be text, numbers, booleans, or null.")
    if isinstance(value, float) and not math.isfinite(value):
        raise RepositoryError("Non-finite numeric cell value.")
    if isinstance(value, str) and len(value) > MAX_CELL_CHARACTERS:
        raise RepositoryError("Cell exceeds the conservative 45,000-character limit.")
    return value


def _url(value):
    # This fallback also permits repository.py to run its tests independently.
    try:
        from .core import canonicalize_url
    except ImportError:
        def canonicalize_url(raw):
            parsed = urlsplit(str(raw).strip())
            query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                     if not k.lower().startswith("utm_")
                     and k.lower() not in {"gh_src", "source", "ref", "referrer"}]
            return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                               parsed.path.rstrip("/"), urlencode(sorted(query)), ""))
    return canonicalize_url(str(value))


def _equivalent(header, left, right):
    if header in {"Company", "Company ID"}:
        return str(left).strip().casefold() == str(right).strip().casefold()
    if header in URL_HEADERS:
        return _url(left) == _url(right)
    return str(left).strip() == str(right).strip()


def _effective(cell):
    for group in ("effectiveValue", "userEnteredValue"):
        value = cell.get(group, {})
        for kind in ("stringValue", "numberValue", "boolValue"):
            if kind in value:
                return value[kind]
    return cell.get("formattedValue", "")


def _value(cell, header):
    if header in URL_HEADERS:
        links = set()
        if cell.get("hyperlink"):
            links.add(cell["hyperlink"])
        for run in cell.get("textFormatRuns", []):
            link = run.get("format", {}).get("link", {}).get("uri")
            if link:
                links.add(link)
        if len(links) > 1:
            raise RepositoryError(f"Ambiguous multiple hyperlinks in {header}.")
        if links:
            return next(iter(links))
        formula = cell.get("userEnteredValue", {}).get("formulaValue", "")
        match = re.match(r'^\s*=HYPERLINK\(\s*"((?:[^"]|"")*)"\s*[,;]', formula, re.I)
        if match:
            return match.group(1).replace('""', '"')
    return _effective(cell)


def _encoded(value):
    value = _scalar(value)
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, (float, int)):
        return {"numberValue": value}
    # Literal stringValue means an ATS string starting with '=' stays text.
    return {"stringValue": value}


@dataclass
class _Sheet:
    headers: list[str]
    cells: dict[tuple[int, int], dict] = field(default_factory=dict)
    sheet_id: int = 0
    row_count: int = 1000
    column_count: int = 26
    tables: list[dict] = field(default_factory=list)

    def records(self):
        records = []
        for row in sorted({r for r, _ in self.cells if r > 0}):
            values = {h: _value(self.cells.get((row, col), {}), h)
                      for col, h in enumerate(self.headers)}
            if any(v != "" for v in values.values()) or any(
                self.cells.get((row, c), {}).get("userEnteredValue", {}).get("formulaValue")
                for c in range(len(self.headers))
            ):
                records.append((row, values))
        return records


def _validate_headers(tab, headers, required):
    if not headers or any(not isinstance(h, str) or not h.strip() for h in headers):
        raise RepositoryError(f"{tab}: empty or non-text header.")
    canonical = [h.strip().casefold() for h in headers]
    if len(set(canonical)) != len(headers):
        raise RepositoryError(f"{tab}: duplicate header.")
    missing = set(required) - set(headers)
    if missing:
        raise RepositoryError(f"{tab}: missing required headers: {', '.join(sorted(missing))}")


def _table_rule(sheet, row, col):
    for table in sheet.tables:
        bounds = table.get("range", {})
        if bounds.get("startRowIndex", 0) <= row and (
            bounds.get("startColumnIndex", 0) <= col < bounds.get("endColumnIndex", 0)
        ):
            offset = col - bounds.get("startColumnIndex", 0)
            for column in table.get("columnProperties", []):
                if column.get("columnIndex") == offset:
                    rule = column.get("dataValidationRule")
                    if rule:
                        return {**rule, "strict": True}
    return {}


def _validate_dropdown(rule, value, tab, header):
    if value == "" or not rule or not rule.get("strict", False):
        return
    condition = rule.get("condition", {})
    kind = condition.get("type")
    if kind == "ONE_OF_LIST":
        choices = [v.get("userEnteredValue", "") for v in condition.get("values", [])]
        if str(value) not in choices:
            raise RepositoryError(f"{tab}.{header}: {value!r} is not an allowed dropdown choice.")
    elif kind == "BOOLEAN":
        choices = [v.get("userEnteredValue", "") for v in condition.get("values", [])]
        if choices:
            if str(value) not in choices:
                raise RepositoryError(f"{tab}.{header}: invalid checkbox value.")
        elif not isinstance(value, bool):
            raise RepositoryError(f"{tab}.{header}: checkbox requires a boolean.")
    else:
        raise RepositoryError(f"{tab}.{header}: strict {kind} validation needs manual confirmation.")


def _prepare(sheets, schemas, operations):
    """Mutate only a private snapshot; return exact, validated cell edits."""
    changed = {}
    inserted = updated = 0
    new_rows = set()
    allowed_keys = {"tab", "identity", "values", "on_insert", "append_if_missing", "append_notes"}
    for operation in operations:
        if not isinstance(operation, dict) or set(operation) - allowed_keys:
            raise RepositoryError("Unexpected operation field or invalid operation object.")
        tab = operation.get("tab")
        _tab(tab)
        if tab not in sheets:
            raise RepositoryError(f"Missing tab: {tab}")
        sheet = sheets[tab]
        _validate_headers(tab, sheet.headers, schemas[tab])
        identity = operation.get("identity")
        if not isinstance(identity, dict) or not identity or any(
            _scalar(v) == "" or not str(v).strip() for v in identity.values()
        ):
            raise RepositoryError("Every operation requires a nonempty, nonblank identity.")
        mappings = [identity]
        for key in ("values", "on_insert", "append_notes"):
            value = operation.get(key, {})
            if not isinstance(value, dict):
                raise RepositoryError(f"{key} must be a mapping.")
            mappings.append(value)
        fields = set().union(*(set(m) for m in mappings))
        unknown = fields - set(sheet.headers)
        if unknown:
            raise RepositoryError(f"{tab}: unknown fields: {', '.join(sorted(unknown))}")
        for mapping in mappings:
            for value in mapping.values():
                _scalar(value)
        for header, value in operation.get("values", {}).items():
            if header in identity and not _equivalent(header, value, identity[header]):
                raise RepositoryError("A commit cannot change its own identity.")
        matches = [(r, values) for r, values in sheet.records()
                   if all(_equivalent(h, values[h], v) for h, v in identity.items())]
        if len(matches) > 1:
            raise RepositoryError(f"{tab}: identity matches multiple rows; refusing to guess.")
        is_new = not matches
        if is_new:
            if not operation.get("append_if_missing", False):
                raise RepositoryError(f"{tab}: identity does not exist; append is not authorized.")
            row = max([0] + [r for r, _ in sheet.records()]) + 1
            if row >= MAX_ROWS:
                raise RepositoryError("Maximum safe row bound reached.")
            old_values = {h: "" for h in sheet.headers}
            values = {**operation.get("on_insert", {}), **identity,
                      **operation.get("values", {})}
            new_rows.add((tab, row))
            inserted += 1
        else:
            row, old_values = matches[0]
            values = dict(operation.get("values", {}))
            # Job-level review lock. If AI has claimed this Job History row,
            # scraper/source updates are ignored for this pass. AI claim refresh
            # and AI completion writes explicitly carry Review Status and remain
            # allowed. This check occurs against the fresh pre-commit Sheet read,
            # so it closes the race between planning and the actual batchUpdate.
            if tab == "Job History" and old_values.get("Review Status") == "In Progress":
                target_status = values.get("Review Status")
                if target_status not in {"In Progress", "Reviewed", "Manual Review"}:
                    continue
            updated += 1
        for header, text in operation.get("append_notes", {}).items():
            if not isinstance(text, str) or not text.strip():
                raise RepositoryError("Appended notes must be nonblank text.")
            if header in operation.get("values", {}):
                raise RepositoryError("A field cannot be both replaced and appended in one operation.")
            previous = str(values.get(header, old_values[header]) or "")
            # A repeated delivery appends exactly once. Never replace personal notes.
            if text not in previous:
                values[header] = previous + ("\n\n" if previous else "") + text
        for header, value in values.items():
            value = _scalar(value)
            col = sheet.headers.index(header)
            cell = sheet.cells.get((row, col), {})
            old_value = old_values[header]
            if value == old_value:
                continue
            if cell.get("userEnteredValue", {}).get("formulaValue"):
                if _equivalent(header, old_value, value):
                    continue
                raise RepositoryError(f"{tab}.{header}: refusing to replace an existing formula.")
            if not is_new and tab == "Opportunities":
                if header in USER_FIELDS:
                    raise RepositoryError(f"Preserving user-controlled Opportunities.{header}.")
                if header == "Notes" and header not in operation.get("append_notes", {}):
                    raise RepositoryError("Existing opportunity Notes may only be appended to.")
            rule = cell.get("dataValidation") or _table_rule(sheet, row, col)
            _validate_dropdown(rule, value, tab, header)
            encoded = _encoded(value)
            replacement = copy.deepcopy(cell)
            replacement["userEnteredValue"] = encoded
            replacement["effectiveValue"] = encoded
            replacement.pop("hyperlink", None)
            replacement.pop("textFormatRuns", None)
            sheet.cells[(row, col)] = replacement
            changed[(tab, row, col)] = encoded
    # Report only rows actually inserted against the authoritative fresh read.
    # Callers receive this metadata only after the write succeeds.
    new_jobs = []
    if any(tab == "Job History" for tab, _ in new_rows):
        for row, values in sheets["Job History"].records():
            if ("Job History", row) in new_rows:
                new_jobs.append((values["Job Title"], values["Company"]))
    return changed, new_rows, {"inserted": inserted, "updated": updated, "new_jobs": new_jobs}


class MemoryRepository:
    """In-memory transactional repository used by offline demos and tests."""

    def __init__(self, tabs=None, schemas=None):
        self.schemas = copy.deepcopy(SCHEMAS if schemas is None else schemas)
        self._sheets = {}
        self._committed_rows = {}
        supplied = tabs or {}
        for tab in supplied:
            _tab(tab)
        for tab, headers in self.schemas.items():
            _tab(tab)
            sheet = _Sheet(list(headers), sheet_id=len(self._sheets))
            for index, record in enumerate(supplied.get(tab, []), 1):
                unknown = set(record) - set(headers)
                if unknown:
                    raise RepositoryError(f"{tab}: unknown input fields: {unknown}")
                for col, header in enumerate(headers):
                    if header in record:
                        value = _encoded(record[header])
                        sheet.cells[(index, col)] = {"userEnteredValue": value,
                                                     "effectiveValue": value}
            self._sheets[tab] = sheet

    @property
    def tables(self):
        return {tab: self.read(tab) for tab in self._sheets}

    def read(self, tab):
        _tab(tab)
        if tab not in self._sheets:
            raise RepositoryError(f"Missing tab: {tab}")
        sheet = self._sheets[tab]
        _validate_headers(tab, sheet.headers, self.schemas[tab])
        return copy.deepcopy([values for _, values in sheet.records()])

    def read_columns(self, tab, headers):
        _tab(tab)
        sheet = self._sheets[tab]
        _validate_headers(tab, sheet.headers, self.schemas[tab])
        missing = [h for h in headers if h not in sheet.headers]
        if missing:
            raise RepositoryError(f"{tab}: missing requested headers: {', '.join(missing)}")
        result = []
        for rownum, values in sheet.records():
            subset = {h: values.get(h, "") for h in headers}
            if any(v != "" for v in subset.values()):
                result.append((rownum + 1, subset))
        return copy.deepcopy(result)

    def read_row(self, tab, row_number):
        _tab(tab)
        if row_number < 2:
            raise RepositoryError("Data row numbers are 1-based and must be >= 2.")
        sheet = self._sheets[tab]
        _validate_headers(tab, sheet.headers, self.schemas[tab])
        row_index = row_number - 1
        values = {h: _value(sheet.cells.get((row_index, col), {}), h)
                  for col, h in enumerate(sheet.headers)}
        return copy.deepcopy(values)

    def validate_schema(self):
        for tab, required in self.schemas.items():
            if tab not in self._sheets:
                raise RepositoryError(f"Missing tab: {tab}")
            _validate_headers(tab, self._sheets[tab].headers, required)
        return True

    def read_many(self, tabs):
        return {tab: self.read(tab) for tab in tabs}

    def commit(self, operations):
        snapshot = copy.deepcopy(self._sheets)
        changed, _, result = _prepare(snapshot, self.schemas, list(operations))
        self._sheets = snapshot
        self._committed_rows = {tab: self.read(tab) for tab in {key[0] for key in changed}}
        return {**result, "requests": len(changed)}


def _column_name(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _execute(request, action):
    try:
        return request.execute()
    except Exception as exc:
        suffix = (" No successful write is confirmed; resume the same keyed decision."
                  if action == "write" else " No spreadsheet changes were requested by this read.")
        # API errors may contain requested cell content. Do not echo that body.
        raise RepositoryError(f"Google Sheets {action} failed ({type(exc).__name__})." + suffix) from exc


class GoogleRepository:
    def __init__(self, service, spreadsheet_id, schemas=None, min_request_interval=2.5):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", str(spreadsheet_id)):
            raise RepositoryError("A spreadsheet ID, not a URL, is required.")
        self.service = service
        self.spreadsheet_id = spreadsheet_id
        self.schemas = copy.deepcopy(SCHEMAS if schemas is None else schemas)
        if not 0 <= min_request_interval <= 30:
            raise RepositoryError("Request interval must be between 0 and 30 seconds.")
        self.min_request_interval = min_request_interval
        self._next_request_at = 0.0
        self._committed_rows = {}
        self._metadata_cache = None
        self._header_cache = {}

    def _execute(self, request, action):
        # Scraper and reviewer run as separate processes but share one Google-user
        # quota. Pace each process conservatively so their combined traffic stays
        # below the Sheets per-user request limit. Read requests may be retried
        # safely by googleapiclient on 429/5xx responses; writes are never
        # automatically retried because a lost write response can be ambiguous.
        delay = max(0.0, self._next_request_at - time.monotonic())
        if delay:
            time.sleep(delay)
        self._next_request_at = time.monotonic() + self.min_request_interval
        try:
            if action == "read":
                try:
                    return request.execute(num_retries=5)
                except TypeError:
                    # Lightweight test doubles and older clients may not expose
                    # num_retries; fall back without changing production behavior.
                    return request.execute()
            return request.execute()
        except Exception as exc:
            suffix = (" No successful write is confirmed; resume the same keyed decision."
                      if action == "write" else " No spreadsheet changes were requested by this read.")
            raise RepositoryError(f"Google Sheets {action} failed ({type(exc).__name__})." + suffix) from exc

    def _metadata(self):
        if self._metadata_cache is None:
            self._metadata_cache = self._execute(self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties),tables)",
            ), "read")
        return self._metadata_cache

    def _load(self, tabs):
        tabs = sorted(set(tabs))
        for tab in tabs:
            _tab(tab)
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        ranges = []
        for tab in tabs:
            if tab not in found:
                raise RepositoryError(f"Missing tab: {tab}")
            grid = found[tab]["properties"].get("gridProperties", {})
            rows, cols = grid.get("rowCount", 0), grid.get("columnCount", 0)
            if not (0 < rows <= MAX_ROWS and 0 < cols <= MAX_COLUMNS):
                raise RepositoryError(f"{tab}: grid exceeds safe read bounds or is not a grid sheet.")
            ranges.append(f"'{tab.replace(chr(39), chr(39)*2)}'!A1:{_column_name(cols)}{rows}")
        if not ranges:
            return {}
        data = self._execute(self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id, ranges=ranges, includeGridData=True,
            fields=("sheets(properties(sheetId,title,gridProperties),tables,"
                    "data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,"
                    "formattedValue,hyperlink,textFormatRuns,dataValidation))))"),
        ), "read")
        loaded = {}
        for raw in data.get("sheets", []):
            props = raw["properties"]
            tab = props["title"]
            if tab not in tabs:
                continue
            grid = props.get("gridProperties", found[tab]["properties"]["gridProperties"])
            sheet = _Sheet([], sheet_id=props["sheetId"], row_count=grid["rowCount"],
                           column_count=grid["columnCount"],
                           tables=raw.get("tables", found[tab].get("tables", [])))
            for block in raw.get("data", []):
                for offset, row in enumerate(block.get("rowData", [])):
                    rownum = block.get("startRow", 0) + offset
                    for coloffset, cell in enumerate(row.get("values", [])):
                        col = block.get("startColumn", 0) + coloffset
                        if cell:
                            sheet.cells[(rownum, col)] = cell
            # Include every populated column, not just the first consecutive headers.
            populated_cols = [col for (row, col), cell in sheet.cells.items()
                              if _effective(cell) != "" or cell.get("userEnteredValue")]
            width = max(populated_cols, default=-1) + 1
            raw_headers = [_effective(sheet.cells.get((0, col), {})) for col in range(width)]
            if any(not isinstance(value, str) for value in raw_headers):
                raise RepositoryError(f"{tab}: headers must be literal text.")
            if any(sheet.cells.get((0, col), {}).get("userEnteredValue", {}).get("formulaValue")
                   for col in range(width)):
                raise RepositoryError(f"{tab}: formula headers are not supported.")
            sheet.headers = [value.strip() for value in raw_headers]
            _validate_headers(tab, sheet.headers, self.schemas[tab])
            loaded[tab] = sheet
        if set(loaded) != set(tabs):
            raise RepositoryError("The server omitted a requested sheet; no write is safe.")
        return loaded

    def _headers(self, tab):
        _tab(tab)
        if tab in self._header_cache:
            return self._header_cache[tab]
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        if tab not in found:
            raise RepositoryError(f"Missing tab: {tab}")
        cols = found[tab]["properties"].get("gridProperties", {}).get("columnCount", 0)
        if not 0 < cols <= MAX_COLUMNS:
            raise RepositoryError(f"{tab}: invalid column count.")
        end = _column_name(cols)
        result = self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab.replace(chr(39), chr(39)*2)}'!A1:{end}1",
                majorDimension="ROWS",
            ),
            "read",
        )
        values = (result.get("values") or [[]])[0]
        headers = [str(v).strip() for v in values]
        _validate_headers(tab, headers, self.schemas[tab])
        mapping = {header: index for index, header in enumerate(headers)}
        self._header_cache[tab] = (headers, mapping)
        return headers, mapping

    def read_columns(self, tab, headers):
        """Read a few plain-value columns with one batchGet request.

        Used for queue/status scans where cell formatting, validation, and rich
        links are irrelevant. Returns (1-based row number, values dict).
        """
        _tab(tab)
        live_headers, mapping = self._headers(tab)
        missing = [h for h in headers if h not in mapping]
        if missing:
            raise RepositoryError(f"{tab}: missing requested headers: {', '.join(missing)}")
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        row_count = found[tab]["properties"].get("gridProperties", {}).get("rowCount", 0)
        escaped = tab.replace(chr(39), chr(39)*2)
        ranges = []
        for header in headers:
            col = _column_name(mapping[header] + 1)
            ranges.append(f"'{escaped}'!{col}2:{col}{row_count}")
        result = self._execute(
            self.service.spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=ranges,
                majorDimension="ROWS",
            ),
            "read",
        )
        columns = []
        for value_range in result.get("valueRanges", []):
            raw = value_range.get("values", [])
            columns.append([row[0] if row else "" for row in raw])
        while len(columns) < len(headers):
            columns.append([])
        max_len = max((len(c) for c in columns), default=0)
        records = []
        for offset in range(max_len):
            values = {header: (columns[i][offset] if offset < len(columns[i]) else "")
                      for i, header in enumerate(headers)}
            if any(value != "" for value in values.values()):
                records.append((offset + 2, values))
        return records

    def read_row(self, tab, row_number):
        """Read one row as plain values; ideal for AI claim validation."""
        _tab(tab)
        if row_number < 2:
            raise RepositoryError("Data row numbers are 1-based and must be >= 2.")
        headers, _ = self._headers(tab)
        end = _column_name(len(headers))
        escaped = tab.replace(chr(39), chr(39)*2)
        result = self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{escaped}'!A{row_number}:{end}{row_number}",
                majorDimension="ROWS",
            ),
            "read",
        )
        values = (result.get("values") or [[]])[0]
        padded = list(values) + [""] * max(0, len(headers) - len(values))
        return {header: padded[index] if index < len(padded) else ""
                for index, header in enumerate(headers)}

    def read(self, tab):
        sheet = self._load([tab])[tab]
        return [values for _, values in sheet.records()]

    def read_many(self, tabs):
        return {tab: [values for _, values in sheet.records()] for tab, sheet in self._load(tabs).items()}

    def validate_schema(self):
        """Validate operational headers without downloading entire tabs."""
        sheets_api = self.service.spreadsheets()
        if not hasattr(sheets_api, "values"):
            # Compatibility fallback for older clients/test doubles.
            self._load(self.schemas)
            return True
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        ranges = []
        tabs = list(self.schemas)
        for tab in tabs:
            if tab not in found:
                raise RepositoryError(f"Missing tab: {tab}")
            cols = found[tab]["properties"].get("gridProperties", {}).get("columnCount", 0)
            if not 0 < cols <= MAX_COLUMNS:
                raise RepositoryError(f"{tab}: invalid column count.")
            escaped = tab.replace(chr(39), chr(39)*2)
            ranges.append(f"'{escaped}'!A1:{_column_name(cols)}1")
        result = self._execute(
            self.service.spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=ranges,
                majorDimension="ROWS",
            ),
            "read",
        )
        value_ranges = result.get("valueRanges", [])
        if len(value_ranges) != len(tabs):
            raise RepositoryError("The server omitted a requested header row.")
        for tab, value_range in zip(tabs, value_ranges):
            values = (value_range.get("values") or [[]])[0]
            headers = [str(v).strip() for v in values]
            _validate_headers(tab, headers, self.schemas[tab])
            self._header_cache[tab] = (headers, {header: index for index, header in enumerate(headers)})
        return True

    def commit(self, operations):
        if self.spreadsheet_id == PROTECTED_BACKUP_ID:
            raise RepositoryError("Refusing to write the protected Job Search Master - Original backup.")
        operations = list(operations)
        self._committed_rows = {}
        if not operations:
            return {"inserted": 0, "updated": 0, "requests": 0}
        for operation in operations:
            if not isinstance(operation, dict):
                raise RepositoryError("Each operation must be a mapping.")
            _tab(operation.get("tab"))
        sheets = self._load([op["tab"] for op in operations])
        changed, new_rows, result = _prepare(sheets, self.schemas, operations)
        requests = []
        for tab, sheet in sheets.items():
            appended = [row for name, row in new_rows if name == tab]
            if not appended:
                continue
            required_rows = max(appended) + 1
            if required_rows > sheet.row_count:
                requests.append({"appendDimension": {"sheetId": sheet.sheet_id,
                    "dimension": "ROWS", "length": required_rows - sheet.row_count}})
            if sheet.tables:
                if len(sheet.tables) != 1:
                    raise RepositoryError(f"{tab}: multiple-table append needs manual setup.")
                table = sheet.tables[0]
                bounds = table.get("range", {})
                if (bounds.get("startRowIndex", 0) != 0 or bounds.get("startColumnIndex", 0) != 0
                        or bounds.get("endColumnIndex") != len(sheet.headers)
                        or "footerColorStyle" in table.get("rowsProperties", {})):
                    raise RepositoryError(f"{tab}: footer or nonstandard table append is not supported.")
                if required_rows > bounds.get("endRowIndex", 0):
                    expanded = {**bounds, "endRowIndex": required_rows}
                    requests.append({"updateTable": {"table": {"tableId": table["tableId"],
                        "range": expanded}, "fields": "range"}})
        for (tab, row, col), value in sorted(changed.items()):
            requests.append({"updateCells": {
                "start": {"sheetId": sheets[tab].sheet_id, "rowIndex": row, "columnIndex": col},
                "rows": [{"values": [{"userEnteredValue": value}]}],
                "fields": "userEnteredValue",
            }})
        if requests:
            if len(json.dumps({"requests": requests}, ensure_ascii=True).encode("utf-8")) > MAX_BATCH_UPDATE_BYTES:
                raise RepositoryError(f"Planned batch exceeds the {MAX_BATCH_UPDATE_MB_LABEL} safety threshold. No write attempted; resume with --batch-size 25 (or 5).")
            structural = any(set(req) & {"appendDimension", "updateTable", "insertDimension", "deleteDimension"}
                             for req in requests)
            # No automatic retry of writes: after a timeout, rerun the same keyed
            # decision so it is resolved against the authoritative fresh sheet.
            self._execute(self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id, body={"requests": requests},
            ), "write")
            if structural:
                self._metadata_cache = None
                self._header_cache = {}
        self._header_cache = {}
        self._committed_rows = {tab: [values for _, values in sheet.records()] for tab, sheet in sheets.items()}
        return {**result, "requests": len(requests)}

    def commit_existing_job_history_flags(self, operations):
        """Update only existing Job History opportunity flags by verified row.

        This avoids loading wide Job History rows (including descriptions) and
        tolerates unused grid allocation above MAX_ROWS. It cannot append,
        delete, move, or update any field other than the validated flag.
        """
        if self.spreadsheet_id == PROTECTED_BACKUP_ID:
            raise RepositoryError("Refusing to write the protected Job Search Master - Original backup.")
        operations = list(operations)
        if not operations:
            return {"inserted": 0, "updated": 0, "requests": 0}
        if len(operations) > 5000:
            raise RepositoryError("Blacklist cleanup exceeds the safe update count.")

        headers, mapping = self._headers("Job History")
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        sheet = found.get("Job History")
        if not sheet:
            raise RepositoryError("Missing tab: Job History")
        props = sheet["properties"]
        row_count = props.get("gridProperties", {}).get("rowCount", 0)
        if not 1 < row_count <= MAX_EXISTING_GRID_ROWS:
            raise RepositoryError("Job History: existing grid exceeds the targeted-cleanup safety bound.")
        required = ["Company", "Job Title", "Added to Opportunities?", "Job Key",
                    "Official Job URL", "Review Status"]
        fresh = dict(self.read_columns("Job History", required))
        target_col = mapping["Added to Opportunities?"]
        escaped = "Job History"
        target_range = f"'{escaped}'!{_column_name(target_col + 1)}2:{_column_name(target_col + 1)}{row_count}"
        cell_data = self._execute(self.service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id, ranges=[target_range], includeGridData=True,
            fields="sheets(data(startRow,startColumn,rowData(values(userEnteredValue,dataValidation))))",
        ), "read")
        cells = {}
        for raw_sheet in cell_data.get("sheets", []):
            for block in raw_sheet.get("data", []):
                start = block.get("startRow", 1)
                for offset, raw_row in enumerate(block.get("rowData", [])):
                    values = raw_row.get("values", [])
                    cells[start + offset] = values[0] if values else {}

        requests = []
        allowed_keys = {"tab", "row_number", "identity", "values"}
        for operation in operations:
            if not isinstance(operation, dict) or set(operation) != allowed_keys:
                raise RepositoryError("Blacklist cleanup operation has unexpected fields.")
            if operation["tab"] != "Job History" or operation["values"] != {"Added to Opportunities?": "No"}:
                raise RepositoryError("Blacklist cleanup may only set the Job History opportunity flag to No.")
            row_number = operation["row_number"]
            identity = operation["identity"]
            if (type(row_number) is not int or not 2 <= row_number <= row_count
                    or not isinstance(identity, dict) or not identity
                    or any(header not in headers or _scalar(value) == "" or not str(value).strip()
                           for header, value in identity.items())):
                raise RepositoryError("Blacklist cleanup requires a valid existing row and identity.")
            current = fresh.get(row_number)
            if current is None or not all(_equivalent(header, current.get(header, ""), value)
                                          for header, value in identity.items()):
                raise RepositoryError("Job History changed after cleanup planning; no cleanup write attempted.")
            if current.get("Review Status") == "In Progress":
                raise RepositoryError("A cleanup target entered review; no cleanup write attempted.")
            if str(current.get("Added to Opportunities?", "")).strip().casefold() == "no":
                continue
            cell = cells.get(row_number - 1, {})
            if cell.get("userEnteredValue", {}).get("formulaValue"):
                raise RepositoryError("Refusing to replace a formula in Added to Opportunities?.")
            _validate_dropdown(cell.get("dataValidation", {}), "No", "Job History", "Added to Opportunities?")
            requests.append({"updateCells": {
                "start": {"sheetId": props["sheetId"], "rowIndex": row_number - 1,
                          "columnIndex": target_col},
                "rows": [{"values": [{"userEnteredValue": {"stringValue": "No"}}]}],
                "fields": "userEnteredValue",
            }})

        if len(json.dumps({"requests": requests}, ensure_ascii=True).encode("utf-8")) > MAX_BATCH_UPDATE_BYTES:
            raise RepositoryError(f"Blacklist cleanup batch exceeds the {MAX_BATCH_UPDATE_MB_LABEL} safety threshold.")
        if requests:
            self._execute(self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id, body={"requests": requests},
            ), "write")
        self._header_cache = {}
        return {"inserted": 0, "updated": len(requests), "requests": len(requests)}


def _authorize(write=False, interactive=False):
    """Use existing OAuth credentials unless explicitly asked to authenticate.

    Read-only and writable credentials never share token files. Token refresh is
    allowed, but preflight will not open a browser or request broader scopes.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RepositoryError("Google support is not installed. Run: .venv/bin/python3.11 -m pip install -e '.[google]'") from exc
    scope = "https://www.googleapis.com/auth/spreadsheets" + ("" if write else ".readonly")
    credentials_path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")).expanduser().resolve()
    token_setting = "GOOGLE_TOKEN_WRITE_FILE" if write else "GOOGLE_TOKEN_READ_FILE"
    default_token = ".secrets/token-write.json" if write else ".secrets/token-readonly.json"
    raw_token = Path(os.getenv(token_setting, default_token)).expanduser()
    if raw_token.is_symlink() or raw_token.parent.is_symlink():
        raise RepositoryError("OAuth token paths must not be symlinks.")
    token_path = raw_token.resolve()
    other_setting = "GOOGLE_TOKEN_READ_FILE" if write else "GOOGLE_TOKEN_WRITE_FILE"
    other_default = ".secrets/token-readonly.json" if write else ".secrets/token-write.json"
    if token_path == Path(os.getenv(other_setting, other_default)).expanduser().resolve():
        raise RepositoryError("Read-only and write credentials require different token files.")
    credentials = None
    must_save = False
    if token_path.exists():
        if token_path.stat().st_mode & 0o077:
            raise RepositoryError(f"Token permissions must be 0600; correct the permissions of {token_path}.")
        # Check the recorded grant BEFORE creating a credential with requested scopes.
        with token_path.open(encoding="utf-8") as handle:
            saved = json.load(handle)
        if set(saved.get("scopes", [])) != {scope}:
            raise RepositoryError("Saved token scopes do not exactly match this command; reauthenticate with a separate token.")
        credentials = Credentials.from_authorized_user_info(saved, [scope])
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            must_save = True
        except Exception:
            if not interactive:
                raise
            # A revoked/expired refresh token should not block an explicit
            # reauthentication request. Fall through to a fresh browser grant.
            credentials = None
            must_save = False
    if not credentials or not credentials.valid:
        if not interactive:
            raise RepositoryError("No valid token is available; run the explicit authenticate command first.")
        if not credentials_path.is_file():
            raise RepositoryError("Google Desktop OAuth credentials.json is missing; configure GOOGLE_CREDENTIALS_FILE.")
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), [scope])
        credentials = flow.run_local_server(host="localhost", port=0, open_browser=True)
        must_save = True
    if must_save:
        token_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Never chmod the user's home or arbitrary existing broad directory.
        if token_path.parent.stat().st_mode & 0o077:
            raise RepositoryError("Token parent directory must already have private 0700 permissions.")
        fd, temporary = tempfile.mkstemp(prefix="token-", suffix=".json", dir=token_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(credentials.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, token_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False)


def authorize(write=False, interactive=False):
    try:
        return _authorize(write=write, interactive=interactive)
    except RepositoryError:
        raise
    except Exception as exc:
        raise RepositoryError(
            f"Google authentication failed ({type(exc).__name__}); check the local OAuth setup. "
            "No credential contents have been displayed."
        ) from exc


build_service = authorize
