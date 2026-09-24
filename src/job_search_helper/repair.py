"""Repair blocked company careers URLs after validating replacement boards."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .ats import FetchError, Inventory, fetch_inventory, is_board_host, resolve_board
from .discovery import discover_board, public_careers_url
from .engine import now
from .repository import RepositoryError, UncertainWriteError
from urllib.parse import urlsplit

CANDIDATE_COLUMN = "Candidate Careers URL"
SKIP_REASON_MARKERS = (
    "Job History:",
    "Opportunities:",
    "review fields changed since planning",
    "duplicate legacy key",
)


@dataclass
class RepairFinding:
    action: str
    company_id: str
    company: str
    current_url: str
    proposed_url: str = ""
    ats: str = ""
    jobs: int = 0
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "company_id": self.company_id,
            "company": self.company,
            "current_url": self.current_url,
            "proposed_url": self.proposed_url,
            "ats": self.ats,
            "jobs": self.jobs,
            "reason": self.reason,
        }


def _board_url(name: str, board: str, root: str, fallback: str) -> str:
    # root+board is the canonical URL the adapters can fetch again. For a
    # direct board already entered by the user, keeping the entered URL avoids
    # changing a human-friendly Workday/iCIMS board to an internal API path.
    if fallback:
        try:
            direct_name, direct_board, _ = resolve_board(name, fallback)
            if direct_name == name and direct_board == board:
                return fallback
        except (ValueError, TypeError):
            pass
    return root + board


def _is_repair_candidate(company: dict) -> tuple[bool, str]:
    if str(company.get("Scan State", "")).strip() != "Blocked / Manual Review":
        return False, "not blocked"
    reason = str(company.get("Blocked Reason", ""))
    if any(marker.casefold() in reason.casefold() for marker in SKIP_REASON_MARKERS):
        return False, "blocked by writer/history conflict, not a careers URL"
    if not str(company.get("Official Careers URL", "")).strip():
        return False, "missing Official Careers URL"
    if not str(company.get("Company ID", "")).strip():
        return False, "missing Company ID"
    return True, ""


def _validated_inventory(inventory: Inventory) -> tuple[bool, str]:
    if inventory.status != "complete":
        return False, inventory.reason or f"inventory status is {inventory.status}"
    if not inventory.jobs:
        return False, "validated fetch completed but returned no jobs"
    return True, ""


def inspect_company(
    company: dict,
    *,
    fetcher: Callable[..., Inventory] = fetch_inventory,
    discoverer: Callable[..., tuple[tuple[str, str, str], str]] = discover_board,
    transport=None,
) -> RepairFinding:
    company_id = str(company.get("Company ID", "")).strip()
    company_name = str(company.get("Company", "")).strip()
    current_url = str(company.get("Official Careers URL", "")).strip()
    ats = str(company.get("ATS / Source", "")).strip()
    eligible, reason = _is_repair_candidate(company)
    if not eligible:
        return RepairFinding("skip", company_id, company_name, current_url, reason=reason)

    try:
        page_url = public_careers_url(current_url)
    except FetchError as exc:
        return RepairFinding("skip", company_id, company_name, current_url, reason=exc.reason)

    proposed_url = current_url
    proposed_ats = ats
    discovery_reason = ""
    try:
        name, board, root = resolve_board(ats, current_url)
        proposed_ats = name
        proposed_url = _board_url(name, board, root, current_url)
    except (ValueError, TypeError) as direct_error:
        if is_board_host(urlsplit(page_url).hostname):
            return RepairFinding("skip", company_id, company_name, current_url, reason=str(direct_error))
        try:
            (name, board, root), evidence_url = discoverer(ats, page_url, transport)
            proposed_ats = name
            # The configured public careers page may be perfectly valid even
            # though the scraper fetches an ATS API endpoint behind it. Keep
            # that human URL as the saved careers URL when discovery succeeds
            # from the current page; the normal scraper can rediscover the
            # board on future runs.
            proposed_url = current_url
            discovery_reason = f"discovered {root}{board} from {evidence_url}"
        except FetchError as exc:
            return RepairFinding("skip", company_id, company_name, current_url, reason=exc.reason)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            return RepairFinding("skip", company_id, company_name, current_url, reason=f"discovery failed: {exc}")

    try:
        inventory = fetcher(proposed_ats, proposed_url, company_id, company_name)
    except FetchError as exc:
        return RepairFinding("candidate", company_id, company_name, current_url, proposed_url, proposed_ats, reason=exc.reason)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return RepairFinding("candidate", company_id, company_name, current_url, proposed_url, proposed_ats, reason=f"fetch failed: {exc}")

    valid, invalid_reason = _validated_inventory(inventory)
    jobs = len(inventory.jobs or [])
    if valid:
        reason = "validated replacement careers board"
        if proposed_url == current_url:
            reason = "validated current careers board"
        if discovery_reason:
            reason = f"{reason}; {discovery_reason}"
        return RepairFinding("update", company_id, company_name, current_url, proposed_url, inventory.ats or proposed_ats, jobs, reason)
    return RepairFinding("candidate", company_id, company_name, current_url, proposed_url, inventory.ats or proposed_ats, jobs, invalid_reason)


def _operation(finding: RepairFinding) -> dict:
    values = {
        "Official Careers URL": finding.proposed_url,
        "ATS / Source": finding.ats,
        "Scan State": "Queued",
        "Blocked Reason": "",
        "Next Action": "",
        "Automatic Retry?": "",
        "Coverage Status": "",
        "Record Updated": now(),
    }
    if finding.jobs:
        values["Last Inventory Count"] = finding.jobs
    return {"tab": "Companies", "identity": {"Company ID": finding.company_id}, "values": values}


def _candidate_operation(finding: RepairFinding) -> dict:
    return {
        "tab": "Companies",
        "identity": {"Company ID": finding.company_id},
        "values": {
            CANDIDATE_COLUMN: finding.proposed_url,
            "Next Action": "Review candidate careers URL; repair command could not validate jobs automatically",
            "Record Updated": now(),
        },
    }


def repair_careers_urls(
    repo,
    *,
    apply: bool = False,
    fetcher: Callable[..., Inventory] = fetch_inventory,
    discoverer: Callable[..., tuple[tuple[str, str, str], str]] = discover_board,
    transport=None,
) -> dict:
    rows = repo.read("Companies")
    findings = [inspect_company(row, fetcher=fetcher, discoverer=discoverer, transport=transport) for row in rows]
    updates = [finding for finding in findings if finding.action == "update"]
    candidates = [finding for finding in findings if finding.action == "candidate" and finding.proposed_url]
    result = {
        "mode": "apply" if apply else "dry_run",
        "companies_scanned": len(rows),
        "validated_updates": len(updates),
        "manual_review_candidates": len(candidates),
        "skipped": sum(1 for finding in findings if finding.action == "skip"),
        "spreadsheet_changes": 0,
        "findings": [finding.as_dict() for finding in findings if finding.action != "skip"],
    }
    if not apply:
        return result

    if candidates and hasattr(repo, "ensure_columns"):
        repo.ensure_columns("Companies", [CANDIDATE_COLUMN])
    operations = [_operation(finding) for finding in updates]
    operations.extend(_candidate_operation(finding) for finding in candidates)
    if operations:
        try:
            result["commit"] = repo.commit(operations)
            result["spreadsheet_changes"] = len(operations)
        except UncertainWriteError:
            raise
        except RepositoryError as exc:
            if candidates and not hasattr(repo, "ensure_columns"):
                result["candidate_write_skipped"] = f"{CANDIDATE_COLUMN} column is missing or unavailable."
                retry_operations = [_operation(finding) for finding in updates]
                result["commit"] = repo.commit(retry_operations) if retry_operations else {"requests": 0}
                result["spreadsheet_changes"] = len(retry_operations)
            else:
                raise
    return result
