"""Rehearse the exact scoped install and rollback on disposable MuleLab source."""
import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys

from test_maintenance import MaintenanceTests, installer


ROOT_PATHS = {"job-search-helper", "job-search-scraper", "release_admission_bootstrap.py"}
PACKAGE = "src/job_search_helper"


def endpoint(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Unsafe source endpoint: {path}")
    return {"mode": f"{stat.S_IMODE(info.st_mode):04o}", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def inventory(root):
    paths = {root / name for name in ROOT_PATHS}
    paths.update(path for path in (root / PACKAGE).rglob("*")
                 if path.suffix in {".py", ".json"} and "__pycache__" not in path.parts)
    return {path.relative_to(root).as_posix(): endpoint(path) for path in paths}


def rehearse(production, candidate):
    before = inventory(production)
    after = inventory(candidate)
    if before.keys() - after.keys():
        raise ValueError("Candidate removes installed source")
    scope = {key for key in after if before.get(key) != after[key]}
    if not scope:
        raise ValueError("No source changes to rehearse")
    fixture = MaintenanceTests()
    try:
        fixture.setUp()
        shutil.rmtree(fixture.package)
        shutil.rmtree(fixture.candidate)
        for relpath in sorted(before):
            destination = fixture.project / relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(production / relpath, destination)
        for relpath in sorted(scope):
            destination = fixture.candidate / relpath
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate / relpath, destination)
        entries = {}
        for relpath in sorted(scope):
            owner = (fixture.project / relpath).lstat() if relpath in before else fixture.package.stat()
            entries[relpath] = {"before": before.get(relpath), "after": after[relpath],
                                "owner": [owner.st_uid, owner.st_gid]}
        manifest = installer.encode({"schema": "sprint-3-source-manifest-v1", "paths": entries})
        fixture.manifest.write_bytes(manifest)
        plan_path = fixture.bundle / "plan.json"
        plan = json.loads(plan_path.read_bytes())
        plan["manifest_sha256"] = hashlib.sha256(manifest).hexdigest()
        plan_path.write_bytes(installer.encode(plan))
        shutil.copy2(Path(installer.__file__), fixture.bundle / "installer.py")
        protected = fixture.state_file.read_bytes()
        package_inode = fixture.package.stat().st_ino
        old_guard_inode = fixture.old_parking.stat().st_ino
        untouched = {name: (fixture.project / name).stat().st_ino for name in before.keys() - scope}

        for action, expected in (("install", after), ("rollback", before)):
            fixture.success(action)
            if inventory(fixture.project) != expected:
                raise ValueError(f"Rehearsal {action} did not converge to the exact source inventory")
            if (fixture.package.stat().st_ino != package_inode
                    or fixture.old_parking.stat().st_ino != old_guard_inode
                    or fixture.state_file.read_bytes() != protected
                    or fixture.marker.exists()
                    or json.loads(fixture.service_states.read_bytes()) != fixture.original_services
                    or any((fixture.project / key).stat().st_ino != inode for key, inode in untouched.items())):
                raise ValueError(f"Rehearsal {action} changed protected state")
        return {"manifest_sha256": plan["manifest_sha256"], "added": sorted(scope - before.keys()),
                "replaced": sorted(scope & before.keys()), "install_and_rollback": "VERIFIED_DISPOSABLE"}
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    print(json.dumps(rehearse(*(Path(value).resolve() for value in sys.argv[1:])), sort_keys=True, indent=2))
