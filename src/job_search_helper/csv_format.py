"""Versioned CSV text protection and verified reversal for company import."""
from __future__ import annotations

import hashlib
import json
import unicodedata


EXPORT_FORMAT = "local-csv-v1"
ESCAPE_VERSION = "text-prefix-v1"
TEXT_PREFIX = "text: "


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def escape_cell(value) -> tuple[str, bool]:
    text = "" if value is None else str(value)
    normalized = unicodedata.normalize("NFKC", text)
    if not normalized:
        return text, False
    unsafe = unicodedata.category(normalized[0]).startswith("C") or normalized[0] in "\t\r\n"
    start = normalized.lstrip()
    while start and unicodedata.category(start[0]).startswith("C"):
        unsafe = True
        start = start[1:].lstrip()
    unsafe = unsafe or bool(start and start[0] in "=+-@\u2212\u2010\u2011\u2012\u2013\u2014")
    return (TEXT_PREFIX + text, True) if unsafe else (text, False)


def restore_company_cells(path, data: bytes, headers: list[str], rows) -> bool:
    """Decode only a complete, unchanged export with verified cell checksums."""
    manifest_path = path.parent / "manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (manifest["format_version"] != EXPORT_FORMAT or manifest["escape_rule"]["version"] != ESCAPE_VERSION
                or manifest["escape_rule"]["prefix"] != TEXT_PREFIX):
            raise ValueError("Unsupported export manifest version")
        files = [item for item in manifest["files"] if item["name"] == path.name]
        if len(files) != 1 or files[0]["kind"] != "companies":
            raise ValueError("File is not the Companies CSV recorded in this export")
        entry = files[0]
        if entry["sha256"] != hashlib.sha256(data).hexdigest():
            raise ValueError("Export file changed; re-import the unchanged bundle or prepare a separate plain company CSV")
        if entry["columns"] != headers or entry["rows"] != len(rows):
            raise ValueError("Export headings or row count do not match the manifest")
        seen = set()
        for cell in entry["escaped_cells"]:
            row, column = cell["row"], cell["column"]
            if type(row) is not int or not 2 <= row < len(rows) + 2 or column not in headers or (row, column) in seen:
                raise ValueError("Invalid escaped-cell position")
            seen.add((row, column))
            values = rows[row - 2][1]
            exported = values[column]
            if not exported.startswith(TEXT_PREFIX) or text_hash(exported) != cell["exported_sha256"]:
                raise ValueError("Escaped-cell checksum mismatch")
            original = exported[len(TEXT_PREFIX):]
            if text_hash(original) != cell["original_sha256"]:
                raise ValueError("Original-cell checksum mismatch")
            values[column] = original
        return True
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ValueError(f"Invalid export manifest: {exc}") from exc
