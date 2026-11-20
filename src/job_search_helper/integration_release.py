"""Guarded multi-file integration activation using the normal scraper lock.

The normal scraper and this controller share the existing writer/scraper lock.
An activation journal is written before the first target changes.  Therefore a
process crash cannot make a later scraper accept a partially installed release:
startup refuses every nonterminal journal until an operator invokes the exact
rollback recorded here.

This is a release primitive, not an automatic approval policy.  Its caller
must supply independently reviewed validation evidence and an exact manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile

from .cli import scraper_lock_name, writer_lock
from .repair_retry import RELEASE_BINDING_SCHEMA


MANIFEST_SCHEMA = "integration-release-manifest-v1"
JOURNAL_SCHEMA = "integration-release-journal-v1"
TERMINAL_JOURNAL_STATES = frozenset({"COMPLETE", "ROLLED_BACK"})
_ROOTS = ("src/job_search_helper", "tests", ".state/integration-configs")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def metadata(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError("Release files must be ordinary single-link files")
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
            "mode": stat.S_IMODE(path.stat().st_mode)}


def tree_digest(root, *, suffix=None):
    """Hash a complete ordinary-file tree, excluding interpreter caches."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Release tree must be an ordinary directory")
    values = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("Release tree must not contain symlinks")
        if path.is_file() and (suffix is None or path.suffix == suffix):
            values[relative.as_posix()] = metadata(path)
    return digest(values)


def source_tree_digest(project_root):
    return tree_digest(Path(project_root) / "src/job_search_helper", suffix=".py")


def config_tree_digest(project_root):
    return tree_digest(Path(project_root) / ".state/integration-configs")


