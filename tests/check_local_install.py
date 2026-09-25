"""Offline wheel/install acceptance check. Run explicitly, outside unittest discovery."""
from __future__ import annotations

import json
import csv
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
import tomllib


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    project = args.project.resolve()
    metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    public = metadata["project"]["scripts"]["job-search-helper"] == "job_search_helper.local_cli:main"
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME"} and not key.startswith("JSH_")}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    with tempfile.TemporaryDirectory(prefix="jsh-install-") as directory:
        root = Path(directory)
        build = root / "source"
        build.mkdir()
        shutil.copy2(project / "pyproject.toml", build)
        for name in ("README.md", "LICENSE"):
            if (project / name).is_file():
                shutil.copy2(project / name, build)
        shutil.copytree(project / "src/job_search_helper", build / "src/job_search_helper",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        def run(*arguments):
            result = subprocess.run(arguments, cwd=root, env=environment, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if result.returncode:
                raise RuntimeError(f"Command failed: {arguments}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-index",
            "--wheel-dir", str(root / "dist"), str(build))
        wheel, = (root / "dist").glob("*.whl")
        with zipfile.ZipFile(wheel) as archive:
            assert "job_search_helper/migrations/001_foundation.sql" in archive.namelist()
            assert "job_search_helper/migrations/002_scan_ingestion.sql" in archive.namelist()
            assert "job_search_helper/migrations/003_local_screening.sql" in archive.namelist()
            assert not any(name.endswith((".db", ".sqlite3", ".env")) for name in archive.namelist())
            if public:
                for name in ("cli", "core", "efficiency", "engine", "repository", "runner", "screening", "browser_scraper"):
                    assert f"job_search_helper/{name}.py" not in archive.namelist()
                assert any(name.endswith("/LICENSE") for name in archive.namelist())
        run(sys.executable, "-m", "venv", str(root / "venv"))
        scripts = root / "venv" / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        command = scripts / ("job-search-helper.exe" if os.name == "nt" else "job-search-helper")
        run(str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel))
        assert "init" in run(str(command), "--help")
        if public:
            assert metadata["project"]["version"] in run(str(command), "--version")
            run(str(python), "-I", "-c", """
import importlib.util
from job_search_helper import local_cli
for name in ('cli', 'core', 'efficiency', 'engine', 'repository', 'runner', 'screening', 'browser_scraper'):
    assert importlib.util.find_spec('job_search_helper.' + name) is None, name
""")
        workspace = root / "empty workspace"
        common = ["--workspace", str(workspace), "--json"]
        initialized = json.loads(run(str(command), "init", *common))
        checked = json.loads(run(str(command), "doctor", *common))
        assert initialized["database_id"] == checked["database_id"]
        assert checked["counts"]["companies"] == 0
        assert json.loads(run(str(command), "db", "migrate", *common))["ok"]
        assert json.loads(run(str(command), "backup", "backups/snapshot.sqlite3", *common))["ok"]
        run(str(python), "-I", "-c", """
import importlib.util, sys
from pathlib import Path
from job_search_helper.database import Database
from job_search_helper.models import JobPosting
from job_search_helper.repositories import CatalogRepository, ApplicationRepository
from job_search_helper.scan_service import ScanService
from job_search_helper.ats import Inventory
assert importlib.util.find_spec('google') is None
assert importlib.util.find_spec('playwright') is None
workspace = Path(sys.argv[1])
with Database(workspace / 'data/job-search-helper.sqlite3') as database:
    catalog = CatalogRepository(database)
    company = catalog.add_company('Fixture company')
    source = catalog.add_source(company, 'lever', 'fixture', 'https://jobs.lever.co/fixture')
    job = catalog.create_job(company, JobPosting(posting_id='001', title='Principal Engineer',
                             description='Full evidence ' * 5000), source_id=source)
    application = ApplicationRepository(database).add(job)
    assert ApplicationRepository(database).get(application)['date_applied'] is None
    service = ScanService(database)
    cycle = service.start_cycle([company])
    attempt = service.begin_attempt(cycle, company)
    service.stage_inventory(attempt, Inventory('complete', [{'posting_id': '001', 'title': 'Updated title',
        'description': 'Full saved evidence ' * 5000, 'created_at': '2026-09-25T09:00:00-04:00'}]))
    assert database.check()['scan_recovery']['pending'] == 1
    database.backup(workspace / 'backups/populated.sqlite3')
with Database(workspace / 'backups/populated.sqlite3') as restored:
    assert ScanService(restored).apply_inventory(attempt)
    assert restored.check()['counts']['jobs'] == 1
    assert restored.check()['counts']['applications'] == 1
    assert CatalogRepository(restored).get_job(job)['title'] == 'Updated title'
    assert CatalogRepository(restored).get_job(job)['source_created_at'] == '2026-09-25T13:00:00Z'
""", str(workspace))
        status = json.loads(run(str(command), "local", "status", *common))
        cycle = status["cycle"]["cycle_id"]
        resumed = json.loads(run(str(command), "local", "resume", "--cycle", cycle, *common))
        assert resumed["cycle"]["status"] == "completed"
        imported_file = workspace / "companies.csv"
        shutil.copy2(project / "examples/companies.csv.example", imported_file)
        preview = json.loads(run(str(command), "local", "import-companies", "companies.csv", *common))
        assert not preview["applied"] and preview["counts"]["add"] == 1
        applied = json.loads(run(str(command), "local", "import-companies", "companies.csv", "--apply", *common))
        assert applied["applied"]
        repeated = json.loads(run(str(command), "local", "import-companies", "companies.csv", "--apply", *common))
        assert repeated["counts"]["unchanged"] == 1
        companies = json.loads(run(str(command), "local", "companies", "list", *common))
        assert companies["total"] == 2
        jobs = json.loads(run(str(command), "local", "jobs", "list", *common))
        assert jobs["items"][0]["title"] == "Updated title"
        applications = json.loads(run(str(command), "local", "applications", "list", *common))
        application = applications["items"][0]
        updated = json.loads(run(str(command), "local", "applications", "update", application["application_id"],
            "--expected-version", str(application["row_version"]), "--status", "applied", "--date-applied", "2026-09-25", *common))
        assert updated["application"]["date_applied"] == "2026-09-25"
        assert len(updated["application"]["events"]) == 2
        shown = json.loads(run(str(command), "local", "applications", "show", application["application_id"], *common))
        assert shown["application"]["company_name"] == "Fixture company"
        assert not json.loads(run(str(command), "local", "policy", *common))["enabled"]
        neutral = json.loads(run(str(command), "local", "screen", "--all", "--apply", *common))
        assert neutral["counts"]["skipped"] == 1
        profile = workspace / "profile.toml"
        profile.write_text('[titles]\nprefer = ["Updated title"]\n', encoding="utf-8")
        screening = json.loads(run(str(command), "local", "screen", "--all", "--profile", "profile.toml", *common))
        assert not screening["applied"] and screening["counts"]["new"] == 1
        screened = json.loads(run(str(command), "local", "screen", "--all", "--profile", "profile.toml", "--apply", *common))
        assessment_id = screened["items"][0]["assessment_id"]
        assessment = json.loads(run(str(command), "local", "assessments", "show", assessment_id, *common))["assessment"]
        assert assessment["result"] == "no_exclusion" and not assessment["stale"]
        assert assessment["policy"]["titles"]["prefer"] == ["updated title"]
        repeated_screen = json.loads(run(str(command), "local", "screen", "--all", "--profile", "profile.toml", "--apply", *common))
        assert repeated_screen["counts"]["unchanged"] == 1
        exported = json.loads(run(str(command), "local", "export", "--output", "exports/snapshot", *common))
        assert len(exported["files"]) == 4
        directory = Path(exported["directory"])
        with (directory / "Jobs.csv").open(encoding="utf-8-sig", newline="") as handle:
            job_rows = list(csv.DictReader(handle))
        assert job_rows[0]["Job Title"] == "Updated title"
        assert job_rows[0]["Job Description"] == "Full saved evidence " * 5000
        assert job_rows[0]["Screening Result"] == "No Exclusion Found"
        assert job_rows[0]["Review Status"] == "Not Evaluated"
        with (directory / "Applications.csv").open(encoding="utf-8-sig", newline="") as handle:
            assert list(csv.DictReader(handle))[0]["Date Applied"] == "2026-09-25"
        imported_again = json.loads(run(str(command), "local", "import-companies", "exports/snapshot/Companies.csv", "--apply", *common))
        assert imported_again["counts"]["unchanged"] == 2
        assert (directory / "manifest.json").exists()
        print("Clean wheel install passed: local catalog/recovery, company import, application tracking, optional screening/history, four CSV exports and verified company re-import.")


if __name__ == "__main__":
    main()
