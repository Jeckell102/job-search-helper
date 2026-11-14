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
import sys
import tempfile
import threading
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
        "Review Questions",
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
    "Job Evidence": [
        "Job Key", "Source Hash", "Company", "Job Title", "Official Job URL",
        "Captured At", "Job Description",
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


class PreflightWriteError(RepositoryError):
    """Commit validation failed before any remote write was submitted."""


class MissingIdentityError(PreflightWriteError):
    """Fresh pre-write identity lookup failed; no batch was submitted."""
    def __init__(self, tab, identity):
        self.tab = tab
        self.identity = dict(identity)
        super().__init__(f"{tab}: identity does not exist; append is not authorized.")


class ReviewFieldsChangedError(PreflightWriteError):
    """Fresh pre-write guards changed; no remote batch has been submitted."""
    def __init__(self, tab, identity):
        self.tab = tab
        self.identity = dict(identity)
        super().__init__(f"{tab}: review fields changed since planning; replan from fresh rows.")


class UncertainWriteError(RepositoryError):
    """A write may have landed; preserve its exact keyed plan for explicit replay."""


class BatchPayloadTooLarge(PreflightWriteError):
    """The encoded request exceeded the limit before any write was attempted."""


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
    append_floor: int = 0
    basic_filter: dict | None = None

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


def _identity_key(header, value):
    if header in {"Company", "Company ID"}:
        return str(value).strip().casefold()
    if header in URL_HEADERS:
        return _url(value)
    return str(value).strip()


class IdentityIndex:
    """Indexed candidate selection with the same normalization as _equivalent."""
    def __init__(self, records):
        self.rows = dict(records)
        self.columns = {}

    def matches(self, identity):
        candidates = None
        for header, value in identity.items():
            if header not in self.columns:
                index = {}
                for row, values in self.rows.items():
                    try:
                        key = _identity_key(header, values.get(header, ""))
                    except ValueError:
                        continue
                    index.setdefault(key, set()).add(row)
                self.columns[header] = index
            ids = self.columns[header].get(_identity_key(header, value), set())
            candidates = ids.copy() if candidates is None else candidates & ids
        return [(r, self.rows[r]) for r in sorted(candidates or ())]

    def put(self, row, values):
        old = self.rows.get(row)
        for header, index in self.columns.items():
            if old is not None:
                try:
                    old_key = _identity_key(header, old.get(header, ""))
                except ValueError:
                    old_key = None
                if old_key is not None:
                    index.get(old_key, set()).discard(row)
            try:
                key = _identity_key(header, values.get(header, ""))
            except ValueError:
                continue
            index.setdefault(key, set()).add(row)
        self.rows[row] = values


def _prepare(sheets, schemas, operations):
    """Validate a private snapshot without leaving ambiguous delivery receipts."""
    try:
        return _prepare_cells(sheets, schemas, operations)
    except PreflightWriteError:
        raise
    except RepositoryError as exc:
        raise PreflightWriteError(str(exc)) from None


def _prepare_cells(sheets, schemas, operations):
    """Mutate only a private snapshot; return exact, validated cell edits."""
    indexes = {tab: IdentityIndex(sheet.records()) for tab, sheet in sheets.items()}
    tails = {tab: max([sheet.append_floor, 0, *indexes[tab].rows]) for tab, sheet in sheets.items()}
    changed = {}
    inserted = updated = 0
    new_rows = set()
    allowed_keys = {"tab", "identity", "values", "on_insert", "append_if_missing", "append_notes", "expected"}
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
        for key in ("values", "on_insert", "append_notes", "expected"):
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
        matches = indexes[tab].matches(identity)
        if len(matches) > 1:
            raise RepositoryError(f"{tab}: identity matches multiple rows; refusing to guess.")
        is_new = not matches
        if is_new:
            if tab == "Job History":
                proposed = {**operation.get("on_insert", {}), **identity, **operation.get("values", {})}
                if proposed.get("Company") and proposed.get("Official Job URL"):
                    aliases = indexes[tab].matches({h: proposed[h] for h in ("Company", "Official Job URL")})
                    if aliases:
                        raise RepositoryError("Job History: official URL already has another identity; replan before inserting.")
            if not operation.get("append_if_missing", False):
                raise MissingIdentityError(tab, identity)
            row = tails[tab] + 1
            tails[tab] = row
            if row >= MAX_ROWS:
                raise RepositoryError("Maximum safe row bound reached.")
            old_values = {h: "" for h in sheet.headers}
            values = {**operation.get("on_insert", {}), **identity,
                      **operation.get("values", {})}
            new_rows.add((tab, row))
            inserted += 1
        else:
            row, old_values = matches[0]
            expected = operation.get("expected", {})
            mismatched = {h for h, v in expected.items()
                          if not _equivalent(h, old_values.get(h, ""), v)}
            if mismatched:
                # Replay only changes this operation could have made. A pure
                # guard, or a changed source field outside the write set, is
                # never evidence that an earlier delivery succeeded.
                intended = operation.get("values", {})
                notes = operation.get("append_notes", {})
                replayed = (mismatched <= set(intended) | set(notes)
                            and bool(intended or notes)
                            and all(_equivalent(h, old_values.get(h, ""), v)
                                    for h, v in intended.items())
                            and all(isinstance(text, str) and bool(text.strip())
                                    and text in str(old_values.get(h, "") or "")
                                    for h, text in notes.items()))
                if not replayed:
                    raise ReviewFieldsChangedError(tab, identity)
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
        current = {h: _value(sheet.cells.get((row, c), {}), h) for c, h in enumerate(sheet.headers)}
        indexes[tab].put(row, current)
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

    def read_rows(self, tab, row_numbers):
        """Read exact native data rows, preserving their 1-based numbers."""
        _tab(tab)
        if tab not in self._sheets:
            raise RepositoryError(f"Missing tab: {tab}")
        row_numbers = list(row_numbers)
        row_count = self._sheets[tab].row_count
        if any(type(row) is not int or not 2 <= row <= row_count for row in row_numbers):
            raise RepositoryError(f"Data row numbers must be integers between 2 and {row_count}.")
        return {row: self.read_row(tab, row) for row in dict.fromkeys(row_numbers)}

    def validate_schema(self):
        for tab, required in self.schemas.items():
            if tab not in self._sheets:
                raise RepositoryError(f"Missing tab: {tab}")
            _validate_headers(tab, self._sheets[tab].headers, required)
        return True

    def ensure_tab(self, tab):
        _tab(tab)
        if tab not in self._sheets:
            self._sheets[tab] = _Sheet(list(self.schemas[tab]), sheet_id=len(self._sheets))
            return {"created": True, "added_headers": list(self.schemas[tab])}
        added = self.ensure_columns(tab, self.schemas[tab])
        return {"created": False, "added_headers": added}

    def read_many(self, tabs):
        return {tab: self.read(tab) for tab in tabs}

    def ensure_columns(self, tab, headers):
        _tab(tab)
        sheet = self._sheets[tab]
        added = []
        for header in [str(header).strip() for header in headers if str(header).strip()]:
            if header not in sheet.headers:
                sheet.headers.append(header)
                self.schemas[tab] = [*self.schemas[tab], header] if header not in self.schemas[tab] else self.schemas[tab]
                added.append(header)
        return added

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
        raise (UncertainWriteError if action == "write" else RepositoryError)(
            f"Google Sheets {action} failed ({type(exc).__name__})." + suffix) from exc


def _uncompressed_read_request(request, error):
    """Copy a safe read for one identity-encoded retry after a ratio failure."""
    try:
        from httplib2.decode import DecodeRatioError
        from googleapiclient.http import HttpRequest
    except ImportError:
        # The Google dependencies are optional, and older httplib2 has no guard.
        return None
    if not isinstance(error, DecodeRatioError) or not isinstance(request, HttpRequest):
        return None
    if request.resumable is not None:
        return None
    headers = getattr(request, "headers", None)
    if not isinstance(headers, dict):
        return None
    if any(not isinstance(key, str) or not isinstance(value, str)
           for key, value in headers.items()):
        return None
    normalized = {key.lower(): value for key, value in headers.items()}
    method = str(getattr(request, "method", "")).upper()
    overrides = [value.upper() for key, value in headers.items()
                 if key.lower() == "x-http-method-override"]
    # googleapiclient converts long GET URLs to POST with this override before
    # sending them. Reuse that exact URI/body, without treating other POSTs as reads.
    if not ((method in {"GET", "HEAD"} and not overrides) or
            (method == "POST" and overrides == ["GET"])):
        return None
    if normalized.get("accept-encoding", "").strip().lower() == "identity":
        return None
    retry = copy.copy(request)
    retry.headers = {key: value for key, value in headers.items()
                     if key.lower() != "accept-encoding"}
    retry.headers["accept-encoding"] = "identity"
    return retry


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
        self._write_layout = {}
        self._identity_hints = {}
        self._compact_identity_hints = {}
        self._committed_partial = False
        self.metrics = {"read_requests": 0, "write_requests": 0, "read_response_bytes": 0,
                        "write_payload_bytes": 0, "read_seconds": 0.0, "write_seconds": 0.0,
                        "throttle_seconds": 0.0, "prepare_seconds": 0.0,
                        "build_requests_seconds": 0.0}

    def _pace_request(self, action):
        delay = max(0.0, self._next_request_at - time.monotonic())
        wait_started = time.monotonic()
        if delay:
            time.sleep(delay)
        self.metrics["throttle_seconds"] += time.monotonic() - wait_started
        self._next_request_at = time.monotonic() + self.min_request_interval
        self.metrics[action + "_requests"] += 1

    def _execute(self, request, action):
        # Scraper and reviewer run as separate processes but share one Google-user
        # quota. Pace each process conservatively so their combined traffic stays
        # below the Sheets per-user request limit. Read requests may be retried
        # safely by googleapiclient on 429/5xx responses; writes are never
        # automatically retried because a lost write response can be ambiguous.
        self._pace_request(action)
        started = time.monotonic()
        try:
            if action == "read":
                try:
                    try:
                        response = request.execute(num_retries=5)
                    except TypeError:
                        response = request.execute()
                except Exception as exc:
                    retry = _uncompressed_read_request(request, exc)
                    if retry is None:
                        raise
                    # Negotiate uncompressed bytes; never weaken decoder limits.
                    # Count and pace the extra read, with no further retry loop.
                    self._pace_request("read")
                    response = retry.execute(num_retries=0)
                self.metrics["read_response_bytes"] += len(json.dumps(response, ensure_ascii=True).encode("utf-8"))
            else:
                response = request.execute()
            return response
        except Exception as exc:
            # Discard layout on ambiguous failures. The next attempt starts
            # from authoritative identities, including remotely applied rows.
            self._write_layout.clear()
            self._identity_hints.clear()
            self._compact_identity_hints.clear()
            self._metadata_cache = None
            self._header_cache.clear()
            suffix = (" No successful write is confirmed; resume the same keyed decision."
                      if action == "write" else " No spreadsheet changes were requested by this read.")
            raise (UncertainWriteError if action == "write" else RepositoryError)(
                f"Google Sheets {action} failed ({type(exc).__name__})." + suffix) from exc
        finally:
            self.metrics[action + "_seconds"] += time.monotonic() - started

    def _metadata(self):
        if self._metadata_cache is None:
            self._metadata_cache = self._execute(self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(sheetId,title,gridProperties),tables)",
            ), "read")
        return self._metadata_cache

    def _load(self, tabs, ranges_override=None):
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
            spreadsheetId=self.spreadsheet_id, ranges=ranges_override or ranges, includeGridData=True,
            fields=("sheets(properties(sheetId,title,gridProperties),tables,basicFilter,"
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
            if not (0 < grid.get("rowCount", 0) <= MAX_ROWS and 0 < grid.get("columnCount", 0) <= MAX_COLUMNS):
                raise RepositoryError(f"{tab}: grid exceeds safe bounds.")
            sheet = _Sheet([], sheet_id=props["sheetId"], row_count=grid["rowCount"],
                           column_count=grid["columnCount"],
                           tables=raw.get("tables", found[tab].get("tables", [])),
                           basic_filter=copy.deepcopy(raw.get("basicFilter")))
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
        for tab, sheet in loaded.items():
            self._header_cache[tab] = (list(sheet.headers),
                                       {header: index for index, header in enumerate(sheet.headers)})
        return loaded

    def _load_existing_commit(self, operations, *, use_hints=True):
        """Resolve existing identities, then read only their guarded/write cells.

        Cached identities only select target ranges; one fresh response still
        includes every identity and affected cell. Moved identities or layouts
        force a fresh discovery read before retrying. Inserts use the normal
        loader because sparse identity reads cannot establish a safe append tail.
        """
        tabs = sorted({op["tab"] for op in operations})
        if not hasattr(self.service.spreadsheets(), "values"):
            return self._load(tabs)
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        layouts, identity_fields, identity_ranges = {}, {}, []
        for tab in tabs:
            if tab not in found:
                raise RepositoryError(f"Missing tab: {tab}")
            headers = self._headers(tab)[0]
            rows = found[tab]["properties"]["gridProperties"]["rowCount"]
            escaped = tab.replace("'", "''")
            identities = set().union(*(set(op["identity"]) for op in operations if op["tab"] == tab))
            if tab == "Job History":
                identities.update({"Company", "Job Key", "Official Job URL"})
            if not identities <= set(headers):
                return self._load(tabs)
            layouts[tab] = (headers, rows)
            identity_fields[tab] = identities
            identity_ranges.append(f"'{escaped}'!1:1")
            for header in sorted(identities):
                col = _column_name(headers.index(header) + 1)
                if rows > 1:
                    identity_ranges.append(f"'{escaped}'!{col}2:{col}{rows}")
        cached = use_hints and all(
            tab in self._identity_hints
            and identity_fields[tab] <= self._identity_hints[tab][1]
            and self._identity_hints[tab][0].headers == layouts[tab][0]
            and self._identity_hints[tab][0].row_count == layouts[tab][1]
            for tab in tabs)
        if cached:
            initial = {tab: self._identity_hints[tab][0] for tab in tabs}
            indexes = {tab: self._identity_hints[tab][2] for tab in tabs}
        else:
            initial = self._load(tabs, identity_ranges)
            indexes = {}
        if any(initial[t].headers != layouts[t][0] or initial[t].row_count != layouts[t][1] for t in tabs):
            self._metadata_cache = None
            self._header_cache = {}
            self._write_layout.clear()
            return self._load(tabs)
        targets, cell_ranges, read_fields = {}, [], {}
        for tab, sheet in initial.items():
            index = indexes[tab] if cached else IdentityIndex(sheet.records())
            selected, fields = {}, set(identity_fields[tab])
            if tab == 'Job History':
                fields.update({'Added to Opportunities?', 'Review Status'})
            for op in operations:
                if op["tab"] != tab:
                    continue
                matches = index.matches(op["identity"])
                if len(matches) != 1:
                    if cached:
                        return self._load_existing_commit(operations, use_hints=False)
                    if not matches:
                        raise MissingIdentityError(tab, op["identity"])
                    detail = "matches multiple rows; refusing to guess" if matches else "does not exist; append is not authorized"
                    raise RepositoryError(f"{tab}: identity {detail}.")
                selected.update(matches)
                for group in ("values", "expected", "append_notes"):
                    fields.update(op.get(group, {}))
            if not fields <= set(sheet.headers):
                return self._load(tabs)
            targets[tab] = selected
            read_fields[tab] = fields
            columns = [sheet.headers.index(field) for field in fields]
            # Read only identities, guards and write destinations. Unrelated
            # columns between those fields need no cell metadata or values.
            spans = []
            for col in sorted(columns):
                if not spans or col != spans[-1][-1] + 1:
                    spans.append([])
                spans[-1].append(col)
            escaped = tab.replace("'", "''")
            row_groups = []
            for row in sorted(selected):
                if not row_groups or row != row_groups[-1][-1] + 1:
                    row_groups.append([])
                row_groups[-1].append(row)
            for group in row_groups:
                for span in spans:
                    cell_ranges.append(f"'{escaped}'!{_column_name(span[0]+1)}{group[0]+1}:{_column_name(span[-1]+1)}{group[-1]+1}")
        final = self._load(tabs, [*identity_ranges, *cell_ranges])
        if any(final[t].headers != initial[t].headers or final[t].row_count != initial[t].row_count for t in tabs):
            if cached:
                self._metadata_cache = None
                self._header_cache = {}
                return self._load_existing_commit(operations, use_hints=False)
            raise RepositoryError("Sheet layout changed while reading affected rows; replan from fresh rows.")
        for tab, selected in targets.items():
            sheet = final[tab]
            for row, previous in selected.items():
                for header in identity_fields[tab]:
                    current = _value(sheet.cells.get((row, sheet.headers.index(header)), {}), header)
                    if not _equivalent(header, current, previous.get(header, "")):
                        if cached:
                            return self._load_existing_commit(operations, use_hints=False)
                        raise RepositoryError(f"{tab}: identity or manual control moved while reading affected rows; replan from fresh rows.")
        self._targeted_existing_tabs = set(tabs)
        self._sparse_identity_fields = identity_fields
        self._committed_field_masks = read_fields
        return final

    def _compact_identities(self, layouts, identity_fields, *, checks=()):
        """Read plain, unformatted keys without per-cell grid metadata.

        URL identities retain the cell-aware loader, since displayed hyperlink
        labels cannot prove a canonical URL. Every optimized batch still gets
        a fresh complete key scan, including rows below previously cached tails.
        """
        ranges, specifications = [], []
        for tab, sheet in layouts.items():
            escaped = tab.replace("'", "''")
            ranges.append(f"'{escaped}'!1:1")
            specifications.append((tab, None))
            for header in sorted(identity_fields[tab]):
                col = _column_name(sheet.headers.index(header) + 1)
                ranges.append(f"'{escaped}'!{col}2:{col}")
                specifications.append((tab, header))
        for tab, r0, r1, c0, c1 in checks:
            escaped = tab.replace("'", "''")
            ranges.append(f"'{escaped}'!{_column_name(c0+1)}{r0+1}:{_column_name(c1+1)}{r1+1}")
            specifications.append((tab, (r0, r1, c0, c1)))
        response = self._execute(self.service.spreadsheets().values().batchGet(
            spreadsheetId=self.spreadsheet_id, ranges=ranges,
            majorDimension='ROWS', valueRenderOption='UNFORMATTED_VALUE'), 'read')
        values = response.get('valueRanges', [])
        if len(values) != len(specifications):
            raise RepositoryError('The server omitted identity ranges; no write is safe.')
        records = {tab: {} for tab in layouts}
        for (tab, header), column in zip(specifications, values):
            rows = column.get('values', [])
            if isinstance(header, tuple):
                r0, r1, c0, c1 = header
                for row in range(r0, r1 + 1):
                    observed = rows[row-r0] if row-r0 < len(rows) else []
                    for col in range(c0, c1 + 1):
                        field = layouts[tab].headers[col]
                        value = observed[col-c0] if col-c0 < len(observed) else ''
                        before = _value(layouts[tab].cells.get((row, col), {}), field)
                        if not _equivalent(field, before, value):
                            self._compact_identity_hints.clear()
                            raise ReviewFieldsChangedError(tab, {'row': row + 1})
                continue
            if header is None:
                if not rows or rows[0] != layouts[tab].headers:
                    self._metadata_cache = None
                    self._header_cache.clear()
                    self._compact_identity_hints.clear()
                    raise RepositoryError('Sheet headers changed during identity validation; retry fresh.')
                continue
            for row, cells in enumerate(rows, 1):
                value = cells[0] if cells else ''
                if value != '':
                    records[tab].setdefault(row, {})[header] = value
        return {tab: IdentityIndex(rows.items()) for tab, rows in records.items()}

    def _load_compact_existing_commit(self, operations, *, use_hints=True):
        """Use cached locations only to select a fresh, exact cell read.

        A following compact key scan must prove each selected identity is still
        unique at the same row. Changed locations trigger fresh discovery; all
        formulas, validations and manual guards come from the detailed read.
        """
        tabs = sorted({op['tab'] for op in operations})
        layouts, identity_fields = {}, {}
        metadata = self._metadata()
        found = {s['properties']['title']: s for s in metadata.get('sheets', [])}
        for tab in tabs:
            if tab not in found:
                raise RepositoryError(f'Missing tab: {tab}')
            props = found[tab]['properties']
            layouts[tab] = _Sheet(list(self._headers(tab)[0]), sheet_id=props['sheetId'],
                row_count=props['gridProperties']['rowCount'],
                column_count=props['gridProperties']['columnCount'])
            identity_fields[tab] = set().union(*(set(op['identity']) for op in operations if op['tab'] == tab))
        cached = use_hints and all(
            tab in self._compact_identity_hints
            and time.monotonic() - self._compact_identity_hints[tab][0] < 60
            and self._compact_identity_hints[tab][1].headers == layouts[tab].headers
            and identity_fields[tab] <= self._compact_identity_hints[tab][2]
            for tab in tabs)
        indexes = ({tab: self._compact_identity_hints[tab][3] for tab in tabs}
                   if cached else self._compact_identities(layouts, identity_fields))
        selected, ranges, read_fields, checks = {}, [], {}, []
        for tab in tabs:
            sheet = layouts[tab]
            fields = set(identity_fields[tab])
            if tab == 'Job History':
                fields.update({'Added to Opportunities?', 'Review Status'})
            selected[tab] = {}
            for op in operations:
                if op['tab'] != tab:
                    continue
                matches = indexes[tab].matches(op['identity'])
                if len(matches) != 1:
                    if cached:
                        return self._load_compact_existing_commit(operations, use_hints=False)
                    if not matches:
                        raise MissingIdentityError(tab, op['identity'])
                    raise RepositoryError(f'{tab}: identity matches multiple rows; refusing to guess.')
                selected[tab].update(matches)
                for group in ('values', 'expected', 'append_notes'):
                    fields.update(op.get(group, {}))
            if not fields <= set(sheet.headers):
                return self._load_existing_commit(operations, use_hints=False)
            read_fields[tab] = fields
            columns = sorted(sheet.headers.index(field) for field in fields)
            spans, row_groups = [], []
            for col in columns:
                if not spans or col != spans[-1][-1] + 1:
                    spans.append([])
                spans[-1].append(col)
            for row in sorted(selected[tab]):
                if not row_groups or row != row_groups[-1][-1] + 1:
                    row_groups.append([])
                row_groups[-1].append(row)
            escaped = tab.replace("'", "''")
            ranges.append(f"'{escaped}'!1:1")
            for rows in row_groups:
                for span in spans:
                    ranges.append(f"'{escaped}'!{_column_name(span[0]+1)}{rows[0]+1}:{_column_name(span[-1]+1)}{rows[-1]+1}")
                # Recheck scalar destinations/guards in the SAME compact
                # response as the final key scan. This catches edits made
                # while that request is in flight. URLs still use grid links.
                scalar_spans = []
                for col in columns:
                    if sheet.headers[col] in URL_HEADERS:
                        continue
                    if not scalar_spans or col != scalar_spans[-1][-1] + 1:
                        scalar_spans.append([])
                    scalar_spans[-1].append(col)
                for span in scalar_spans:
                    checks.append((tab, rows[0], rows[-1], span[0], span[-1]))
        final = self._load(tabs, ranges)
        if any(final[t].headers != layouts[t].headers or final[t].sheet_id != layouts[t].sheet_id
               or final[t].row_count != layouts[t].row_count for t in tabs):
            self._metadata_cache = None
            self._header_cache.clear()
            self._compact_identity_hints.clear()
            return self._load_existing_commit(operations, use_hints=False)
        fresh = self._compact_identities(final, identity_fields, checks=checks)
        for op in operations:
            tab = op['tab']
            before = indexes[tab].matches(op['identity'])
            after = fresh[tab].matches(op['identity'])
            if len(after) > 1:
                raise RepositoryError(f'{tab}: identity matches multiple rows; refusing to guess.')
            if [r for r, _ in before] != [r for r, _ in after]:
                self._compact_identity_hints.clear()
                if cached:
                    return self._load_compact_existing_commit(operations, use_hints=False)
                raise RepositoryError('Sheet identities moved during validation; retry fresh.')
        for tab, rows in selected.items():
            for row in rows:
                for header in identity_fields[tab]:
                    actual = _value(final[tab].cells.get((row, final[tab].headers.index(header)), {}), header)
                    if not _equivalent(header, actual, fresh[tab].rows[row].get(header, '')):
                        self._compact_identity_hints.clear()
                        if cached:
                            return self._load_compact_existing_commit(operations, use_hints=False)
                        raise RepositoryError('Sheet identity changed while reading guarded cells; retry fresh.')
            self._compact_identity_hints[tab] = (time.monotonic(), final[tab], identity_fields[tab], fresh[tab])
        self._targeted_existing_tabs = set(tabs)
        # Only affected rows enter _prepare and acknowledgement processing.
        # The compact index above already proved global identity uniqueness.
        self._sparse_identity_fields = {}
        self._committed_field_masks = read_fields
        return final

    def _load_commit(self, operations):
        """Read fresh identities and only the rows needed by this commit."""
        tabs = sorted({op["tab"] for op in operations})
        if (set(tabs) <= {'Job History', 'Opportunities', 'Companies'}
                and hasattr(self.service.spreadsheets(), 'values')
                and all(not op.get('append_if_missing') and not (set(op['identity']) & URL_HEADERS)
                        for op in operations)):
            return self._load_compact_existing_commit(operations)
        if set(tabs) <= {"Job History", "Opportunities", "Companies"} and all(not op.get("append_if_missing") for op in operations):
            return self._load_existing_commit(operations)
        if not hasattr(self.service.spreadsheets(), "values"):
            return self._load(tabs)
        return self._load_sparse_commit(operations)

    def _load_sparse_commit(self, operations):
        """Keep descriptions out of unrelated reads, including evidence upserts.

        The first read locates identities. The final read repeats that scan and
        loads complete affected rows, preserving cell guards and the planning
        cache's untouched fields. Appends additionally inspect the unused tail
        for orphan values/formulas and destination validation.
        """
        tabs = sorted({op["tab"] for op in operations})
        by_tab = {tab: [op for op in operations if op["tab"] == tab] for tab in tabs}
        identity_fields = {}
        for tab, tab_ops in by_tab.items():
            fields = set().union(*(set(op["identity"]) for op in tab_ops))
            if tab == "Job History":
                fields.update({"Company", "Job Key", "Official Job URL"})
            identity_fields[tab] = fields

        def identity_ranges_for(layouts):
            identity_ranges = []
            for tab in tabs:
                headers = layouts[tab]
                if not identity_fields[tab] <= set(headers):
                    raise RepositoryError(f"{tab}: unknown identity fields.")
                escaped = tab.replace("'", "''")
                identity_ranges.append(f"'{escaped}'!1:1")
                for header in sorted(identity_fields[tab]):
                    col = _column_name(headers.index(header) + 1)
                    # Do not stop at a cached tail: newly added identities and
                    # duplicates must participate in the fresh identity check.
                    identity_ranges.append(f"'{escaped}'!{col}2:{col}")
            return identity_ranges

        def select_rows(sheets, indexes):
            match_rows, floors, row_ranges = [], {}, []
            for tab, sheet in sheets.items():
                index = indexes[tab]
                selected = set()
                needs_append = False
                for op in by_tab[tab]:
                    rows = tuple(row for row, _ in index.matches(op["identity"]))
                    match_rows.append((tab, op["identity"], rows))
                    selected.update(rows)
                    # _prepare resolves sequential operations, including an
                    # insert followed by an update to that same new identity.
                    needs_append |= not rows and bool(op.get("append_if_missing"))
                escaped = tab.replace("'", "''")
                end = _column_name(sheet.column_count)
                groups = []
                for row in sorted(selected):
                    if not groups or row != groups[-1][-1] + 1:
                        groups.append([])
                    groups[-1].append(row)
                for group in groups:
                    row_ranges.append(f"'{escaped}'!A{group[0]+1}:{end}{group[-1]+1}")
                if needs_append:
                    floor = max(index.rows, default=0)
                    floors[tab] = floor
                    if floor + 1 < sheet.row_count:
                        row_ranges.append(f"'{escaped}'!A{floor+2}:{end}{sheet.row_count}")
            return match_rows, floors, row_ranges

        def unchanged(sheets, final, match_rows):
            for tab, before in sheets.items():
                after = final[tab]
                if (after.headers != before.headers or after.row_count != before.row_count
                        or after.column_count != before.column_count or after.sheet_id != before.sheet_id):
                    return False
            indexes = {tab: IdentityIndex(sheet.records()) for tab, sheet in final.items()}
            return all(tuple(row for row, _ in indexes[tab].matches(identity)) == rows
                       for tab, identity, rows in match_rows)

        def finish(final, floors):
            for tab, sheet in final.items():
                sheet.append_floor = floors.get(tab, 0)
            # Existing-only reads do not establish an append tail.
            self._targeted_existing_tabs.update(set(tabs) - set(floors))
            self._sparse_identity_fields = identity_fields
            return final

        layouts = {tab: self._headers(tab)[0] for tab in tabs}
        identity_ranges = identity_ranges_for(layouts)
        initial = None
        if all(tab in self._identity_hints
               and identity_fields[tab] <= self._identity_hints[tab][1]
               and layouts[tab] == self._identity_hints[tab][0].headers for tab in tabs):
            hints = {tab: self._identity_hints[tab][0] for tab in tabs}
            indexes = {tab: self._identity_hints[tab][2] for tab in tabs}
            match_rows, floors, row_ranges = select_rows(hints, indexes)
            initial = self._load(tabs, [*identity_ranges, *row_ranges])
            if unchanged(hints, initial, match_rows):
                # Cached locations selected ranges; all values, identities,
                # formulas and validation now come from one fresh response.
                return finish(initial, floors)

        # A reordered header triggers one rescan using the freshly validated
        # header. Changed cached locations reuse the response as discovery data.
        for attempt in range(2):
            if initial is None:
                initial = self._load(tabs, identity_ranges)
            if all(initial[tab].headers == layouts[tab] for tab in tabs):
                break
            layouts = {tab: initial[tab].headers for tab in tabs}
            identity_ranges = identity_ranges_for(layouts)
            initial = None
        else:
            raise RepositoryError("Sheet headers changed while resolving identities; replan from fresh rows.")
        indexes = {tab: IdentityIndex(sheet.records()) for tab, sheet in initial.items()}
        match_rows, floors, row_ranges = select_rows(initial, indexes)
        final = self._load(tabs, [*identity_ranges, *row_ranges])
        if not unchanged(initial, final, match_rows):
            raise RepositoryError("Sheet layout or identity moved or changed while reading affected rows; replan from fresh rows.")
        return finish(final, floors)

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
        value_ranges = result.get("valueRanges", [])
        if len(value_ranges) != len(headers):
            raise RepositoryError("The server omitted a requested value column; no blank edits were inferred.")
        columns = []
        for value_range in value_ranges:
            raw = value_range.get("values", [])
            columns.append([row[0] if row else "" for row in raw])
        max_len = max((len(c) for c in columns), default=0)
        records = []
        for offset in range(max_len):
            values = {header: (columns[i][offset] if offset < len(columns[i]) else "")
                      for i, header in enumerate(headers)}
            if any(value != "" for value in values.values()):
                records.append((offset + 2, values))
        if records:
            self._write_layout[tab] = (list(live_headers), max(row_number - 1 for row_number, _ in records))
        return records

    def read_cached_columns(self, tab, headers):
        """Read value columns using layout learned from the planning snapshot."""
        _tab(tab)
        if tab not in self._write_layout:
            return self.read_columns(tab, headers)
        live_headers = self._write_layout[tab][0]
        mapping = {header: index for index, header in enumerate(live_headers)}
        missing = [h for h in headers if h not in mapping]
        if missing:
            raise RepositoryError(f"{tab}: missing requested headers: {', '.join(missing)}")
        row_count = max(2, self._write_layout[tab][1] + 1)
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
        value_ranges = result.get("valueRanges", [])
        if len(value_ranges) != len(headers):
            raise RepositoryError("The server omitted a requested value column; no blank edits were inferred.")
        columns = []
        for value_range in value_ranges:
            raw = value_range.get("values", [])
            columns.append([row[0] if row else "" for row in raw])
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

    def read_rows(self, tab, row_numbers):
        """Read exact native rows as plain values in batches of at most 100.

        Blank and trailing cells are retained as empty strings. These values
        support review planning; commits still reread guarded cells themselves.
        """
        _tab(tab)
        row_numbers = list(row_numbers)
        if any(type(row) is not int or row < 2 for row in row_numbers):
            raise RepositoryError("Data row numbers are 1-based integers and must be >= 2.")
        row_numbers = list(dict.fromkeys(row_numbers))
        if not row_numbers:
            return {}
        headers, _ = self._headers(tab)
        metadata = self._metadata()
        found = {sheet["properties"]["title"]: sheet for sheet in metadata.get("sheets", [])}
        row_count = found[tab]["properties"].get("gridProperties", {}).get("rowCount", 0)
        if not 0 < row_count <= MAX_ROWS:
            raise RepositoryError(f"{tab}: invalid row count.")
        if any(row > row_count for row in row_numbers):
            raise RepositoryError(f"Data row numbers must be within the {row_count}-row grid.")
        escaped = tab.replace(chr(39), chr(39)*2)
        end = _column_name(len(headers))
        records = {}
        for offset in range(0, len(row_numbers), 100):
            batch = row_numbers[offset:offset + 100]
            result = self._execute(
                self.service.spreadsheets().values().batchGet(
                    spreadsheetId=self.spreadsheet_id,
                    ranges=[f"'{escaped}'!A{row}:{end}{row}" for row in batch],
                    majorDimension="ROWS",
                ),
                "read",
            )
            value_ranges = result.get("valueRanges", [])
            if len(value_ranges) != len(batch):
                raise RepositoryError("The server omitted a requested data row.")
            for row, value_range in zip(batch, value_ranges):
                values = (value_range.get("values") or [[]])[0]
                records[row] = {header: values[index] if index < len(values) else ""
                                for index, header in enumerate(headers)}
        return records

    def read(self, tab):
        sheet = self._load([tab])[tab]
        return [values for _, values in sheet.records()]

    def read_many(self, tabs):
        rows = {}
        for tab, sheet in self._load(tabs).items():
            records = sheet.records()
            rows[tab] = [values for _, values in records]
            # The initial planning snapshot already established this tail.
            # Reuse only layout information; the next write rereads identities
            # and the tail, never trusting cached contents as write authority.
            self._write_layout[tab] = (list(sheet.headers), max([0, *[r for r, _ in records]]))
        return rows

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


    def ensure_tab(self, tab):
        _tab(tab)
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        if tab in found:
            return {"created": False, "added_headers": self.ensure_columns(tab, self.schemas[tab])}
        used = {s["properties"].get("sheetId", 0) for s in metadata.get("sheets", [])}
        sheet_id = max(used or {0}) + 1
        while sheet_id in used:
            sheet_id += 1
        headers = self.schemas[tab]
        requests = [
            {"addSheet": {"properties": {"sheetId": sheet_id, "title": tab,
                "gridProperties": {"rowCount": 1000, "columnCount": max(len(headers), 1)}}}},
            {"updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                "rows": [{"values": [{"userEnteredValue": _encoded(header)} for header in headers]}],
                "fields": "userEnteredValue",
            }},
        ]
        payload = {"requests": requests}
        self.metrics["write_payload_bytes"] += len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
        self._execute(self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=payload,
        ), "write")
        self._metadata_cache = None
        self._header_cache.pop(tab, None)
        self._write_layout.clear()
        return {"created": True, "added_headers": list(headers)}

    def ensure_columns(self, tab, headers):
        _tab(tab)
        headers = [str(header).strip() for header in headers if str(header).strip()]
        if not headers:
            return []
        live, mapping = self._headers(tab)
        missing = [header for header in headers if header not in mapping]
        if not missing:
            return []
        if len(live) + len(missing) > MAX_COLUMNS:
            raise RepositoryError(f"{tab}: adding columns would exceed the safe column limit.")
        metadata = self._metadata()
        found = {s["properties"]["title"]: s for s in metadata.get("sheets", [])}
        if tab not in found:
            raise RepositoryError(f"Missing tab: {tab}")
        sheet_id = found[tab]["properties"]["sheetId"]
        start_col = len(live)
        requests = [{"updateCells": {
            "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": start_col},
            "rows": [{"values": [{"userEnteredValue": _encoded(header)} for header in missing]}],
            "fields": "userEnteredValue",
        }}]
        capacity = found[tab]['properties'].get('gridProperties', {}).get('columnCount', 0)
        if capacity < start_col + len(missing):
            requests.insert(0, {'appendDimension': {
                'sheetId': sheet_id, 'dimension': 'COLUMNS',
                'length': start_col + len(missing) - capacity}})
        payload = {"requests": requests}
        self.metrics["write_payload_bytes"] += len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
        self._execute(self.service.spreadsheets().batchUpdate(
            spreadsheetId=self.spreadsheet_id, body=payload,
        ), "write")
        self._metadata_cache = None
        self._header_cache.pop(tab, None)
        self._write_layout.clear()
        return missing

    def commit(self, operations):
        # Include identity/layout reads and request construction in the proven
        # pre-write boundary. Once a write starts, failures retain receipts.
        before = self.metrics["write_requests"]
        try:
            return self._commit(operations)
        except RepositoryError as exc:
            if (not isinstance(exc, (PreflightWriteError, UncertainWriteError))
                    and self.metrics["write_requests"] == before):
                raise PreflightWriteError(str(exc)) from exc
            raise

    def _commit(self, operations):
        timings = {}
        commit_started = time.monotonic()
        if self.spreadsheet_id == PROTECTED_BACKUP_ID:
            raise RepositoryError("Refusing to write the protected Job Search Master - Original backup.")
        operations = list(operations)
        self._committed_rows = {}
        self._committed_field_masks = {}
        self._targeted_existing_tabs = set()
        self._sparse_identity_fields = {}
        if not operations:
            return {"inserted": 0, "updated": 0, "requests": 0}
        for operation in operations:
            if not isinstance(operation, dict):
                raise RepositoryError("Each operation must be a mapping.")
            _tab(operation.get("tab"))
        load_started = time.monotonic()
        metrics_before = dict(self.metrics)
        sheets = self._load_commit(operations)
        timings["sheets_load_seconds"] = time.monotonic() - load_started
        prepare_started = time.monotonic()
        try:
            changed, new_rows, result = _prepare(sheets, self.schemas, operations)
        finally:
            timings["prepare_seconds"] = time.monotonic() - prepare_started
            self.metrics["prepare_seconds"] += timings["prepare_seconds"]
        build_started = time.monotonic()
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
        # Existing rows: contiguous changed spans only (never blank holes).
        # New rows: rectangular blocks of just populated spans, batched across
        # consecutive rows with identical columns. Explicit addresses allow
        # validation at the exact destination and keyed replay after timeouts.
        spans = {}
        for (tab, row, col), value in sorted(changed.items()):
            spans.setdefault((tab, row), []).append((col, value))
        blocks = []
        for (tab, row), cells in spans.items():
            groups = []
            for col, value in cells:
                if not groups or col != groups[-1][-1][0] + 1:
                    groups.append([])
                groups[-1].append((col, value))
            for group in groups:
                col = group[0][0]
                values = [{"userEnteredValue": value} for _, value in group]
                # Merge inserts vertically; updates retain precise changed spans.
                previous = next((b for b in reversed(blocks)
                    if (tab, row) in new_rows and b["new"] and b["tab"] == tab
                    and b["col"] == col and b["row"] + len(b["rows"]) == row
                    and len(b["rows"][0]["values"]) == len(values)), None)
                if previous is not None:
                    previous["rows"].append({"values": values})
                else:
                    blocks.append({"tab": tab, "row": row, "col": col,
                                   "new": (tab, row) in new_rows, "rows": [{"values": values}]})
        for block in blocks:
            requests.append({"updateCells": {
                "start": {"sheetId": sheets[block["tab"]].sheet_id,
                          "rowIndex": block["row"], "columnIndex": block["col"]},
                "rows": block["rows"], "fields": "userEnteredValue"}})
        # API cell edits do not always refresh the visible basic filter. Reapply
        # only the existing filter from this commit's fresh grid read, preserving
        # all criteria, bounds, and sort settings; never create a new filter.
        history = sheets.get("Job History")
        if history and history.basic_filter and any(
                tab == "Job History" and history.headers[col] in {"Added to Opportunities?", "Review Status"}
                for tab, _, col in changed):
            requests.append({"setBasicFilter": {"filter": copy.deepcopy(history.basic_filter)}})
        timings["build_requests_seconds"] = time.monotonic() - build_started
        self.metrics["build_requests_seconds"] += timings["build_requests_seconds"]
        structural = False
        if requests:
            payload_started = time.monotonic()
            payload_bytes = len(json.dumps({"requests": requests}, ensure_ascii=True).encode("utf-8"))
            timings["payload_seconds"] = time.monotonic() - payload_started
            timings["payload_bytes"] = payload_bytes
            if payload_bytes > MAX_BATCH_UPDATE_BYTES:
                raise BatchPayloadTooLarge(f"Planned batch exceeds the {MAX_BATCH_UPDATE_MB_LABEL} safety threshold. No write attempted; resume with --batch-size 25 (or 5).")
            structural = any(set(req) & {"appendDimension", "updateTable", "insertDimension", "deleteDimension"}
                             for req in requests)
            # No automatic retry of writes: after a timeout, rerun the same keyed
            # decision so it is resolved against the authoritative fresh sheet.
            self.metrics["write_payload_bytes"] += payload_bytes
            write_started = time.monotonic()
            self._execute(self.service.spreadsheets().batchUpdate(
                spreadsheetId=self.spreadsheet_id, body={"requests": requests},
            ), "write")
            timings["sheets_write_seconds"] = time.monotonic() - write_started
            if structural:
                self._metadata_cache = None
                self._header_cache = {}
                self._identity_hints.clear()
                self._compact_identity_hints.clear()
            else:
                for tab, _, col in changed:
                    hint = self._compact_identity_hints.get(tab)
                    if hint and sheets[tab].headers[col] in hint[2]:
                        self._compact_identity_hints.pop(tab, None)
        committed_started = time.monotonic()
        self._committed_partial = True
        self._committed_rows = {}
        for tab, sheet in sheets.items():
            records = sheet.records()
            fields = self._sparse_identity_fields.get(tab)
            if fields and not structural:
                # Cache locations/identity values only; never cached cell data
                # as authority for a later write.
                layout = _Sheet(list(sheet.headers), sheet_id=sheet.sheet_id,
                                row_count=sheet.row_count, column_count=sheet.column_count)
                identities = ((row, {field: values[field] for field in fields})
                              for row, values in records if any(values[field] != "" for field in fields))
                self._identity_hints[tab] = (layout, set(fields), IdentityIndex(identities))
            else:
                self._identity_hints.pop(tab, None)
            if tab in self._targeted_existing_tabs:
                # This read did not inspect arbitrary orphan cells below the last
                # identity; a later append must rediscover its destination fully.
                self._write_layout.pop(tab, None)
            else:
                self._write_layout[tab] = (list(sheet.headers), max([sheet.append_floor, 0, *[r for r, _ in records]]))
            index = IdentityIndex(records)
            touched = {}
            for op in operations:
                if op["tab"] == tab:
                    touched.update(index.matches(op["identity"]))
            self._committed_rows[tab] = list(touched.values())
        timings.update({key: self.metrics[key] - metrics_before[key] for key in self.metrics})
        timings["committed_rows_seconds"] = time.monotonic() - committed_started
        timings["commit_total_seconds"] = time.monotonic() - commit_started
        return {**result, "requests": len(requests), "timings": timings}

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
            fields="sheets(data(startRow,startColumn,rowData(values(userEnteredValue,effectiveValue,dataValidation))))",
        ), "read")
        cells = {}
        for raw_sheet in cell_data.get("sheets", []):
            for block in raw_sheet.get("data", []):
                start = block.get("startRow", 1)
                for offset, raw_row in enumerate(block.get("rowData", [])):
                    values = raw_row.get("values", [])
                    cells[start + offset] = values[0] if values else {}

        requests = []
        allowed_keys = {"tab", "row_number", "identity", "values", "expected"}
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
            expected = operation["expected"]
            if not isinstance(expected, dict) or set(expected) != {"Added to Opportunities?"}:
                raise RepositoryError("Blacklist cleanup requires the observed opportunity choice.")
            _scalar(expected["Added to Opportunities?"])
            cell = cells.get(row_number - 1, {})
            if cell.get("userEnteredValue", {}).get("formulaValue"):
                raise RepositoryError("Refusing to replace a formula in Added to Opportunities?.")
            latest = _value(cell, "Added to Opportunities?")
            if str(latest).strip().casefold() == "no":
                continue  # A repeated delivery is already applied.
            if any(not _equivalent("Added to Opportunities?", value, expected["Added to Opportunities?"])
                   for value in (current.get("Added to Opportunities?", ""), latest)):
                raise ReviewFieldsChangedError("Job History", identity)
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


