"""Disposable Sprint 1 integration tests. Run with Python 3.11 or newer.

Set JSH_S1_BASE and JSH_S1_CANDIDATE to use alternate copies of the exact
pinned fixtures.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest


INSTALLER = Path(__file__).with_name("installer.py")
BASE = Path(os.environ.get("JSH_S1_BASE", "/tmp/jsh-f3-production-source-rollback.O6bjzo"))
CANDIDATE = Path(os.environ.get("JSH_S1_CANDIDATE", "/tmp/jsh-f3-resume.ErTFRd"))
PREFLIGHT_BASE_DIGEST = "8a3c42b90063bf780733166cb8817c60e550c9da6b35c6475449b6fadc33862e"
EXPECTED_BASE_DIGEST = "7db9d0c151a5a0f3599b1d942d315604ab20284362d35c9a6ec32b17c98f5cd6"
EXPECTED_AFTER_DIGEST = "a8341ba3eeca99a2e52e02a1372143340e7fd3eb84b678bd80b4b7267e79a847"
SCOPE = (
    "job-search-helper",
    "job-search-scraper",
    "release_admission_bootstrap.py",
    "src/job_search_helper/cli.py",
    "src/job_search_helper/engine.py",
    "src/job_search_helper/exact_cycle_recovery.py",
    "src/job_search_helper/inbox.py",
    "src/job_search_helper/integration_release.py",
    "src/job_search_helper/launcher.py",
    "src/job_search_helper/local_pipeline.py",
    "src/job_search_helper/runner.py",
    "src/job_search_helper/scrape_first_pass.py",
    "src/job_search_helper/sync_cli.py",
)
BOOTSTRAP = "release_admission_bootstrap.py"
ENGINE = "src/job_search_helper/engine.py"
HOLD_ID = "fixture-maintenance"
PACKAGE = "src/job_search_helper"
PARKED = "src/.f3-maintenance-package"

VERIFIER = """
import fcntl
import json
from pathlib import Path
import sys

controller = Path(__file__).parent
persisted = json.loads((controller / "hold.json").read_text())
request = json.load(sys.stdin)
identity = {
    "schema": "sprint-1-hold-check-v1",
    "project": str(controller / "project"),
    "state": str(controller / "transaction"),
    "gate": str(controller / "gate"),
    "marker": str(controller / "project/.state/integration-release-journal.json"),
    "maintenance_id": "fixture-maintenance",
}
if any(request[key] != expected for key, expected in identity.items()):
    sys.exit("fixture controller rejected conflicting identity")
if not persisted["routes_closed"] or request["checkpoint"] == persisted.get("deny"):
    sys.exit("fixture controller rejected open route")
