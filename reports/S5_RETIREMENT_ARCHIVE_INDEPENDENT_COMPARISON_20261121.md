# CYC-B639C6D864EC retirement backup eligibility — read-only comparison

## Scope and method

Compared production `.state` with the verified backup at:

`/home/chris/.local/state/job-search-helper-backups/current-scraper-20261121-090919/project/.state`

All SQLite opens used `mode=ro&immutable=1` and `PRAGMA query_only=ON`.
No application command, State/Jobs/Inbox constructor, Google client, lock, or
write API was used.  Production and backup file facts were reread after the
queries.  The backup database files are independent inodes on the same device,
not aliases of the live files.

## Verified retained-cycle equality

The following raw stored SQLite values were exactly equal between live and the
backup: the saved State cycle JSON, every `inventories` row for the cycle
(Company, raw payload, blocked flag), and every `sync_plans` row (Company, raw
payload, cursor).  This is stronger than a count-only comparison, while this
report intentionally does not reproduce job descriptions or other private
payload contents.

- State cycle members: **800** in both copies.
- Saved inventories: **45** in both copies.
- Saved plans: **6** in both copies.
- Plan cursors: five terminal Companies at **1/1**; Saronic `COMP-0054` at
  **67/208**.
- The five terminal plan IDs are `COMP-0002`, `COMP-0008`, `COMP-0016`,
  `COMP-0040`, and `COMP-0045`.
- Scoped Company dirty cells: **0**; scoped Company conflicts: **0**.
- Current-cycle exact local/remote plan, chunk, legacy migration, and legacy
  delivery-evidence rows: **0** in both copies.
- Related normal publication receipts are two historical records for other
  Companies (`COMP-0035`, `COMP-0052`), both `SYNC_CONFIRMED`; none belongs
  to any of the five terminal plans or Saronic.

The three principal `.state` database sizes are equal live versus backup:
state 24,961,024 bytes; Jobs 1,667,158,016 bytes; Inbox 4,025,163,776 bytes.
Live WAL files were empty and no rollback journals were present at observation.
The backup contains distinct copies of the three main databases plus its
state-side evidence archive/request metadata.

## Retirement assessment

**Sufficient for reversible retirement of the scoped old cycle's saved State,
Jobs, and Inbox data, subject to preserving this backup unchanged.**  The
backup retains the exact raw retained-cycle payloads/plans/cursors that would
be needed to restore or inspect the old cycle after retirement, and those
records still match production at this checkpoint.  This says nothing about a
future rescrape's output, future Sheets state, credentials, provider content,
or a tested restore procedure.  It also does not authorize retirement itself.

## Limits

A whole-file SHA-256 sweep of the 4 GB Inbox was deliberately stopped when it
exceeded the bounded read-only window.  The conclusion rests on independent
file identities/sizes plus exact raw equality of every retained-cycle State,
inventory, and plan row; it is not a claim that every unrelated SQLite page in
the complete databases is byte-identical.  No live retirement, archive,
deletion, cleanup, rescan, or Google action occurred.
