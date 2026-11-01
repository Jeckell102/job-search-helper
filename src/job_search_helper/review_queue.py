"""Read-only weighted triage for the Job History AI review queue.

The scorer reduces description-token volume without making final job decisions.
Low-score rows remain available for a title-only AI rescue pass, and current
deterministic exclusions are exported separately for audit.
"""
from __future__ import annotations

import json
import logging
import hashlib
import os
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
import re
from pathlib import Path

from .core import canonicalize_url
from .title_audit import load_title_audits
from .efficiency import classify_title
from .screening import screen_posting

FIRST_PASS_BORDERLINE_THRESHOLD = 8
SECOND_PASS_THRESHOLD = 17
HIGH_PRIORITY_THRESHOLD = 30
DEFAULT_THRESHOLD = SECOND_PASS_THRESHOLD
MAX_REFRESH_ATTEMPTS = 3


class ReviewSourcesChanged(RuntimeError):
    """A queue build became stale before publication; safe to rebuild."""


# Positive-only evidence weights. These were initially calibrated against the
# historical Opportunity set; overlapping phrases may intentionally reinforce
# a role family. Keep negative evidence in the downstream responsibility review.
TITLE_WEIGHTS = {
    "field applications engineer": 14,
    "field application engineer": 14,
    "field engineering": 12,
    "field engineer": 9,
    "field service": 11,
    "field support": 10,
    "solutions engineer": 12,
    "solution engineer": 12,
    "solution architect": 6,
    "application support": 9,
    "applications engineer": 10,
    "application engineer": 10,
    "customer engineer": 9,
    "sales engineer": 9,
    "technical product manager": 12,
    "product manager": 10,
    "product line manager": 10,
    "product engineer": 8,
    "technical program manager": 10,
    "program manager": 7,
    "technical project manager": 10,
    "technical project management": 10,
    "project manager": 4,
    "forward deployed": 11,
    "deployment strategist": 10,
    "deployment operations": 9,
    "deployment engineer": 8,
    "network deployment": 8,
    "deployment": 6,
    "mission operations": 10,
    "mission manager": 9,
    "mission lead": 9,
    "mission success": 9,
    "mission strategist": 9,
    "mission management": 7,
    "integration": 7,
    "integrator": 7,
    "customer success": 7,
    "technical account": 8,
    "account manager": 4,
    "technical support": 7,
    "support engineer": 7,
    "service engineer": 7,
    "technical operations": 8,
    "product support": 8,
    "training manager": 9,
    "training program": 8,
    "training specialist": 8,
    "technical instructor": 9,
    "instructor": 7,
    "enablement": 6,
    "adoption manager": 6,
    "demo operations": 10,
    "field test": 9,
    "applications engineering": 10,
    "product specialist": 7,
    "site operations": 9,
    "site manager": 5,
    "operations specialist": 5,
    "operations manager": 5,
    "operations lead": 6,
    "fleet manager": 5,
    "project leader": 4,
    "post sales": 5,
}