def _relative(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Release path must be nonempty text")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError("Release path must be normalized and project-relative")
    if not any(value == root or value.startswith(root + "/") for root in _ROOTS):
        raise ValueError("Release path is outside approved source, test, or configuration roots")
    if value.startswith("src/job_search_helper/") and path.suffix != ".py":
        raise ValueError("Runtime source releases may contain Python modules only")
    if value.startswith("tests/") and (not path.name.startswith("test_") or path.suffix != ".py"):
        raise ValueError("Release tests must use test_*.py names")
    return value


def _file_binding(value, *, before):
    if value is None and before:
        return None
    if not isinstance(value, dict) or set(value) != {"sha256", "size", "mode"}:
        raise ValueError("Release file metadata is incomplete")
    sha = value.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Release file SHA-256 is invalid")
    if type(value.get("size")) is not int or value["size"] < 0:
        raise ValueError("Release file size is invalid")
    if type(value.get("mode")) is not int or value["mode"] < 0 or value["mode"] > 0o777:
        raise ValueError("Release file mode is invalid")
    return {"sha256": sha, "size": value["size"], "mode": value["mode"]}


def canonical_manifest(value):
    required = {"schema", "release_id", "failed_request_id", "company_id", "source_revision", "files",
                "before_source_manifest_sha256", "source_manifest_sha256",
                "dependency_manifest_sha256", "before_config_sha256", "config_sha256",
                "validation_receipt_sha256"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("Release manifest has unsupported fields")
    if value.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("Release manifest schema is unsupported")
    files = value.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Release manifest requires files")
    canonical_files = {}
    for name, binding in sorted(files.items()):
        name = _relative(name)
        if not isinstance(binding, dict) or set(binding) != {"before", "after"}:
            raise ValueError("Release file binding is incomplete")
        before = _file_binding(binding["before"], before=True)
        after = _file_binding(binding["after"], before=False)
        if before == after:
            raise ValueError("Release manifest must not include unchanged files")
        canonical_files[name] = {"before": before, "after": after}
    result = {
        "schema": MANIFEST_SCHEMA,
        "failed_request_id": _bounded(value.get("failed_request_id"), "failed request ID"),
        "company_id": _bounded(value.get("company_id"), "Company ID"),
        "source_revision": _bounded(value.get("source_revision"), "source revision"),
        "files": canonical_files,
        "before_source_manifest_sha256": _sha(value.get("before_source_manifest_sha256")),
        "source_manifest_sha256": _sha(value.get("source_manifest_sha256")),
        "dependency_manifest_sha256": _sha(value.get("dependency_manifest_sha256")),
        "before_config_sha256": _sha(value.get("before_config_sha256")),
        "config_sha256": _sha(value.get("config_sha256")),
        "validation_receipt_sha256": _sha(value.get("validation_receipt_sha256")),
    }
    expected = "REL-" + digest(result)[:24]
    if value.get("release_id") != expected:
        raise ValueError("Release ID does not match the complete immutable manifest")
    result["release_id"] = expected
    return result


def manifest_release_id(value_without_id):
    value = dict(value_without_id)
    value.pop("release_id", None)
    canonical = {
        "schema": value["schema"], "failed_request_id": value["failed_request_id"],
        "company_id": value["company_id"],
        "source_revision": value["source_revision"],
        "files": {name: value["files"][name] for name in sorted(value["files"])},
        "before_source_manifest_sha256": value["before_source_manifest_sha256"],
        "source_manifest_sha256": value["source_manifest_sha256"],
        "dependency_manifest_sha256": value["dependency_manifest_sha256"],
        "before_config_sha256": value["before_config_sha256"],
        "config_sha256": value["config_sha256"],
        "validation_receipt_sha256": value["validation_receipt_sha256"],
    }
    return "REL-" + digest(canonical)[:24]


def release_binding(manifest):
    manifest = canonical_manifest(manifest)
    return {
        "schema": RELEASE_BINDING_SCHEMA,
        "release_id": manifest["release_id"],
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "dependency_manifest_sha256": manifest["dependency_manifest_sha256"],
        "config_sha256": manifest["config_sha256"],
    }


def assert_release_settled(state_directory):
    """Called under the scraper lock before importing/dispatching a run."""
    path = Path(state_directory) / "integration-release-journal.json"
    if not path.exists():
        return None
    journal = _read_json(path)
    if journal.get("schema") != JOURNAL_SCHEMA or journal.get("state") not in TERMINAL_JOURNAL_STATES:
        raise RuntimeError("An interrupted integration release blocks scraper startup; run guarded rollback first")
    return journal


def assert_active_release_binding(state_directory, binding):
    """Require a retry's exact release to remain the active completed release.

    A repair request is intentionally not an authorization to run whatever
    happens to be installed later.  Its full release binding must still be
    present in the durable activation journal, and that journal must describe
    the currently active, successfully completed release.  Missing legacy
    journal bindings and every non-COMPLETE state fail closed.
    """
    from .repair_retry import canonical_release_binding

    required = canonical_release_binding(binding)
    path = Path(state_directory) / "integration-release-journal.json"
    try:
        journal = _read_json(path)
        actual = canonical_release_binding(journal.get("release"))
    except (RuntimeError, ValueError, TypeError) as exc:
        raise ValueError(
            "Repair retry release binding is not the active COMPLETE release; "
            "keeping its durable request and saved work on hold."
        ) from exc
    if (journal.get("schema") != JOURNAL_SCHEMA
            or journal.get("state") != "COMPLETE"
            or actual != required
            or journal.get("release_id") != required["release_id"]):
        raise ValueError(
            "Repair retry release binding is not the active COMPLETE release; "
            "keeping its durable request and saved work on hold."
        )
    return journal


def activate_release(project_root, candidate_root, database, record_root, manifest,
                     *, current_source_revision, dependency_digest, verify=None, fault=None):
    """Activate exact reviewed files while excluding all normal scraper runs."""
    project_root, candidate_root = Path(project_root), Path(candidate_root)
    database, record_root = Path(database), Path(record_root)
    manifest = canonical_manifest(manifest)
    if current_source_revision(manifest["company_id"]) != manifest["source_revision"]:
        raise ValueError("Company source revision changed before release activation")
    if not callable(dependency_digest) or dependency_digest() != manifest["dependency_manifest_sha256"]:
        raise ValueError("Runtime dependency manifest changed before release activation")
    state_directory = database.parent
    journal_path = state_directory / "integration-release-journal.json"
    record = record_root / manifest["release_id"]
    with writer_lock(state_directory / scraper_lock_name()):
        prior = assert_release_settled(state_directory)
        receipt_path = record / "receipt.json"
        if prior and prior.get("state") == "COMPLETE" and receipt_path.exists():
            receipt = _read_json(receipt_path)
            if receipt.get("manifest_sha256") == digest(manifest):
                return receipt
            raise RuntimeError("Completed release identity conflicts with its receipt")
        if record.exists() or record.is_symlink():
            raise ValueError("Release record already exists without a matching completed receipt")
        _verify_inputs(project_root, candidate_root, manifest)
        record.mkdir(parents=True, mode=0o700)
        backup = record / "before"
        backup.mkdir(mode=0o700)
        for name, item in manifest["files"].items():
            if item["before"] is not None:
                target = project_root / name
                destination = backup / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, destination)
                if metadata(destination) != item["before"]:
                    raise RuntimeError("Release backup verification failed")
        journal = {
            "schema": JOURNAL_SCHEMA, "state": "PREPARED",
            "release_id": manifest["release_id"], "manifest_sha256": digest(manifest),
            "release": release_binding(manifest), "record": str(record.resolve()),
            "paths": list(manifest["files"]),
        }
        _write_json(journal_path, journal)
        _write_json(record / "manifest.json", manifest)
        _fault(fault, "prepared")
        try:
            journal["state"] = "INSTALLING"
            _write_json(journal_path, journal)
            for index, (name, item) in enumerate(manifest["files"].items()):
                _atomic_copy(candidate_root / name, project_root / name, item["after"])
                _fault(fault, "installed:" + str(index))
            _verify_installed(project_root, manifest, use_after=True)
            if dependency_digest() != manifest["dependency_manifest_sha256"]:
                raise RuntimeError("Runtime dependency manifest changed during release activation")
            journal["state"] = "INSTALLED"
            _write_json(journal_path, journal)
            evidence = verify(project_root, manifest) if callable(verify) else {"result": "NOT_RUN"}
            if (not isinstance(evidence, dict) or evidence.get("result") != "PASS"
                    or digest(evidence) != manifest["validation_receipt_sha256"]):
                raise RuntimeError("Installed release verification did not pass")
            _verify_installed(project_root, manifest, use_after=True)
            receipt = {
                "state": "COMPLETE", "release_id": manifest["release_id"],
                "failed_request_id": manifest["failed_request_id"],
                "company_id": manifest["company_id"],
                "source_revision": manifest["source_revision"],
                "activated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "manifest_sha256": digest(manifest), "release": release_binding(manifest),
                "verification": evidence,
            }
            _write_json(receipt_path, receipt)
            journal["state"] = "COMPLETE"
            _write_json(journal_path, journal)
            return receipt
        except BaseException:
            # Deliberately retain the nonterminal journal.  Startup remains
            # blocked until guarded rollback inspects the exact installed set.
            raise


def rollback_release(project_root, database, record_root, release_id):
    """Restore only the exact interrupted release while holding scraper admission."""
    project_root, database, record_root = Path(project_root), Path(database), Path(record_root)
    state_directory = database.parent
    journal_path = state_directory / "integration-release-journal.json"
    with writer_lock(state_directory / scraper_lock_name()):
        journal = _read_json(journal_path)
        if (journal.get("schema") != JOURNAL_SCHEMA or journal.get("release_id") != release_id
                or journal.get("state") in TERMINAL_JOURNAL_STATES):
            raise ValueError("No matching interrupted release is available for rollback")
        record = record_root / release_id
        manifest = canonical_manifest(_read_json(record / "manifest.json"))
        if digest(manifest) != journal.get("manifest_sha256"):
            raise RuntimeError("Rollback manifest does not match the durable journal")
        backup = record / "before"
        for name, item in manifest["files"].items():
            target = project_root / name
            actual = metadata(target) if target.exists() else None
            if actual not in (item["before"], item["after"]):
                raise RuntimeError("Rollback target changed outside the recorded release")
        for name, item in manifest["files"].items():
            target = project_root / name
            if item["before"] is None:
                if target.exists():
                    target.unlink()
                    _fsync_directory(target.parent)
            else:
                _atomic_copy(backup / name, target, item["before"])
        _verify_installed(project_root, manifest, use_after=False)
        journal["state"] = "ROLLED_BACK"
        _write_json(journal_path, journal)
        receipt = {"state": "ROLLED_BACK", "release_id": release_id,
                   "manifest_sha256": digest(manifest)}
        _write_json(record / "rollback.json", receipt)
        return receipt


def _verify_inputs(project_root, candidate_root, manifest):
    if source_tree_digest(project_root) != manifest["before_source_manifest_sha256"]:
        raise ValueError("Installed complete source tree changed before activation")
    if config_tree_digest(project_root) != manifest["before_config_sha256"]:
        raise ValueError("Installed complete configuration tree changed before activation")
    for name, item in manifest["files"].items():
        target, candidate = project_root / name, candidate_root / name
        actual = metadata(target) if target.exists() else None
        if actual != item["before"] or metadata(candidate) != item["after"]:
            raise ValueError("Installed or candidate release input changed: " + name)


def _verify_installed(project_root, manifest, *, use_after):
    key = "after" if use_after else "before"
    for name, item in manifest["files"].items():
        path, expected = project_root / name, item[key]
        actual = metadata(path) if path.exists() else None
        if actual != expected:
            raise RuntimeError("Installed release set is incomplete: " + name)
    expected_source = manifest["source_manifest_sha256" if use_after else "before_source_manifest_sha256"]
    expected_config = manifest["config_sha256" if use_after else "before_config_sha256"]
    if source_tree_digest(project_root) != expected_source:
        raise RuntimeError("Installed complete source tree does not match the release")
    if config_tree_digest(project_root) != expected_config:
        raise RuntimeError("Installed complete configuration tree does not match the release")


def _atomic_copy(source, target, expected):
    if metadata(source) != expected:
        raise ValueError("Candidate changed during activation")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".integration-release-", dir=target.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(source.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), expected["mode"])
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if metadata(target) != expected or metadata(source) != expected:
        raise RuntimeError("Atomic release copy verification failed")


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write((_canonical(value) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Release evidence is missing or invalid") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Release evidence must be object JSON")
    return value


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _bounded(value, name):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 256:
        raise ValueError("Release manifest requires bounded " + name)
    return value.strip()


def _sha(value):
    value = _bounded(value, "SHA-256")
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Release manifest SHA-256 is invalid")
    return value


def _fault(callback, stage):
    if callable(callback):
        callback(stage)
