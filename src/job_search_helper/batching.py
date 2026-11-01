"""Local planning buffers; the real repository rechecks cells at commit time."""
from __future__ import annotations

import copy
import uuid

from .core import canonicalize_url
from .repository import SCHEMAS, RepositoryError, _equivalent, IdentityIndex


def _safe_canonical_url(value):
    try:
        return canonicalize_url(value)
    except ValueError:
        return ""


def _identity_label(identity):
    return ", ".join(f"{key}={value!r}" for key, value in identity.items())


def _match_label(row):
    parts = []
    for key in ("Company", "Company ID", "Job Title", "Job Key", "Official Job URL", "Job URL"):
        value = row.get(key)
        if value:
            text = str(value)
            if len(text) > 90:
                text = text[:87] + "..."
            parts.append(f"{key}={text!r}")
    return "; ".join(parts) or "populated row"


class PlanningRepository:
    """Cache lookups, collect operations, and never perform writes itself.

    Values here are planning data only. The underlying repository freshly reads
    affected identities, destination rows and append tails, validating formulas
    and user-owned cells immediately before its single atomic batchUpdate.
    """
    def __init__(self, repository, rows=None):
        self.base = repository
        self.is_local = getattr(repository, 'is_local', False)
        self.schemas = getattr(repository, 'schemas', SCHEMAS)
        self.rows = self._load_planning_rows(repository) if rows is None else rows
        self.operations = []
        self._reindex()

    @staticmethod
    def _blank_row(tab, values):
        row = {header: "" for header in SCHEMAS[tab]}
        row.update(values)
        return row

    @classmethod
    def _read_column_rows(cls, repository, tab, headers):
        return [cls._blank_row(tab, values) for _, values in repository.read_columns(tab, headers)]

    @classmethod
    def _load_planning_rows(cls, repository):
        """Load only columns needed to classify scraped SQLite inventories.

        Commit remains authoritative: the real repository rereads identities,
        protected review fields and append tails immediately before writing.
        """
        if not hasattr(repository, "read_cached_columns"):
            return repository.read_many(SCHEMAS)
        return {
            "Companies": repository.read("Companies"),
            "Job History": cls._read_column_rows(repository, "Job History", [
                "Company", "Job Key", "Official Job URL", "Requisition ID", "Job Title",
                "Current Snapshot", "Added to Opportunities?", "Review Status",
                "Decision", "Reconsideration Count", "Description Hash", "Source Hash",
                "Rejection Reason", "Review Notes", "Job Status",
                "Consecutive Missing Scans", "Prior Job Key",
            ]),
            "Job Evidence": cls._read_column_rows(repository, "Job Evidence", ["Job Key", "Source Hash"]),
            "Opportunities": cls._read_column_rows(repository, "Opportunities", ["Company", "Job URL"] +
                (['Opportunity ID'] if 'Opportunity ID' in repository.schemas['Opportunities'] else [])),
            "Scan Cycles": cls._read_column_rows(repository, "Scan Cycles", ["Cycle ID"]),
        }

    def _reindex(self):
        self.indexes = {tab: IdentityIndex(enumerate(rows)) for tab, rows in self.rows.items()}

    def history_candidates(self, company, key, url):
        index = self.indexes["Job History"]
        candidates = dict(index.matches({"Company": company, "Job Key": key}))
        for number, row in index.matches({"Company": company}):
            if row.get("Official Job URL") and _safe_canonical_url(row["Official Job URL"]) == url:
                candidates[number] = row
        return list(candidates.values())

    def opportunity_candidates(self, company, urls):
        index = self.indexes["Opportunities"]
        candidates = {}
        for url in urls:
            candidates.update(index.matches({"Company": company, "Job URL": url}))
        return list(candidates.values())

    def begin(self):
        self.operations = []

    def read(self, tab):
        if tab not in SCHEMAS:
            raise RepositoryError("Tab is not operationally allowlisted")
        return self.rows[tab]

    def read_columns(self, tab, headers):
        """Expose cached numbered values for read-only engine helpers."""
        if tab not in SCHEMAS:
            raise RepositoryError("Tab is not operationally allowlisted")
        unknown = set(headers) - set(SCHEMAS[tab])
        if unknown:
            raise RepositoryError("Unknown column requested: " + ", ".join(sorted(unknown)))
        return [(number, {header: row.get(header, "") for header in headers})
                for number, row in enumerate(self.rows[tab])]

    def validate_schema(self):
        return True  # read_many has validated the authoritative schema.

    def refresh_company(self, company_id):
        # User pauses and coordinator claims are checked between batches.
        self.rows["Companies"] = self.base.read("Companies")
        matches = [r for r in self.rows["Companies"] if r.get("Company ID") == company_id]
        if len(matches) != 1:
            raise ValueError("Company was removed or its identity is ambiguous")
        company = matches[0]
        if str(company.get("Company Status", "Active")).strip().casefold() in {"pause", "paused", "remove"}:
            raise ValueError("Company was paused; saved batch progress is preserved")
        if company.get("Claimed By") or company.get("Claim Token"):
            raise ValueError("Company has an external worker claim; saved batch progress is preserved")
        return company

    def commit(self, operations):
        # Simulate only record values. Validation/format protection belongs to
        # the real fresh-read commit, not this cached approximation.
        for op in operations:
            op = copy.deepcopy(op)
            tab = op["tab"]
            if tab not in SCHEMAS:
                raise RepositoryError("Unapproved planning tab")
            identity = op["identity"]
            indexed = self.indexes[tab].matches(identity)
            matches = [r for _, r in indexed]
            if (tab == 'Opportunities' and self.is_local and len(matches) > 1
                    and all(r.get('Opportunity ID') for r in matches)):
                self.commit([dict(copy.deepcopy(op), identity={'Opportunity ID': row['Opportunity ID']})
                             for row in matches])
                continue
            if len(matches) > 1:
                sample = " | ".join(_match_label(row) for row in matches[:3])
                raise RepositoryError(
                    f"Ambiguous cached identity in {tab} for {_identity_label(identity)}; "
                    f"matched {len(matches)} rows: {sample}. Refusing to guess."
                )
            if not matches:
                if not op.get("append_if_missing"):
                    raise RepositoryError("Expected row no longer exists")
                if (tab == 'Opportunities' and self.is_local
                        and 'Opportunity ID' in self.schemas['Opportunities']):
                    op.setdefault('on_insert', {}).setdefault('Opportunity ID', 'OPP-' + uuid.uuid4().hex)
                row = {h: "" for h in SCHEMAS[tab]}
                row.update(op.get("on_insert", {}))
                row.update(identity)
                rownum = len(self.rows[tab])
                self.rows[tab].append(row)
            else:
                rownum, original = indexed[0]
                row = copy.deepcopy(original)
                self.rows[tab][rownum] = row
            row.update(op.get("values", {}))
            for header, note in op.get("append_notes", {}).items():
                previous = str(row.get(header) or "")
                if note not in previous:
                    row[header] = previous + ("\n\n" if previous else "") + note
            self.indexes[tab].put(rownum, row)
            self.operations.append(copy.deepcopy(op))
        return {"staged": len(operations)}

    def accept_commit(self):
        # Reuse the fresh authoritative rows already obtained by commit. This
        # includes manual edits that occurred after the initial lookup read.
        for tab, rows in self.base._committed_rows.items():
            if not getattr(self.base, "_committed_partial", False):
                self.rows[tab] = copy.deepcopy(rows)
                continue
            # Partial authoritative results contain only touched rows.
            keys = {"Job History": ("Job Key",), "Job Evidence": ("Job Key", "Source Hash"),
                    "Opportunities": ("Company", "Job URL"),
                    "Companies": ("Company ID",), "Scan Cycles": ("Cycle ID",)}[tab]
            index = IdentityIndex(enumerate(self.rows[tab]))
            for row in rows:
                identity = ({'Opportunity ID': row['Opportunity ID']}
                            if tab == 'Opportunities' and row.get('Opportunity ID')
                            else {key: row[key] for key in keys})
                matches = index.matches(identity)
                if len(matches) == 1:
                    self.rows[tab][matches[0][0]] = copy.deepcopy(row)
                elif not matches:
                    self.rows[tab].append(copy.deepcopy(row))
        self.operations = []
        self._reindex()


class PendingState:
    """Keep SQLite updates pending until the spreadsheet batch succeeds."""
    def __init__(self, state):
        self.base = state
        self.updates = {}
        self.changed_cycles = {}

    def __getattr__(self, name):
        return getattr(self.base, name)

    def put_review(self, cycle_id, key, data, status="pending"):
        self.updates[(cycle_id, key)] = (copy.deepcopy(data), status)

    def reviews(self, cycle_id, status=None):
        rows = {r["job_key"]: r for r in self.base.reviews(cycle_id)}
        for (cid, key), (data, state) in self.updates.items():
            if cid == cycle_id:
                rows[key] = dict(copy.deepcopy(data), queue_status=state)
        return [r for r in rows.values() if status is None or r["queue_status"] == status]

    def cycle(self, cycle_id):
        if cycle_id in self.changed_cycles:
            return copy.deepcopy(self.changed_cycles[cycle_id])
        return self.base.cycle(cycle_id)

    def save_cycle(self, cycle):
        self.changed_cycles[cycle["id"]] = copy.deepcopy(cycle)

    def flush(self):
        self.base.apply_buffer(self.updates, self.changed_cycles)
