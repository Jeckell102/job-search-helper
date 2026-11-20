"""Release a reservation-scoped review queue after exact Sheets confirmation.

This deliberately does not export the global review queue.  It projects only
the Job History identities delivered by one frozen retained publication and
records exact file hashes before advancing the durable release state.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .exact_cycle_planner import _exact_plan_digest
from .retained_dirty_provenance import (
    FIRST_PASS_RELEASED, REMOTE_CONFIRMED, retained_publication,
)
from .review_queue import DEFAULT_THRESHOLD, build_review_queues
from .sqlite_repository import timestamp


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bytes_digest(value):
    return hashlib.sha256(value).hexdigest()


def _final_identity(operation):
    identity = dict(operation.get("identity", {}))
    if not identity:
        raise ValueError("retained_first_pass_identity_missing")
    for values in (operation.get("on_insert", {}), operation.get("values", {})):
        for key in tuple(identity):
            if key in values:
                identity[key] = values[key]
    return identity


def _selected_jobs(repository, plan):
    selected = []
    for operation in plan["remote_projection"]:
        if operation.get("tab") != "Job History":
            continue
        identity = _final_identity(operation)
        matches = repository.matches("Job History", identity)
        if len(matches) != 1:
            raise ValueError("retained_first_pass_job_identity_ambiguous")
        row_id, row = matches[0]
        for values in (operation.get("on_insert", {}), operation.get("values", {})):
            if any(row.get(header, "") != value for header, value in values.items()):
                raise ValueError("retained_first_pass_job_value_changed")
        job_key = str(row.get("Job Key", "") or "").strip()
        source_hash = str(row.get("Source Hash", "") or "").strip()
        if not job_key or not source_hash:
            raise ValueError("retained_first_pass_job_version_missing")
        selected.append({"row_id": row_id, "job_key": job_key,
                         "source_hash": source_hash})
    labels = [(item["job_key"], item["source_hash"]) for item in selected]
    if len(labels) != len(set(labels)):
        raise ValueError("retained_first_pass_job_version_repeated")
    return sorted(selected, key=lambda item: (item["job_key"], item["source_hash"]))


class _SelectedReviewRepository:
    """Read-only projection with no route to unrelated Job History rows."""
    def __init__(self, repository, selected):
        self.repository = repository
        self.spreadsheet_id = repository.spreadsheet_id
        self.is_local = False
        self._history = {item["row_id"] for item in selected}
        self._evidence = {(item["job_key"], item["source_hash"])
                          for item in selected}

    def read_columns(self, tab, headers):
        if tab == "Job History":
            rows = []
            for row_id in sorted(self._history):
                row = self.repository.row(tab, row_id)
                if row is None:
                    raise ValueError("retained_first_pass_job_disappeared")
                rows.append((row_id + 1, {header: row.get(header, "")
                                         for header in headers}))
            return rows
        if tab == "Job Evidence":
            rows = []
            # ``read_columns`` would retrieve the entire shared evidence tab
            # before filtering it.  Resolve only each frozen Job History
            # identity instead; no foreign evidence may enter this projection.
            for job_key, source_hash in sorted(self._evidence):
                matches = self.repository.matches(
                    tab, {"Job Key": job_key, "Source Hash": source_hash})
                if len(matches) > 1:
                    raise ValueError("retained_first_pass_evidence_ambiguous")
                if matches:
                    row_id, row = matches[0]
                    rows.append((row_id + 1, {
                        header: row.get(header, "") for header in headers}))
            return rows
        raise ValueError("retained_first_pass_unexpected_tab")


def _queue_payload(repository, plan, selected, threshold):
    projection = _SelectedReviewRepository(repository, selected)
    result = build_review_queues(projection, threshold=threshold,
                                 inventory_database=None)
    selected_labels = {(item["job_key"], item["source_hash"]) for item in selected}
    observed = set()
    for name in ("first_pass", "second_pass", "deterministic_filtered"):
        for item in result[name]:
            label = (item.get("job_key"), item.get("source_hash"))
            if label not in selected_labels:
                raise ValueError("retained_first_pass_foreign_job_emitted")
            observed.add(label)
    if observed != selected_labels:
        raise ValueError("retained_first_pass_selected_job_missing")
    return result


def _release_material(result, evidence):
    names = {
        "first_pass": "first-pass.jsonl",
        "second_pass": "second-pass.jsonl",
        "deterministic_filtered": "deterministic-filtered.jsonl",
    }
    files = {}
    hashes = {}
    for key, name in names.items():
        value = "".join(_canonical(row) + "\n" for row in result[key]).encode("utf-8")
        files[name] = value
        hashes[name] = _bytes_digest(value)
    summary = {**result["summary"],
               "generated_at": evidence["generated_at"],
               "source_fingerprint": evidence["source_fingerprint"],
               "file_sha256": dict(hashes)}
    summary_value = (json.dumps(
        summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    files["summary.json"] = summary_value
    hashes["summary.json"] = _bytes_digest(summary_value)
    complete = {**evidence, "file_sha256": hashes,
                "counts": {key: len(result[key]) for key in names}}
    complete["evidence_digest"] = _digest(complete)
    files["release.json"] = (json.dumps(
        complete, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return files, complete


def _write_fsynced(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    path.chmod(0o600)


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_release(destination, result, evidence):
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists() or destination.is_symlink():
        raise ValueError("retained_first_pass_output_exists")
    staging = Path(tempfile.mkdtemp(prefix=".retained-first-pass-", dir=parent))
    try:
        files, complete = _release_material(result, evidence)
        for name, value in files.items():
            _write_fsynced(staging / name, value)
        _fsync_directory(staging)
        os.replace(staging, destination)
        _fsync_directory(parent)
        return complete
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _read_release(destination):
    release_path = destination / "release.json"
    if not release_path.is_file() or release_path.is_symlink():
        raise ValueError("retained_first_pass_release_evidence_missing")
    try:
        evidence = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("retained_first_pass_release_evidence_invalid") from error
    claimed = evidence.get("evidence_digest")
    if claimed != _digest({key: value for key, value in evidence.items()
                           if key != "evidence_digest"}):
        raise ValueError("retained_first_pass_release_evidence_invalid")
    expected_names = {"first-pass.jsonl", "second-pass.jsonl",
                      "deterministic-filtered.jsonl", "summary.json"}
    if set(evidence.get("file_sha256", {})) != expected_names:
        raise ValueError("retained_first_pass_release_evidence_invalid")
    for name, expected in evidence["file_sha256"].items():
        path = destination / name
        if (not path.is_file() or path.is_symlink()
                or _file_digest(path) != expected):
            raise ValueError("retained_first_pass_release_file_changed")
    return evidence


def release_retained_first_pass(repository, reservation_digest, plan, output_dir,
                                *, threshold=DEFAULT_THRESHOLD):
    """Create and seal one selected-company queue, then release FIRST PASS."""
    if (not isinstance(plan, dict) or plan.get("exact_plan_version") != 2
            or plan.get("plan_digest") != _exact_plan_digest(plan)):
        raise ValueError("retained_first_pass_plan_invalid")
    publication = retained_publication(repository, reservation_digest)
    if (publication["cycle"] != plan.get("cycle_id")
            or publication["company"] != plan.get("company_id")
            or publication["plan_digest"] != plan.get("plan_digest")):
        raise ValueError("retained_first_pass_plan_binding_changed")
    root = Path(output_dir).expanduser().resolve()
    if root.exists() and (not root.is_dir() or root.is_symlink()):
        raise ValueError("retained_first_pass_output_root_invalid")
    destination = root / ("retained-" + hashlib.sha256(
        str(reservation_digest).encode("utf-8")).hexdigest()[:24])
    if publication["state"] == FIRST_PASS_RELEASED:
        evidence = _read_release(destination)
        if (_digest(evidence) != publication["queue_evidence_digest"]
                or evidence != publication["queue_evidence"]):
            raise ValueError("retained_first_pass_durable_evidence_changed")
        return evidence
    if publication["state"] != REMOTE_CONFIRMED:
        raise ValueError("retained_first_pass_remote_confirmation_required")
    if repository.db.execute("SELECT 1 FROM dirty LIMIT 1").fetchone():
        raise ValueError("retained_first_pass_dirty_cells_present")
    selected = _selected_jobs(repository, plan)
    source = {
        "reservation_digest": reservation_digest,
        "cycle_id": publication["cycle"], "company_id": publication["company"],
        "plan_digest": publication["plan_digest"],
        "receipt_id": publication["receipt_id"],
        "acknowledgement_id": publication["acknowledgement_id"],
        "selected_jobs": selected, "threshold": threshold,
    }
    evidence_base = {
        **source, "source_fingerprint": _digest(source),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(destination),
    }
    result = _queue_payload(repository, plan, selected, threshold)
    if destination.exists() and not destination.is_symlink():
        evidence = _read_release(destination)
        expected_base = {**evidence_base, "generated_at": evidence.get("generated_at")}
        _files, expected = _release_material(result, expected_base)
        if evidence != expected:
            raise ValueError("retained_first_pass_existing_release_changed")
    else:
        evidence = _write_release(destination, result, evidence_base)
    # Recompute the complete queue input and material after file publication.
    # Selected Job Evidence and every queue-affecting history field are mutable
    # independently of the exact-plan values checked by _selected_jobs().
    fresh_selected = _selected_jobs(repository, plan)
    if fresh_selected != selected:
        raise ValueError("retained_first_pass_source_changed")
    fresh_result = _queue_payload(
        repository, plan, fresh_selected, threshold)
    fresh_base = {**evidence_base,
                  "generated_at": evidence.get("generated_at")}
    _fresh_files, fresh_evidence = _release_material(
        fresh_result, fresh_base)
    if fresh_evidence != evidence:
        raise ValueError("retained_first_pass_source_changed")
    if _read_release(destination) != evidence:
        raise ValueError("retained_first_pass_release_file_changed")
    encoded = _canonical(evidence)
    evidence_digest = _digest(evidence)
    with repository.transaction():
        current = retained_publication(repository, reservation_digest)
        if current["state"] == REMOTE_CONFIRMED:
            changed = repository.db.execute(
                "UPDATE retained_publications SET state=?,queue_evidence=?,"
                "queue_evidence_digest=?,first_pass_released_at=? "
                "WHERE reservation_digest=? AND state=?",
                (FIRST_PASS_RELEASED, encoded, evidence_digest, timestamp(),
                 reservation_digest, REMOTE_CONFIRMED)).rowcount
            if changed != 1:
                raise ValueError("retained_first_pass_state_changed")
        elif (current["state"] != FIRST_PASS_RELEASED
              or current["queue_evidence_digest"] != evidence_digest):
            raise ValueError("retained_first_pass_state_changed")
    return evidence
