"""Prepared read-only Amphenol evaluator. Executing this makes live public reads.

No invocation was made during preparation. It uses normal dispatch and only wraps
existing parser/detail methods to observe their inputs/results. No DB/release API.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import math
from urllib.parse import parse_qs, urlsplit


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def emit(value):
    print(json.dumps(value, sort_keys=True), flush=True)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def retry_after_observation(headers, *, now=None):
    """Sanitize the received provider cooldown; never alter its retry behavior."""
    if not hasattr(headers, "items"):
        return {}
    value = next((item for name, item in headers.items() if str(name).casefold() == "retry-after"), None)
    try:
        delay = float(value)
    except (TypeError, ValueError, OverflowError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            delay = (stamp - (datetime.now(timezone.utc) if now is None else now)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return {}
    if not math.isfinite(delay) or delay < 0:
        return {}
    if delay > 24 * 60 * 60:
        return {"retry_after_exceeds_observation_bound": True}
    return {"retry_after_seconds": delay}


class DetailRateLimitHold(BaseException):
    """Stop the qualification observer across the client's retry handlers."""

    def __init__(self, evidence):
        super().__init__("Provider returned HTTP 429.")
        self.evidence = evidence


def observe_detail_response(client, url, get_body, observations):
    """Observe unchanged detail requests and stop on the first HTTP 429."""
    original_get = client.request.get
    hold = None

    def observed_get(*args, **kwargs):
        nonlocal hold
        if hold is not None:
            raise hold
        response = original_get(*args, **kwargs)
        status = getattr(response, "status", None)
        if type(status) is int and status == 429:
            observed_at = datetime.now(timezone.utc)
            evidence = {"status": status, "observed_at_utc": observed_at.isoformat()}
            hold = DetailRateLimitHold(evidence)
            try:
                cooldown = retry_after_observation(getattr(response, "headers", None), now=observed_at)
            except Exception:
                cooldown = {}
            evidence.update(cooldown)
            if "retry_after_seconds" in cooldown:
                deadline = observed_at + timedelta(seconds=cooldown["retry_after_seconds"])
                evidence["retry_not_before_utc"] = deadline.isoformat()
            observations.append(evidence)
            raise hold
        if type(status) is int and 100 <= status <= 599:
            observations.append({"status": status,
                                 **retry_after_observation(getattr(response, "headers", None))})
        return response

    client.request.get = observed_get
    try:
        body = get_body(client, url)
        if hold is not None:
            raise hold
        return body
    finally:
        client.request.get = original_get


