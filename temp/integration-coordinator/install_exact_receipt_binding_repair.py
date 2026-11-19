#!/usr/bin/env python3
"""Atomic rollback-capable install of the exact receipt binding repair."""
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

CANDIDATE = Path(
    "/tmp/job-search-helper-integration-automation/temp/integration-coordinator/"
    "exact-receipt-binding-package-20261119"
)
TARGET = Path("/home/chris/job-search-helper_old")
EXPECTED_COUNT = 4


def sha(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest(path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.removeprefix("*")
        if name in result:
            raise RuntimeError("duplicate_manifest_target:" + name)
        result[name] = digest
    return result


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fsync_dir(path.parent)


def atomic_copy(source, target, mode):
    descriptor, staged = tempfile.mkstemp(
        dir=target.parent, prefix=".exact-receipt-binding-install-"
    )
    try:
        with os.fdopen(descriptor, "wb") as output, open(source, "rb") as input_file:
            shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(staged, mode)
        os.replace(staged, target)
        fsync_dir(target.parent)
    finally:
        if os.path.exists(staged):
            os.unlink(staged)


def main():
    after = manifest(CANDIDATE / "SHA256SUMS")
    before = manifest(CANDIDATE / "PROTECTED_BASELINE_SHA256SUMS")
    if set(after) != set(before) or len(after) != EXPECTED_COUNT:
        raise RuntimeError("installation_manifest_scope")
    for name, digest in after.items():
        source = CANDIDATE / name
        if not source.is_file() or sha(source) != digest:
            raise RuntimeError("candidate_hash:" + name)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = Path(tempfile.mkdtemp(
        prefix="jsh-exact-receipt-binding-" + stamp + "-", dir="/tmp"
    ))
    fsync_dir(backup.parent)
    receipt = {
        "schema": "exact-receipt-binding-install-v1",
        "candidate_manifest_sha256": sha(CANDIDATE / "SHA256SUMS"),
        "protected_baseline_manifest_sha256": sha(
            CANDIDATE / "PROTECTED_BASELINE_SHA256SUMS"
        ),
        "files": {},
        "status": "PREFLIGHT",
    }
    lock_path = TARGET / ".integration-install.lock"
    if not lock_path.is_file():
        raise RuntimeError("integration_install_lock_missing")
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for name, digest in before.items():
            target = TARGET / name
            if not target.is_file() or sha(target) != digest:
                raise RuntimeError("protected_hash:" + name)
            previous = backup / "previous" / name
            previous.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, previous)
            with open(previous, "rb") as backup_stream:
                os.fsync(backup_stream.fileno())
            if sha(previous) != digest:
                raise RuntimeError("rollback_copy_hash:" + name)
            receipt["files"][name] = {
                "before": digest,
                "installed": after[name],
                "mode": target.stat().st_mode & 0o777,
            }
        for directory in sorted(
                {path for path in (backup / "previous").rglob("*") if path.is_dir()},
                key=lambda path: len(path.parts), reverse=True):
            fsync_dir(directory)
        fsync_dir(backup / "previous")
        fsync_dir(backup)
        receipt["status"] = "BACKUP_DURABLE"
        durable_json(backup / "manifest.json", receipt)
        changed = []
        try:
            for name in sorted(after):
                details = receipt["files"][name]
                # Include the target in rollback before replacement starts.
                # atomic_copy can fail after os.replace (for example, while
                # syncing the parent directory), when the target is already
                # changed even though the call did not return.
                changed.append(name)
                atomic_copy(CANDIDATE / name, TARGET / name, details["mode"])
                if sha(TARGET / name) != after[name]:
                    raise RuntimeError("installed_hash:" + name)
        except BaseException:
            for name in reversed(changed):
                details = receipt["files"][name]
                atomic_copy(
                    backup / "previous" / name, TARGET / name, details["mode"]
                )
            for name, details in receipt["files"].items():
                target = TARGET / name
                if not target.is_file() or sha(target) != details["before"]:
                    raise RuntimeError("rollback_hash:" + name)
            receipt["status"] = "ROLLED_BACK"
            durable_json(backup / "manifest.json", receipt)
            raise
        receipt["status"] = "INSTALLED_HASH_VERIFIED"
        durable_json(backup / "manifest.json", receipt)
    print(json.dumps({
        "backup": str(backup), "files": len(after), "status": receipt["status"]
    }, sort_keys=True))


if __name__ == "__main__":
    main()
