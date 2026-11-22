"""Observation-only qualification for one immutable Amphenol candidate.

This invokes normal ATS dispatch when run; it never changes its request pacing,
storage, release state, or Sheets.  The wrappers below only record evidence.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlsplit

DETAIL_GAP_SECONDS = 12.0
COMPANY_ID = "COMP-0490"
SOURCE = "https://amphenol-aerospace.acquiretm.com/home.aspx"
PROJECT = Path("/home/chris/job-search-helper_old")
COHORT_SHA256 = "728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b"
DETAILS_SHA256 = "dfc88fe9ea1383495535d8b1d8715f7e37f5df886f24fa4702dd17688d6cab71"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def require(value, text):
    if not value:
        raise RuntimeError(text)


def source_manifest(root):
    paths = list((root / "src").rglob("*.py"))
    paths += [root / name for name in ("pyproject.toml", "title-blacklist.txt", "title-review-list.txt") if (root / name).is_file()]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}


def cooldown(headers, now):
    if not hasattr(headers, "items"):
        return {}
    raw = next((value for name, value in headers.items() if str(name).casefold() == "retry-after"), None)
    try:
        delay = float(raw)
    except (TypeError, ValueError, OverflowError):
        try:
            stamp = parsedate_to_datetime(raw)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            delay = (stamp - now).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return {}
    if not math.isfinite(delay) or delay < 0:
        return {}
    return ({"retry_after_exceeds_observation_bound": True} if delay > 86400 else {"retry_after_seconds": delay})


def prepare(root, raw_sha256):
    """Read the adjacent immutable preparation and proposal before imports."""
    require(isinstance(raw_sha256, str) and len(raw_sha256) == 64, "raw preparation SHA-256 required")
    prep_path, manifest_path = root.parent / "PREPARED.json", root.parent / "PROPOSED_MANIFEST.json"
    raw = prep_path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == raw_sha256, "preparation bytes differ")
    prep, manifest = json.loads(raw), json.loads(manifest_path.read_text())
    keys = {"candidate_root", "candidate_vector_count", "candidate_vector_sha256", "release_id",
            "manifest_sha256", "company_id", "source_revision", "source_manifest_sha256",
            "paced_adapter_sha256", "dispatcher_sha256"}
    require(keys <= set(prep) and Path(prep["candidate_root"]) == root and prep["candidate_vector_count"] == 256,
            "candidate binding differs")
    require(prep["company_id"] == COMPANY_ID and isinstance(prep["source_revision"], str)
            and len(prep["source_revision"]) == 64, "company/source binding differs")
    require(all(isinstance(prep[name], str) and len(prep[name]) == 64 for name in
                ("paced_adapter_sha256", "dispatcher_sha256")), "runtime transport binding differs")
    require(manifest.get("release_id") == prep["release_id"] and digest(manifest) == prep["manifest_sha256"]
            and manifest.get("company_id") == COMPANY_ID and manifest.get("source_revision") == prep["source_revision"],
            "proposal binding differs")
    prep = dict(prep)
    prep["_manifest"] = manifest
    return prep


def observed_request(original, calls):
    """Call the existing transport unchanged, recording only bounded timing/status."""
    def wrapped(*args, **kwargs):
        start, wall = time.monotonic_ns(), datetime.now(timezone.utc)
        row = {"wall_utc": wall.isoformat(), "monotonic_ns": start}
        calls.append(row)
        try:
            response = original(*args, **kwargs)
        except BaseException as error:
            row.update(error_class=type(error).__name__, completed_monotonic_ns=time.monotonic_ns())
            raise
        finished = datetime.now(timezone.utc)
        status = getattr(response, "status", None)
        row.update(completed_wall_utc=finished.isoformat(), completed_monotonic_ns=time.monotonic_ns(),
                   status=status if type(status) is int and 100 <= status <= 599 else None,
                   **cooldown(getattr(response, "headers", None), finished))
        return response
    return wrapped


def require_normal_pacing(calls, listings):
    """PASS evidence must prove the adapter's own spacing, including reread."""
    require(calls and listings, "no normal detail/listing timing evidence")
    for previous, current in zip(calls, calls[1:]):
        require("completed_monotonic_ns" in previous and current["monotonic_ns"] - previous["completed_monotonic_ns"]
                >= int(DETAIL_GAP_SECONDS * 1_000_000_000), "detail request began before normal pacing boundary")
    final_listing = listings[-1]["started_monotonic_ns"]
    require("completed_monotonic_ns" in calls[-1]
            and final_listing - calls[-1]["completed_monotonic_ns"] >= int(DETAIL_GAP_SECONDS * 1_000_000_000),
            "final listing reread began before normal pacing boundary")


