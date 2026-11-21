"""Maintained release-to-retry orchestration for one reviewed integration.

The controller deliberately stops after placing a durable normal-scraper
request.  It never starts a scraper itself.  Repeating the call after a crash
reuses both the completed release receipt and the same retry attempt.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .integration_release import (
    _verify_projected_release,
    activate_release,
    canonical_manifest,
    config_tree_digest,
    source_tree_digest,
)
from .repair_retry import (
    REPAIR_RETRY_SCHEMA,
    RepairRetryBridge,
    retry_attempt_id,
)


def release_and_schedule(project_root, candidate_root, database, record_root, manifest,
                         *, current_source_revision, dependency_digest, verify, fault=None):
    """Activate one exact release and durably schedule its fresh Company retry."""
    return _release_and_schedule(
        project_root, candidate_root, database, record_root, manifest,
        current_source_revision=current_source_revision, dependency_digest=dependency_digest,
        verify=verify, fault=fault,
    )


def release_and_schedule_qualified(project_root, candidate_root, database, record_root, manifest,
                                   *, qualification_owner, current_source_revision, dependency_digest,
                                   verify, fault=None):
    """Enter automatic installation only with an independently qualified candidate."""
    from .release_qualification import _QualificationOwner

    if not isinstance(qualification_owner, _QualificationOwner):
        raise ValueError('An independently configured release qualification owner is required')
    if not callable(verify):
        raise ValueError('Automated release still requires installed candidate verification')
    manifest = canonical_manifest(manifest)

    def preinstall(exact_manifest):
        if (source_tree_digest(candidate_root) != exact_manifest['source_manifest_sha256']
                or config_tree_digest(candidate_root) != exact_manifest['config_sha256']):
            raise ValueError('The complete candidate differs from the qualified source or configuration')
        _verify_projected_release(project_root, exact_manifest)
        qualification_owner.require(exact_manifest)

    qualification_owner.require(manifest)
    return _release_and_schedule(
        project_root, candidate_root, database, record_root, manifest,
        current_source_revision=current_source_revision, dependency_digest=dependency_digest,
        verify=verify, fault=fault, preinstall=preinstall,
    )


def _release_and_schedule(project_root, candidate_root, database, record_root, manifest,
                          *, current_source_revision, dependency_digest, verify, fault, preinstall=None):
    receipt = activate_release(
        project_root, candidate_root, database, record_root, manifest,
        current_source_revision=current_source_revision,
        dependency_digest=dependency_digest, verify=verify, preinstall=preinstall,
    )
    _fault(fault, "after_activation")
    binding = {
        "schema": REPAIR_RETRY_SCHEMA,
        "failed_request_id": receipt["failed_request_id"],
        "company_id": receipt["company_id"],
        "source_revision": receipt["source_revision"],
        "release": receipt["release"],
        "activated_at": receipt["activated_at"],
    }
    binding["attempt_id"] = retry_attempt_id(binding)
    bridge = RepairRetryBridge(
        database, current_source_revision=current_source_revision,
    )
    scheduled = bridge.deliver(binding)
    result = {
        "state": scheduled["state"],
        "release_id": receipt["release_id"],
        "attempt_id": binding["attempt_id"],
        "failed_request_id": binding["failed_request_id"],
        "company_id": binding["company_id"],
        "source_revision": binding["source_revision"],
    }
    record = Path(record_root) / receipt["release_id"] / "release-to-retry.json"
    _write_json(record, result)
    return result


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write((json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _fault(callback, stage):
    if callable(callback):
        callback(stage)
