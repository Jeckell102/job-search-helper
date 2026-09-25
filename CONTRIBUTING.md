# Contributing

Use Python 3.11 or later. The standard library is sufficient for the runtime and
unit tests. Install the project in an isolated virtual environment for command
line and packaging checks.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python -m unittest discover -s tests
.venv/bin/python tests/check_local_install.py
```

The installation check needs `pip` and `setuptools>=68` already installed in the
build environment, plus Python's `venv` support. It builds offline, installs into
a separate empty environment, and exercises the actual installed command.
All test data is temporary. Unit tests must not depend on live job boards.

Keep changes focused and describe the behavior and verification in your pull
request. Include a regression test for changes to identity, source scope,
inventory completeness, recovery, screening, or application history. Do not
edit existing SQL migration files: checksums protect installed catalogs. Add a
new numbered migration and cover upgrade preservation instead.

Use invented companies, descriptions, profiles, and records in examples and
tests. Avoid copying a personal catalog, resume, application note, token,
spreadsheet identifier, or captured employer response into the repository.
Public issue reports should contain a minimal synthetic reproduction. Reports
about credentials or personal information should use a private channel offered
by the repository maintainer, without attaching the sensitive content.

The public application starts in `src/job_search_helper/local_cli.py`. Scrapers
return inventories; `scan_service.py` stages and applies them; repositories
manage catalog records; optional screening appends assessments. Application
decisions remain under user control. Contributions are under the MIT license.