def source_manifest(root):
    paths = list((root / "src").rglob("*.py"))
    paths += [root / name for name in ("pyproject.toml", "title-blacklist.txt", "title-review-list.txt") if (root / name).is_file()]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main():
    require(len(sys.argv) == 2, "one explicit candidate root is required")
    root = Path(sys.argv[1]).resolve(strict=True)
    expected = Path("/tmp/jsh-amphenol-current-validation.fehq8g9f/candidate").resolve(strict=True)
    require(root == expected, "candidate root differs from this exact task")
    before = source_manifest(root)
    require(digest(before) == "7e371be5094a3d23de58af47e8e8607c7f64d6d35a4a7e58bfb365baa132bdea",
            "source manifest differs from independently frozen candidate")
    require(before["src/job_search_helper/acquiretm.py"] == "895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d"
            and before["src/job_search_helper/ats.py"] == "111ccb9067402832ad96b798100dfca293668cf24830409874c1ab4d6eaac07e",
            "adapter or dispatcher differs from accepted source")
    sys.path.insert(0, str(root / "src"))
    from job_search_helper import ats, acquiretm, company_sources, shared_boards
    for module in (ats, acquiretm, company_sources, shared_boards):
        require(Path(module.__file__).resolve().is_relative_to(root / "src"), "foreign source import")
    source = "https://amphenol-aerospace.acquiretm.com/home.aspx"
    require(acquiretm.SOURCE == source, "candidate changed canonical source")
    emit({"stage": "started", "task": "WRAP-6a3a372032", "at": datetime.now(timezone.utc).isoformat(),
          "candidate": str(root), "source_manifest_digest": digest(before),
          "inputs": {"ats": "AcquireTM", "url": source, "company_id": "COMP-0490", "company": "Amphenol Aerospace"}})

    parse = acquiretm.parse_listing
    inventory = acquiretm.inventory
    get_body = acquiretm._DetailClient.get_body
    current = {}

    def observe_parse(body):
        result = parse(body)
        total, rows, pages = result
        current["pages"].append({"total": total, "ids": sorted(rows), "page_controls": sorted(pages)})
        return result

    def observe_inventory(*args, **kwargs):
        current["pages"] = []
        result = inventory(*args, **kwargs)
        page_evidence = current["pages"]
        current["listings"].append({"entries": result, "pages": page_evidence})
        emit({"stage": "listing_observed", "run": current["run"], "listing_number": len(current["listings"]),
              "pages": page_evidence, "membership_digest": digest(result), "entries": result})
        return result

    def observe_body(client, url):
        observations = current["detail_responses"].setdefault(url, [])
        try:
            body = observe_detail_response(client, url, get_body, observations)
        except Exception as error:
            emit({"stage": "detail_response_failed", "run": current["run"], "url": url,
                  "responses": observations, "type": type(error).__name__})
            raise
        emit({"stage": "detail_response_observed", "run": current["run"], "url": url,
              "responses": observations})
        records = shared_boards.Scripts(body).jobs()
        require(len(records) == 1, "independent detail check: nonunique JSON-LD JobPosting")
        record = records[0]
        current["details"][url] = record
        return body

    acquiretm.parse_listing = observe_parse
    acquiretm.inventory = observe_inventory
    acquiretm._DetailClient.get_body = observe_body
    cohorts = []
    for number in (3,):
        current.clear()
        current.update(run=number, pages=[], listings=[], details={}, detail_responses={})
        try:
            result = ats.fetch_inventory("AcquireTM", source, "COMP-0490", "Amphenol Aerospace")
        except DetailRateLimitHold as hold:
            emit({"stage": "held_provider_rate_limit", "run": number, **hold.evidence})
            require(source_manifest(root) == before, "candidate changed during evaluation")
            return 1
        emit({"stage": "dispatch_returned", "run": number, "status": result.status,
              "reason": result.reason, "count": len(result.jobs), "source_url": result.source_url,
              "ats": result.ats, "listing_passes": len(current["listings"]),
              "details_observed": len(current["details"])})
        require(result.status == "complete", "normal dispatch is not complete")
        require(result.source_url == source and result.ats == "AcquireTM", "returned source/ATS differs")
        listings = current["listings"]
        require(len(listings) >= 2, "complete initial/final listing observations are missing")
        require(listings[0]["entries"] == listings[-1]["entries"], "final listing membership changed")
        entries = listings[-1]["entries"]
        for listing in listings:
            pages = listing["pages"]
            require(bool(pages), "listing has no independently observed advertised total")
            totals = {page["total"] for page in pages}
            ids = [ident for page in pages for ident in page["ids"]]
            require(len(totals) == 1 and len(ids) == len(set(ids)), "page totals changed or IDs repeated")
            require(set(ids) == set(listing["entries"]) and len(ids) == next(iter(totals)), "incomplete advertised inventory")
        jobs = result.jobs
        require(len(jobs) == len(entries), "normal result omits or duplicates listed jobs")
        require({str(job["posting_id"]) for job in jobs} == set(entries), "returned job IDs differ from complete listing")
        require(len({job["url"] for job in jobs}) == len(jobs), "duplicate returned URL")
        details = []
        for job in jobs:
            ident, url = str(job["posting_id"]), job["url"]
            parsed = urlsplit(url)
            require(parsed.scheme == "https" and parsed.hostname == "amphenol-aerospace.acquiretm.com"
                    and parsed.path == "/job_details_clean.aspx" and parse_qs(parsed.query) == {"ID": [ident]}, "foreign detail URL")
            require(url == entries[ident]["url"] and job["title"] == entries[ident]["title"], "listing/detail identity changed")
            record = current["details"].get(url)
            require(record is not None, "full detail response was not observed")
            identifier = record.get("identifier", {})
            record_id = identifier.get("value") if isinstance(identifier, dict) else identifier
            require(str(record_id) == ident and record.get("url") == url
                    and ats.text(record.get("title")) == job["title"], "JSON-LD identity mismatch")
            employer = " ".join(str(record.get("hiringOrganization", {}).get("name", "")).split()).casefold()
            require(employer in {"amphenol aerospace", "amphenol aerospace operations"}, "foreign employer")
            description = ats.text(record.get("description"))
            require(len(description) >= 120 and job["description"] == description, "missing or truncated full description")
            details.append({"id": ident, "url": url, "employer": employer,
                            "description_chars": len(description), "description_sha256": hashlib.sha256(description.encode()).hexdigest()})
        cohort = sorted((str(job["posting_id"]), job["url"], job["title"]) for job in jobs)
        cohorts.append(cohort)
        emit({"stage": "run_verified", "run": number, "cohort_digest": digest(cohort), "details": details})
        require(source_manifest(root) == before, "candidate changed during evaluation")
    require(digest(cohorts[0]) == '728760e92022eccd9a959341c45951b2dda5b1ae7de0d0a26ae5b5658918150b', "fresh complete membership differs from the prior complete observation")
    require(digest(sorted(details, key=lambda item: item["id"])) == 'dfc88fe9ea1383495535d8b1d8715f7e37f5df886f24fa4702dd17688d6cab71',
            "fresh full-detail digests differ from the prior complete observation")
    emit({"stage": "separate_candidate_confirmation_passed", "at": datetime.now(timezone.utc).isoformat(),
          "count": len(cohorts[0]), "source_manifest_digest": digest(before),
          "installation": "not_performed", "storage_sync": "not_performed", "backup": "not_verified"})


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        emit({"stage": "failed", "type": type(error).__name__, "reason": str(error)})
        raise SystemExit(1)
