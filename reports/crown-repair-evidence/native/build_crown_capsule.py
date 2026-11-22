"""Prepare source-only Crown deployment inputs without changing MuleLab state."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_json(path, document):
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def build(project, handoff, package):
    from coordinator_baseline import binding, files
    from job_search_helper import integration_release as release
    from release_admission_bootstrap import _load_environment, _validate_runtime

    _load_environment(project / ".env")
    journal = project / ".state/integration-release-journal.json"
    prior_hash = digest(journal)
    runtime = _validate_runtime(project, journal.parent)
    if runtime.get("state") != "COMPLETE":
        raise ValueError("Crown requires a complete predecessor runtime.")
    pins = json.loads((handoff / "crown_operator_handoff_source_pins.json").read_text())
    proposed = handoff / "admission-stage"
    if (package / "PREPARED_PACKAGE.json").exists():
        raise ValueError("Use a new private capsule rather than replacing a sealed one.")
    groups = {"app_and_launchers": [], "wrapper_tools": []}
    endpoints = {}
    for name, pin in sorted(pins.items()):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe reviewed source path.")
        target, candidate = project / relative, proposed / relative
        if target.is_symlink() or target.resolve() != target or candidate.resolve() != candidate:
            raise ValueError(f"Expected physical source endpoint: {name}")
        before = release.metadata(target) if target.exists() else None
        expected = pin["before_sha256"]
        if (before["sha256"] if before else None) != expected or digest(candidate) != pin["staged_sha256"]:
            raise ValueError(f"Source pin changed: {name}")
        owner = (target if before else target.parent).stat()
        for side, origin in (("before", target if before else None), ("staged", candidate)):
            if origin is None:
                continue
            image = package / side / relative
            image.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, image)
            if side == "staged" and before:
                image.chmod(before["mode"])
        endpoints[name] = {
            "before": before,
            "staged": release.metadata(package / "staged" / relative),
            "owner": [owner.st_uid, owner.st_gid],
        }
        group = "wrapper_tools" if name.startswith("dev/wrapper-coder/tools/") else "app_and_launchers"
        groups[group].append(name)

    with TemporaryDirectory(dir=package, prefix="baseline-") as scratch:
        baseline = Path(scratch) / "assembly"
        baseline.mkdir()
        for name in files(project):
            destination = baseline / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            origin = package / "staged" / name if name in endpoints else project / name
            shutil.copy2(origin, destination)
        regression = baseline / "tests/test_crown_inventory_regression.py"
        if regression.exists():
            raise ValueError("Crown's private regression already exists in the production baseline.")
        shutil.copy2(handoff / "crown_inventory_regression.py", regression)
        source_digest = release.source_tree_digest(baseline)
        if source_digest != release.source_tree_digest(proposed):
            raise ValueError("The staged full source does not match the reviewed overlay.")
        baseline_manifest = files(baseline)
        baseline_hash = binding(baseline_manifest)["digest"]
        relative_path = f"pilot-bases/crown-{baseline_hash}"
        (package / "pilot-bases").mkdir(mode=0o700)
        baseline.rename(package / relative_path)

    if digest(journal) != prior_hash or _validate_runtime(project, journal.parent) != runtime:
        raise ValueError("The original runtime moved while the capsule was prepared.")
    document = {
        "schema": "crown-owned-native-prepared-package-v1",
        "approval": "PREPARATION_ONLY",
        "live_runtime": runtime,
        "live_journal_sha256": prior_hash,
        "staged_source_sha256": source_digest,
        "package_files": endpoints,
        "groups": groups,
        "pilot_baseline": {
            "relative_path": relative_path,
            "sha256": baseline_hash,
            "file_count": len(baseline_manifest),
        },
    }
    spec = package / "PREPARED_PACKAGE.json"
    write_json(spec, document)
    return {"package_sha256": digest(spec), "source_sha256": source_digest,
            "predecessor_release": runtime["release_id"], "roles": {key: len(value) for key, value in groups.items()},
            "baseline": document["pilot_baseline"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project = args.project.resolve(strict=True)
    package = Path(__file__).resolve().parent
    sys.path[:0] = [str(project), str(project / "src"), str(project / "dev/wrapper-coder/tools")]
    print(json.dumps(build(project, package.parent, package), sort_keys=True))