def evaluate(root, prep, *, record=emit):
    vector = source_manifest(root)
    require(digest(vector) == prep["candidate_vector_sha256"], "candidate source vector differs")
    sys.path.insert(0, str(root / "src"))
    from job_search_helper import ats, acquiretm, cli, company_sources, integration_release, shared_boards
    for module in (ats, acquiretm, cli, company_sources, integration_release, shared_boards):
        require(Path(module.__file__).resolve().is_relative_to(root / "src"), "foreign source import")
    require(hashlib.sha256(Path(ats.__file__).read_bytes()).hexdigest() == prep["dispatcher_sha256"],
            "dispatcher pin differs")
    require(hashlib.sha256(Path(acquiretm.__file__).read_bytes()).hexdigest() == prep["paced_adapter_sha256"],
            "paced adapter pin differs")
    before = integration_release.source_tree_digest(root)
    require(before == prep["source_manifest_sha256"], "candidate source manifest differs")
    # This is the same effective environment/dependency measurement boundary as
    # prepare/release: candidate source, shared installed production .venv.
    cli.load_environment(PROJECT / ".env")
    config_before = integration_release.config_tree_digest(root)
    dependency_before = integration_release.dependency_manifest_digest(PROJECT)
    manifest = prep["_manifest"]
    require(config_before == manifest.get("config_sha256") and dependency_before == manifest.get("dependency_manifest_sha256"),
            "candidate config/dependency runtime differs")
    require(acquiretm.SOURCE == SOURCE, "canonical source differs")
    seen = {"pages": [], "listings": [], "details": {}, "calls": []}
    parse, inventory, get_body = acquiretm.parse_listing, acquiretm.inventory, acquiretm._DetailClient.get_body

    def watched_parse(body):
        total, rows, pages = parse(body)
        seen["pages"].append({"total": total, "ids": sorted(rows), "page_controls": sorted(pages)})
        return total, rows, pages

    def watched_inventory(*args, **kwargs):
        # A normal dispatch has multiple inventory passes.  Keep each pass's
        # advertised pages separate; this is evidence scoping, not pacing.
        seen["pages"].clear()
        started = time.monotonic_ns()
        record({"stage": "listing_start", "listing_number": len(seen["listings"]) + 1,
                "wall_utc": datetime.now(timezone.utc).isoformat(), "monotonic_ns": started})
        value = inventory(*args, **kwargs)
        seen["listings"].append({"entries": value, "pages": list(seen["pages"]), "started_monotonic_ns": started})
        record({"stage": "listing_complete", "listing_number": len(seen["listings"]),
                "membership_digest": digest(value), "page_count": len(seen["pages"])})
        return value

    def watched_body(client, url):
        token = hashlib.sha256(url.encode()).hexdigest()
        record({"stage": "detail_start", "job_key_digest": token, "wall_utc": datetime.now(timezone.utc).isoformat(),
                "monotonic_ns": time.monotonic_ns()})
        original, calls = client.request.get, []
        client.request.get = observed_request(original, calls)
        try:
            body = get_body(client, url)
        except BaseException as error:
            record({"stage": "detail_complete", "job_key_digest": token, "error_class": type(error).__name__,
                    "wall_utc": datetime.now(timezone.utc).isoformat(), "monotonic_ns": time.monotonic_ns(), "calls": calls})
            raise
        finally:
            client.request.get = original
            # A normal blocked FetchError skips parsing; retain its exact calls
            # once for terminal HOLD classification rather than falling through.
            seen["calls"].extend(calls)
        record({"stage": "detail_complete", "job_key_digest": token, "wall_utc": datetime.now(timezone.utc).isoformat(),
                "monotonic_ns": time.monotonic_ns(), "calls": calls})
        rows = shared_boards.Scripts(body).jobs()
        require(len(rows) == 1, "nonunique JSON-LD JobPosting")
        seen["details"][url] = rows[0]
        return body

    acquiretm.parse_listing, acquiretm.inventory, acquiretm._DetailClient.get_body = watched_parse, watched_inventory, watched_body
    try:
        result = ats.fetch_inventory("AcquireTM", SOURCE, COMPANY_ID, "Amphenol Aerospace")
    finally:
        acquiretm.parse_listing, acquiretm.inventory, acquiretm._DetailClient.get_body = parse, inventory, get_body
    holds = [(number, call) for number, call in enumerate(seen["calls"])
             if call.get("status") == 429 or (call.get("status") in {408, 500, 502, 503, 504}
                 and (call.get("retry_after_seconds", 0) > DETAIL_GAP_SECONDS or call.get("retry_after_exceeds_observation_bound")))]
    if holds:
        number, first = holds[0]
        require(result.status == "blocked" and number == len(seen["calls"]) - 1,
                "normal dispatch did not stop cleanly at first observed hold")
        output = {"stage": "held_provider_rate_limit" if first["status"] == 429 else "held_provider_retry_after",
                  "status": first["status"], "observed_at_utc": first["completed_wall_utc"]}
        if "retry_after_seconds" in first:
            output["retry_after_seconds"] = first["retry_after_seconds"]
            output["retry_not_before_utc"] = (datetime.fromisoformat(first["completed_wall_utc"]) + timedelta(seconds=first["retry_after_seconds"])).isoformat()
        if first.get("retry_after_exceeds_observation_bound"):
            output["retry_after_exceeds_observation_bound"] = True
        require(source_manifest(root) == vector and integration_release.source_tree_digest(root) == before
                and integration_release.config_tree_digest(root) == config_before
                and integration_release.dependency_manifest_digest(PROJECT) == dependency_before,
                "candidate changed during held evaluation")
        record(output)
        return 1
    require(result.status == "complete" and result.source_url == SOURCE and result.ats == "AcquireTM", "normal dispatch is not complete")
    listings = seen["listings"]
    require(len(listings) >= 2 and listings[0]["entries"] == listings[-1]["entries"], "stable two listing passes missing")
    entries = listings[-1]["entries"]
    for listing in listings:
        pages, ids = listing["pages"], [ident for page in listing["pages"] for ident in page["ids"]]
        totals = {page["total"] for page in pages}
        require(pages and len(totals) == 1 and len(ids) == len(set(ids)) and set(ids) == set(listing["entries"])
                and len(ids) == next(iter(totals)), "incomplete advertised inventory")
    require_normal_pacing(seen["calls"], listings)
    jobs = result.jobs
    require(len(jobs) == len(entries) and {str(job["posting_id"]) for job in jobs} == set(entries)
            and len({job["url"] for job in jobs}) == len(jobs), "normal result differs from listing")
    details = []
    for job in jobs:
        ident, url = str(job["posting_id"]), job["url"]
        parsed, item = urlsplit(url), seen["details"].get(url)
        require(parsed.scheme == "https" and parsed.hostname == "amphenol-aerospace.acquiretm.com"
                and parsed.path == "/job_details_clean.aspx" and parse_qs(parsed.query) == {"ID": [ident]}
                and item is not None and url == entries[ident]["url"] and job["title"] == entries[ident]["title"], "identity changed")
        identifier = item.get("identifier", {})
        record_id = identifier.get("value") if isinstance(identifier, dict) else identifier
        employer = " ".join(str(item.get("hiringOrganization", {}).get("name", "")).split()).casefold()
        description = ats.text(item.get("description"))
        require(str(record_id) == ident and item.get("url") == url and ats.text(item.get("title")) == job["title"]
                and employer in {"amphenol aerospace", "amphenol aerospace operations"}
                and len(description) >= 120 and job["description"] == description, "full detail differs")
        details.append({"id": ident, "url": url, "employer": employer, "description_chars": len(description),
                        "description_sha256": hashlib.sha256(description.encode()).hexdigest()})
    cohort = sorted((str(job["posting_id"]), job["url"], job["title"]) for job in jobs)
    require(digest(cohort) == COHORT_SHA256 and digest(sorted(details, key=lambda item: item["id"])) == DETAILS_SHA256,
            "cohort/detail digest differs")
    require(source_manifest(root) == vector and integration_release.source_tree_digest(root) == before
            and integration_release.config_tree_digest(root) == config_before
            and integration_release.dependency_manifest_digest(PROJECT) == dependency_before,
            "candidate changed during evaluation")
    record({"stage": "observation_candidate_confirmation_passed", "count": len(cohort),
            "source_manifest_sha256": before, "installation": "not_performed", "storage_sync": "not_performed"})
    return 0


def main():
    require(len(sys.argv) == 3, "candidate root and raw preparation SHA-256 required")
    intended = Path("/home/chris/job-search-helper_old/.venv").resolve()
    require(sys.flags.isolated and sys.flags.dont_write_bytecode and Path(sys.prefix).resolve() == intended,
            "isolated project interpreter required")
    path = Path(sys.argv[1])
    require(path.is_absolute() and not path.is_symlink(), "physical absolute candidate required")
    root = path.resolve(strict=True)
    return evaluate(root, prepare(root, sys.argv[2]))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit({"stage": "failed", "type": type(error).__name__, "reason": str(error)})
        raise SystemExit(1)
