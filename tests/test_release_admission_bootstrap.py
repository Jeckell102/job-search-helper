import fcntl
import importlib.util
import json
import os
from pathlib import Path
import py_compile
import shutil
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
        env.pop("JSH_SCRAPER_ADMISSION_FD", None)
        env.pop("JSH_SCRAPER_ADMISSION_PATH", None)
        env.pop("JSH_SCRAPER_RUNTIME_BINDING", None)
        return env

    def command(self):
        return [sys.executable, str(self.root / BOOTSTRAP.name), "start"]

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

    def test_worker_imports_measured_source_even_with_an_old_timestamp_cache(self):
        runner_path = self.root / 'src/job_search_helper/runner.py'
        runner_path.write_text('print("old")\n')
        previous = runner_path.stat()
        py_compile.compile(str(runner_path), doraise=True,
                           invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
        runner_path.write_text('print("new")\n')
        os.utime(runner_path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        result = subprocess.run(self.command(), cwd=self.root, env=self.environment(),
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'new')

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
        record = self.root / ".state/record"
        record.mkdir()
        journal.update(record=str(record), manifest_sha256="a" * 64)
        (record / "receipt.json").write_text(json.dumps({
            key: journal[key] for key in ("state", "release_id", "release", "manifest_sha256")
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
            "JSH_SCRAPER_ADMISSION_FD": str(descriptor),
            "JSH_SCRAPER_ADMISSION_PATH": str(lock_path.resolve()),
            "JSH_SCRAPER_RUNTIME_BINDING": json.dumps(
                load_bootstrap()._validate_runtime(self.root, database.parent)),
        }
        with patch.dict(os.environ, environment, clear=False), patch.object(runner, 'PROJECT_ROOT', self.root):
            with patch("job_search_helper.runner.scraper_lock_name", return_value="scraper.lock"):
                with runner._scraper_admission(database) as binding:
                    self.assertEqual(binding["state"], "NO_RELEASE")
                    with self.assertRaises(WriterLockBusy):
                        with writer_lock(lock_path):
                            pass
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_runner_rejects_incomplete_handoff_and_unlocked_descriptor(self):
        lock = self.root / '.state/scraper.lock'
        database = lock.parent / 'state.db'
        descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, descriptor)
        binding = load_bootstrap()._validate_runtime(self.root, lock.parent)
        environment = {'JSH_SCRAPER_ADMISSION_PATH': str(lock),
                       'JSH_SCRAPER_RUNTIME_BINDING': json.dumps(binding)}
        with patch.object(runner, 'PROJECT_ROOT', self.root), patch.object(
                runner, 'scraper_lock_name', return_value='scraper.lock'):
            for fd_value, message in (('', 'incomplete'), (str(descriptor), 'not locked')):
                with self.subTest(fd_value=fd_value), patch.dict(
                        os.environ, {**environment, 'JSH_SCRAPER_ADMISSION_FD': fd_value}):
                    with self.assertRaisesRegex(RuntimeError, message):
                        with runner._scraper_admission(database):
                            self.fail('invalid descriptor admitted')


class PublicAdmissionRouteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        for name in ('release_admission_bootstrap.py', 'job-search-scraper', 'pyproject.toml'):
            shutil.copy2(PROJECT / name, self.project / name)
        shutil.copytree(PROJECT / 'src', self.project / 'src',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        self.state_dir = self.project / '.state'
        self.state_dir.mkdir()
        (self.project / '.storage-backend').write_text('sqlite\n')
        venv_bin = self.project / '.venv/bin'
        venv_bin.mkdir(parents=True)
        (venv_bin / 'python').symlink_to(sys.executable)

    def launch(self, *args, environment=None):
        return subprocess.run([str(self.project / 'job-search-scraper'), *args],
                              cwd=self.root, env=environment or self.environment(),
                              text=True, capture_output=True, timeout=15)

    def environment(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith('JSH_SCRAPER_')}
        env.update(JOB_STORAGE_BACKEND='sqlite', STATE_DB_FILE='.state/state.db',
                   JOB_DB_FILE='.state/jobs.sqlite3', PYTHONDONTWRITEBYTECODE='1')
        return env

    def test_named_sync_obtains_admission_without_double_acquisition(self):
        from job_search_helper.engine import State

        state = State(self.state_dir / 'state.db')
        state.close()
        result = self.launch('sync', '--cycle-id', 'CYC-fixture', '--company-id', 'C-1')
        self.assertEqual(result.returncode, 1, result)
        # The missing inbox is checked only after the actual named recovery
        # enters the inherited admission boundary.
        self.assertIn('inventory', result.stderr.lower())
        self.assertNotIn('holds the writer lock', result.stderr)
        self.assertNotIn('does not own', result.stderr)

    def test_public_controller_passes_admission_to_its_worker(self):
        package = self.project / 'src/job_search_helper'
        workflow_dir = self.state_dir / 'scrape-first-pass'
        work = workflow_dir / 'run-fixture'
        work.mkdir(parents=True)
        workflow = work / 'workflow.json'
        workflow.write_text(json.dumps({
            'workflow_id': 'run-fixture', 'stage': 'SCRAPE_PENDING',
            'before_cycles': [], 'status': 'RUNNING',
        }))
        (workflow_dir / 'latest.json').write_text(json.dumps({'workflow': str(workflow)}))
        (package / 'pipeline_probe.py').write_text(
            'import fcntl, json, pathlib\n'
            'directory = pathlib.Path(".state").resolve()\n'
            'with (directory / "scraper.lock").open("r+") as lock:\n'
            '    try:\n'
            '        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)\n'
            '        busy = False\n'
            '    except BlockingIOError:\n'
            '        busy = True\n'
            'cycles = [{"id": "CYC-fixture", "status": "In Progress"}] '
            'if (directory / "worker.json").exists() else []\n'
            'print(json.dumps(dict(state_dir=str(directory), scraper_busy=busy, cycles=cycles)))\n')
        (package / 'scrape_worker.py').write_text(
            'import json\n'
            'from .runner import _load_environment, _scraper_admission, state_path\n'
            '_load_environment()\n'
            'database = state_path()\n'
            'with _scraper_admission(database) as binding:\n'
            '    with (database.parent / "worker.json").open("x") as stream:\n'
            '        json.dump(binding, stream)\n')

        result = self.launch('start', '--resume')
        self.assertEqual(result.returncode, 1, result)
        self.assertIn('Scrape did not finish successfully', result.stderr)
        receipt = json.loads((self.state_dir / 'worker.json').read_text())
        self.assertEqual(receipt['state'], 'NO_RELEASE')
        self.assertEqual(json.loads(workflow.read_text())['status'], 'PAUSED_NOT_COMPLETE')
        with writer_lock(self.state_dir / 'scraper.lock'):
            pass


if __name__ == "__main__":
    unittest.main()