_OAUTH_SCOPES = {
    False: "https://www.googleapis.com/auth/spreadsheets.readonly",
    True: "https://www.googleapis.com/auth/spreadsheets",
}


def _needs_google_sign_in(error):
    """Recognize permanent grant failures without displaying OAuth responses."""
    if getattr(error, "retryable", False):
        return False
    for detail in error.args:
        if isinstance(detail, dict):
            code = detail.get("error")
        elif isinstance(detail, str):
            code = detail.partition(":")[0]
            if detail.startswith("{"):
                try:
                    response = json.loads(detail)
                    code = response.get("error") if isinstance(response, dict) else None
                except (TypeError, ValueError):
                    pass
        else:
            continue
        if code in ("invalid_grant", "invalid_scope"):
            return True
    return False


class _OAuthSession:
    """Keep independently scoped credentials valid throughout a scraper run."""

    def __init__(self, write=False, interactive=False, renew_both=False):
        try:
            from google.auth.exceptions import RefreshError
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_httplib2 import AuthorizedHttp
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.http import build_http
        except ImportError as exc:
            raise RepositoryError("Google support is not installed. Run: .venv/bin/python3.11 -m pip install -e '.[google]'") from exc
        self.refresh_error = RefreshError
        self._request = Request
        self._credential_type = Credentials
        self._flow_type = InstalledAppFlow
        self._authorized_http = AuthorizedHttp
        self._build = build
        self._build_http = build_http
        self.write = bool(write)
        self.interactive = interactive
        self.renew_both = renew_both
        self.modes = (False, True) if renew_both else (self.write,)
        self.lock = threading.RLock()
        self.credentials_path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")).expanduser().resolve()
        self.paths = {}
        for mode, setting, default in (
            (False, "GOOGLE_TOKEN_READ_FILE", ".secrets/token-readonly.json"),
            (True, "GOOGLE_TOKEN_WRITE_FILE", ".secrets/token-write.json"),
        ):
            raw = Path(os.getenv(setting, default)).expanduser()
            if raw.is_symlink() or raw.parent.is_symlink():
                raise RepositoryError("OAuth token paths must not be symlinks.")
            self.paths[mode] = raw.resolve()
        if self.paths[False] == self.paths[True]:
            raise RepositoryError("Read-only and write credentials require different token files.")
        # Validate every selected file before refreshing or replacing either one.
        self.credentials = {mode: self._load(mode) for mode in self.modes}
        self._saved = {mode: self._fingerprint(self.credentials[mode]) for mode in self.modes}

    @staticmethod
    def _fingerprint(credentials):
        if credentials is None:
            return None
        return (credentials.token, credentials.refresh_token, credentials.expiry)

    def _load(self, write):
        path = self.paths[write]
        if not path.exists():
            return None
        if path.stat().st_mode & 0o077:
            raise RepositoryError(f"Token permissions must be 0600; correct the permissions of {path}.")
        with path.open(encoding="utf-8") as handle:
            saved = json.load(handle)
        if set(saved.get("scopes", [])) != {_OAUTH_SCOPES[write]}:
            if self.interactive:
                return None
            raise RepositoryError("Saved token scopes do not exactly match this command; reauthenticate with a separate token.")
        return self._credential_type.from_authorized_user_info(saved, [_OAUTH_SCOPES[write]])

    @staticmethod
    def _validate_grant(credentials, write):
        granted = getattr(credentials, "granted_scopes", None)
        if granted is not None and _OAUTH_SCOPES[write] not in granted:
            raise RepositoryError("Google did not grant the requested Sheets permission; authorize the requested access.")
        if not credentials.valid or not credentials.refresh_token:
            raise RepositoryError("Google did not return valid offline credentials; run ./job-search-scraper auth again.")

    def _sign_in(self, write):
        if not self.interactive:
            raise RepositoryError("No valid token is available; run ./job-search-scraper auth first.")
        if not self.credentials_path.is_file():
            raise RepositoryError("Google Desktop OAuth credentials.json is missing; configure GOOGLE_CREDENTIALS_FILE.")
        label = "write" if write else "read-only"
        print(f"Google {label} authorization needs sign-in. Complete the browser authorization to continue.",
              file=sys.stderr, flush=True)
        flow = self._flow_type.from_client_secrets_file(str(self.credentials_path), [_OAUTH_SCOPES[write]])
        # Explicit consent obtains a replacement refresh token, including when a
        # previous grant exists but its refresh token has expired or been revoked.
        credentials = flow.run_local_server(
            host="localhost", port=0, open_browser=True,
            access_type="offline", prompt="consent",
        )
        self._validate_grant(credentials, write)
        return credentials

    def _save_if_changed(self, write):
        credentials = self.credentials[write]
        fingerprint = self._fingerprint(credentials)
        if fingerprint == self._saved[write]:
            return
        serialized = credentials.to_json()
        if set(json.loads(serialized).get("scopes", [])) != {_OAUTH_SCOPES[write]}:
            raise RepositoryError("Refusing to save a credential with mismatched Sheets scopes.")
        path = self.paths[write]
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Never chmod the user's home or arbitrary existing broad directory.
        if path.parent.stat().st_mode & 0o077:
            raise RepositoryError("Token parent directory must already have private 0700 permissions.")
        fd, temporary = tempfile.mkstemp(prefix="token-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            self._saved[write] = fingerprint
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def ensure_valid(self, force=False):
        with self.lock:
            # A scraper session renews the pair when either credential expires.
            # Standalone read commands continue to use only read-only access.
            renew = force or (self.renew_both and any(
                credential is None or not credential.valid
                for credential in self.credentials.values()
            ))
            for mode in self.modes:
                credentials = self.credentials[mode]
                if renew or credentials is None or not credentials.valid:
                    if credentials is not None and credentials.refresh_token:
                        try:
                            credentials.refresh(self._request())
                        except self.refresh_error as exc:
                            # A network/server/client-configuration failure is
                            # not evidence that consent needs to be replaced.
                            if not self.interactive or not _needs_google_sign_in(exc):
                                raise
                            credentials = self._sign_in(mode)
                    else:
                        credentials = self._sign_in(mode)
                    self._validate_grant(credentials, mode)
                    self.credentials[mode] = credentials
                self._save_if_changed(mode)

    def save_changed(self):
        for mode in self.modes:
            self._save_if_changed(mode)


class _RenewingGoogleHttp:
    """Recover only credential failures in Google's authorized HTTP transport."""

    def __init__(self, authorization):
        self._authorization = authorization
        self._http = authorization._authorized_http(
            authorization.credentials[authorization.write], http=authorization._build_http(),
        )

    def __getattr__(self, name):
        return getattr(self._http, name)

    def request(self, *args, **kwargs):
        authorization = self._authorization
        with authorization.lock:
            # Refresh and persist both credentials before sending Sheets changes.
            authorization.ensure_valid()
            self._http.credentials = authorization.credentials[authorization.write]
            try:
                response = self._http.request(*args, **kwargs)
            except authorization.refresh_error as exc:
                if not _needs_google_sign_in(exc):
                    raise
                # AuthorizedHttp refreshes before transmission or following an
                # HTTP 401 rejection. An expired/revoked grant can therefore be
                # recovered here without replaying an acknowledged Sheets write.
                # The exact request is attempted once more; transport failures,
                # timeouts and other uncertain write failures still propagate.
                authorization.ensure_valid(force=True)
                self._http.credentials = authorization.credentials[authorization.write]
                response = self._http.request(*args, **kwargs)
            # Google's own 401 refresh can succeed even before local expiry.
            authorization.save_changed()
            return response


def _authorize(write=False, interactive=False, renew_both=False):
    """Refresh selected credentials; scraper sessions maintain both token files."""
    authorization = _OAuthSession(write=write, interactive=interactive, renew_both=renew_both)
    authorization.ensure_valid()
    return authorization._build("sheets", "v4", http=_RenewingGoogleHttp(authorization), cache_discovery=False)


def authorize(write=False, interactive=False, renew_both=False):
    try:
        if renew_both:
            return _authorize(write=write, interactive=interactive, renew_both=True)
        return _authorize(write=write, interactive=interactive)
    except RepositoryError:
        raise
    except Exception as exc:
        raise RepositoryError(
            f"Google authentication failed ({type(exc).__name__}); check the local OAuth setup. "
            "No credential contents have been displayed."
        ) from exc


build_service = authorize
