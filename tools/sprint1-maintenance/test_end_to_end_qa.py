"""Exercise the real source pins in disposable, credential-free checkouts."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import py_compile
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest

from test_installer import (
    BASE,
    CANDIDATE,
    EXPECTED_AFTER_DIGEST,
    EXPECTED_BASE_DIGEST,
    HOLD_ID,
    INSTALLER,
    PACKAGE,
    PARKED,
    SCOPE,
    VERIFIER,
    manifest_digest,
    source_manifest,
)


HERE = Path(__file__).resolve().parent
SYNC = "src/job_search_helper/sync_cli.py"
EXTENSION = "__init__.so"

SYSTEMCTL = r"""
import json
from pathlib import Path
import sys

root = Path(__file__).parent
units = root / "units"
state = root / "units.json"
active = json.loads(state.read_text())
assert sys.argv[1] == "--user"
action, *args = sys.argv[2:]
if action == "show":
    for name in args[-2:]:
        props = {
            "Id": name, "LoadState": "loaded", "ActiveState": active[name],
            "SubState": "running" if active[name] == "active" else "dead",
            "UnitFileState": "enabled" if name.startswith("wrapper") else "disabled",
            "MainPID": "31415" if active[name] == "active" else "0",
            "ControlPID": "0", "ControlGroup": "/qa-fixture",
            "FragmentPath": str(units / name),
            "DropInPaths": " ".join(str(p) for p in sorted((units / (name + ".d")).glob("*.conf"))),
            "NeedDaemonReload": "no",
        }
        print(*(key + "=" + value for key, value in props.items()), sep="\n")
        print()
elif action in {"start", "stop"}:
    for name in args:
        active[name] = {"start": "active", "stop": "inactive"}[action]
    state.write_text(json.dumps(active))
else:
    assert action == "daemon-reload"
"""

HOST_CHECK = """
import json
import os
from pathlib import Path
import subprocess
import sys

req = json.load(sys.stdin)
project = Path(req["project"])
checkpoint = req["checkpoint"]
package = Path(req["package"])
canonical = project / "src/job_search_helper"
parked = project / "src/.f3-maintenance-package"
guard = canonical / "__init__.so"
marker = Path(req["marker"])
if checkpoint.startswith("held:") or checkpoint == "pre-publish":
    assert package == parked, ("host check expected parked package", package)
    assert "raise ImportError" in (canonical / "__init__.py").read_text()
elif checkpoint in {"preflight", "published", "admitted"}:
    assert package == canonical, ("host check expected canonical package", package)
    assert "raise ImportError" not in (canonical / "__init__.py").read_text()
    if checkpoint != "preflight":
        assert marker.is_file(), "bootstrap hold lifted before the probe"
        environment = {**os.environ, "PYTHONPATH": str(project / "src")}
        result = subprocess.run([sys.executable, "-B", "-c", "import job_search_helper"],
                                capture_output=True, text=True, env=environment, cwd="/")
        if checkpoint == "published":
            assert guard.is_file() and guard.stat().st_size == 0
            assert result.returncode != 0 and str(guard) in result.stderr, result
        else:
            assert not guard.exists()
            assert result.returncode == 0, result.stderr
else:
    raise RuntimeError(checkpoint)
bundle = Path(__file__).parent
rejection = bundle / "reject-checkpoint"
if rejection.exists() and rejection.read_text().strip() == checkpoint:
    sys.exit("fixture refused " + checkpoint)
with (bundle / "host-check.log").open("a") as log:
    print(checkpoint, file=log)
