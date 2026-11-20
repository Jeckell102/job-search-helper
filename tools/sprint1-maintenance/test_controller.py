"""Rehearse the controller and exact installer with disposable files and fake units."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
import gate
import installer


TOOLS = Path(__file__).resolve().parent
BASE = Path("/tmp/jsh-f3-production-source-rollback.O6bjzo")
CANDIDATE = Path("/tmp/jsh-f3-resume.ErTFRd")

SYSTEMCTL = r"""
import json
from pathlib import Path
import sys

root = Path(__file__).parent
units = root / "units"
state = root / "services.json"
status = json.loads(state.read_text())
mode, action, *args = sys.argv[1:]
assert mode == "--user"

def configs(name):
    return sorted((units / (name + ".d")).glob("*.conf"))

if action == "show":
    properties = [arg.split("=", 1)[1] for arg in args if arg.startswith("--property=")]
    blocks = []
    for name, service in status.items():
        active = service["active"]
        all_props = {
            "Id": name,
            "LoadState": "loaded",
            "ActiveState": "active" if active else "inactive",
            "SubState": "running" if active else "dead",
            "UnitFileState": service["enabled"],
            "MainPID": "12345" if active else "0",
            "ControlPID": "0",
            "ControlGroup": "/jsh-s1-disposable-wrapper" if active else "",
            "FragmentPath": str(units / name),
            "DropInPaths": " ".join(map(str, configs(name))),
            "NeedDaemonReload": "no"
        }
        blocks.append("\n".join(f"{key}={all_props[key]}" for key in properties))
    print("\n\n".join(blocks))
elif action in {"stop", "start"}:
    for name in args:
        if action == "start":
            for cfg in configs(name):
                for line in cfg.read_text().splitlines():
                    if line.startswith("ConditionPathExists=!") and Path(line.split("!", 1)[1]).exists():
                        sys.exit("service admission held")
        status[name]["active"] = action == "start"
    state.write_text(json.dumps(status))
elif action != "daemon-reload":
    sys.exit(f"unexpected command: {action}")
"""

HOST_CHECK = r"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
request = json.load(sys.stdin)
root = Path(__file__).parent
package = Path(request["package"])
marker = Path(request["marker"])
checkpoint = request["checkpoint"]
control = root / "fault"
match = control.read_text().splitlines() if control.exists() else []
def parent(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])

if match and match[0] == checkpoint:
    if match[1] == "deny":
        sys.exit("fixture verifier refused " + checkpoint)
    if match[1] == "orphan":
        controller = parent(parent(os.getppid()))
        os.kill(controller, signal.SIGKILL)
        # Let the signal take effect before acknowledging the host check.
        for _ in range(100):
            try:
                state = Path(f"/proc/{controller}/stat").read_text().rsplit(")", 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == "Z":
                break
            time.sleep(0.01)
        else:
            sys.exit("fixture controller did not exit")
    if match[1] == "kill-installer":
        os.kill(parent(os.getppid()), signal.SIGKILL)
    if match[1] == "edit":
        (package / "untouched.py").write_text("unexpected edit\n")
if checkpoint.startswith("held:") or checkpoint == "pre-publish":
    assert marker.is_file()
    assert package.name == ".f3-maintenance-package"
    assert "raise ImportError" in (package.with_name("job_search_helper") / "__init__.py").read_text()
if checkpoint in {"published", "admitted"}:
    assert marker.is_file() and package.name == "job_search_helper"
    services = json.loads((root.parent / "services.json").read_text())
    assert not services["wrapper-development-host.service"]["active"]
    assert not services["job-search-sync.service"]["active"]
    probe = subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import sys; sys.path.insert(0,sys.argv[1]); import job_search_helper", str(package.parent)],
        capture_output=True, text=True)
    if checkpoint == "published":
        assert probe.returncode != 0 and "__init__.so: file too short" in probe.stderr
        assert (package / "__init__.so").read_bytes() == b""
    else:
        assert probe.returncode == 0, probe.stderr
        assert not (package / "__init__.so").exists()
print(json.dumps({**request, "verified": True}))
"""

