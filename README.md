# Job Search Helper

**Keep your job search organized, keep your data on your computer, and help build what comes next.**

[![Tests](https://github.com/Jeckell102/job-search-helper/actions/workflows/tests.yml/badge.svg)](https://github.com/Jeckell102/job-search-helper/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Job Search Helper is a local command-line tool that collects public job postings,
keeps their descriptions and source history, and helps you track applications.
Your catalog lives in a SQLite database on your computer. You choose the
companies, decide whether to screen postings, and control your application history.

This is an early open-source project. Documentation fixes, bug reports, tests,
adapter improvements, and ideas from people actually searching for work are all
welcome. You do not need to be an experienced developer to contribute.

[Get started](#get-started) | [User guide](docs/user-guide.md) |
[Contribute](CONTRIBUTING.md) | [Roadmap and starter tasks](ROADMAP.md)

## What You Can Do

- Collect postings from supported employer job boards and keep full descriptions.
- Resume interrupted scans without discarding already-saved work.
- Track application statuses, notes, and edit history independently of job updates.
- Optionally screen titles, work arrangements, and annual USD base salary using
  a profile you define. No profile means no screening rules.
- Export readable CSV files and create verified database backups.

Supported adapters cover Greenhouse, Lever, Ashby, Workday, iCIMS, ADP Workforce
Now, Paylocity, and Taleo. There is also a narrowly scoped Textron Systems
careers-page adapter. Use verified direct board URLs; arbitrary careers pages
are not automatically supported.

**Current status:** version 0.2.0, alpha, Python 3.11+, Linux. The runtime uses
only Python's standard library. No Google credentials, account, or AI API key
is required. Live scans need internet access. The tool does not submit applications.

## Get Started

These commands are for a Linux shell with Python 3.11+, Git, and Python's virtual
environment support installed. Check `python3 --version` first. If it is older
than 3.11, install a supported Python and use its executable (for example,
`python3.11`) in the venv command below. If Python reports that `venv` or
`ensurepip` is missing, install your distribution's matching Python venv package.

```bash
git clone https://github.com/Jeckell102/job-search-helper.git
cd job-search-helper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
job-search-helper --help
```

You can also download the source from GitHub's **Code > Download ZIP**, extract
it, and run the commands starting at `python3 -m venv .venv` inside the extracted
directory. Installation may download Python build tools.

### Try An Empty Catalog

Create a private workspace outside the repository:

```bash
job-search-helper init --workspace "$HOME/job-search-workspace"
job-search-helper doctor --workspace "$HOME/job-search-workspace"
job-search-helper local jobs list --workspace "$HOME/job-search-workspace"
```

This first check works offline after installation. A new catalog has no jobs;
`doctor` checks its database. No account setup or existing spreadsheet is needed.

### Add Companies And Collect Jobs

Copy the example into your workspace:

```bash
cp examples/companies.csv.example "$HOME/job-search-workspace/companies.csv"
```

Open that copy in a text editor or spreadsheet application. Replace the fictional
company and placeholder URL with a company and its verified public hiring-board
URL. The example itself will not produce jobs. The
[company import guide](docs/user-guide.md#companies-and-sources) describes the
columns and supported URL shapes.

```bash
job-search-helper local import-companies companies.csv --workspace "$HOME/job-search-workspace"
job-search-helper local import-companies companies.csv --apply --workspace "$HOME/job-search-workspace"
job-search-helper local companies list --workspace "$HOME/job-search-workspace"
job-search-helper local scan --all --workspace "$HOME/job-search-workspace"
job-search-helper local jobs list --workspace "$HOME/job-search-workspace"
```

The first import previews changes; `--apply` saves them. Relative input paths
resolve inside the workspace. A scan saves fetched evidence before the catalog
writer applies it. Interrupted work can resume.

Next, use the [user guide](docs/user-guide.md) to track applications, customize
screening, recover scans, and export your catalog.

## Built Around Your Records

Application history stays separate from job availability and screening results.
An incomplete or blocked scan cannot mark a job closed. Unknown salary, missing
dates, and ambiguous time zones remain unknown instead of being guessed.

Normal output and CSV exports show dates as `2026-09-25` or timestamps as
`2026-09-25 14:30:00 UTC`. SQLite and JSON retain ISO timestamps, and original
source date text remains available.

Keep personal catalogs, profiles, application notes, exports, and backups in
your private workspace. Use invented records when sharing a bug report or test.

## Help Shape The Project

Start with a small improvement that matters to you:

| You enjoy... | A useful contribution |
| --- | --- |
| Trying tools and explaining things | Test the setup instructions and improve an unclear step. |
| Finding edge cases | Add a synthetic example of an ambiguous date or incomplete board response. |
| Working with Python | Improve a provider adapter, command output, or recovery test. |
| Designing workflows | Describe a concrete job-search task the tool could make easier. |

See the [starter tasks](ROADMAP.md#starter-tasks) for bounded ideas with suggested
files and completion criteria. The [contribution guide](CONTRIBUTING.md) walks
through your first pull request, and the [architecture guide](docs/architecture.md)
shows where to extend the code.

[Report a bug or suggest an improvement](https://github.com/Jeckell102/job-search-helper/issues/new/choose).
Questions and documentation-only pull requests are welcome. For larger changes,
open a proposal first so the approach can be discussed before you invest time.
Please follow the [community guidelines](CODE_OF_CONDUCT.md).

## Current Limits

Scanning uses one worker. Browser fallback, automatic source repair, spreadsheet
migration, a graphical interface, and AI reviews are not included. Live providers
can change their pages or restrict access. Respect access restrictions and request
limits; a blocked source is a result to report, not a restriction to bypass.

Automated checks use synthetic data on Linux. They do not certify every live
provider or other operating systems. The [roadmap](ROADMAP.md) separates existing
features from possible future work; it is an invitation to contribute, not a
release-date commitment.

For help, see [support](SUPPORT.md). For sensitive reports, see
[security reporting](SECURITY.md).

## License

Released under the [MIT license](LICENSE). You may use, modify, and redistribute
the project under its terms. Contributions are welcome under the same license.