print(json.dumps({**req, "verified": True}))
"""


class PreflightQA(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="jsh-maint-qa-", dir="/tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.project = self.root / "project"
        shutil.copytree(
            CANDIDATE / "src" / "job_search_helper",
            self.project / PACKAGE,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for relative in SCOPE:
            shutil.copy2(BASE / relative, self.project / relative)
        shutil.copy2(CANDIDATE / "pyproject.toml", self.project / "pyproject.toml")
        self.inode = (self.project / PACKAGE).stat().st_ino
        self.runtime = self.project / ".state"
        self.runtime.mkdir(mode=0o700)
        self.state = self.root / "transaction"
        self.state.mkdir(mode=0o700)
        self.gate = self.root / "gate"
        self.gate.touch(mode=0o600)
        self.marker = self.runtime / "integration-release-journal.json"
        self.verifier = self.root / "verify"
        self.verifier.write_text(f"#!{sys.executable}\n" + VERIFIER)
        self.verifier.chmod(0o700)
        (self.root / "hold.json").write_text(json.dumps({"routes_closed": True}))
        (self.project / ".storage-backend").write_text("sqlite\n")
        self.bin = self.project / ".venv" / "bin"
        self.bin.mkdir(parents=True)
        (self.bin / "python").symlink_to(sys.executable)
        self.db = self.runtime / "jobs.sqlite3"
        with sqlite3.connect(self.db) as db:
            db.execute("create table jobs (title text)")
            db.execute("insert into jobs values ('fixture')")
        self.db_fingerprint = self.fingerprint(self.db)
        self.request = self.runtime / "next-scan.json"
        self.request.write_text('{"fixture":true}\n')
        self.request_fingerprint = self.fingerprint(self.request)
        self.nonscope = self.nonscope_fingerprints()

    @staticmethod
    def fingerprint(path):
        info = path.stat()
        return info.st_ino, stat.S_IMODE(info.st_mode), hashlib.sha256(path.read_bytes()).hexdigest()

    def nonscope_fingerprints(self, package=PACKAGE):
        root = self.project / package
        return {
            path.relative_to(root).as_posix(): self.fingerprint(path)
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path != root / EXTENSION
            and (Path(PACKAGE) / path.relative_to(root)).as_posix() not in SCOPE
        }

    def run_clean(self, *command, paths=()):
        return subprocess.run(
            command,
            cwd=self.root,
            env={
                "PATH": os.defpath,
                "PYTHONPATH": os.pathsep.join(map(str, paths)),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "JOB_STORAGE_BACKEND": "sqlite",
                "STATE_DB_FILE": str(self.runtime / "state.db"),
                "JOB_DB_FILE": str(self.db),
            },
            capture_output=True,
            text=True,
            timeout=30,
        )

    def manifest(self, package, expected):
        actual = manifest_digest(source_manifest(self.project, package))
        self.assertEqual(actual, expected)

    def crash_after_transition(self, action):
        command = """
import fcntl
import os
from pathlib import Path
import sys
import gate

action, root, inode, mutex, marker, marker_text = sys.argv[1:]
with Path(mutex).open("rb") as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    if action == "park" and not Path(marker).exists():
        with Path(marker).open("x") as journal:
            journal.write(marker_text)
            journal.flush()
            os.fsync(journal.fileno())
        gate.syncdir(Path(marker).parent)
    getattr(gate, action)(Path(root), int(inode))
    os._exit(87)
