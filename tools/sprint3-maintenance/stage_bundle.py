"""Build a source-only Sprint 3 capsule for independent review."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

from host_check import HOLD_ID
from rehearse_source_scope import PACKAGE, inventory


TOOLS = Path("/tmp/jsh-s3-maint")
ATTESTER = Path(__file__).with_name("host_check.py")


def snapshot_package(root, manifest):
    facts = {}
    for name, endpoint in manifest.items():
        if not name.startswith(PACKAGE + "/"):
            continue
        facts[name.removeprefix(PACKAGE + "/")] = {
            "sha256": endpoint["sha256"],
            "size": (root / name).stat().st_size,
            "mode": int(endpoint["mode"], 8),
        }
    return hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def build(production, candidate, bundle):
    before = inventory(production)
    after = inventory(candidate)
    unexpected = before.keys() - after.keys()
    if unexpected:
        raise ValueError(f"Candidate removes source: {sorted(unexpected)}")
    paths = sorted(name for name in after if before.get(name) != after[name])
    if not paths:
        raise ValueError("No Sprint 3 source change")
    bundle.mkdir(mode=0o700)
    manifest = {}
    for name in paths:
        path = production / name if name in before else production / PACKAGE
        owner = path.lstat()
        manifest[name] = {"before": before.get(name), "after": after[name],
                          "owner": [owner.st_uid, owner.st_gid]}
        copy = bundle / "candidate" / name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate / name, copy)
    manifest_path = bundle / "manifest.json"
    raw_manifest = encode({"schema": "sprint-3-source-manifest-v1", "paths": manifest})
    manifest_path.write_bytes(raw_manifest)
    manifest_hash = hashlib.sha256(raw_manifest).hexdigest()
    plan = {"project": str(production), "hold_id": HOLD_ID,
            "unit_directory": str(production.parent / ".config/systemd/user"),
            "systemctl": "/usr/bin/systemctl", "pycache_prefixes": [], "manifest_sha256": manifest_hash}
    (bundle / "plan.json").write_bytes(encode(plan))
    for name in ("controller.py", "gate.py", "installer.py", "verify_hold"):
        shutil.copy2(TOOLS / name, bundle / name)
    versions = {"INSTALLED": snapshot_package(candidate, after), "ROLLED_BACK": snapshot_package(production, before)}
    source = ATTESTER.read_text(encoding="utf-8")
    source = source.replace("MANIFEST_SHA256 = None", f"MANIFEST_SHA256 = {manifest_hash!r}")
    source = source.replace('PACKAGE_SHA256 = {"INSTALLED": None, "ROLLED_BACK": None}',
                            f"PACKAGE_SHA256 = {versions!r}")
    checker = bundle / "host-check"
    checker.write_text(source, encoding="utf-8")
    checker.chmod(0o700)
    return {"manifest_sha256": manifest_hash, "package_pins": versions,
            "added": sorted(set(paths) - before.keys()), "replaced": sorted(set(paths) & before.keys())}


if __name__ == "__main__":
    print(json.dumps(build(*(Path(value).resolve() for value in sys.argv[1:])), indent=2, sort_keys=True))