KILL = r"""
import os
from pathlib import Path
import signal
import sys
path, boundary, *args = sys.argv[1:]
sys.path.insert(0, str(Path(path).parent))
import controller
sys.argv = [path, *args]

def kill():
    os.kill(os.getpid(), signal.SIGKILL)

if boundary in {"hold", "publishing", "admission-ready"}:
    real = controller.Controller.save
    wanted = {"hold": "HELD", "publishing": "PUBLISHING", "admission-ready": "ADMISSION_READY"}[boundary]
    def save(self, record, phase):
        real(self, record, phase)
        if phase == wanted:
            kill()
    controller.Controller.save = save
elif boundary == "park":
    real = controller.gate.park
    def park(*args):
        real(*args)
        kill()
    controller.gate.park = park
elif boundary == "swap":
    real = controller.gate.publish
    def publish(*args):
        real(*args)
        kill()
    controller.gate.publish = publish
elif boundary == "extension-link":
    real = controller.os.link
    def link(source, target, **kwargs):
        real(source, target, **kwargs)
        if target == controller.EXTENSION:
            kill()
    controller.os.link = link
elif boundary == "extension-stage":
    real = controller.write
    def write(path, *args, **kwargs):
        real(path, *args, **kwargs)
        if path.name == controller.STAGED_EXTENSION:
            kill()
    controller.write = write
elif boundary == "admission-unlink":
    real = controller.os.unlink
    def unlink(name, **kwargs):
        real(name, **kwargs)
        if name == controller.EXTENSION:
            kill()
    controller.os.unlink = unlink
elif boundary == "release":
    def restore(*args):
        kill()
    controller.Systemd.restore = restore
controller.main()
"""


def program(path, source):
    path.write_text("#!" + sys.executable + " -I\n" + source)
    path.chmod(0o700)


