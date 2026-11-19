"""Canonical Company change facts for the durable intake outbox.

This module deliberately knows nothing about Sheets, scheduling, or network
delivery.  It turns the small set of fields that can change a scrape into a
stable, auditable fact.  The SQLite repository records those facts in the
same transaction as a supported Company mutation.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .repository import RepositoryError, _url


RELEVANT_FIELDS = ("Company ID", "Company Status", "Official Careers URL", "ATS / Source")
INELIGIBLE_STATUSES = frozenset({"pause", "paused", "remove", "removed"})


def _text(value):
    return str(value or "").strip()


def canonical_company_fact(company):
    """Return the immutable scrape-relevant Company fact.

    A missing ID or careers URL is intentionally *not* eligible.  The store
    leaves a newly incomplete Company alone, but records a withdrawal if an
    already eligible Company loses its source so consumers can cancel scope.
    """
    company_id = _text(company.get("Company ID"))
    if not company_id:
        raise RepositoryError("Company event requires a stable Company ID.")
    status = _text(company.get("Company Status") or "Active").casefold()
    careers_url = _text(company.get("Official Careers URL"))
    source = _text(company.get("ATS / Source")).casefold()
    return {
        "company_id": company_id,
        "company_status": status,
        "official_careers_url": _url(careers_url) if careers_url else "",
        "ats_source": source,
        "eligible": bool(careers_url) and status not in INELIGIBLE_STATUSES,
    }


def source_revision(company):
    """Hash the canonical fact; cosmetic/progress fields never affect it."""
    fact = canonical_company_fact(company)
    encoded = json.dumps(fact, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def event_kind(fact):
    if fact["eligible"]:
        return "company.eligible"
    return "company.withdrawn" if not fact["official_careers_url"] else "company.ineligible"
