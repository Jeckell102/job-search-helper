"""Actual isolated entrypoint with a disposable installed release and no pilot."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    harness = load("release_fixture", Path(sys.argv[1]).resolve(strict=True) / "test_combined_release.py")
    harness.ARTIFACTS = Path(tempfile.mkdtemp(prefix="isolated-command.", dir=harness.ROOT))
    print("Disposable isolated command evidence:", harness.ARTIFACTS, flush=True)
    fixture = harness.Fixture("release-command", HERE)
    project, bundle = fixture.project, fixture.bundle
    fixture.environment["SPREADSHEET_ID"] = "fixture-sheet"
    runner = load("pilot_restore_command", HERE / "pilot_restore_command.py")
    for name in runner.TOOLS - set(harness.TOOLS) - {"host-check", "plan.json", "manifest.json"}:
        shutil.copy2(HERE / name, bundle / name)
    venv.EnvBuilder(with_pip=False, symlinks=True).create(project / ".venv")
    installed = fixture.run("install")
    assert installed.returncode == 0, installed.stderr
    assert json.loads(installed.stdout)["phase"] == "RELEASED", installed.stdout

    exchange = load("host_exchange", bundle / "host_exchange.py")

    def pin(path):
        descriptor = os.open(path, os.O_RDONLY)
        try:
            return vars(exchange.pin(descriptor))
        finally:
            os.close(descriptor)

    root = bundle / "fixtures/example"
    control = root / "private"
    control.mkdir(parents=True, mode=0o700)
    lock = control / exchange.LOCK
    lock.touch(mode=0o600)
    parent = root / "routes"
    parent.mkdir(mode=0o700)
    canonical, parked = parent / "copy", parent / ".exchange-park-copy"
    canonical.mkdir(mode=0o700)
    (canonical / "launcher").write_text("fixture only")
    parked.mkdir(mode=0o500)
    policy_file = control / exchange.POLICY
    policy = dict(schema=exchange.POLICY_SCHEMA, mode="fixture", generation="a" * 32,
                  mount_namespace=os.readlink("/proc/self/ns/mnt"), control=str(control),
                  control_pin=pin(control), lock_pin=pin(lock),
                  pairs=[dict(parent=str(parent), canonical=canonical.name, parked=parked.name,
                              parent_pin=pin(parent), original_pin=pin(canonical), sentinel_pin=pin(parked))])
    policy_bytes = exchange.encode(policy)
    harness.write(policy_file, policy_bytes)
    policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
    closure = exchange.HostExchange(policy_file, policy_sha256)
    closure.prepare()
    closure.close()

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    executable = project / ".venv/bin/python"
    selected = {
        "schema": runner.SCHEMA, "tools": {name: digest(bundle / name) for name in runner.TOOLS},
        "project": str(project), "interpreter": str(executable),
        "bootstrap_sha256": digest(project / "release_admission_bootstrap.py"),
        "exchange_policy": str(policy_file), "exchange_policy_sha256": policy_sha256,
        "receiver_database": str(project / "not-created/tasks.sqlite3"),
        "workbook_id_sha256": hashlib.sha256(b"fixture-sheet").hexdigest(),
        "pilot": {"request_sha256": "a" * 64, "reservation_digest": "b" * 64,
                  "source_revision": "c" * 64, "company_event_id": "CEV-" + "d" * 32,
                  "company_id": "COMP-0001", "blocking_cycle_id": "CYC-ABCDEF123456"},
    }
    selection = bundle / "selection.json"
    harness.write(selection, runner.canonical(selected))
    initial = closure.witness()
    prior = fixture.protected()
    # The installed controller fixture deliberately provides opaque protected files
    # in place of live SQLite. Observation must hold before opening any receiver.
    result = subprocess.run([
        str(executable), "-I", "-B", "-X", "pycache_prefix=/dev/null",
        str(bundle / "pilot_restore_command.py"), "observe",
        "--selection", str(selection), "--selection-sha256", digest(selection),
    ], cwd="/", env=fixture.environment, capture_output=True, text=True, timeout=60)
    print(result.stderr.strip(), flush=True)
    assert result.returncode == 1 and not result.stdout, result
    assert "held (RuntimeError)" in result.stderr, result
    assert closure.witness() == initial
    assert fixture.protected() == prior
    assert not Path(selected["receiver_database"]).exists()
    print("Verified isolated launch holds on unavailable pilot evidence with protected files and checkout closure unchanged.")


if __name__ == "__main__":
    main()