def manifest(project, parked=False):
    with installer.source_tree(project, parked) as tree:
        return {path: installer.version(*installer.read_file(*installer.entry(tree, path)))
                for path in installer.SCOPE}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jsh-s1-controller-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "prod-copy"
        self.bundle = self.root / "bundle"
        self.bundle.mkdir(mode=0o700)
        self.candidate = self.bundle / "candidate"
        for dest, original in ((self.project, BASE), (self.candidate, CANDIDATE)):
            (dest / "src/job_search_helper").mkdir(parents=True)
            for path in installer.SCOPE:
                shutil.copy2(original / path, dest / path)
        self.package = self.project / "src/job_search_helper"
        self.parked = self.package.with_name(gate.PARKED)
        (self.package / "__init__.py").write_text("")
        self.initializer_inode = (self.package / "__init__.py").stat().st_ino
        self.transient = self.package / "__init__.so"
        (self.package / "untouched.py").write_text("CONSTANT = 42\n")
        (self.project / ".storage-backend").write_text("sqlite\n")
        self.runtime = self.project / ".state"
        self.runtime.mkdir()
        self.data = self.runtime / "state.db"
        self.data.write_bytes(b"fixture state sentinel")
        self.marker = self.runtime / "integration-release-journal.json"
        self.app_locks = [self.project / ".integration-install.lock",
                          *(self.runtime / name for name in ("scraper.lock", "writer.lock",
                                                             "review-writeback.lock"))]
        for path in self.app_locks:
            path.write_bytes(b"existing lease diagnostic\n")
        self.locks = {path: (path.stat().st_ino, path.read_bytes()) for path in self.app_locks}
        self.cache = self.package / "__pycache__"
        self.cache.mkdir()
        (self.cache / "engine.cpython-test.pyc").write_bytes(b"stale")
        (self.cache / "untouched.cpython-test.pyc").write_bytes(b"keep")
        self.prefix = self.root / "prefixed"
        self.prefix_cache = self.prefix / self.package.relative_to("/")
        self.prefix_cache.mkdir(parents=True)
        (self.prefix_cache / "engine.cpython-test.pyc").write_bytes(b"stale")
        self.units = self.root / "units"
        self.units.mkdir()
        self.wrapper = "wrapper-development-host.service"
        self.sync = "job-search-sync.service"
        for name in (self.wrapper, self.sync):
            (self.units / name).write_text("[Service]\nExecStart=/usr/bin/true\n")
        (self.units / (self.sync + ".d")).mkdir()
        (self.units / (self.sync + ".d") / "expiry.conf").write_text("[Unit]\nDescription=Existing policy\n")
        self.services = self.root / "services.json"
        self.prestate = {self.wrapper: {"enabled": "enabled", "active": True},
                         self.sync: {"enabled": "disabled", "active": False}}
        self.services.write_text(json.dumps(self.prestate))
        self.systemctl = self.root / "systemctl"
        program(self.systemctl, SYSTEMCTL)
        for name in ("controller.py", "gate.py", "installer.py", "verify_hold"):
            shutil.copy2(TOOLS / name, self.bundle / name)
        program(self.bundle / "host-check", HOST_CHECK)
        self.plan = self.bundle / "plan.json"
        self.plan.write_text(json.dumps({"project": str(self.project), "hold_id": "fixture",
                                         "unit_directory": str(self.units),
                                         "systemctl": str(self.systemctl),
                                         "pycache_prefixes": [str(self.prefix)]}))
        self.journal = self.bundle / "controller.json"
        self.txn = self.bundle / "transaction" / "transaction.json"
        self.sentinel = self.bundle / "service-hold"
        self.ctl = self.bundle / "controller.py"

    def invoke(self, action="install", kill=None):
        command = [sys.executable, "-I", "-B", str(self.ctl)]
        if kill:
            command = [sys.executable, "-B", "-c", KILL, str(self.ctl), kill]
        return subprocess.run([*command, action], text=True, capture_output=True, timeout=45,
                              env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})

    def import_probe(self):
        return subprocess.run(
            [sys.executable, "-I", "-B", "-c",
             f"import sys; sys.path.insert(0,{str(self.project / 'src')!r}); import job_search_helper"],
            capture_output=True, text=True)

    def check_held(self, parked=True, *, admitted=False):
        self.assertTrue(self.sentinel.is_file())
        self.assertEqual(json.loads(self.marker.read_text())["state"], "FOUNDATION_MAINTENANCE")
        self.assertFalse(json.loads(self.services.read_text())[self.wrapper]["active"])
        for unit in (self.wrapper, self.sync):
            retry = subprocess.run([self.systemctl, "--user", "start", unit], capture_output=True, text=True)
            self.assertEqual(retry.returncode, 1, retry)
            self.assertIn("service admission held", retry.stderr)
        if parked:
            self.assertEqual((self.package / "__init__.py").read_bytes(), gate.MESSAGE)
            self.assertIn("held for source maintenance", self.import_probe().stderr)
        elif admitted:
            probe = self.import_probe()
            self.assertEqual(probe.returncode, 0, probe.stderr)
        else:
            probe = self.import_probe()
            self.assertNotEqual(probe.returncode, 0)
            self.assertIn("__init__.so: file too short", probe.stderr)

    def complete(self, result, expected="INSTALLED"):
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["source"], expected)
        self.assertEqual(value["phase"], "RELEASED")
        self.assertEqual(manifest(self.project), installer.AFTER if expected == "INSTALLED" else installer.BEFORE)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.sentinel.exists())
        self.assertFalse(self.transient.exists())
        self.assertFalse((self.bundle / "admission-guard.pending").exists())
        self.assertEqual((self.package / "__init__.py").read_bytes(), b"")
        self.assertEqual((self.package / "__init__.py").stat().st_ino, self.initializer_inode)
        self.assertEqual(self.import_probe().returncode, 0)
        self.assertEqual(json.loads(self.services.read_text()), self.prestate)
        self.assertEqual(self.data.read_bytes(), b"fixture state sentinel")
        for path, identity in self.locks.items():
            self.assertEqual((path.stat().st_ino, path.read_bytes()), identity)
        self.assertFalse((self.cache / "engine.cpython-test.pyc").exists())
        self.assertFalse((self.prefix_cache / "engine.cpython-test.pyc").exists())
        self.assertEqual((self.cache / "untouched.cpython-test.pyc").read_bytes(), b"keep")
        gate.verify_marker(self.parked)
        return value

    def fault(self, checkpoint, action):
        (self.bundle / "fault").write_text(f"{checkpoint}\n{action}\n")

    def clear_fault(self):
        (self.bundle / "fault").unlink()

    def test_install_and_reopen_same_guard_for_rollback(self):
        self.complete(self.invoke())
        guard = self.parked.stat().st_ino
        self.complete(self.invoke())
        self.complete(self.invoke("rollback"), "ROLLED_BACK")
        self.assertEqual(self.parked.stat().st_ino, guard)
        self.complete(self.invoke("rollback"), "ROLLED_BACK")

    def test_kill_after_exchange_before_hold_journal(self):
        self.assertEqual(self.invoke(kill="park").returncode, -signal.SIGKILL)
        self.check_held()
        self.assertEqual(manifest(self.project, True), installer.BEFORE)
        self.complete(self.invoke())

    def test_kill_after_terminal_record_before_publish(self):
        self.assertEqual(self.invoke(kill="publishing").returncode, -signal.SIGKILL)
        self.check_held()
        self.assertEqual(manifest(self.project, True), installer.AFTER)
        self.complete(self.invoke())

    def test_kill_after_publish_before_journal(self):
        self.assertEqual(self.invoke(kill="swap").returncode, -signal.SIGKILL)
        self.check_held(parked=False)
        self.assertEqual(manifest(self.project), installer.AFTER)
        self.fault("published", "deny")
        refused = self.invoke()
        self.assertIn("fixture verifier refused published", refused.stderr)
        self.check_held(parked=False)
        self.assertEqual(json.loads(self.journal.read_text())["phase"], "PUBLISHED")
        self.clear_fault()
        self.complete(self.invoke())

    def test_kill_after_extension_link_recovers_pinned_inode(self):
        self.assertEqual(self.invoke(kill="extension-link").returncode, -signal.SIGKILL)
        self.check_held()
        stage = self.bundle / "admission-guard.pending"
        extension = self.parked / "__init__.so"
        self.assertTrue(os.path.samefile(stage, extension))
        self.assertEqual(extension.stat().st_nlink, 2)
        original = json.loads(self.journal.read_text())["admission_guard"]["file"]
        self.complete(self.invoke())
        self.assertEqual(json.loads(self.journal.read_text())["admission_guard"]["file"], original)

    def test_kill_after_private_guard_creation_replays_durable_intent(self):
        self.assertEqual(self.invoke(kill="extension-stage").returncode, -signal.SIGKILL)
        self.check_held()
        self.assertEqual(json.loads(self.journal.read_text())["admission_guard"], {"file": None})
        stage = self.bundle / "admission-guard.pending"
        identity = [stage.stat().st_dev, stage.stat().st_ino]
        self.assertFalse((self.parked / "__init__.so").exists())
        self.complete(self.invoke())
        self.assertEqual(json.loads(self.journal.read_text())["admission_guard"]["file"][:2], identity)

    def test_admission_ready_rechecks_updated_source_and_guard(self):
        self.assertEqual(self.invoke(kill="admission-ready").returncode, -signal.SIGKILL)
        self.assertEqual(json.loads(self.journal.read_text())["phase"], "ADMISSION_READY")
        self.check_held(parked=False)
        self.fault("published", "deny")
        self.assertIn("fixture verifier refused published", self.invoke().stderr)
        self.check_held(parked=False)
        self.clear_fault()
        self.complete(self.invoke())

    def test_kill_after_unlink_replays_admitted_probe_before_service_restore(self):
        self.assertEqual(self.invoke(kill="admission-unlink").returncode, -signal.SIGKILL)
        self.assertEqual(json.loads(self.journal.read_text())["phase"], "ADMISSION_READY")
        self.check_held(parked=False, admitted=True)
        self.fault("admitted", "deny")
        self.assertIn("fixture verifier refused admitted", self.invoke().stderr)
        self.check_held(parked=False, admitted=True)
        self.clear_fault()
        self.complete(self.invoke())

    def test_missing_or_substituted_canonical_guard_stops_recovery(self):
        self.assertEqual(self.invoke(kill="swap").returncode, -signal.SIGKILL)
        saved = self.bundle / "original-extension"
        self.transient.rename(saved)
        result = self.invoke()
        self.assertIn("Missing transient import guard", result.stderr)
        self.assertTrue(self.marker.is_file())
        self.assertTrue(self.sentinel.is_file())
        self.transient.touch(mode=0o444)
        self.transient.chmod(0o444)
        result = self.invoke()
        self.assertIn("Transient import guard identity changed", result.stderr)
        self.transient.unlink()
        saved.rename(self.transient)
        self.complete(self.invoke())

    def test_reject_abi_tagged_extension_at_entry(self):
        conflict = self.package / "__init__.abi3.so"
        conflict.touch(mode=0o444)
        result = self.invoke()
        self.assertIn("Unexpected extension initializer", result.stderr)
        self.assertTrue(conflict.is_file())
        self.assertFalse(self.sentinel.exists())
        self.assertFalse(self.marker.exists())

    def test_rehold_guarded_canonical_source_and_resume_rollback(self):
        self.assertEqual(self.invoke(kill="admission-ready").returncode, -signal.SIGKILL)
        self.check_held(parked=False)
        self.assertEqual(self.invoke("rollback", kill="park").returncode, -signal.SIGKILL)
        self.assertEqual(json.loads(self.journal.read_text())["phase"], "REHOLDING")
        self.check_held()
        self.complete(self.invoke("rollback"), "ROLLED_BACK")

    def test_kill_after_marker_removed_before_service_restore(self):
        self.assertEqual(self.invoke(kill="release").returncode, -signal.SIGKILL)
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.sentinel.exists())
        self.assertEqual(manifest(self.project), installer.AFTER)
        self.complete(self.invoke())

    def test_cancel_before_transaction(self):
        self.assertEqual(self.invoke(kill="hold").returncode, -signal.SIGKILL)
        self.check_held()
        value = self.complete(self.invoke("rollback"), "ROLLED_BACK")
        self.assertIsNone(value["receipt"])

    def test_rollback_partial_install(self):
        self.fault("held:INSTALLING:" + installer.SCOPE[3], "kill-installer")
        self.assertEqual(self.invoke().returncode, 1)
        self.check_held()
        self.assertNotEqual(manifest(self.project, True), installer.BEFORE)
        self.assertNotEqual(manifest(self.project, True), installer.AFTER)
        self.clear_fault()
        self.complete(self.invoke("rollback"), "ROLLED_BACK")

    def test_killed_controller_restricts_orphaned_partial_installer(self):
        self.fault("held:INSTALLING:" + installer.SCOPE[3], "orphan")
        self.assertEqual(self.invoke().returncode, -signal.SIGKILL)
        self.check_held()
        mixed = manifest(self.project, True)
        self.assertEqual([mixed[name] for name in installer.SCOPE],
                         [installer.AFTER[name] if i < 3 else installer.BEFORE[name]
                          for i, name in enumerate(installer.SCOPE)])
        self.clear_fault()
        self.complete(self.invoke())

    def test_reject_non_scope_drift_immediately_before_publication(self):
        self.fault("pre-publish", "edit")
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result)
        self.assertIn("Non-scope package changed", result.stderr)
        self.check_held()
        self.clear_fault()
        (self.parked / "untouched.py").write_text("CONSTANT = 42\n")
        result = self.invoke()
        self.assertEqual(result.returncode, 1, result)
        self.assertIn("Non-scope package changed", result.stderr)

    def test_gate_and_existing_integration_lock_contention(self):
        path = self.app_locks[0]
        with path.open("rb") as locked:
            fcntl.flock(locked, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.invoke()
            self.assertEqual(result.returncode, 1, result)
        self.assertEqual(json.loads(self.services.read_text()), self.prestate)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.sentinel.exists())

    def test_conflicting_runtime_journal_and_sync_prestate_rejected(self):
        self.marker.write_text('{"state":"COMPLETE"}')
        result = self.invoke()
        self.assertIn("Existing maintenance path or runtime release journal", result.stderr)
        self.assertEqual(self.marker.read_text(), '{"state":"COMPLETE"}')
        self.marker.unlink()
        self.services.write_text(json.dumps({**self.prestate, self.sync: {"enabled": "enabled", "active": False}}))
        result = self.invoke()
        self.assertIn("Sync must be inactive and disabled", result.stderr)
        self.assertFalse(self.sentinel.exists())


if __name__ == "__main__":
    unittest.main()
