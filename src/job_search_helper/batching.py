"""Local planning buffers; the real repository rechecks cells at commit time."""
from __future__ import annotations

import copy

from .repository import SCHEMAS, RepositoryError, _equivalent


class PlanningRepository:
    """Cache lookups, collect operations, and never perform writes itself.

    Values here are planning data only. The underlying repository freshly reads
    all affected tabs and validates formulas, identities and user-owned cells
    immediately before its single atomic batchUpdate.
    """
    def __init__(self, repository):
        self.base = repository
        self.rows = repository.read_many(SCHEMAS)
        self.operations = []

    def begin(self):
        self.operations = []

    def read(self, tab):
        if tab not in SCHEMAS:
            raise RepositoryError("Tab is not operationally allowlisted")
        return self.rows[tab]

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
            tab = op["tab"]
            if tab not in SCHEMAS:
                raise RepositoryError("Unapproved planning tab")
            identity = op["identity"]
            matches = [r for r in self.rows[tab]
                       if all(_equivalent(h, r.get(h, ""), v) for h, v in identity.items())]
            if len(matches) > 1:
                raise RepositoryError("Ambiguous cached identity; refusing to guess")
            if not matches:
                if not op.get("append_if_missing"):
                    raise RepositoryError("Expected row no longer exists")
                row = {h: "" for h in SCHEMAS[tab]}
                row.update(op.get("on_insert", {}))
                row.update(identity)
                self.rows[tab].append(row)
            else:
                row = matches[0]
            row.update(op.get("values", {}))
            for header, note in op.get("append_notes", {}).items():
                previous = str(row.get(header) or "")
                if note not in previous:
                    row[header] = previous + ("\n\n" if previous else "") + note
            self.operations.append(copy.deepcopy(op))
        return {"staged": len(operations)}

    def accept_commit(self):
        # Reuse the fresh authoritative rows already obtained by commit. This
        # includes manual edits that occurred after the initial lookup read.
        for tab, rows in self.base._committed_rows.items():
            self.rows[tab] = copy.deepcopy(rows)
        self.operations = []


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