with Path(request["gate"]).open("r") as gate:
    try:
        fcntl.flock(gate, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        sys.exit("fixture controller found an unlocked gate")
marker = json.loads(Path(identity["marker"]).read_text())
if marker != {
    "schema": "integration-release-journal-v1",
    "state": "FOUNDATION_MAINTENANCE",
    "maintenance_id": identity["maintenance_id"],
}:
    sys.exit("fixture controller rejected marker")
with (controller / "verifier.log").open("a") as log:
    print(json.dumps(request), file=log)
if persisted.get("stale"):
    request["nonce"] = "stale"
print(json.dumps({**request, "verified": True}))
"""

# Inject faults only in subprocesses. Kill after the real rename returns, at
# the boundary immediately before write_atomic would fsync either directory.
SUBPROCESS_PROBE = """
import json
import os
from pathlib import Path
import runpy
import signal
import sys

installer, probe, target, state, log, *arguments = sys.argv[1:]
sys.argv = [installer, *arguments]
real_replace = os.replace
real_fsync = os.fsync

def replace(source, destination, *, src_dir_fd=None, dst_dir_fd=None):
    hit = False
    if probe == "source":
        parent = Path(os.readlink(f"/proc/self/fd/{dst_dir_fd}"))
        hit = parent / destination == Path(target)
    if probe == "journal" and destination == "transaction.json":
        fd = os.open(source, os.O_RDONLY, dir_fd=src_dir_fd)
        with os.fdopen(fd) as stream:
            hit = json.load(stream)["phase"] == target
    real_replace(source, destination, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
    if hit:
        os.kill(os.getpid(), signal.SIGKILL)

def fsync(fd):
    real_fsync(fd)
    path = os.readlink(f"/proc/self/fd/{fd}")
    if path == state:
        with open(log, "a") as stream:
            print(path, file=stream)

os.replace = replace
os.fsync = fsync
runpy.run_path(installer, run_name="__main__")
"""


def measure(path):
    return stat.S_IMODE(path.stat().st_mode), hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root, package=PACKAGE):
    return {path: measure(root / path.replace(PACKAGE, package, 1)) for path in SCOPE}


def manifest_digest(manifest):
    rows = (f"{mode:04o} {sha} {path}\n" for path, (mode, sha) in sorted(manifest.items()))
    return hashlib.sha256("".join(rows).encode()).hexdigest()


def byte_manifest_digest(manifest):
    rows = (f"{sha}  {path}\n" for path, (_, sha) in sorted(manifest.items()))
    return hashlib.sha256("".join(rows).encode()).hexdigest()


def snapshot(root, excluded=()):
    result = {}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_dir() or name in excluded:
            continue
        info = path.stat()
        result[name] = (measure(path), info.st_ino, info.st_uid, info.st_gid, info.st_mtime_ns)
    return result


class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before, cls.after = source_manifest(BASE), source_manifest(CANDIDATE)
        if (byte_manifest_digest(cls.before) != PREFLIGHT_BASE_DIGEST
                or manifest_digest(cls.before) != EXPECTED_BASE_DIGEST):
            raise ValueError(f"Base fixture does not match the pinned bytes and modes: {BASE}")
        if manifest_digest(cls.after) != EXPECTED_AFTER_DIGEST:
            raise ValueError(f"Candidate fixture does not match the pinned bytes and modes: {CANDIDATE}")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jsh-sprint-1-installer-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.candidate = self.root / "candidate"
        for destination, original in ((self.project, BASE), (self.candidate, CANDIDATE)):
            (destination / "src/job_search_helper").mkdir(parents=True)
            for path in SCOPE:
                shutil.copy2(original / path, destination / path)
        for destination in (self.project, self.candidate):
            (destination / "src/job_search_helper/__init__.py").write_text("")
        (self.candidate / "candidate-only.txt").write_text("must never appear in the runtime\n")
        (self.project / "project-only.txt").write_text("keep local settings\n")
        (self.project / ".storage-backend").write_text("sqlite\n")
        (self.project / "pyproject.toml").write_text('[project]\nname = "fixture"\n')
        runtime_state = self.project / ".state"
        runtime_state.mkdir(mode=0o700)
        (runtime_state / "state.db").write_bytes(b"synthetic no-job-data sentinel\0\xff")
        self.marker = runtime_state / "integration-release-journal.json"
        self.marker.write_text(json.dumps({
            "schema": "integration-release-journal-v1",
            "state": "FOUNDATION_MAINTENANCE",
            "maintenance_id": HOLD_ID,
        }))
        self.original_marker = self.marker.read_bytes()
        self.gate = self.root / "gate"
        self.gate.touch(mode=0o600)
        self.state = self.root / "transaction"
        self.state.mkdir(mode=0o700)
        self.journal = self.state / "transaction.json"
        self.verifier = self.root / "verifier"
        self.verifier.write_text(f"#!{sys.executable}\n" + VERIFIER)
        self.verifier.chmod(0o700)
        self.fsync_log = self.root / "fsync.log"
        self.set_controller()
        self.before_unscoped = snapshot(self.project, SCOPE)
        self.candidate_snapshot = snapshot(self.candidate)

    def set_controller(self, **overrides):
        hold = {"routes_closed": True, **overrides}
        (self.root / "hold.json").write_text(json.dumps(hold))

    def invoke(self, action, *, candidate=False, parked=False, probe=None, target=""):
        args = [action, "--project", str(self.project), "--state", str(self.state),
                "--gate", str(self.gate), "--marker", str(self.marker),
                "--verifier", str(self.verifier), "--hold-id", HOLD_ID]
        if candidate:
            args += ["--candidate", str(self.candidate)]
        if parked:
            args.append("--parked-package")
        command = [sys.executable, str(INSTALLER)]
        if probe:
            command = [sys.executable, "-c", SUBPROCESS_PROBE, str(INSTALLER), probe,
                       str(target), str(self.state), str(self.fsync_log)]
        return subprocess.run([*command, *args], cwd=self.root,
                              env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
                              capture_output=True, text=True, timeout=25)

    def phase(self):
        return json.loads(self.journal.read_text())["phase"]

    def assertReceipt(self, result, phase):
        self.assertEqual(result.returncode, 0, result)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["phase"], phase)
        self.assertEqual(receipt["maintenance_id"], HOLD_ID)
        self.assertEqual(receipt["before_manifest_sha256"], EXPECTED_BASE_DIGEST)
        self.assertEqual(receipt["after_manifest_sha256"], EXPECTED_AFTER_DIGEST)
        self.assertEqual(self.phase(), phase)
        self.assertEqual(self.marker.read_bytes(), self.original_marker)
        return receipt

    def assertRejected(self, result, stderr):
        self.assertEqual(result.returncode, 1, result)
        self.assertIn(stderr, result.stderr)
        self.assertEqual(result.stdout, "")

    def assertMixed(self, through, old, new):
        split = SCOPE.index(through) + 1
        expected = {path: (new if index < split else old)[path]
                    for index, path in enumerate(SCOPE)}
        self.assertEqual(source_manifest(self.project), expected)

    def assertPayload(self, side, manifest):
        for index, path in enumerate(SCOPE):
            self.assertEqual(measure(self.state / f"{side}-{index:02d}"), manifest[path], path)

    def assertUnscoped(self):
        self.assertEqual(snapshot(self.project, SCOPE), self.before_unscoped)
        self.assertEqual(snapshot(self.candidate), self.candidate_snapshot)

    def assertBootstrapHeld(self):
        bootstrap = self.project / BOOTSTRAP
        result = subprocess.run([sys.executable, "-I", "-S", str(bootstrap), "start"],
                                cwd=self.project, text=True, capture_output=True, timeout=10,
                                env={"JOB_STORAGE_BACKEND": "sqlite",
                                     "STATE_DB_FILE": ".state/state.db"})
        self.assertEqual(result.returncode, 2, result)
        self.assertIn("Interrupted integration release blocks pre-import scraper admission",
                      result.stderr)
        self.assertEqual(result.stdout, "")

    def test_exact_manifests_install_idempotence_and_rollback(self):
        self.assertTrue(all(self.before[path] != self.after[path] for path in SCOPE))
        original_owners = {}
        for path in SCOPE:
            info = (self.project / path).stat()
            original_owners[path] = (info.st_uid, info.st_gid)
        installed = self.assertReceipt(self.invoke("install", candidate=True), "INSTALLED")
        self.assertEqual(source_manifest(self.project), self.after)
        after_files = snapshot(self.project)
        self.assertEqual(self.assertReceipt(self.invoke("install"), "INSTALLED"), installed)
        self.assertEqual(self.assertReceipt(self.invoke("verify"), "INSTALLED"), installed)
        self.assertEqual(snapshot(self.project), after_files)
        self.assertPayload("before", self.before)
        self.assertPayload("after", self.after)
        rolled_back = self.assertReceipt(self.invoke("rollback"), "ROLLED_BACK")
        self.assertEqual(source_manifest(self.project), self.before)
        restored_files = snapshot(self.project)
        self.assertEqual(self.assertReceipt(self.invoke("rollback"), "ROLLED_BACK"), rolled_back)
        self.assertEqual(self.assertReceipt(self.invoke("verify"), "ROLLED_BACK"), rolled_back)
        self.assertEqual(snapshot(self.project), restored_files)
        for path, owner in original_owners.items():
            info = (self.project / path).stat()
            self.assertEqual((info.st_uid, info.st_gid), owner, path)
        self.assertRejected(self.invoke("install", candidate=True), "Rollback selected")
        self.assertUnscoped()

    def test_install_death_replays_with_durable_payload_and_no_candidate(self):
        died = self.invoke("install", candidate=True, probe="source", target=self.project / ENGINE)
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        self.assertEqual(died.stdout, "")
        self.assertEqual(self.phase(), "INSTALLING")
        self.assertMixed(ENGINE, self.before, self.after)
        self.assertPayload("before", self.before)
        self.assertPayload("after", self.after)
        self.assertRejected(self.invoke("verify"), "No terminal transaction")
        shutil.rmtree(self.candidate)
        self.assertReceipt(self.invoke("install"), "INSTALLED")
        self.assertEqual(source_manifest(self.project), self.after)
        self.assertEqual(snapshot(self.project, SCOPE), self.before_unscoped)

    def test_rollback_death_replays_with_no_candidate_or_after_payload(self):
        self.assertReceipt(self.invoke("install", candidate=True), "INSTALLED")
        (self.state / "after-00").unlink()
        died = self.invoke("rollback", probe="source", target=self.project / ENGINE)
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        self.assertEqual(died.stdout, "")
        self.assertEqual(self.phase(), "ROLLING_BACK")
        self.assertMixed(ENGINE, self.after, self.before)
        self.assertPayload("before", self.before)
        self.assertRejected(self.invoke("verify"), "No terminal transaction")
        self.assertRejected(self.invoke("install"), "Rollback selected")
        self.assertReceipt(self.invoke("rollback"), "ROLLED_BACK")
        self.assertEqual(source_manifest(self.project), self.before)
        self.assertUnscoped()

    def test_rollback_can_start_from_crashed_install_and_both_bootstraps_hold(self):
        died = self.invoke("install", candidate=True, probe="source",
                           target=self.project / SCOPE[0])
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        self.assertMixed(SCOPE[0], self.before, self.after)
        self.assertEqual(measure(self.project / BOOTSTRAP), self.before[BOOTSTRAP])
        self.assertBootstrapHeld()
        died = self.invoke("install", probe="source", target=self.project / BOOTSTRAP)
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        self.assertMixed(BOOTSTRAP, self.before, self.after)
        self.assertEqual(measure(self.project / BOOTSTRAP), self.after[BOOTSTRAP])
        self.assertBootstrapHeld()
        self.assertReceipt(self.invoke("rollback"), "ROLLED_BACK")
        self.assertEqual(source_manifest(self.project), self.before)

    def test_terminal_rename_death_requires_directory_sync_before_receipt(self):
        for action, terminal, kwargs in (("install", "INSTALLED", {"candidate": True}),
                                         ("rollback", "ROLLED_BACK", {})):
            with self.subTest(terminal=terminal):
                died = self.invoke(action, probe="journal", target=terminal, **kwargs)
                self.assertEqual(died.returncode, -signal.SIGKILL, died)
                self.assertEqual(died.stdout, "")
                self.assertEqual(self.phase(), terminal)
                self.fsync_log.unlink()
                self.assertReceipt(self.invoke("verify", probe="fsync"), terminal)
                self.assertTrue(self.fsync_log.exists(), "receipt returned without fsyncing the state directory")

    def test_missing_or_corrupt_backup_blocks_source_writes(self):
        died = self.invoke("install", candidate=True, probe="source", target=self.project / ENGINE)
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        mixed = snapshot(self.project)
        backup = self.state / "before-00"
        original = backup.read_bytes()
        backup.unlink()
        self.assertRejected(self.invoke("install"), "before-00")
        self.assertRejected(self.invoke("rollback"), "before-00")
        self.assertEqual(snapshot(self.project), mixed)
        backup.write_bytes(b"corrupt durable backup")
        backup.chmod(self.before[SCOPE[0]][0])
        self.assertRejected(self.invoke("install"), "before payload digest or mode drift")
        self.assertRejected(self.invoke("rollback"), "before payload digest or mode drift")
        self.assertEqual(snapshot(self.project), mixed)
        backup.write_bytes(original)
        self.assertReceipt(self.invoke("rollback"), "ROLLED_BACK")
        self.assertUnscoped()

    def test_unverified_hold_marker_and_competing_gate_are_fail_closed(self):
        self.set_controller(routes_closed=False)
        self.assertRejected(self.invoke("install", candidate=True), "fixture controller rejected open route")
        self.set_controller(stale=True)
        self.assertRejected(self.invoke("install", candidate=True), "did not confirm this checkpoint")
        self.set_controller()
        self.marker.write_text(json.dumps({"state": "COMPLETE"}))
        self.assertRejected(self.invoke("install", candidate=True), "Expected the persistent maintenance marker")
        self.marker.write_bytes(self.original_marker)
        with self.gate.open("r") as other_controller:
            fcntl.flock(other_controller, fcntl.LOCK_EX)
            self.assertRejected(self.invoke("install", candidate=True), "temporarily unavailable")
        self.assertFalse(self.journal.exists())
        self.assertEqual(source_manifest(self.project), self.before)

    def test_rejected_mid_install_checkpoint_preserves_hold_for_replay(self):
        self.set_controller(deny=f"INSTALLING:{BOOTSTRAP}")
        self.assertRejected(self.invoke("install", candidate=True), "fixture controller rejected open route")
        self.assertEqual(self.phase(), "INSTALLING")
        self.assertMixed(SCOPE[1], self.before, self.after)
        self.assertEqual(self.marker.read_bytes(), self.original_marker)
        self.set_controller()
        self.assertReceipt(self.invoke("install"), "INSTALLED")
        with (self.root / "verifier.log").open() as log:
            checks = [json.loads(line) for line in log]
        self.assertEqual(len(checks), len({check["nonce"] for check in checks}))
        self.assertEqual(checks[-1]["checkpoint"], "verified-INSTALLED")
        self.assertUnscoped()

    def test_base_byte_drift_and_candidate_mode_drift_are_rejected(self):
        base_file = self.project / ENGINE
        base_file.write_bytes(b"unrelated local edit")
        self.assertRejected(self.invoke("install", candidate=True), "Base digest or mode drift")
        self.assertEqual(base_file.read_bytes(), b"unrelated local edit")
        self.assertFalse(self.journal.exists())
        shutil.copy2(BASE / ENGINE, base_file)
        candidate_file = self.candidate / SCOPE[0]
        candidate_file.chmod(0o644)
        self.assertRejected(self.invoke("install", candidate=True), "Candidate digest or mode drift")
        self.assertFalse(self.journal.exists())
        self.assertEqual(source_manifest(self.project), self.before)

    def test_unexpected_source_drift_stops_install_and_rollback_without_mutation(self):
        died = self.invoke("install", candidate=True, probe="source", target=self.project / ENGINE)
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        (self.project / SCOPE[-1]).write_text("# concurrent edit\n")
        mixed = snapshot(self.project)
        self.assertRejected(self.invoke("install"), "Unexpected source digest")
        self.assertRejected(self.invoke("rollback"), "Unexpected source digest")
        self.assertEqual(snapshot(self.project), mixed)
        self.assertEqual(self.phase(), "INSTALLING")

    def test_parked_package_replays_and_rejects_replaced_guard_inode(self):
        package = self.project / PACKAGE
        parked = self.project / PARKED
        package.rename(parked)
        package.mkdir()
        guard = package / "__init__.py"
        guard.write_text('raise RuntimeError("fixture import is held")\n')
        guard_snapshot = snapshot(package)
        target = parked / Path(ENGINE).name
        died = self.invoke("install", candidate=True, parked=True, probe="source", target=target)
        self.assertEqual(died.returncode, -signal.SIGKILL, died)
        self.assertEqual(self.phase(), "INSTALLING")
        self.assertEqual(measure(target), self.after[ENGINE])
        self.assertEqual(snapshot(package), guard_snapshot)

        saved_guard = self.root / "saved-guard"
        package.rename(saved_guard)
        shutil.copytree(saved_guard, package)
        interrupted = snapshot(self.project)
        self.assertRejected(self.invoke("install", parked=True), "does not bind this installation")
        self.assertEqual(snapshot(self.project), interrupted)
        shutil.rmtree(package)
        saved_guard.rename(package)

        receipt = self.assertReceipt(self.invoke("install", parked=True), "INSTALLED")
        self.assertIs(receipt["parked_package"], True)
        self.assertEqual(source_manifest(self.project, PARKED), self.after)
        self.assertEqual(self.assertReceipt(self.invoke("verify", parked=True), "INSTALLED"), receipt)
        self.assertReceipt(self.invoke("rollback", parked=True), "ROLLED_BACK")
        self.assertEqual(source_manifest(self.project, PARKED), self.before)
        self.assertEqual(snapshot(package), guard_snapshot)


if __name__ == "__main__":
    unittest.main()
