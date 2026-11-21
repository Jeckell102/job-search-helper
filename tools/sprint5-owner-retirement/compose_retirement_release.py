"""Reconcile the reviewed release and retirement source without touching either input."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess


PACKAGE = Path("src/job_search_helper")
MERGED = ("engine", "runner", "scan_request", "exact_cycle_sync", "exact_cycle_recovery")
ADDED_PATHS = (
    "retained_cycle_retirement", "retained_cycle_retirement_control",
    "control_before_prefix_runner", "exact_legacy_migration_runner",
    "selected_recovery_runner", "exact_recovery_pause_executor",
)


def endpoint(path):
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Non-regular source endpoint: {path.name}")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}"}


def combine(installed, reviewed, retirement, output):
    if any(output.is_relative_to(root) or root.is_relative_to(output)
           for root in (installed, reviewed, retirement)):
        raise ValueError("Use a separate staging directory.")
    after = output / "after_images"
    shutil.copytree(reviewed, after)
    relative_paths = {p.relative_to(after) for p in after.rglob("*") if p.is_file()}
    if len(relative_paths) != 38:
        raise ValueError("Expected the prior exact 38-path review package.")
    for name in MERGED:
        rel = PACKAGE / (name + ".py")
        merged = subprocess.run(
            ["git", "merge-file", "-p", str(reviewed / rel), str(installed / rel),
             str(retirement / rel)], capture_output=True,
        )
        if merged.returncode:
            raise ValueError(f"Reconcile source conflict in {rel}.")
        (after / rel).write_bytes(merged.stdout)
    for name in ADDED_PATHS:
        rel = PACKAGE / (name + ".py")
        relative_paths.add(rel)
        if name == "control_before_prefix_runner":
            # Carry only the retirement guard into the package. An earlier
            # source-transition preview remains useful as diagnostic source.
            content = (installed / rel).read_text()
            marker = "    with context:\n"
            if content.count(marker) != 1:
                raise ValueError("Expected the original local-only hold boundary.")
            (after / rel).write_text(content.replace(marker, marker + (
                "        from .retained_cycle_retirement_control import assert_cycle_path_not_retired\n"
                '        assert_cycle_path_not_retired(Path(inventory_path).parent / "state.db", cycle_id)\n'
            )))
        else:
            shutil.copy2(retirement / rel, after / rel)
    reports = {}
    for rel in sorted(relative_paths):
        path = after / rel
        if path.suffix == ".py":
            compile(path.read_bytes(), rel.as_posix(), "exec", dont_inherit=True)
        before, replacement = endpoint(installed / rel), endpoint(path)
        if before == replacement:
            raise ValueError(f"Unexpected unchanged path: {rel}.")
        reports[rel.as_posix()] = {"before": before, "after": replacement}
    (output / "COMPOSED_SOURCE_REVIEW.json").write_text(json.dumps({
        "status": "CANDIDATE_FOR_INDEPENDENT_REVIEW",
        "replaces": 38, "adds_exact_paths": len(ADDED_PATHS),
        "path_count": len(reports), "paths": reports,
    }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("installed", "reviewed", "retirement", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    combine(args.installed.resolve(strict=True), args.reviewed.resolve(strict=True),
            args.retirement.resolve(strict=True), args.output.resolve())