"""
        marker = json.dumps({
            "schema": "integration-release-journal-v1",
            "state": "FOUNDATION_MAINTENANCE",
            "maintenance_id": HOLD_ID,
        })
        result = self.run_clean(
            sys.executable, "-B", "-c", command, action, self.project,
            str(self.inode), self.gate, self.marker, marker, paths=(HERE,),
        )
        self.assertEqual(result.returncode, 87, result.stderr)
        with self.gate.open("rb") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def installer(self, action, phase, with_candidate=False):
        args = [
            sys.executable, "-B", INSTALLER, action,
            "--project", self.project, "--state", self.state, "--gate", self.gate,
            "--marker", self.marker, "--hold-id", HOLD_ID, "--verifier", self.verifier,
            "--parked-package",
        ]
        if with_candidate:
            args += ["--candidate", CANDIDATE]
        result = self.run_clean(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["phase"], phase)
        self.assertEqual(receipt["source_directories"][1][1], self.inode)
        self.assertEqual(receipt["before_manifest_sha256"], EXPECTED_BASE_DIGEST)
        self.assertEqual(receipt["after_manifest_sha256"], EXPECTED_AFTER_DIGEST)

    def bootstrap_startup(self, blocked):
        routes = (
            (self.project / "job-search-helper", "start", "--help"),
            (self.project / "job-search-scraper", "start", "--help"),
            (self.project / "job-search-scraper", "sync", "--help"),
            (sys.executable, "-B", self.project / "release_admission_bootstrap.py", "start", "--help"),
        )
        for route in routes:
            with self.subTest(bootstrap=route, blocked=blocked):
                result = self.run_clean(*route, paths=(CANDIDATE / "src",))
                if blocked:
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("Interrupted integration release", result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("usage:", result.stdout.lower())

    def direct_startup(self, blocked, extension=False):
        routes = [
            (self.project / "job-search-helper", "--help"),
            (self.project / "job-search-scraper", "--help"),
        ]
        routes.extend(
            (sys.executable, "-B", "-m", f"job_search_helper.{module}", "--help")
            for module in ("cli", "sync_cli", "scrape_first_pass")
        )
        console = self.bin / "job-search-helper"
        if console.exists():
            routes.append((console, "--help"))
        for route in routes:
            with self.subTest(direct=route, blocked=blocked):
                paths = () if route[0] == console else (self.project / "src", CANDIDATE / "src")
                result = self.run_clean(*route, paths=paths)
                if blocked:
                    self.assertNotEqual(result.returncode, 0)
                    denial = str(self.project / PACKAGE / EXTENSION) if extension else "Job Search Helper is held"
                    self.assertIn(denial, result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("usage:", result.stdout.lower())

    def test_interrupted_handoff_and_publication_with_terminal_replay(self):
        self.manifest(PACKAGE, EXPECTED_BASE_DIGEST)
        self.crash_after_transition("park")
        self.assertFalse((self.state / "transaction.json").exists())
        marker_fingerprint = self.fingerprint(self.marker)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True)
        alternate = self.run_clean(
            sys.executable, "-B", "-c", "import job_search_helper; print(job_search_helper.__file__)",
            paths=(CANDIDATE / "src", self.project / "src"),
        )
        self.assertEqual(alternate.returncode, 0, alternate.stderr)
        self.assertEqual(alternate.stdout.strip(), str(CANDIDATE / PACKAGE / "__init__.py"))
        self.installer("install", "INSTALLED", with_candidate=True)
        self.installer("install", "INSTALLED")
        self.installer("verify", "INSTALLED")
        self.manifest(PARKED, EXPECTED_AFTER_DIGEST)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True)

        self.crash_after_transition("publish")
        self.manifest(PACKAGE, EXPECTED_AFTER_DIGEST)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=False)

        self.crash_after_transition("park")
        self.installer("verify", "INSTALLED")
        self.installer("rollback", "ROLLED_BACK")
        self.installer("rollback", "ROLLED_BACK")
        self.installer("verify", "ROLLED_BACK")
        self.manifest(PARKED, EXPECTED_BASE_DIGEST)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True)

        self.crash_after_transition("publish")
        self.manifest(PACKAGE, EXPECTED_BASE_DIGEST)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=False)
        self.assertEqual(self.fingerprint(self.marker), marker_fingerprint)
        self.assertEqual(self.fingerprint(self.db), self.db_fingerprint)
        self.assertEqual(self.fingerprint(self.request), self.request_fingerprint)

    def test_direct_sync_can_read_timestamp_valid_old_bytecode(self):
        source = self.project / SYNC
        timestamp = 1700000000
        os.utime(source, (timestamp, timestamp))
        py_compile.compile(str(source), invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        self.assertEqual(source.stat().st_size, (CANDIDATE / SYNC).stat().st_size)
        shutil.copyfile(CANDIDATE / SYNC, source)
        os.utime(source, (timestamp, timestamp))
        probe = """
from importlib.machinery import SourceFileLoader
import sys

def constants(code):
    yield from code.co_consts
    for child in code.co_consts:
        if hasattr(child, "co_consts"):
            yield from constants(child)

code = SourceFileLoader("job_search_helper.sync_cli", sys.argv[1]).get_code("job_search_helper.sync_cli")
orders = [value for value in constants(code) if isinstance(value, tuple)
          and set(value) == {"scraper.lock", "writer.lock", "review-writeback.lock"}]