DESCRIPTION_WEIGHTS = {
    "customer facing": 3,
    "customer site": 2,
    "field deployment": 3,
    "deployment": 2,
    "systems integration": 3,
    "system integration": 3,
    "integration": 2,
    "technical training": 3,
    "training": 2,
    "enablement": 2,
    "onboarding": 2,
    "readiness": 2,
    "demonstration": 2,
    "demo": 2,
    "troubleshoot": 2,
    "hardware": 2,
    "defense": 2,
    "department of defense": 2,
    "dod": 2,
    "military": 2,
    "government customer": 2,
    "u s government": 2,
    "us government": 2,
    "autonomy": 2,
    "autonomous vehicle": 2,
    "robotics": 2,
    "physical ai": 2,
    "unmanned": 2,
    "uas": 2,
    "usv": 2,
    "rf": 2,
    "communications": 2,
    "networking": 2,
    "mission systems": 3,
    "mission operations": 3,
    "mission": 1,
    "sustainment": 2,
    "field support": 2,
    "professional services": 2,
    "customer requirements": 2,
    "requirements": 1,
    "product roadmap": 2,
    "cross functional": 1,
    "technical support": 2,
    "installation": 1,
    "business development": 1,
    "navy": 2,
    "marine corps": 2,
    "socom": 2,
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _weighted_hits(text: str, weights: dict[str, int], source: str):
    normalized = _normalize(text)
    hits = []
    for phrase, weight in weights.items():
        term = _normalize(phrase)
        suffix = r"(?:s|ing)?" if len(term.split()[-1]) > 3 else ""
        if re.search(r"(?<!\w)" + re.escape(term) + suffix + r"(?!\w)", normalized):
            hits.append({"source": source, "phrase": phrase, "weight": weight})
    return hits


def score_posting(title: str, description: str):
    hits = [
        *_weighted_hits(title, TITLE_WEIGHTS, "title"),
        *_weighted_hits(description, DESCRIPTION_WEIGHTS, "description"),
    ]
    title_score = sum(item["weight"] for item in hits if item["source"] == "title")
    description_score = sum(item["weight"] for item in hits if item["source"] == "description")
    return {
        "score": title_score + description_score,
        "title_score": title_score,
        "description_score": description_score,
        "score_reasons": hits,
    }


def _evidence_map(repo):
    exact = {}
    for _, row in repo.read_columns(
        "Job Evidence", ["Job Key", "Source Hash", "Job Description"]
    ):
        key = str(row.get("Job Key", "") or "")
        source_hash = str(row.get("Source Hash", "") or "")
        description = str(row.get("Job Description", "") or "")
        if key and source_hash and description.strip():
            exact[(key, source_hash)] = description
    return exact


def _score_band(score: int, threshold: int = DEFAULT_THRESHOLD) -> str:
    if score >= HIGH_PRIORITY_THRESHOLD:
        return "SECOND_PASS_HIGH"
    if score >= threshold:
        return "SECOND_PASS_STANDARD"
    if score >= FIRST_PASS_BORDERLINE_THRESHOLD:
        return "FIRST_PASS_BORDERLINE"
    return "FIRST_PASS_LOW"


def _complete_description(description):
    return bool(description.strip()) and "[truncated" not in description.casefold()


def _safe_url(value):
    try:
        return canonicalize_url(str(value or ""))
    except ValueError:
        return ""


def _json_line(record):
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"


def build_review_queues(repo, threshold: int = DEFAULT_THRESHOLD, *, inventory_database=None):
    """Build read-only queues. Scores route work; they never decide fit."""
    if not FIRST_PASS_BORDERLINE_THRESHOLD <= threshold <= HIGH_PRIORITY_THRESHOLD:
        raise ValueError("Second-pass threshold must be between 8 and 30.")
    evidence = _evidence_map(repo)
    headers = ["Job Title", "Added to Opportunities?", "Job Key", "Review Status",
               "Source Hash", "Reconsideration Status", "Job Status", "Salary / Range",
               "Official Job URL"]
    history = repo.read_columns("Job History", headers)
    candidates = []
    known_keys = {str(row.get("Job Key", "") or "") for _, row in history}
    known_urls = {_safe_url(row.get("Official Job URL")) for _, row in history} - {""}
    for row_number, row in history:
        if str(row.get("Added to Opportunities?", "")).strip().casefold() != "pending":
            continue
        if str(row.get("Review Status", "")).strip().casefold() != "needs review":
            continue
        if str(row.get("Reconsideration Status", "")).strip().casefold() == "frozen after 2":
            continue
        if str(row.get("Job Status", "")).strip().casefold() == "closed":
            continue
        key, source_hash = str(row.get("Job Key", "") or ""), str(row.get("Source Hash", "") or "")
        candidates.append(({
            "row_number": row_number, "job_key": key, "source_hash": source_hash,
            "job_title": str(row.get("Job Title", "") or ""),
        }, evidence.get((key, source_hash), ""), row.get("Salary / Range", "")))

    local, coverage = load_title_audits(inventory_database, getattr(repo, "spreadsheet_id", None))
    deduplicated = 0
    for record in local:
        posting = record["posting"]
        # Protect reviewed, claimed and frozen history, including legacy URL keys.
        if record["job_key"] in known_keys or _safe_url(posting.get("url")) in known_urls:
            deduplicated += 1
            continue
        candidates.append(({
            "row_number": None, "job_key": record["job_key"], "source_hash": record["source_hash"],
            "job_title": str(posting.get("title", "") or ""),
            "evidence_source": "local_title_audit", "observed_at": record["observed_at"],
        }, str(posting.get("description", "") or ""), posting.get("compensation", "")))

    first_pass, second_pass, filtered, baseline = [], [], [], []
    descriptions_before = 0
    for identity, description, compensation in candidates:
        title = identity["job_title"]
        scored = score_posting(title, description)
        common = {**identity, "band": _score_band(scored["score"], threshold), **scored}
        baseline.append({**common, "job_description": description})
        descriptions_before += len(description)
        # Independent hard exclusions cannot be rescued by a title-only review.
        screen = screen_posting({"title": title, "description": description,
                                 "compensation": compensation}, skip_title_filter=True)
        if screen.reason:
            filtered.append({**identity, "reason": screen.reason, "first_pass_audit": False})
            continue
        if classify_title(title) == "reject":
            reason = "Title exclusion: matches title-blacklist.txt."
            first_pass.append({**common, "band": "FIRST_PASS_TITLE_FILTER_AUDIT",
                               "python_reason": reason, "evidence_missing": not _complete_description(description)})
            filtered.append({**identity, "reason": reason, "first_pass_audit": True})
        elif _complete_description(description) and scored["score"] >= threshold:
            second_pass.append({**common, "job_description": description})
        else:
            # Missing/truncated evidence overrides routing, not the numerical band.
            first_pass.append({**common, "evidence_missing": not _complete_description(description)})

    order = lambda item: (-item.get("score", 0), item.get("row_number") or 10**12, item["job_key"])
    first_pass.sort(key=order)
    second_pass.sort(key=order)
    filtered.sort(key=order)
    bands = dict.fromkeys(["SECOND_PASS_HIGH", "SECOND_PASS_STANDARD", "FIRST_PASS_BORDERLINE",
                           "FIRST_PASS_LOW", "FIRST_PASS_TITLE_FILTER_AUDIT"], 0)
    bands.update(Counter(item["band"] for item in first_pass + second_pass))
    before = sum(len(_json_line(item)) for item in baseline)
    after = sum(len(_json_line(item)) for item in first_pass + second_pass)
    summary = {
        "first_pass_borderline_threshold": FIRST_PASS_BORDERLINE_THRESHOLD,
        "second_pass_threshold": threshold, "high_priority_threshold": HIGH_PRIORITY_THRESHOLD,
        "first_pass": len(first_pass), "second_pass": len(second_pass),
        "deterministic_filtered": len(filtered), "band_counts": bands,
        "queue_band_counts": {"first_pass": dict(Counter(item["band"] for item in first_pass)),
                              "second_pass": dict(Counter(item["band"] for item in second_pass))},
        "first_pass_missing_evidence": sum(item["evidence_missing"] for item in first_pass),
        "title_filter_audit_overlap": sum(item["first_pass_audit"] for item in filtered),
        "local_title_audit_candidates": len(local) - deduplicated,
        "local_title_audit_existing_history_skipped": deduplicated,
        **coverage,
        "description_chars_before": descriptions_before,
        "full_description_ai_chars_before": before, "initial_ai_chars_after": after,
        "estimated_initial_reduction_pct": round((1 - after / before) * 100, 1) if before else 0.0,
        "reduction_basis": "Serialized JSONL characters, including metadata; excludes prompts, outputs and later rescues. Not measured tokens or cost.",
    }
    return {"summary": summary, "first_pass": first_pass, "second_pass": second_pass,
            "deterministic_filtered": filtered}


def _write_jsonl(path: Path, rows):
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(_json_line(row))
    path.chmod(0o600)


def _export_review_queues_unlocked(repo, output_dir, threshold: int = DEFAULT_THRESHOLD, overwrite=False,
                         *, inventory_database=None):
    from .review_runtime import publication_lock
    from .review_refresh import fingerprint
    from .efficiency import load_title_blacklist, load_title_review_list
    destination = Path(output_dir).expanduser().resolve()
    names = {"first_pass": "first-pass.jsonl", "second_pass": "second-pass.jsonl",
             "deterministic_filtered": "deterministic-filtered.jsonl", "summary": "summary.json"}
    files = {key: destination / name for key, name in names.items()}
    legacy = [destination / name for name in ("full-review.jsonl", "title-audit.jsonl")]
    if not overwrite and any(path.exists() or path.is_symlink() for path in [*files.values(), *legacy]):
        raise ValueError("Review queue output already exists; use --overwrite or another directory.")
    # Build under the separate refresh lock, NOT the reader publication lock.
    # SQLite readers see one source snapshot without blocking WAL writers.
    started = time.monotonic()
    local = getattr(repo, 'is_local', False)
    if local and repo.db.in_transaction:
        raise RuntimeError('Refresh requires its own read snapshot; source transaction is already active')
    if local: repo.db.execute('BEGIN')
    try:
        source = fingerprint(repo, threshold, inventory_database)
        load_title_blacklist.cache_clear(); load_title_review_list.cache_clear()
        result = build_review_queues(repo, threshold=threshold, inventory_database=inventory_database)
    finally:
        if local: repo.db.execute('ROLLBACK')
    build_seconds = time.monotonic() - started
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".refresh-", dir=destination) as staging:
        staging = Path(staging)
        hashes = {}
        for key in ("first_pass", "second_pass", "deterministic_filtered"):
            path = staging / names[key]
            _write_jsonl(path, result[key])
            hashes[names[key]] = hashlib.sha256(path.read_bytes()).hexdigest()
        summary = {**result["summary"], "generated_at": datetime.now(timezone.utc).isoformat(),
                   "file_sha256": hashes, "source_fingerprint": source}
        (staging / names["summary"]).write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        (staging / names["summary"]).chmod(0o600)
        with publication_lock(destination, exclusive=True):
            locked_at = time.monotonic()
            # Never publish a completed build as current if relevant source or
            # policy inputs changed while it was prepared. Old output survives.
            if source is not None and fingerprint(repo, threshold, inventory_database) != source:
                raise ReviewSourcesChanged('Review sources changed during refresh; prior queue preserved. Retry refresh.')
            if not overwrite and any(path.exists() or path.is_symlink() for path in [*files.values(), *legacy]):
                raise ValueError('Review queue output already exists; use --overwrite or another directory.')
            for key in names:  # summary must remain last
                os.replace(staging / names[key], files[key])
            if overwrite:
                for path in legacy:
                    if path.is_file() or path.is_symlink():
                        path.unlink()
            publish_seconds = time.monotonic() - locked_at
    return {**summary, "output_dir": str(destination),
            "files": {key: str(path) for key, path in files.items()},
            'refresh': {'reused': False, 'build_seconds': build_seconds,
                        'publication_lock_seconds': publish_seconds}}


