"""Exercise the real release journal and bootstrap in separate processes."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys

import pytest

from job_search_helper import integration_release as release
from job_search_helper.cli import WriterLockBusy


PROJECT = Path(__file__).resolve().parents[1]
MODULES = ("src/job_search_helper/adapter_a.py", "src/job_search_helper/adapter_b.py")
VERIFICATION = {"result": "PASS", "case": "release-process-fixture"}
TIMEOUT = 15

APPLY = """
import json
from pathlib import Path
import sys
from job_search_helper import integration_release as release

project, candidate, state, records, manifest_path, barrier = sys.argv[1:]
manifest = json.loads(Path(manifest_path).read_text())

def hold(stage):
    if stage == barrier:
        print(stage, flush=True)
        if sys.stdin.readline().strip() != "continue":
            raise RuntimeError("Test did not release activation barrier")

release.activate_release(
    project, candidate, state, records, manifest,
    current_source_revision=lambda _: "fixture-source",
    dependency_digest=lambda: release.dependency_manifest_digest(project),
    verify=lambda *_: {"result": "PASS", "case": "release-process-fixture"},
    fault=hold,
)
"""

ROLLBACK = """
import sys
from pathlib import Path
from unittest.mock import patch
from job_search_helper import integration_release as release

project, state, records, release_id = sys.argv[1:]
write = release._write_json

def hold_after_receipt(path, value):
    write(path, value)
    if Path(path).name == "rollback.json":
        print("rollback-receipt", flush=True)
        if sys.stdin.readline().strip() != "continue":
            raise RuntimeError("Test did not release rollback barrier")

with patch.object(release, "_write_json", hold_after_receipt):
    release.rollback_release(project, state, records, release_id)
"""

RUNNER = """
import json
import os
from pathlib import Path
import sys
from .adapter_a import VERSION as first

print("runner-imported", flush=True)
if "--barrier" in sys.argv and sys.stdin.readline().strip() != "continue":
    raise RuntimeError("Test did not release scraper barrier")

from .adapter_b import VERSION as second