print(orders[0][0])
"""
        cached = self.run_clean(sys.executable, "-B", "-c", probe, source)
        bypass = self.run_clean(
            sys.executable, "-B", "-X", "pycache_prefix=/dev/null", "-c", probe, source
        )
        self.assertEqual(cached.returncode, 0, cached.stderr)
        self.assertEqual(bypass.returncode, 0, bypass.stderr)
        self.assertEqual(cached.stdout.strip(), "writer.lock")
        self.assertEqual(bypass.stdout.strip(), "scraper.lock")

    def make_controller(self):
        venv = self.run_clean(sys.executable, "-m", "venv", "--clear", "--without-pip",
                              self.project / ".venv")
        self.assertEqual(venv.returncode, 0, venv.stderr)
        ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        site = self.project / ".venv" / "lib" / ver / "site-packages"
        (site / "fixture-editable.pth").write_text(f"{self.project / 'src'}\n")
        console = self.bin / "job-search-helper"
        console.write_text(
            f"#!{self.bin / 'python'}\n"
            "from job_search_helper.launcher import main\n"
            "raise SystemExit(main())\n"
        )
        console.chmod(0o755)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir(mode=0o700)
        for path in ("controller.py", "gate.py", "installer.py", "verify_hold"):
            shutil.copy2(HERE / path, self.bundle / path)
        candidate = self.bundle / "candidate"
        (candidate / PACKAGE).mkdir(parents=True)
        for path in SCOPE:
            shutil.copy2(CANDIDATE / path, candidate / path)
        units = self.bundle / "units"
        units.mkdir()
        active = {
            "wrapper-development-host.service": "active",
            "job-search-sync.service": "inactive",
        }
        for unit in active:
            (units / unit).write_text("[Service]\n")
        (self.bundle / "units.json").write_text(json.dumps(active))
        for name, content in (("systemctl", SYSTEMCTL), ("host-check", HOST_CHECK)):
            tool = self.bundle / name
            tool.write_text(f"#!{sys.executable}\n" + content)
            tool.chmod(0o700)
        plan = {
            "project": str(self.project),
            "hold_id": HOLD_ID,
            "unit_directory": str(units),
            "systemctl": str(self.bundle / "systemctl"),
            "pycache_prefixes": [],
        }
        (self.bundle / "plan.json").write_text(json.dumps(plan))
        (self.project / ".integration-install.lock").touch()
        for stem in ("scraper", "writer", "review-writeback"):
            (self.runtime / f"{stem}.lock").touch(mode=0o600)

    def assert_service_state(self, held):
        active = json.loads((self.bundle / "units.json").read_text())
        self.assertEqual(active, {
            "wrapper-development-host.service": "inactive" if held else "active",
            "job-search-sync.service": "inactive",
        })
        self.assertEqual((self.bundle / "service-hold").exists(), held)
        self.assertEqual(len(list((self.bundle / "units").glob("*/*.conf"))), 2 if held else 0)

    def invoke_controller(self, action, crash=None):
        if crash is None:
            return self.run_clean(sys.executable, "-I", "-B", self.bundle / "controller.py", action)
        inject = """
import os
from pathlib import Path
import sys
import controller

crash, action = sys.argv[1:]
if crash == "handoff":
    def stop_before_handoff(*args):
        os._exit(87)
    controller.Controller.installer_command = stop_before_handoff
elif crash == "publication":
    publish = controller.gate.publish
    def stop_after_publication(*args):
        publish(*args)
        os._exit(87)
    controller.gate.publish = stop_after_publication
elif crash == "rehold":
    park = controller.gate.park
    def stop_after_rehold(*args):
        park(*args)
        os._exit(87)
    controller.gate.park = stop_after_rehold
elif crash == "guard-unlink":
    unlink = os.unlink
    def stop_after_unlink(path, *args, **kw):
        unlink(path, *args, **kw)
        if Path(path).name == "__init__.so":
            os._exit(87)
    os.unlink = stop_after_unlink
else:
    raise RuntimeError(crash)
