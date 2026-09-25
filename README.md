# Job Search Helper

A local command-line tool for collecting public job postings, reviewing saved
evidence, and tracking applications. Your catalog lives in SQLite on your own
computer. Screening is optional and starts with no personal preferences.

This is an early public release for Python 3.11+ on Linux. It has no required
third-party runtime packages, accounts, Google credentials, or model API keys.
Live scans need internet access. It does not submit applications.

## Install

Extract the source archive, open its `job-search-helper` directory, and run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/job-search-helper --help
```

Installation may download Python build tools. For development, use
`.venv/bin/python -m pip install -e .` instead. Prefix commands below with
`.venv/bin/`, or activate the environment using `source .venv/bin/activate`.

## Start A Catalog

Keep your personal workspace outside the source directory:

```bash
job-search-helper init --workspace "$HOME/job-search-workspace"
job-search-helper doctor --workspace "$HOME/job-search-workspace"
```

Prepare `companies.csv` in that workspace using
[`examples/companies.csv.example`](examples/companies.csv.example). Replace the
fictional example with your chosen companies and their verified public hiring
board URLs. The example domain is a placeholder and will not produce jobs.

```bash
job-search-helper local import-companies companies.csv --workspace "$HOME/job-search-workspace"
job-search-helper local import-companies companies.csv --apply --workspace "$HOME/job-search-workspace"
job-search-helper local companies list --workspace "$HOME/job-search-workspace"
job-search-helper local scan --all --workspace "$HOME/job-search-workspace"
job-search-helper local jobs list --workspace "$HOME/job-search-workspace"
```

Import previews changes first; `--apply` saves them. A scan saves its fetched
inventory before the writer updates the catalog. Interrupted work can resume.
Application history remains independent of job updates and screening decisions.

## What Is Included

- Direct public adapters for Greenhouse, Lever, Ashby, Workday, iCIMS, ADP
  Workforce Now, Paylocity, and Taleo, plus one explicitly scoped careers adapter.
- Full descriptions, stable identities, source history, scan recovery, and
  conservative missing-job tracking.
- Company import, application statuses and edit history, verified backups,
  and readable CSV exports.
- Explicit screening profiles for title phrases, work arrangements, and annual
  USD base salary. No profile means no screening rules.
- Offline tests with synthetic records and no personal data or previous history.

Dates use readable text: `2026-09-25` or `2026-09-25 14:30:00 UTC` in normal
output and exports. SQLite and JSON retain ISO timestamps. Original source
dates remain available; ambiguous dates and unknown time zones are not guessed.

See the [user guide](docs/user-guide.md) for recovery, applications, settings,
screening, exports, and upgrades, and [CONTRIBUTING.md](CONTRIBUTING.md) for tests.

## Current Limits

Local scanning uses one worker and verified supported board URLs. General
careers pages can be saved but may be reported as unsupported. Browser fallback,
automatic source repair, legacy workbook import, and AI reviews are not included.
Blocked or incomplete pages remain incomplete; they cannot establish closure.
Use public endpoints responsibly and respect access restrictions.

This release is tested offline on Linux. Live provider behavior and other
operating systems have not been certified. Personal catalogs, exports, notes,
and profiles belong in your private workspace and should not be committed.

## License

[MIT](LICENSE). Contributions and modifications are welcome.
