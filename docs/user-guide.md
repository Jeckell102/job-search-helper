# User Guide

All examples use a private workspace at `$HOME/job-search-workspace`. Supply
`--workspace` after the final command action. Relative input, backup, export,
settings, and profile paths resolve against that workspace. `JSH_WORKSPACE`
can supply the workspace default; otherwise the current directory is used.

## Companies And Sources

Company import requires UTF-8 CSV with `Company Name` and `Careers URL` columns.
Optional columns are `Company ID`, `Status`, `Website`, `Category`,
`Technology / Focus`, `Priority`, `Notes`, `Why It Fits`, and `ATS Type`.
Status values are `active`, `paused`, and `archived`.

```bash
job-search-helper local import-companies companies.csv --workspace "$HOME/job-search-workspace"
job-search-helper local import-companies companies.csv --apply --workspace "$HOME/job-search-workspace"
job-search-helper local companies list --workspace "$HOME/job-search-workspace"
job-search-helper local companies show COMPANY-ID --workspace "$HOME/job-search-workspace"
```

Replace placeholder IDs with those shown by the list commands. Preview reports
invalid rows and source changes. Apply revalidates everything and commits the
whole import together. Repeating an unchanged import is a no-op. Blank optional
cells preserve existing values; `[clear]` clears an optional text value. A new
supplied ID requires `--preserve-ids`; otherwise IDs are generated.

URLs must be public HTTPS URLs without credentials. Import validates URL shape
offline. Verify the board belongs to the employer yourself. Use a direct board
URL such as `https://jobs.lever.co/BOARD_NAME` or
`https://boards.greenhouse.io/BOARD_TOKEN`; these are URL shapes, not real boards
to scan. General careers pages can be stored but are not automatically resolved
by this local workflow. Supported types are listed in the README. The additional
scoped Taleo adapter recognizes only the Textron Systems `careers/apply-today`
page, retaining that page's employer scope instead of scanning its parent board.

Include the existing Company ID when changing a source. Historical jobs and
application records are retained. Complete an unfinished scan cycle before
changing its companies' sources.

## Scans And Recovery

```bash
job-search-helper local scan --company-id COMPANY-ID --workspace "$HOME/job-search-workspace"
job-search-helper local scan --all --workspace "$HOME/job-search-workspace"
job-search-helper local status --workspace "$HOME/job-search-workspace"
job-search-helper local resume --cycle CYCLE-ID --workspace "$HOME/job-search-workspace"
job-search-helper local resume --cycle CYCLE-ID --retry-exceptions --workspace "$HOME/job-search-workspace"
```

`--all` selects active companies with a current source. A cycle saves its company
selection and scan settings. Only one coordinator may scan a catalog at once.
Resume applies already-saved inventories first and does not refetch completed
members. `--retry-exceptions` explicitly retries incomplete or failed sources.
Results with conflicting identities or invalid checksums remain quarantined
for inspection. There is no automatic quarantine-resolution command.

Fetching occurs before transactional catalog updates. Full fetched evidence is
saved durably before interpretation. Partial inventories can establish positive
sightings but cannot mark jobs missing. By default, two comparable complete
scans without a posting infer closure. Changes to board scope reset comparisons.
Fresh sightings can reopen jobs without changing application records.

Exit codes: 0 success, 1 scan completed with exceptions, 2 invalid settings or
database error, 3 busy catalog, and 130 interruption.

## Jobs And Applications

```bash
job-search-helper local jobs list --workspace "$HOME/job-search-workspace"
job-search-helper local jobs show JOB-ID --workspace "$HOME/job-search-workspace"
job-search-helper local applications add --job-id JOB-ID --notes "Interested" --workspace "$HOME/job-search-workspace"
job-search-helper local applications list --workspace "$HOME/job-search-workspace"
job-search-helper local applications show APPLICATION-ID --workspace "$HOME/job-search-workspace"
job-search-helper local applications update APPLICATION-ID --expected-version 1 --status applied --date-applied 2026-09-25 --workspace "$HOME/job-search-workspace"
```