def export_review_queues(repo, output_dir, threshold: int = DEFAULT_THRESHOLD, overwrite=False,
                         *, inventory_database=None, reuse_if_current=False):
    from .review_refresh import refresh_lock, fingerprint, reusable
    destination = Path(output_dir).expanduser().resolve()
    started = time.monotonic()
    # Competing starters recheck after the builder completes: exactly one build
    # for identical source inputs, without serially rebuilding per worker.
    with refresh_lock(destination) as waited:
        current = fingerprint(repo, threshold, inventory_database) if reuse_if_current and overwrite else None
        cached = reusable(destination, current)
        if cached is not None and fingerprint(repo, threshold, inventory_database) == current:
            return {**cached, 'output_dir': str(destination), 'refresh': {
                'reused': True, 'build_seconds': 0, 'publication_lock_seconds': 0,
                'refresh_lock_wait_seconds': waited, 'elapsed_seconds': time.monotonic() - started,
                'attempts': 0, 'retries': 0}}
        for attempt in range(1, MAX_REFRESH_ATTEMPTS + 1):
            try:
                result = _export_review_queues_unlocked(
                    repo, output_dir, threshold, overwrite, inventory_database=inventory_database
                )
            except ReviewSourcesChanged as error:
                if attempt == MAX_REFRESH_ATTEMPTS:
                    raise ReviewSourcesChanged(
                        f'Review sources changed during refresh after {attempt} attempts; '
                        'prior queue preserved. Retry refresh when inputs settle.'
                    ) from error
                logging.getLogger(__name__).warning(
                    'Review sources changed during refresh; retrying (attempt %s of %s). '
                    'Prior queue remains available.', attempt + 1, MAX_REFRESH_ATTEMPTS)
                # The rejected build has released its read snapshot and publication
                # lock. Readers keep using the prior queue while inputs settle.
                time.sleep(0.5 * attempt)
                continue
            result['refresh'].update(refresh_lock_wait_seconds=waited,
                elapsed_seconds=time.monotonic() - started, attempts=attempt, retries=attempt - 1)
            return result
