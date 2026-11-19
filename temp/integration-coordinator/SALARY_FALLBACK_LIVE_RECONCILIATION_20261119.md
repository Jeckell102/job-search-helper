# Guarded salary-fallback reconciliation — 2026-11-19

## Scope and policy

This is a bounded synchronization evidence record. It contains no raw job
descriptions, salary values, credentials, or Google response payloads.

The owner-directed rule is now installed: a spreadsheet-maintained numeric
salary estimate may become the local fallback only if the current posting has
an empty `Salary / Range` or the exact known empty compensation envelope. A
nonblank, malformed, partial, unfamiliar, or locally dirty posting value still
uses the ordinary protected-conflict path.

## Implementation and test evidence

- Reviewed source backup: GitHub commit `87568ae` on
  `codex/integration-automation-20261118`.
- Independent QA passed the constrained branch. A requested partial-envelope
  regression was added before installation.
- The protected checkout merged the narrow branch into its already-installed
  synchronization safeguards rather than replacing the file.
- Installed source SHA-256:
  `034c90e64f5d44767094a525ecb363826f40ec70eea3864e7e9ce19592934fa2`
  (`src/job_search_helper/sheets_sync.py`).
- Installed regression-test SHA-256:
  `3eca0239d7d9ebc57645f947fa6d93ae3aaf676f46c8434a36480540356b3c03`
  (`tests/test_sqlite_migration.py`).
- Protected focused suite: 65 checks passed across SQLite synchronization,
  review correction, and batching tests.
- A consistent pre-live SQLite backup was created at the private local path
  `/tmp/job-search-salary-fallback-prelive-20261119.sqlite3`, SHA-256
  `fdcaaa444fd464ce64c4148bab14ff88ff42bbfdf9323bfa1e40c46403c5cce0`.

## Live bounded result

- Fresh process inspection found no active scraper or coordinator. Existing
  locks were retained untouched; automatic queue and campaign controls stayed
  off.
- The first system-Python attempt stopped before Google initialization because
  it lacked the preinstalled Google support. It made no Google or job-data
  change.
- The existing project virtual environment completed a normal guarded pull:
  20 eligible remote salary estimates were reconciled locally under the exact
  fallback rule. No nonblank posting salary was overwritten.
- The one already-pending Saronic `Last Checked` delivery retained its exact
  durable receipt through an uncertain acknowledgement, then a one-row normal
  publisher retry settled it without replay.
- The final no-op Google readback at `2026-11-19T14:10:28+00:00` reported
  zero pending cells, zero pending rows, zero published rows, and no error.
- One deliberate conflict remains: the missing `Prepared` Companies row. It
  was neither recreated nor bypassed.

## Limits and next gate

This proves guarded salary fallback, normal synchronization, receipt recovery,
and a clean publisher state for this narrow scope. It does not prove a
company-only scrape, job/evidence creation, FIRST PASS, broad-cycle recovery,
or automatic release. Those remain separate roadmap gates.
