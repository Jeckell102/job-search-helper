import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from job_search_helper.cli import WriterLockBusy, writer_lock
from job_search_helper.integration_release import dependency_manifest_digest
from job_search_helper import runner


PROJECT = Path(__file__).resolve().parents[1]
BOOTSTRAP = PROJECT / "release_admission_bootstrap.py"
OPERATOR_COMMAND = "run-retained-operator-company"


def load_bootstrap(path=BOOTSTRAP):
    spec = importlib.util.spec_from_file_location("release_admission_bootstrap_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseAdmissionBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy2(BOOTSTRAP, self.root / BOOTSTRAP.name)
        package = self.root / "src/job_search_helper"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (self.root / ".state/integration-configs").mkdir(parents=True)
        (self.root / ".storage-backend").write_text("sqlite\n")
        (self.root / "pyproject.toml").write_text("[project]\nname='fixture'\nversion='1'\n")
        self.output = self.root / "runner-output.json"
        self.hold = self.root / "hold"
        (package / "runner.py").write_text(
            "import json, os, pathlib, time\n"
            "out=pathlib.Path(os.environ['JSH_TEST_OUTPUT'])\n"
            "out.write_text(os.environ['JSH_SCRAPER_RUNTIME_BINDING'])\n"
            "hold=os.environ.get('JSH_TEST_HOLD')\n"
            "while hold and pathlib.Path(hold).exists(): time.sleep(0.01)\n"
        )

    def environment(self):
        env = dict(os.environ)
        env.update(JSH_TEST_OUTPUT=str(self.output), JSH_TEST_HOLD=str(self.hold),
                   PYTHONDONTWRITEBYTECODE="1")
        for name in ("JSH_SCRAPER_ADMISSION_FD", "JSH_SCRAPER_ADMISSION_PATH",
                     "JSH_SCRAPER_RUNTIME_BINDING", "JSH_RETAINED_OPERATOR_SQLITE_LAYOUT",
                     "JOB_STORAGE_BACKEND", "STATE_DB_FILE", "JOB_DB_FILE",
                     "JOB_SEARCH_RETAINED_OWNER_TOKEN"):
            env.pop(name, None)
        return env

    def command(self):
        return [sys.executable, str(self.root / BOOTSTRAP.name), "start"]

    def operator_fixture(self):
        shutil.copy2(PROJECT / "job-search-scraper", self.root / "job-search-scraper")
        for name in ("state.db", "jobs.sqlite3"):
            with sqlite3.connect(self.root / ".state" / name) as database:
                database.execute("CREATE TABLE fixture (value INTEGER)")
        initializer = self.root / "src/job_search_helper/__init__.py"
        self.imported = self.root / "package-imported"
        initializer.write_text(
            "from pathlib import Path\n"
            f"Path({str(self.imported)!r}).touch()\n"
        )

    def run_launcher(self, command=OPERATOR_COMMAND, **environment):
        env = {**self.environment(), "PYTHON": sys.executable, **environment}
        return subprocess.run([str(self.root / "job-search-scraper"), command], cwd=self.root,
                              env=env, text=True, capture_output=True, timeout=10)

    def test_operator_launcher_checks_the_scraper_lock_before_any_package_import(self):
        self.operator_fixture()
        lock = self.root / ".state/scraper.lock"
        with writer_lock(lock):
            result = self.run_launcher()
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("owns admission", result.stderr)
            self.assertFalse(self.imported.exists())
            self.assertFalse(self.output.exists())

    def test_operator_launcher_rejects_an_incomplete_release_before_import(self):
        self.operator_fixture()
        (self.root / ".state/integration-release-journal.json").write_text(json.dumps({
            "schema": "integration-release-journal-v1", "state": "FOUNDATION_MAINTENANCE",
        }))
        result = self.run_launcher()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Interrupted integration release", result.stderr)
        self.assertFalse(self.imported.exists())

    def test_operator_launcher_preserves_v1_dispatch_and_passes_the_exact_layout(self):
        self.operator_fixture()
        package = self.root / "src/job_search_helper"
        (package / "runner.py").write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['JSH_TEST_OUTPUT']).write_text(json.dumps({"
            "'args': sys.argv[1:], 'runtime': os.environ.get('JSH_SCRAPER_RUNTIME_BINDING'), "
            "'layout': os.environ.get('JSH_RETAINED_OPERATOR_SQLITE_LAYOUT')}))\n"
        )
        with writer_lock(self.root / ".state/scraper.lock"):
            result = self.run_launcher("run-retained-company-event")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(self.output.read_text()),
                             {"args": ["run-retained-company-event"], "runtime": None, "layout": None})
        result = self.run_launcher()
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(self.output.read_text())
        self.assertEqual(observed["args"], [OPERATOR_COMMAND])
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        with patch.dict(os.environ, self.environment(), clear=True):
            runtime = stable._validate_runtime(self.root, self.root / ".state")
        self.assertEqual(json.loads(observed["runtime"]), runtime)
        for name, filename in (("state", "state.db"), ("jobs", "jobs.sqlite3")):
            path = self.root / ".state" / filename
            st = path.stat()
            self.assertEqual(json.loads(observed["layout"])[name],
                             {"path": str(path), "device": st.st_dev, "inode": st.st_ino})

    def test_operator_launcher_refuses_wrong_backend_layout_or_dispatcher_token(self):
        self.operator_fixture()
        for env, message in (
                ({"JOB_STORAGE_BACKEND": "sheets"}, "requires the SQLite backend"),
                ({"JOB_DB_FILE": ".state/other.sqlite3"}, "co-located state.db and jobs.sqlite3"),
                ({"STATE_DB_FILE": ".state/other.db"}, "co-located state.db and jobs.sqlite3"),
                ({"JOB_SEARCH_RETAINED_OWNER_TOKEN": "fixture-token"}, "dispatcher owner token")):
            with self.subTest(env=env):
                result = self.run_launcher(**env)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.imported.exists())
        jobs = self.root / ".state/jobs.sqlite3"
        other = jobs.with_name("target.sqlite3")
        jobs.rename(other)
        jobs.symlink_to(other)
        result = self.run_launcher()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("must be canonical", result.stderr)
        self.assertFalse(self.imported.exists())

    def test_operator_launcher_with_real_runner_fails_closed_without_handler(self):
        self.operator_fixture()
        package = self.root / "src/job_search_helper"
        shutil.copytree(PROJECT / "src/job_search_helper", package, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        for module in ("retained_company_event", "scrape_first_pass"):
            (package / (module + ".py")).write_text(
                "raise AssertionError('Unexpected fallback into a different command')\n"
            )
        result = self.run_launcher()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Specify the retained operator command and exact request identity", result.stderr)
        self.assertEqual(result.stdout, "")
        with writer_lock(self.root / ".state/scraper.lock"):
            pass
        # Its ordinary module entry cannot create a post-import operator lease.
        result = subprocess.run([sys.executable, "-m", "job_search_helper.runner", OPERATOR_COMMAND],
                                cwd=self.root, env={**self.environment(), "PYTHONPATH": "src:."},
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("requires the pre-import scraper lease", result.stderr)

    def test_dependency_measurement_matches_stable_bootstrap_contract(self):
        stable = load_bootstrap()
        self.assertEqual(stable.dependency_manifest_digest(PROJECT),
                         dependency_manifest_digest(PROJECT))

    def test_absent_configuration_tree_has_same_stable_empty_identity(self):
        stable = load_bootstrap()
        shutil.rmtree(self.root / ".state/integration-configs")
        from job_search_helper.integration_release import config_tree_digest
        self.assertEqual(stable.config_tree_digest(self.root),
                         config_tree_digest(self.root))

    def test_dependency_digest_changes_when_installed_module_bytes_change(self):
        stable = load_bootstrap()
        site = self.root / ".venv/lib/python3.11/site-packages/example"
        site.mkdir(parents=True)
        module = site / "runtime.py"
        module.write_text("VALUE = 1\n")
        before = stable.dependency_manifest_digest(self.root)
        module.write_text("VALUE = 2\n")
        self.assertNotEqual(before, stable.dependency_manifest_digest(self.root))

    def test_filter_and_runtime_selection_changes_are_configuration_drift(self):
        stable = load_bootstrap()
        blacklist = self.root / "title-blacklist.txt"
        blacklist.write_text("first\n")
        before = stable.config_tree_digest(self.root)
        blacklist.write_text("second\n")
        self.assertNotEqual(before, stable.config_tree_digest(self.root))
        with patch.dict(os.environ, {"JOB_STORAGE_BACKEND": "sheets"}):
            selected = stable.config_tree_digest(self.root)
        self.assertNotEqual(selected, stable.config_tree_digest(self.root))

    def test_startup_owns_lock_before_runner_import_and_through_process_lifetime(self):
        self.hold.touch()
        process = subprocess.Popen(self.command(), cwd=self.root, env=self.environment(),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 5
        while not self.output.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.output.exists(), "runner never reached its lock-held import")
        binding = json.loads(self.output.read_text())
        self.assertEqual(binding["state"], "NO_RELEASE")
        with self.assertRaises(WriterLockBusy):
            with writer_lock(self.root / ".state/scraper.lock"):
                pass
        self.hold.unlink()
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, (stdout, stderr))

    def test_activation_wins_before_import_then_fresh_worker_loads_new_source(self):
        lock = self.root / ".state/scraper.lock"
        with writer_lock(lock):
            blocked = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                     text=True, capture_output=True, timeout=5)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("owns admission", blocked.stderr)
            self.assertFalse(self.output.exists())
            runner_path = self.root / "src/job_search_helper/runner.py"
            runner_path.write_text(runner_path.read_text() + "\n# activated-new-version\n")
        fresh = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                               text=True, capture_output=True, timeout=5)
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertTrue(self.output.exists())

    def test_terminal_release_tree_mismatch_fails_before_runner_import(self):
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        measured = {
            "source_manifest_sha256": stable.source_tree_digest(self.root),
            "config_sha256": stable.config_tree_digest(self.root),
            "dependency_manifest_sha256": stable.dependency_manifest_digest(self.root),
        }
        journal = {
            "schema": stable.JOURNAL_SCHEMA, "state": "COMPLETE",
            "release_id": "REL-fixture", "release": {
                "schema": "integration-release-binding-v1", "release_id": "REL-fixture",
                **measured,
            },
        }
        record = self.root / ".state/releases/REL-fixture"
        record.mkdir(parents=True)
        journal.update(record=str(record), manifest_sha256="a" * 64)
        (record / "receipt.json").write_text(json.dumps({
            key: journal[key] for key in ("state", "release_id", "manifest_sha256", "release")
        }))
        (self.root / ".state/integration-release-journal.json").write_text(json.dumps(journal))
        (self.root / "src/job_search_helper/runner.py").write_text("MIXED=True\n")
        result = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not match", result.stderr)
        self.assertFalse(self.output.exists())

    def test_completed_release_requires_receipt_and_starts_with_exact_binding(self):
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        measured = {
            "source_manifest_sha256": stable.source_tree_digest(self.root),
            "config_sha256": stable.config_tree_digest(self.root),
            "dependency_manifest_sha256": stable.dependency_manifest_digest(self.root),
        }
        release_id = "REL-fixture"
        record = self.root / ".state/releases" / release_id
        record.mkdir(parents=True)
        binding = {"schema": "integration-release-binding-v1",
                   "release_id": release_id, **measured}
        journal = {"schema": stable.JOURNAL_SCHEMA, "state": "COMPLETE",
                   "release_id": release_id, "manifest_sha256": "a" * 64,
                   "release": binding, "record": str(record)}
        (self.root / ".state/integration-release-journal.json").write_text(json.dumps(journal))
        missing = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                 text=True, capture_output=True, timeout=5)
        self.assertEqual(missing.returncode, 2)
        self.assertFalse(self.output.exists())
        (record / "receipt.json").write_text(json.dumps({
            "state": "COMPLETE", "release_id": release_id,
            "manifest_sha256": "a" * 64, "release": binding,
        }))
        started = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                 text=True, capture_output=True, timeout=5)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(json.loads(self.output.read_text()),
                         {"state": "COMPLETE", "release_id": release_id, **measured})

    def test_rolled_back_runtime_requires_exact_receipt(self):
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        measured = {
            "source_manifest_sha256": stable.source_tree_digest(self.root),
            "config_sha256": stable.config_tree_digest(self.root),
            "dependency_manifest_sha256": stable.dependency_manifest_digest(self.root),
        }
        release_id = "REL-rolled-back"
        record = self.root / ".state/releases" / release_id
        record.mkdir(parents=True)
        manifest = {
            "before_source_manifest_sha256": measured["source_manifest_sha256"],
            "before_config_sha256": measured["config_sha256"],
            "dependency_manifest_sha256": measured["dependency_manifest_sha256"],
        }
        manifest_sha = stable._digest(manifest)
        (record / "manifest.json").write_text(json.dumps(manifest))
        journal = {"schema": stable.JOURNAL_SCHEMA, "state": "ROLLED_BACK",
                   "release_id": release_id, "manifest_sha256": manifest_sha,
                   "record": str(record)}
        (self.root / ".state/integration-release-journal.json").write_text(json.dumps(journal))
        missing = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                 text=True, capture_output=True, timeout=5)
        self.assertEqual(missing.returncode, 2)
        (record / "rollback.json").write_text(json.dumps({
            "state": "ROLLED_BACK", "release_id": release_id,
            "manifest_sha256": manifest_sha,
        }))
        started = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                 text=True, capture_output=True, timeout=5)
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(json.loads(self.output.read_text()),
                         {"state": "ROLLED_BACK", "release_id": release_id, **measured})

    def test_runner_consumes_exact_inherited_descriptor_without_reacquiring(self):
        database = self.root / ".state/state.db"
        lock_path = self.root / ".state/scraper.lock"
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        environment = {
            **self.environment(),
            "JSH_SCRAPER_ADMISSION_FD": str(descriptor),
            "JSH_SCRAPER_ADMISSION_PATH": str(lock_path.resolve()),
        }
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        with patch.dict(os.environ, environment, clear=True):
            os.environ["JSH_SCRAPER_RUNTIME_BINDING"] = json.dumps(
                stable._validate_runtime(self.root, database.parent))
            with (patch.object(runner, "PROJECT_ROOT", self.root),
                  patch.object(runner, "scraper_lock_name", return_value="scraper.lock")):
                with runner._scraper_admission(database) as binding:
                    self.assertEqual(binding["state"], "NO_RELEASE")
                    with self.assertRaises(WriterLockBusy):
                        with writer_lock(lock_path):
                            pass
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_operator_helper_keeps_the_verified_lock_and_rejects_replaced_db(self):
        self.operator_fixture()
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        state = self.root / ".state/state.db"
        jobs = self.root / ".state/jobs.sqlite3"
        lock = self.root / ".state/scraper.lock"
        for replace in (False, True):
            with self.subTest(replace=replace), patch.dict(os.environ, self.environment(), clear=True):
                descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.environ.update(
                    JSH_SCRAPER_ADMISSION_FD=str(descriptor), JSH_SCRAPER_ADMISSION_PATH=str(lock),
                    JSH_SCRAPER_RUNTIME_BINDING=json.dumps(stable._validate_runtime(self.root, state.parent)),
                    JSH_RETAINED_OPERATOR_SQLITE_LAYOUT=json.dumps(
                        stable._retained_operator_sqlite_layout(self.root, state, "sqlite")),
                )
                if replace:
                    replacement = jobs.with_name("replacement.sqlite3")
                    shutil.copy2(jobs, replacement)
                    replacement.replace(jobs)
                with (patch.object(runner, "PROJECT_ROOT", self.root),
                      patch.object(runner.helper_cli, "PROJECT_ROOT", self.root)):
                    if replace:
                        with self.assertRaisesRegex(RuntimeError, "SQLite identity no longer matches"):
                            with runner._retained_operator_admission():
                                self.fail("A changed database reached the handler")
                    else:
                        with runner._retained_operator_admission() as admission:
                            self.assertEqual(admission[:2], (state, jobs))
                            self.assertEqual(admission[2]["state"], "NO_RELEASE")
                            self.assertFalse(os.get_inheritable(descriptor))
                            with self.assertRaises(WriterLockBusy), writer_lock(lock):
                                pass
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_operator_helper_rejects_a_different_descriptor_for_the_same_lock(self):
        self.operator_fixture()
        stable = load_bootstrap(self.root / BOOTSTRAP.name)
        state = self.root / ".state/state.db"
        lock = self.root / ".state/scraper.lock"
        with (writer_lock(lock), lock.open("r+b") as other,
              patch.dict(os.environ, self.environment(), clear=True),
              patch.object(runner, "PROJECT_ROOT", self.root),
              patch.object(runner.helper_cli, "PROJECT_ROOT", self.root)):
            os.environ.update(
                JSH_SCRAPER_ADMISSION_FD=str(other.fileno()), JSH_SCRAPER_ADMISSION_PATH=str(lock),
                JSH_SCRAPER_RUNTIME_BINDING=json.dumps(stable._validate_runtime(self.root, state.parent)),
                JSH_RETAINED_OPERATOR_SQLITE_LAYOUT=json.dumps(
                    stable._retained_operator_sqlite_layout(self.root, state, "sqlite")),
            )
            with self.assertRaisesRegex(RuntimeError, "lock belongs to another process"):
                with runner._retained_operator_admission():
                    self.fail("An unlocked descriptor reached the handler")


if __name__ == "__main__":
    unittest.main()
