"""Disposable tests for the maintenance package gate."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import gate


class PackageGateTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="jsh-gate-test-", dir="/tmp")
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)
        self.project = self.root / "checkout"
        self.src = self.project / "src"
        self.package = self.src / "job_search_helper"
        self.parked = self.src / ".f3-maintenance-package"
        self.fallback = self.root / "fallback"
        self.write_package(self.package, "checkout")
        self.write_package(self.fallback / self.package.name, "fallback")
        self.inode = self.package.stat().st_ino
        self.unrelated = {
            self.src / "unrelated.py": b"VALUE = 19\n",
            self.project / "config.toml": b"[jobs]\nactive = true\n",
            self.root / "outside.txt": b"outside the checkout\n",
        }
        self.unrelated_metadata = {}
        for path, content in self.unrelated.items():
            path.write_bytes(content)
            attrs = path.stat()
            self.unrelated_metadata[path] = (attrs.st_ino, attrs.st_mode)
        self.original_payload = {
            path.name: (path.stat().st_ino, path.read_bytes())
            for path in self.package.iterdir()
        }

    @staticmethod
    def write_package(package, origin):
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "legacy.py").write_text(
            f"def main():\n    print({origin + ':legacy'!r})\n", encoding="utf-8"
        )
        (package / "__main__.py").write_text(
            f"print({origin + ':module'!r})\n", encoding="utf-8"
        )

    def python(self, args, *paths):
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(map(str, paths))
        return subprocess.run(
            [sys.executable, "-B", *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_startup(self, *paths, origin):
        launchers = {
            "legacy": ["-c", "from job_search_helper.legacy import main; main()"],
            "module": ["-m", "job_search_helper"],
        }
        for name, args in launchers.items():
            with self.subTest(launcher=name, origin=origin):
                result = self.python(args, *paths)
                if origin is None:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("ImportError", result.stderr)
                    self.assertIn(str(self.package / "__init__.py"), result.stderr)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), f"{origin}:{name}")

    def assert_original_payload(self, package):
        self.assertEqual(package.stat().st_ino, self.inode)
        for name, (inode, content) in self.original_payload.items():
            path = package / name
            self.assertEqual(path.stat().st_ino, inode)
            self.assertEqual(path.read_bytes(), content)

    def assert_unrelated_intact(self):
        for path, content in self.unrelated.items():
            attrs = path.stat()
            self.assertEqual((attrs.st_ino, attrs.st_mode), self.unrelated_metadata[path])
            self.assertEqual(path.read_bytes(), content)

    def test_park_blocks_both_launchers_even_with_fallback(self):
        self.assert_startup(self.src, self.fallback, origin="checkout")
        self.assert_startup(self.fallback, origin="fallback")

        gate.park(self.project, self.inode)
        gate.verify_parked(self.project, self.inode)
        self.assertEqual({path.name for path in self.package.iterdir()}, {"__init__.py"})
        self.assert_original_payload(self.parked)
        self.assert_startup(self.src, origin=None)
        self.assert_startup(self.src, self.fallback, origin=None)
        self.assert_unrelated_intact()

        gate.publish(self.project, self.inode)
        self.assert_startup(self.src, self.fallback, origin="checkout")
        self.assert_original_payload(self.package)
        self.assert_unrelated_intact()

    def test_park_survives_abrupt_process_exit(self):
        gate_dir = Path(gate.__file__).resolve().parent
        worker = (
            "import os, sys, gate\n"
            "from pathlib import Path\n"
            "gate.park(Path(sys.argv[1]), int(sys.argv[2]))\n"
            "os._exit(73)\n"
        )
        args = [str(self.project), str(self.inode)]
        crashed = self.python(["-c", worker, *args], gate_dir)
        self.assertEqual(crashed.returncode, 73, crashed.stderr)
        verifier = (
            "import sys, gate\n"
            "from pathlib import Path\n"
            "gate.verify_parked(Path(sys.argv[1]), int(sys.argv[2]))\n"
        )
        fresh = self.python(["-c", verifier, *args], gate_dir)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assert_startup(self.src, self.fallback, origin=None)
        self.assert_original_payload(self.parked)
        self.assert_unrelated_intact()

    def test_tampered_marker_is_refused(self):
        gate.park(self.project, self.inode)
        marker = self.package / "__init__.py"
        mode = marker.stat().st_mode & 0o777
        marker.chmod(mode | 0o200)
        try:
            marker.write_text("pass\n", encoding="utf-8")
        finally:
            marker.chmod(mode)

        with self.assertRaises(ValueError):
            gate.verify_parked(self.project, self.inode)
        with self.assertRaises(ValueError):
            gate.publish(self.project, self.inode)
        self.assertEqual(marker.read_text(encoding="utf-8"), "pass\n")
        self.assert_original_payload(self.parked)
        self.assert_unrelated_intact()

    def test_replaced_parked_directory_is_refused(self):
        gate.park(self.project, self.inode)
        displaced = self.src / "displaced"
        self.parked.rename(displaced)
        self.write_package(self.parked, "impostor")

        with self.assertRaises(ValueError):
            gate.verify_parked(self.project, self.inode)
        with self.assertRaises(ValueError):
            gate.publish(self.project, self.inode)
        self.assert_startup(self.src, self.fallback, origin=None)
        self.assert_original_payload(displaced)
        self.assert_unrelated_intact()

    def test_park_and_publish_can_be_replayed(self):
        gate.park(self.project, self.inode)
        marker_inode = self.package.stat().st_ino
        gate.park(self.project, self.inode)
        gate.verify_parked(self.project, self.inode)
        self.assertEqual(self.package.stat().st_ino, marker_inode)
        self.assert_original_payload(self.parked)

        gate.publish(self.project, self.inode)
        gate.publish(self.project, self.inode)
        self.assert_original_payload(self.package)
        self.assertEqual(self.parked.stat().st_ino, marker_inode)
        self.assert_startup(self.src, self.fallback, origin="checkout")

        gate.park(self.project, self.inode)
        gate.verify_parked(self.project, self.inode)
        self.assertEqual(self.package.stat().st_ino, marker_inode)
        self.assert_original_payload(self.parked)
        self.assert_unrelated_intact()


if __name__ == "__main__":
    unittest.main()
