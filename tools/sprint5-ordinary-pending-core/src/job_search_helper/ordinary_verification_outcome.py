"""Exact immutable Jobs outcome readback for an enrolled ordinary attempt."""

import json

from .ordinary_verification_pending import digest
from .outcomes import validate_public_outcome_record
from .repository import RepositoryError
from .sqlite_repository import encode


def existing_outcome(repository, owner):
    """Return one exact prior outcome, regardless of its existing classification.

    The coordinator must first prove the owner from saved State and use a fresh
    descriptor-bound Jobs handle. This read itself can neither release a
    pending outcome nor add or change a Jobs row.
    """
    identity = (owner["request_id"], owner["company_id"], owner["source_revision"])
    rows = repository.db.execute(
        "SELECT outcome_id,request_id,company_id,source_revision,outcome,action,payload "
        "FROM main.scrape_outcomes WHERE request_id=? AND company_id=? AND source_revision=?",
        identity,
    )
    selected = None
    for outcome_id, request_id, company_id, source_revision, outcome, action, raw in rows:
        try:
            payload = validate_public_outcome_record(json.loads(raw))
        except (TypeError, ValueError):
            payload = None
        if payload is None or encode(payload) != raw:
            raise RepositoryError("Stored outcome has invalid immutable evidence.")
        public_identity = payload["identity"]
        if (outcome_id, request_id, company_id, source_revision, outcome, action) != (
            payload["outcome_id"], public_identity["request_id"], public_identity["company_id"],
            public_identity["source_revision"], payload["outcome"], payload["action"],
        ):
            raise RepositoryError("Stored outcome disagrees with its indexed identity.")
        cycle_id = public_identity.get("cycle_id")
        if cycle_id is None:
            raise RepositoryError("Stored outcome cannot be attributed to an exact ordinary cycle.")
        if cycle_id != owner["cycle_id"]:
            continue
        if set(public_identity) - {"request_id", "company_id", "source_revision",
                                  "cycle_id", "provider", "adapter_version"}:
            raise RepositoryError("A different outcome route owns the exact ordinary attempt.")
        if selected is not None:
            raise RepositoryError("Multiple immutable outcomes claim the exact ordinary attempt.")
        selected = {"outcome_id": outcome_id, "payload_sha256": digest(payload), "outcome": payload}
    return selected