Use the row version shown by `show` for `--expected-version`. Stale edits are
refused. Each edit appends history. Application statuses are `interested`,
`preparing`, `applied`, `interviewing`, `offer`, `accepted`, `rejected`,
`withdrawn`, `archived`, and `unknown`. Saving `applied` without a date leaves
the date unknown. `--resume-used` stores a label only; it uploads no file.

Lists default to 100 rows; use `--limit` and `--offset` for pagination. Jobs and
companies support `--search`; jobs and applications support `--company-id`.
Use each command's `--help` for filters and editable fields. `--json` returns
machine-readable results.

## Optional Screening

Copy the neutral example profile into your private workspace and edit it:

```bash
job-search-helper local policy --profile config/profile.toml --workspace "$HOME/job-search-workspace"
job-search-helper local screen --all --profile config/profile.toml --workspace "$HOME/job-search-workspace"
job-search-helper local screen --all --profile config/profile.toml --apply --workspace "$HOME/job-search-workspace"
job-search-helper local assessments list --workspace "$HOME/job-search-workspace"
job-search-helper local assessments show ASSESSMENT-ID --workspace "$HOME/job-search-workspace"
```

Profiles are loaded only when explicitly passed. Supported fields are title
`exclude`/`prefer` phrases, `work_arrangements`, and an annual USD base-salary
`minimum` with explicit `currency` and `period`. Empty settings enable no rules.
Title phrases match whole words, case-insensitively; they are not regular
expressions. Exclusion wins over preference. Unknown salary or work-arrangement
evidence requires review instead of being guessed.

Screening previews first. Apply saves an immutable assessment of the current
evidence and exact profile. Unchanged retries do not duplicate assessments.
Changed evidence marks earlier results stale. Results are Not Evaluated,
Excluded by Profile, Needs Review, or No Exclusion Found; none is a complete
fit decision. Jobs remain in the catalog and applications remain unchanged.
Travel, geography, clearance, employment type, and free-text requirements are
not evaluated by this release.

## Dates, Exports, And Backups

```bash
job-search-helper local export --output exports/review --workspace "$HOME/job-search-workspace"
job-search-helper backup backups/catalog.sqlite3 --workspace "$HOME/job-search-workspace"
job-search-helper doctor --workspace "$HOME/job-search-workspace"
```

Exports create Companies, Jobs, Applications, and ScanCycles CSV files with a
checksum manifest in a new directory. Timestamps display as
`2026-09-25 14:30:00 UTC`; date-only values remain `2026-09-25`. SQLite and JSON
store ISO timestamps. Original source text is retained. Ambiguous dates remain
unparsed, and unzoned times do not acquire an invented time zone.

Descriptions are not truncated. Formula-like cells receive a visible `text: `
prefix. Import identifier columns as text in spreadsheet software. An unchanged
Companies export can be re-imported with its accompanying manifest; edited
exports require a separate plain company CSV. Jobs and Applications CSV editing
does not update the catalog. CSV snapshots omit some history and are not backups.

Backups include the entire database and pending work, are verified before
publication, and refuse to overwrite an existing file. To inspect a backup,
run `doctor --database backups/catalog.sqlite3` with the same workspace. To
restore, stop writers, keep the original catalog, copy the verified backup to a
new filename, and pass that file using `--database`. Backups and exports contain
your private records and notes.

## Settings And Upgrades

`examples/settings.toml.example` documents settings. Supply an explicit file
using `--settings config/settings.toml`. Database paths are workspace-relative
unless absolute. Scan timeout, request interval, and missing threshold are
configurable. This release requires one worker, three HTTP attempts, and browser
fallback disabled. Resuming a cycle uses that cycle's saved settings.

For an existing catalog, back it up with its compatible installation before
upgrading. Install the new version and explicitly run:

```bash
job-search-helper db migrate --workspace "$HOME/job-search-workspace"
job-search-helper doctor --workspace "$HOME/job-search-workspace"
```

New catalogs use schema 3. Ordinary commands do not silently upgrade old
catalogs. Migration checksums prevent edited historical migrations from being
applied. Unsupported schemas are refused.
