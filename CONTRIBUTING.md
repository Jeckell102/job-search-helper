# Contributing To Job Search Helper

A clearer sentence, a reproducible bug report, or a small test can be as useful
as a new feature. First-time contributors are welcome. You do not need a live
job board, a personal catalog, or an API key to work on the project.

## Choose A Starting Point

- Read the [roadmap and starter tasks](ROADMAP.md) for concrete ideas.
- Browse [open issues](https://github.com/Jeckell102/job-search-helper/issues)
  before opening a new one. Comment on an existing issue to coordinate work.
- For a small documentation correction, go straight to a pull request.
- For a new provider, dependency, data model, or large feature, open a proposal
  describing the user problem and intended approach first.

Questions are welcome through the question issue template. There is no need to
claim a task formally before experimenting locally. Maintainer review is needed
before merging; opening a proposal does not guarantee acceptance or a timeline.

## Set Up A Development Copy

Use Linux and Python 3.11 or later. Fork the repository on GitHub, then replace
`YOUR-USERNAME` below with your GitHub username. Check `python3 --version` first;
if it is older than 3.11, use a supported executable such as `python3.11` when
creating the virtual environment:

```bash
git clone https://github.com/YOUR-USERNAME/job-search-helper.git
cd job-search-helper
git switch -c docs/clearer-setup
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m pip install 'setuptools>=68' wheel
```

Choose a branch name describing your change. Build-tool installation may use the
network; the tests below use synthetic data and run offline. The application and
unit tests need no third-party runtime packages.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m unittest discover -s tests
python tests/check_local_install.py
```

The second check builds a wheel offline, installs it into a fresh temporary
environment, and exercises the installed command. It needs pip, setuptools 68+
and wheel in the development environment, and Python's `venv` support. Test
catalogs are temporary; tests must never depend on a contributor's own data.

For a focused adapter test during development:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -m unittest test_ats
```

GitHub Actions runs the full checks on Linux with Python 3.11, 3.12, and 3.13.
For documentation-only changes, check links and try any commands you changed;
you do not need to invent a test for a wording correction.

## Make A Focused Change

Follow the style of nearby code and keep unrelated formatting out of the change.
Add a regression test when changing job identity, source scope, inventory
completeness, recovery, screening, or application history. Keep user-facing
instructions in sync with command changes.

These behaviors protect users' records:

- Adapters return evidence; they do not write directly to the catalog or decide
  whether someone should apply.
- Partial, blocked, or failed inventories cannot establish that a job closed.
- Application history remains independent of scans and screening assessments.
- Preserve full descriptions, original dates, and uncertainty in source data.
- SQL migrations are append-only. Never edit an existing migration: installed
  catalogs verify its checksum. Add a numbered migration with preservation tests.
- Use bounded requests to supported public endpoints. Do not add CAPTCHA bypasses,
  login scraping, or credentials to fixtures.

The [architecture guide](docs/architecture.md) maps modules and explains the
adapter extension path. The Python internals are still evolving; discuss new
extension contracts before treating them as stable plugin APIs.

## Open Your First Pull Request

1. Run the relevant checks and review your diff for unrelated or personal files.
2. Commit your change and push your branch to your fork.
3. Open a pull request against this repository's `main` branch. A draft is fine
   when you would like feedback on unfinished work.
4. Explain the user problem, what changes, and how you verified it. Link a related
   issue if there is one; an issue is not required for every small change.
5. Respond to review questions and keep the description current as the change evolves.

For command-output changes, include a short before/after example using invented
records. Mention checks you could not run. Please be patient with review; this
project does not promise a response time.

## Share Examples Safely

Invent companies, descriptions, profiles, and records for fixtures and reports.
Do not upload personal catalogs, resumes, application notes, tokens, spreadsheet
identifiers, or unreviewed captured employer responses. A minimal synthetic
reproduction makes issues easier to review and keeps them shareable.

See [SECURITY.md](SECURITY.md) for sensitive reports and
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for community expectations.
Contributions are made under the project's [MIT license](LICENSE); only submit
work you have the right to contribute.
