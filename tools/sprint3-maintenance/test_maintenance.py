"""Disposable exact source, process-death, and rollback fixtures for Sprint 3."""
import hashlib
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
REPLACED = "src/job_search_helper/runner.py"
ADDED = "src/job_search_helper/operator_feature.py"
ROOT_LAUNCHER = "job-search-scraper"
BOOTSTRAP = "release_admission_bootstrap.py"

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
            "ControlGroup": "/jsh-s3-disposable-wrapper" if active else "",
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
assert request["source_manifest_sha256"] == json.loads((root / "plan.json").read_text())["manifest_sha256"]
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
    assert package.name == ".s3-maintenance-package"
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


# This modifier is written only into the disposable installer copy. It
# terminates the real installer after the selected filesystem syscall and
# before its following directory fsync.
INSTALLER_FAULT = r"""
def inject_fixture_fault():
    fault = Path(__file__).with_name("installer-fault")
    if not fault.exists():
        return
    boundary = fault.read_text()
    if boundary in ("after-create", "foreign-create"):
        original = create_exclusive
        def create(state, scratch, parent, name):
            if name == "operator_feature.py" and boundary == "foreign-create":
                descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644, dir_fd=parent)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(b"foreign edit")
            original(state, scratch, parent, name)
            if name == "operator_feature.py":
                os.kill(os.getpid(), 9)
        globals()["create_exclusive"] = create
    if boundary == "after-unlink":
        original = os.unlink
        def unlink(path, **kwargs):
            original(path, **kwargs)
            if path == "operator_feature.py":
                os.kill(os.getpid(), 9)
        os.unlink = unlink

inject_fixture_fault()
"""


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="jsh-s3-maint-fixture-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "project"
        self.bundle = self.root / "bundle"
        self.bundle.mkdir(mode=0o700)
        self.candidate = self.bundle / "candidate"
        for destination in (self.project, self.candidate):
            (destination / "src/job_search_helper").mkdir(parents=True)
        old = {ROOT_LAUNCHER: b"#!/bin/sh\n# old\n", BOOTSTRAP: b"# Old bootstrap\n",
               REPLACED: b"VERSION = 'old'\n"}
        new = {ROOT_LAUNCHER: b"#!/bin/sh\n# new\n", BOOTSTRAP: b"# New bootstrap\n",
               REPLACED: b"from .operator_feature import VERSION\n", ADDED: b"VERSION = 'new'\n"}
        self.modes = {ROOT_LAUNCHER: 0o755, BOOTSTRAP: 0o664, REPLACED: 0o644, ADDED: 0o664}
        self.old, self.new = old, new
        for destination, files in ((self.project, old), (self.candidate, new)):
            for name, data in files.items():
                path = destination / name
                path.write_bytes(data)
                path.chmod(self.modes[name])

        self.package = self.project / "src/job_search_helper"
        self.parked = self.package.with_name(gate.PARKED)
        self.package_inode = self.package.stat().st_ino
        (self.package / "__init__.py").write_text("from .runner import VERSION\n")
        self.untouched = self.package / "untouched.py"
        self.untouched.write_bytes(b"unrelated source")
        self.untouched_inode = self.untouched.stat().st_ino
        self.old_parking = self.package.with_name(".f3-maintenance-package")
        self.old_parking.mkdir()
        (self.old_parking / "__init__.py").write_bytes(gate.MESSAGE)
        self.old_parking_inode = self.old_parking.stat().st_ino
        (self.project / "job-search-helper").write_bytes(b"unrelated root launcher")
        self.state = self.project / ".state"
        self.state.mkdir(mode=0o700)
        (self.project / ".storage-backend").write_text("sqlite\n")
        self.state_file = self.state / "state.db"
        self.state_file.write_bytes(b"untouched fixture state")
        self.marker = self.state / "integration-release-journal.json"
        self.locks = [self.project / ".integration-install.lock", *(
            self.state / name for name in ("scraper.lock", "writer.lock", "review-writeback.lock"))]
        for path in self.locks:
            path.write_text("existing fixture lock\n")

        self.units = self.root / "units"
        self.units.mkdir()
        self.service_states = self.root / "services.json"
        self.original_services = {
            "wrapper-development-host.service": {"active": True, "enabled": "enabled"},
            "job-search-sync.service": {"active": False, "enabled": "disabled"},
        }
        for name in self.original_services:
            (self.units / name).write_text("fixture unit bytes")
        expiry = self.units / "job-search-sync.service.d"
        expiry.mkdir()
        (expiry / "expiry.conf").write_text("unrelated expiry")
        self.service_states.write_text(json.dumps(self.original_services))
        fake_systemctl = self.root / "fake-systemctl"
        program(fake_systemctl, SYSTEMCTL)
        program(self.bundle / "host-check", HOST_CHECK)

        for name in ("controller.py", "installer.py", "gate.py", "verify_hold"):
            shutil.copy2(TOOLS / name, self.bundle / name)
        installer_path = self.bundle / "installer.py"
        body = installer_path.read_text()
        installer_path.write_text(body.replace('\nif __name__ == "__main__":',
                                               "\n" + INSTALLER_FAULT + '\nif __name__ == "__main__":'))
        self.control = self.bundle / "controller.py"
        self.fault = self.bundle / "installer-fault"
        entries = {}
        for name in new:
            entries[name] = {
                "before": None if name not in old else self.pin(name, old[name]),
                "after": self.pin(name, new[name]),
                "owner": [os.getuid(), os.getgid()],
            }
        self.manifest = self.bundle / "manifest.json"
        self.manifest.write_bytes(installer.encode({
            "schema": "sprint-3-source-manifest-v1", "paths": entries}))
        self.pin_hash = hashlib.sha256(self.manifest.read_bytes()).hexdigest()
        (self.bundle / "plan.json").write_bytes(installer.encode({
            "project": str(self.project), "hold_id": "sprint3-fixture-only",
            "unit_directory": str(self.units), "systemctl": str(fake_systemctl),
            "pycache_prefixes": [], "manifest_sha256": self.pin_hash,
        }))
        self.journal = self.bundle / "transaction/transaction.json"

    def pin(self, name, data):
        return {"mode": f"{self.modes[name]:04o}", "sha256": hashlib.sha256(data).hexdigest()}

    def execute(self, verb, *, crash=None):
        command = [sys.executable, "-I", "-B"]
        if crash:
            command.extend(("-c", KILL, str(self.control), crash))
        else:
            command.append(str(self.control))
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("PYTHON", "JSH_")) and key not in
               {"STATE_DB_FILE", "JOB_DB_FILE", "JOB_STORAGE_BACKEND"}}
        return subprocess.run([*command, verb], cwd=self.root, env=env, text=True,
                              capture_output=True, timeout=100)

    def success(self, verb):
        result = self.execute(verb)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def assert_protected(self):
        self.assertEqual(self.untouched_inode, self.untouched.stat().st_ino)
        self.assertEqual(b"unrelated source", self.untouched.read_bytes())
        self.assertEqual(self.old_parking_inode, self.old_parking.stat().st_ino)
        self.assertEqual(gate.MESSAGE, (self.old_parking / "__init__.py").read_bytes())
        self.assertEqual(b"unrelated root launcher", (self.project / "job-search-helper").read_bytes())
        self.assertEqual(b"untouched fixture state", self.state_file.read_bytes())
        self.assertEqual("unrelated expiry",
                         (self.units / "job-search-sync.service.d/expiry.conf").read_text())

    def assert_visible(self, files):
        self.assertEqual(self.package_inode, self.package.stat().st_ino)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.package / "__init__.so").exists())
        self.assertEqual(self.original_services, json.loads(self.service_states.read_text()))
        for name in self.new:
            if name in files:
                path = self.project / name
                self.assertEqual(files[name], path.read_bytes())
                self.assertEqual(self.modes[name], path.stat().st_mode & 0o7777)
                self.assertEqual((os.getuid(), os.getgid()), (path.stat().st_uid, path.stat().st_gid))
            else:
                self.assertFalse((self.project / name).exists())

    def assert_held(self):
        self.assertTrue(self.marker.is_file())
        self.assertTrue((self.bundle / "service-hold").is_file())
        self.assertFalse(any(item["active"] for item in json.loads(self.service_states.read_text()).values()))

    def test_install_and_rollback_preserve_unrelated_files_and_restore_absence(self):
        first = self.success("install")
        self.assertEqual("INSTALLED", first["source"])
        self.assertEqual(first, self.success("install"))
        self.assert_visible(self.new)
        self.assert_protected()
        stored = json.loads(self.journal.read_text())
        self.assertEqual("sprint-3-transaction-v1", stored["schema"])
        self.assertEqual(self.pin_hash, stored["source_manifest_sha256"])
        manifest = installer.load_manifest(self.manifest, self.pin_hash)
        index = manifest.paths.index(ADDED)
        self.assertFalse((self.journal.parent / installer.payload_name("before", index)).exists())
        self.assertTrue((self.journal.parent / installer.payload_name("after", index)).is_file())
        # A rollback must remove bytecode for the module it removes.
        cache = self.package / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "operator_feature.cpython-311.pyc").write_bytes(b"obsolete")
        (cache / "untouched.cpython-311.pyc").write_bytes(b"unrelated")
        shutil.rmtree(self.candidate)
        second = self.success("rollback")
        self.assertEqual("ROLLED_BACK", second["source"])
        self.assertEqual(second, self.success("rollback"))
        self.assert_visible(self.old)
        self.assert_protected()
        self.assertFalse((cache / "operator_feature.cpython-311.pyc").exists())
        self.assertEqual(b"unrelated", (cache / "untouched.cpython-311.pyc").read_bytes())

    def test_installer_death_before_new_file_sync_replays_exact_install(self):
        self.fault.write_text("after-create")
        result = self.execute("install")
        self.assertNotEqual(0, result.returncode)
        self.assert_held()
        self.assertEqual(self.new[ADDED], (self.parked / Path(ADDED).name).read_bytes())
        self.assertEqual("INSTALLING", json.loads(self.journal.read_text())["phase"])
        self.fault.unlink()
        shutil.rmtree(self.candidate)
        self.success("install")
        self.assert_visible(self.new)
        self.assert_protected()

    def test_rollback_of_partial_install_uses_no_candidate_and_restores_absence(self):
        self.fault.write_text("after-create")
        result = self.execute("install")
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("INSTALLING", json.loads(self.journal.read_text())["phase"])
        self.assertTrue((self.parked / Path(ADDED).name).is_file())
        self.assert_held()
        self.fault.unlink()
        shutil.rmtree(self.candidate)
        self.assertEqual("ROLLED_BACK", self.success("rollback")["source"])
        self.assert_visible(self.old)
        self.assert_protected()

    def test_installer_death_after_addition_unlink_replays_exact_rollback(self):
        self.success("install")
        self.fault.write_text("after-unlink")
        result = self.execute("rollback")
        self.assertNotEqual(0, result.returncode)
        self.assert_held()
        self.assertFalse((self.parked / Path(ADDED).name).exists())
        self.assertEqual("ROLLING_BACK", json.loads(self.journal.read_text())["phase"])
        self.fault.unlink()
        self.success("rollback")
        self.assert_visible(self.old)
        self.assert_protected()

    def test_interloping_new_target_is_not_overwritten_or_removed(self):
        self.fault.write_text("foreign-create")
        result = self.execute("install")
        self.assertNotEqual(0, result.returncode)
        self.assert_held()
        foreign = self.parked / Path(ADDED).name
        self.assertEqual(b"foreign edit", foreign.read_bytes())
        self.fault.unlink()
        for action in ("install", "rollback"):
            result = self.execute(action)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(b"foreign edit", foreign.read_bytes())
            self.assert_held()

    def test_preexisting_added_path_and_changed_pinned_manifest_fail_before_hold(self):
        foreign = self.project / ADDED
        foreign.symlink_to(self.untouched)
        result = self.execute("install")
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())
        self.assertTrue(foreign.is_symlink())
        foreign.unlink()
        self.manifest.write_bytes(self.manifest.read_bytes() + b" ")
        result = self.execute("install")
        self.assertIn("manifest hash differs", result.stderr)
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.original_services, json.loads(self.service_states.read_text()))

    def test_verifier_refusal_before_installing_leaves_base_and_durable_hold(self):
        denial = self.bundle / "fault"
        denial.write_text("held:before-journal\ndeny\n")
        result = self.execute("install")
        self.assertNotEqual(0, result.returncode)
        self.assert_held()
        self.assertFalse(self.journal.exists())
        self.assertEqual(self.old[REPLACED], (self.parked / Path(REPLACED).name).read_bytes())
        self.assertFalse((self.parked / Path(ADDED).name).exists())
        self.assertEqual(self.old[ROOT_LAUNCHER], (self.project / ROOT_LAUNCHER).read_bytes())
        denial.unlink()
        self.success("install")
        self.assert_visible(self.new)

    def test_package_exchange_and_guard_unlink_deaths_preserve_held_recovery(self):
        result = self.execute("install", crash="swap")
        self.assertEqual(-signal.SIGKILL, result.returncode, result.stderr)
        self.assert_held()
        self.assertTrue((self.package / "__init__.so").is_file())
        self.assertEqual(self.new[ADDED], (self.project / ADDED).read_bytes())
        result = self.execute("install", crash="admission-unlink")
        self.assertEqual(-signal.SIGKILL, result.returncode, result.stderr)
        self.assert_held()
        self.assertFalse((self.package / "__init__.so").exists())
        self.success("install")
        self.assert_visible(self.new)
        self.assert_protected()


if __name__ == "__main__":
    unittest.main()