runtime = json.loads(os.environ["JSH_SCRAPER_RUNTIME_BINDING"])
Path(os.environ["F3_FIXTURE_RESULT"]).write_text(json.dumps([first, second, runtime]))
"""


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("JOB_STORAGE_BACKEND", "sqlite")
    monkeypatch.delenv("STATE_DB_FILE", raising=False)
    for key in ("JSH_SCRAPER_ADMISSION_FD", "JSH_SCRAPER_ADMISSION_PATH",
                "JSH_SCRAPER_RUNTIME_BINDING"):
        monkeypatch.delenv(key, raising=False)
    project, candidate = tmp_path / "installed", tmp_path / "candidate"
    for root, version in ((project, "old"), (candidate, "new")):
        package = root / "src/job_search_helper"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "runner.py").write_text(RUNNER)
        for name in MODULES:
            (root / name).write_text(f"VERSION = {version!r}\n")
        (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    shutil.copyfile(PROJECT / "release_admission_bootstrap.py", project / "release_admission_bootstrap.py")
    return ProcessFixture(tmp_path, project, candidate)


class ProcessFixture:
    def __init__(self, root, project, candidate):
        self.project = project
        self.candidate = candidate
        self.database = project / ".state/state.db"
        self.records = root / "release-records"
        self.result = root / "runner-result.json"
        self.journal = self.database.parent / "integration-release-journal.json"
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                        F3_FIXTURE_RESULT=str(self.result), PYTHONPATH=str(PROJECT / "src"))
        self.manifest = {
            "schema": release.MANIFEST_SCHEMA,
            "failed_request_id": "REQ-fixture",
            "company_id": "COMP-fixture",
            "source_revision": "fixture-source",
            "files": {name: {"before": release.metadata(project / name),
                             "after": release.metadata(candidate / name)} for name in MODULES},
            "before_source_manifest_sha256": release.source_tree_digest(project),
            "source_manifest_sha256": release.source_tree_digest(candidate),
            "before_config_sha256": release.config_tree_digest(project),
            "config_sha256": release.config_tree_digest(project),
            "dependency_manifest_sha256": release.dependency_manifest_digest(project),
            "validation_receipt_sha256": release.digest(VERIFICATION),
        }
        self.release_id = release.manifest_release_id(self.manifest)
        self.manifest["release_id"] = self.release_id
        self.manifest_path = root / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest))

    def bootstrap(self, *args):
        return [sys.executable, "-I", "-S", str(self.project / "release_admission_bootstrap.py"),
                "start", *args]

    def activating(self, barrier):
        return [sys.executable, "-c", APPLY, str(self.project), str(self.candidate),
                str(self.database), str(self.records), str(self.manifest_path), barrier]

    def rolling_back(self):
        return [sys.executable, "-c", ROLLBACK, str(self.project),
                str(self.database), str(self.records), self.release_id]

    @contextmanager
    def spawn(self, command):
        with subprocess.Popen(command, cwd=self.project, env=self.env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) as process:
            try:
                yield process
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=TIMEOUT)

    def check_start_blocked(self, reason):
        process = subprocess.run(self.bootstrap(), cwd=self.project, env=self.env,
                                 capture_output=True, text=True, timeout=TIMEOUT)
        assert process.returncode == 2, (process.stdout, process.stderr)
        assert reason in process.stderr
        assert "runner-imported" not in process.stdout
        assert not self.result.exists()

    def check_started_version(self, version, state):
        process = subprocess.run(self.bootstrap(), cwd=self.project, env=self.env,
                                 capture_output=True, text=True, timeout=TIMEOUT)
        assert process.returncode == 0, (process.stdout, process.stderr)
        first, second, runtime = json.loads(self.result.read_text())
        assert (first, second) == (version, version)
        assert runtime["state"] == state
        if state == "NO_RELEASE":
            assert "release_id" not in runtime
        else:
            assert runtime["release_id"] == self.release_id
        digest_field = ("source_manifest_sha256" if state == "COMPLETE"
                        else "before_source_manifest_sha256")
        assert runtime["source_manifest_sha256"] == self.manifest[digest_field]


def wait_for_boundary(process, boundary):
    ready, _, _ = select.select([process.stdout], [], [], TIMEOUT)
    assert ready, f"Timed out waiting for {boundary}"
    line = process.stdout.readline()
    if not line:
        _, stderr = process.communicate(timeout=TIMEOUT)
        pytest.fail(f"Child exited before {boundary}: {process.returncode} {stderr}")
    assert line.strip() == boundary


def finish(process):
    stdout, stderr = process.communicate("continue\n", timeout=TIMEOUT)
    assert process.returncode == 0, (stdout, stderr)


def test_worker_first_excludes_activation_until_after_lazy_import(fixture):
    with fixture.spawn(fixture.bootstrap("--barrier")) as worker:
        wait_for_boundary(worker, "runner-imported")
        with pytest.raises(WriterLockBusy):
            release.activate_release(
                fixture.project, fixture.candidate, fixture.database, fixture.records,
                fixture.manifest, current_source_revision=lambda _: "fixture-source",
                dependency_digest=lambda: release.dependency_manifest_digest(fixture.project),
                verify=lambda *_: VERIFICATION)
        assert not fixture.journal.exists()
        finish(worker)
    first, second, runtime = json.loads(fixture.result.read_text())
    assert (first, second, runtime["state"]) == ("old", "old", "NO_RELEASE")


def test_activation_first_excludes_worker_until_entire_release_is_durable(fixture):
    with fixture.spawn(fixture.activating("installed:0")) as installer:
        wait_for_boundary(installer, "installed:0")
        assert json.loads(fixture.journal.read_text())["state"] == "INSTALLING"
        assert "new" in (fixture.project / MODULES[0]).read_text()
        assert "old" in (fixture.project / MODULES[1]).read_text()
        fixture.check_start_blocked("owns admission")
        finish(installer)
    fixture.check_started_version("new", "COMPLETE")


def test_crash_after_record_is_durable_allows_old_start_and_exact_replay(fixture):
    with fixture.spawn(fixture.activating("record_durable")) as installer:
        wait_for_boundary(installer, "record_durable")
        record_manifest = fixture.records / fixture.release_id / "manifest.json"
        assert json.loads(record_manifest.read_text()) == fixture.manifest
        assert not fixture.journal.exists()
        fixture.check_start_blocked("owns admission")
        installer.kill()
        installer.communicate(timeout=TIMEOUT)
        assert installer.returncode < 0
    assert not fixture.journal.exists()
    fixture.check_started_version("old", "NO_RELEASE")

    # Re-enter the same activation with the durable record still in place.
    with fixture.spawn(fixture.activating("record_durable")) as installer:
        wait_for_boundary(installer, "record_durable")
        assert not fixture.journal.exists()
        finish(installer)
    fixture.check_started_version("new", "COMPLETE")


def test_partial_activation_and_interrupted_rollback_hold_start_until_recovery(fixture):
    with fixture.spawn(fixture.activating("installed:0")) as installer:
        wait_for_boundary(installer, "installed:0")
        installer.kill()
        installer.communicate(timeout=TIMEOUT)
        assert installer.returncode < 0
    fixture.check_start_blocked("Interrupted integration release")
    with fixture.spawn(fixture.rolling_back()) as rollback:
        wait_for_boundary(rollback, "rollback-receipt")
        fixture.check_start_blocked("owns admission")
        rollback.kill()
        rollback.communicate(timeout=TIMEOUT)
        assert rollback.returncode < 0
    assert json.loads(fixture.journal.read_text())["state"] == "INSTALLING"
    fixture.check_start_blocked("Interrupted integration release")
    receipt = release.rollback_release(fixture.project, fixture.database,
                                       fixture.records, fixture.release_id)
    assert receipt["state"] == "ROLLED_BACK"
    fixture.check_started_version("old", "ROLLED_BACK")