sys.argv = [controller.__file__, action]
controller.main()
"""
        return self.run_clean(sys.executable, "-B", "-c", inject, crash, action, paths=(self.bundle,))

    @unittest.skipUnless((HERE / "controller.py").is_file(), "controller unavailable")
    def test_controller_recovers_handoff_and_publication_with_strict_probe(self):
        self.make_controller()
        controller_journal = self.bundle / "controller.json"
        died = self.invoke_controller("install", crash="handoff")
        self.assertEqual(died.returncode, 87, died.stderr)
        self.assertEqual(json.loads(controller_journal.read_text())["phase"], "HELD")
        self.assertFalse((self.bundle / "transaction/transaction.json").exists())
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True)
        self.assert_service_state(held=True)
        self.assertEqual((self.project / PARKED).stat().st_ino, self.inode)
        self.assertEqual(self.nonscope_fingerprints(PARKED), self.nonscope)

        died = self.invoke_controller("install", crash="publication")
        self.assertEqual(died.returncode, 87, died.stderr)
        self.assertEqual(json.loads(controller_journal.read_text())["phase"], "PUBLISHING")
        self.manifest(PACKAGE, EXPECTED_AFTER_DIGEST)
        guard = self.project / PACKAGE / EXTENSION
        self.assertEqual(guard.read_bytes(), b"")
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True, extension=True)
        self.assert_service_state(held=True)
        self.assertEqual((self.project / PACKAGE).stat().st_ino, self.inode)
        self.assertEqual(self.nonscope_fingerprints(), self.nonscope)

        died = self.invoke_controller("install", crash="guard-unlink")
        self.assertEqual(died.returncode, 87, died.stderr)
        self.assertFalse(guard.exists())
        self.assertEqual(json.loads(controller_journal.read_text())["phase"], "ADMISSION_READY")
        self.assertEqual(self.checkpoints()[-1], "published")
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=False)
        self.assert_service_state(held=True)

        installed = self.invoke_controller("install")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assert_admission_checks()
        self.assert_released_and_rolls_back(installed, crash_rollback=True)

    @unittest.skipUnless((HERE / "controller.py").is_file(), "controller unavailable")
    def test_controller_terminal_install_and_rollback_replay(self):
        self.make_controller()
        installed = self.invoke_controller("install")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assert_released_and_rolls_back(installed)

    @unittest.skipUnless((HERE / "controller.py").is_file(), "controller unavailable")
    def test_published_guard_missing_or_replaced_before_admission_is_refused(self):
        self.make_controller()
        died = self.invoke_controller("install", crash="publication")
        self.assertEqual(died.returncode, 87, died.stderr)
        guard = self.project / PACKAGE / EXTENSION
        displaced = self.root / "original-guard"
        guard.rename(displaced)
        journal = self.bundle / "controller.json"
        before = journal.read_bytes()

        missing = self.invoke_controller("install")
        self.assertNotEqual(missing.returncode, 0, missing.stdout)
        self.assertFalse(guard.exists())
        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue(self.marker.exists())
        self.bootstrap_startup(blocked=True)

        guard.touch(mode=stat.S_IMODE(displaced.stat().st_mode))
        replacement = self.fingerprint(guard)
        self.assertNotEqual(replacement[0], displaced.stat().st_ino)
        replaced = self.invoke_controller("install")
        self.assertNotEqual(replaced.returncode, 0, replaced.stdout)
        self.assertEqual(self.fingerprint(guard), replacement)
        self.assertEqual(journal.read_bytes(), before)
        self.assertTrue(self.marker.exists())
        self.assertNotIn("published", self.checkpoints())
        self.assertNotIn("admitted", self.checkpoints())
        self.assertEqual(self.nonscope_fingerprints(), self.nonscope)
        self.assertEqual(self.fingerprint(self.db), self.db_fingerprint)

    @unittest.skipUnless((HERE / "controller.py").is_file(), "controller unavailable")
    def test_refused_verification_retains_expected_holds(self):
        self.make_controller()
        reject = self.bundle / "reject-checkpoint"
        reject.write_text("published\n")
        stopped = self.invoke_controller("install")
        self.assertNotEqual(stopped.returncode, 0, stopped.stdout)
        self.assertIn("fixture refused published", stopped.stderr)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True, extension=True)
        self.assert_service_state(held=True)

        reject.write_text("admitted\n")
        stopped = self.invoke_controller("install")
        self.assertNotEqual(stopped.returncode, 0, stopped.stdout)
        self.assertIn("fixture refused admitted", stopped.stderr)
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=False)
        self.assert_service_state(held=True)

        reject.unlink()
        released = self.invoke_controller("install")
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assert_admission_checks()
        self.assertFalse(self.marker.exists())
        self.assert_service_state(held=False)

    @unittest.skipUnless((HERE / "controller.py").is_file(), "controller unavailable")
    def test_rollback_from_guarded_publication_reparks_before_removing_guard(self):
        self.make_controller()
        published = self.invoke_controller("install", crash="publication")
        self.assertEqual(published.returncode, 87, published.stderr)
        original_guard = self.fingerprint(self.project / PACKAGE / EXTENSION)
        reheld = self.invoke_controller("rollback", crash="rehold")
        self.assertEqual(reheld.returncode, 87, reheld.stderr)
        self.assertEqual(self.fingerprint(self.project / PARKED / EXTENSION), original_guard)
        self.assertFalse((self.project / PACKAGE / EXTENSION).exists())
        self.bootstrap_startup(blocked=True)
        self.direct_startup(blocked=True)
        self.assert_service_state(held=True)

        rejected = self.invoke_controller("install")
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
        rolled_back = self.invoke_controller("rollback")
        self.assertEqual(rolled_back.returncode, 0, rolled_back.stderr)
        self.assertEqual(json.loads(rolled_back.stdout)["source"], "ROLLED_BACK")
        self.assert_admission_checks()
        self.manifest(PACKAGE, EXPECTED_BASE_DIGEST)
        self.assertEqual(self.nonscope_fingerprints(), self.nonscope)
        self.assertEqual(self.fingerprint(self.db), self.db_fingerprint)
        self.assertEqual(self.fingerprint(self.request), self.request_fingerprint)
        self.assert_service_state(held=False)
        self.bootstrap_startup(blocked=False)
        self.direct_startup(blocked=False)

    def checkpoints(self):
        return (self.bundle / "host-check.log").read_text().splitlines()

    def assert_admission_checks(self):
        phases = {"pre-publish", "published", "admitted"}
        self.assertEqual([item for item in self.checkpoints() if item in phases][-3:],
                         ["pre-publish", "published", "admitted"])

    def assert_released_and_rolls_back(self, installed, crash_rollback=False):
        self.assertEqual(json.loads(installed.stdout)["phase"], "RELEASED")
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.project / PACKAGE / EXTENSION).exists())
        self.assert_service_state(held=False)
        self.manifest(PACKAGE, EXPECTED_AFTER_DIGEST)
        self.assertEqual(self.nonscope_fingerprints(), self.nonscope)
        self.assert_admission_checks()
        self.bootstrap_startup(blocked=False)
        self.direct_startup(blocked=False)
        self.assertEqual(self.invoke_controller("install").stdout, installed.stdout)
        if crash_rollback:
            died = self.invoke_controller("rollback", crash="guard-unlink")
            self.assertEqual(died.returncode, 87, died.stderr)
            journal = json.loads((self.bundle / "controller.json").read_text())
            self.assertEqual(journal["phase"], "ADMISSION_READY")
            self.assertEqual(journal["target"], "ROLLED_BACK")
            self.assertEqual(self.checkpoints()[-1], "published")
            self.manifest(PACKAGE, EXPECTED_BASE_DIGEST)
            self.bootstrap_startup(blocked=True)
            self.direct_startup(blocked=False)
            self.assert_service_state(held=True)
        rolled_back = self.invoke_controller("rollback")
        self.assertEqual(rolled_back.returncode, 0, rolled_back.stderr)
        self.assertEqual(json.loads(rolled_back.stdout)["source"], "ROLLED_BACK")
        self.assertEqual(self.invoke_controller("rollback").stdout, rolled_back.stdout)
        self.assertFalse(self.marker.exists())
        self.assertFalse((self.project / PACKAGE / EXTENSION).exists())
        self.assert_service_state(held=False)
        self.manifest(PACKAGE, EXPECTED_BASE_DIGEST)
        self.assertEqual(self.nonscope_fingerprints(), self.nonscope)
        self.assert_admission_checks()
        self.bootstrap_startup(blocked=False)
        self.direct_startup(blocked=False)
        self.assertEqual(self.fingerprint(self.db), self.db_fingerprint)
        self.assertEqual(self.fingerprint(self.request), self.request_fingerprint)


if __name__ == "__main__":
    unittest.main()
