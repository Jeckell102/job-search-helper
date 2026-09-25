"""Preview and atomically import company CSVs with explicit field ownership."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import hashlib
import io
from pathlib import Path
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit

from .ats import FetchError, is_board_host, resolve_board
from .posting import canonicalize_url
from .csv_format import restore_company_cells
from .discovery import public_careers_url
from .models import COMPANY_STATUSES, SourceScope, canonical_json, new_id, utc_now
from .repositories import CatalogRepository
from .taleo_careers import supports_scoped_taleo_careers


FORMAT_VERSION = "companies-csv-v1"
CLEAR_VALUE = "[clear]"
FIELDS = {"Company Name": "company_name", "Status": "status", "Website": "website_url", "Category": "category",
          "Technology / Focus": "technology_focus", "Priority": "priority", "Notes": "notes", "Why It Fits": "personal_rationale"}
COMPUTED = {"Last Successful Scan", "Last Scan", "Last Scan Result", "Updated At", "Created At",
            "Blocked / Error Reason", "Next Action", "Jobs Found In Last Scan", "Source ID"}
HEADERS = set(FIELDS) | COMPUTED | {"Company ID", "Careers URL", "ATS Type"}
PROVIDERS = {"greenhouse", "lever", "ashby", "workday", "icims", "adp", "paylocity", "taleo", "unknown"}


@dataclass(frozen=True)
class SourceDefinition:
    provider: str
    namespace: str
    scope_key: str
    careers_url: str
    supported: bool


def source_definition(url: str, provider: str = "") -> SourceDefinition:
    try:
        url = canonicalize_url(public_careers_url(url.strip()))
    except (FetchError, ValueError) as exc:
        raise ValueError("Careers URL must be a public HTTPS URL without credentials") from exc
    hint = provider.strip().casefold()
    if hint and hint not in PROVIDERS:
        raise ValueError("ATS Type must name a supported provider or unknown")
    if supports_scoped_taleo_careers(hint if hint != "unknown" else "", url):
        return SourceDefinition("taleo", url, url, url, True)
    try:
        name, board, root = resolve_board("" if hint == "unknown" else hint, url)
    except ValueError:
        if is_board_host(urlsplit(url).hostname):
            raise
        return SourceDefinition(hint or "unknown", "url:" + url, url, url, False)
    if name == "ADP":
        identity = {key: value for key, value in parse_qsl(board) if key in {"cid", "ccId"}}
        namespace = root + urlencode(sorted(identity.items()))
    else:
        namespace = root + board.partition("?")[0]
    return SourceDefinition(name.casefold(), namespace, root + board, url, True)


def _name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _read(path: Path):
    with path.open("rb") as handle:
        data = handle.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Company CSV exceeds 16 MiB")
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    try:
        headers = next(reader, [])
        if len(headers) != len(set(headers)):
            raise ValueError("Line 1: duplicate column headings")
        if not {"Company Name", "Careers URL"} <= set(headers):
            raise ValueError("Line 1: Company Name and Careers URL are required")
        if set(headers) - HEADERS:
            raise ValueError("Line 1: unsupported columns: " + ", ".join(sorted(set(headers) - HEADERS)))
        rows = []
        while True:
            line = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values or not any(value.strip() for value in values):
                continue
            if len(values) != len(headers):
                raise ValueError(f"Line {line}: expected {len(headers)} cells, found {len(values)}")
            rows.append((line, dict(zip(headers, values))))
    except csv.Error as exc:
        raise ValueError(f"Line {reader.line_num}: invalid CSV: {exc}") from exc
    literal = restore_company_cells(path, data, headers, rows)
    if not rows and not literal:
        raise ValueError("Company CSV has no data rows")
    return rows, hashlib.sha256(data).hexdigest(), sorted(set(headers) & COMPUTED), literal


class CompanyImporter:
    def __init__(self, database):
        self.database = database
        self.connection = database.connection
        self.catalog = CatalogRepository(database)

    def preview(self, path: Path, *, preserve_ids=False) -> dict:
        rows, digest, ignored, literal = _read(path)
        with self.database.transaction(immediate=False):
            return self._plan(rows, digest, ignored, preserve_ids, literal)

    def apply(self, path: Path, *, preserve_ids=False) -> dict:
        rows, digest, ignored, literal = _read(path)
        with self.database.transaction():
            plan = self._plan(rows, digest, ignored, preserve_ids, literal)
            if not plan["ok"]:
                return plan
            plan["applied"] = True
            if not plan["counts"]["add"] and not plan["counts"]["update"]:
                return plan
            import_id, stamp = new_id(), utc_now()
            self.connection.execute("INSERT INTO import_batches VALUES (?, ?, ?, 'pending', ?, NULL)",
                                    (import_id, digest, FORMAT_VERSION, stamp))
            originals = dict(rows)
            for row in plan["rows"]:
                if row["action"] == "add":
                    row["company_id"] = self.catalog.add_company(row["company_name"], company_id=row["company_id"])
                    row["expected_version"] = 1
                changes = {field: change["after"] for field, change in row["changes"].items()}
                if changes:
                    self.catalog.update_company(row["company_id"], expected_version=row["expected_version"], **changes)
                if row["source_change"]:
                    self._select_source(row)
                    if not changes:
                        self.connection.execute("UPDATE companies SET row_version=row_version+1, updated_at=? WHERE company_id=?",
                                                (stamp, row["company_id"]))
                self.connection.execute("INSERT INTO legacy_records VALUES (?, ?, ?, ?, ?, NULL)",
                    (new_id(), import_id, f"line:{row['line']}",
                     canonical_json({"input": originals[row["line"]], "changes": row["changes"],
                                     "source_before": row["source_before"], "source_after": row["source"]}), row["company_id"]))
            self.connection.execute("UPDATE import_batches SET status='completed', completed_at=? WHERE import_id=?", (utc_now(), import_id))
            plan["import_id"] = import_id
            return plan

    def _plan(self, rows, digest, ignored, preserve_ids, literal=False):
        companies = {row["company_id"]: dict(row) for row in self.connection.execute("SELECT * FROM companies")}
        sources = [dict(row) for row in self.connection.execute("SELECT * FROM job_sources")]
        definitions = {}
        for source in sources:
            try:
                definitions[source["source_id"]] = source_definition(source["careers_url"], source["provider"])
            except ValueError:
                pass
        result = {"ok": True, "applied": False, "database_id": self.database.database_id,
                  "input_fingerprint": digest, "format_version": FORMAT_VERSION, "ignored_columns": ignored,
                  "counts": {"add": 0, "update": 0, "unchanged": 0}, "rows": [], "errors": []}
        seen_ids, seen_scopes = set(), set()
        for line, raw in rows:
            try:
                name = raw["Company Name"] if literal else raw["Company Name"].strip()
                url = raw["Careers URL"].strip()
                if not name.strip() or (name == CLEAR_VALUE and not literal) or not url:
                    raise ValueError("Company Name and Careers URL cannot be blank or cleared")
                source = source_definition(url, raw.get("ATS Type", ""))
                company_id = raw.get("Company ID", "") if literal else raw.get("Company ID", "").strip()
                if not source.supported and not raw.get("ATS Type", "").strip():
                    known = [s for s in sources if s["source_id"] in definitions
                             and definitions[s["source_id"]].careers_url == source.careers_url
                             and (s["company_id"] == company_id if company_id else
                                  _name(companies[s["company_id"]]["company_name"]) == _name(name))]
                    current_known = [s for s in known if s["is_current"]]
                    known = current_known or known
                    if len({s["provider"] for s in known}) > 1:
                        raise ValueError("Careers page has conflicting stored provider labels; supply Company ID and ATS Type")
                    if known:
                        source = definitions[known[0]["source_id"]]
                scope_key = (source.provider, source.scope_key)
                if scope_key in seen_scopes:
                    raise ValueError("Duplicate careers scope in this file; keep one company row per exact scope")
                seen_scopes.add(scope_key)
                matches = {s["company_id"] for s in sources if s["source_id"] in definitions
                           and (definitions[s["source_id"]].provider, definitions[s["source_id"]].scope_key) == scope_key}
                if company_id:
                    if company_id not in companies and not preserve_ids:
                        raise ValueError("Unknown Company ID; omit it for a generated ID or use --preserve-ids")
                    if company_id not in companies and matches:
                        raise ValueError("Unknown Company ID conflicts with an existing careers scope")
                elif matches:
                    candidates = [identity for identity in matches if _name(companies[identity]["company_name"]) == _name(name)]
                    if len(candidates) != 1:
                        raise ValueError("Careers scope matches existing companies ambiguously; supply the exact Company ID")
                    company_id = candidates[0]
                    if not any(s["company_id"] == company_id and s["is_current"] and s["source_id"] in definitions
                               and definitions[s["source_id"]].scope_key == source.scope_key for s in sources):
                        raise ValueError("This URL belongs to a retired source; supply Company ID to switch back explicitly")
                else:
                    same_board = [s for s in sources if s["source_id"] in definitions
                                  and definitions[s["source_id"]].namespace == source.namespace
                                  and _name(companies[s["company_id"]]["company_name"]) == _name(name)]
                    if same_board:
                        raise ValueError("Company scope changed; supply Company ID to preserve its identity")
                if company_id and company_id in seen_ids:
                    raise ValueError("Duplicate Company ID or multiple rows matching the same company")
                if company_id:
                    seen_ids.add(company_id)
                existing = companies.get(company_id)
                changes = {}
                for heading, field in FIELDS.items():
                    value = raw.get(heading, "")
                    if not value.strip():
                        continue
                    if value.strip() == CLEAR_VALUE and not literal:
                        if field in {"company_name", "status"}:
                            raise ValueError(f"{heading} cannot be cleared")
                        value = ""
                    elif not literal and field not in {"notes", "personal_rationale"}:
                        value = value.strip()
                    if field == "status" and value not in COMPANY_STATUSES:
                        raise ValueError("Status must be active, paused or archived")
                    if field == "website_url" and value:
                        try:
                            value = public_careers_url(value)
                        except FetchError as exc:
                            raise ValueError("Website must be a public HTTPS URL") from exc
                    previous = existing[field] if existing else ("active" if field == "status" else "")
                    if value != previous:
                        changes[field] = {"before": previous, "after": value}
                current = next((s for s in sources if s["company_id"] == company_id and s["is_current"]), None)
                candidates = [s for s in sources if s["company_id"] == company_id and s["source_id"] in definitions
                              and definitions[s["source_id"]].provider == source.provider
                              and definitions[s["source_id"]].namespace == source.namespace]
                if len(candidates) > 1:
                    raise ValueError("Multiple stored sources share this namespace; inspect source identities before importing")
                selected = candidates[0] if candidates else None
                source_change = not current or current != selected or current["careers_url"] != source.careers_url
                if source_change and existing and self.connection.execute(
                    "SELECT 1 FROM cycle_companies m JOIN scan_cycles c USING(cycle_id) "
                    "WHERE m.company_id=? AND c.status IN ('running', 'interrupted')", (company_id,)).fetchone():
                    raise ValueError("Resume the unfinished local cycle before changing this company's source")
                action = "add" if existing is None else "update" if changes or source_change else "unchanged"
                result["rows"].append({"line": line, "company_id": company_id or None, "company_name": name,
                    "action": action, "expected_version": existing["row_version"] if existing else None,
                    "changes": changes, "source": asdict(source), "source_change": source_change,
                    "source_before": current, "selected_source_id": selected["source_id"] if selected else None,
                    "warning": "" if source.supported else "Careers page saved; local scanning needs a supported official board URL"})
                result["counts"][action] += 1
            except ValueError as exc:
                result["errors"].append({"line": line, "error": str(exc)})
        result["ok"] = not result["errors"]
        return result

    def _select_source(self, row):
        company, definition, source_id = row["company_id"], row["source"], row["selected_source_id"]
        if source_id is None:
            source_id = self.catalog.add_source(company, definition["provider"], definition["namespace"], definition["careers_url"])
        else:
            self.connection.execute("UPDATE job_sources SET is_current=0 WHERE company_id=?", (company,))
            self.connection.execute("UPDATE job_sources SET is_current=1, careers_url=? WHERE source_id=?", (definition["careers_url"], source_id))
        scope_id = self.catalog.add_scope(SourceScope(source_id, definition["careers_url"], "official-v1"))
        # A reselected source/scope starts a fresh comparison. Observations and
        # versions remain immutable; only the derived missing counters reset.
        self.connection.execute("DELETE FROM job_scope_state WHERE source_id=?", (source_id,))
        # Retained results from before a source selection remain historical,
        # including when a user later switches back to an earlier URL.
        sequence = self.connection.execute("SELECT coalesce(max(observation_sequence), 0) FROM scan_attempts").fetchone()[0]
        self.connection.execute(
            "INSERT INTO source_scan_state VALUES (?, ?, ?) ON CONFLICT(source_id) DO UPDATE SET "
            "scope_id=excluded.scope_id, latest_observation_sequence=max(source_scan_state.latest_observation_sequence, excluded.latest_observation_sequence)",
            (source_id, scope_id, sequence),
        )
