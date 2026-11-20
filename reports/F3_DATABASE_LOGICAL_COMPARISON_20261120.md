# Sprint 1 jobs database forensic comparison

**Finding.** Two local snapshots exactly match the protected witness. Every
existing table contains identical rows in the protected snapshot and the live
database. The schema gained two empty outcome-delivery tables and their
automatic primary-key indexes. The comparison did not establish which process
created them.

## Snapshot identity

| File | Bytes | SHA-256 |
|---|---:|---|
| Protected witness | 1,665,511,424 | `89f2e858ca7e7e778232495cb26b37950065fe9c96e51b6d81845fdc4eb42ad3` |
| Supervisor overlay snapshot | 1,665,511,424 | `89f2e858ca7e7e778232495cb26b37950065fe9c96e51b6d81845fdc4eb42ad3` |
| Temporary-retry overlay snapshot | 1,665,511,424 | `89f2e858ca7e7e778232495cb26b37950065fe9c96e51b6d81845fdc4eb42ad3` |
| Live database | 1,665,527,808 | `57c57db78388d35850972137ff33fcef0e0a7a7d2d3b3be235ddfd2b82a6e65b` |

The two matching copies are
[supervisor overlay database](/tmp/job-search-helper-m3-supervisor-overlay/.state/jobs.sqlite3)
and
[temporary-retry overlay database](/tmp/job-search-helper-m3-temp-retry-overlay/.state/jobs.sqlite3).
The supervisor overlay was used to compare the live
[jobs.sqlite3](/home/chris/job-search-helper_old/.state/jobs.sqlite3).
Both snapshots have different inodes from the live file. The baseline digest
and size were independently verified against the
[protected witness](/tmp/jsh-s1-maint/witness-before.json).

## Existing rows

All 23 existing tables matched, including 898,061 rows. The comparison read
each table directly in row-ID order with indexes disabled for the scan. It
compared the row ID and every column value, including SQLite storage types.
There were zero inserted, removed, or changed rows in each existing table.

| Table | Rows in each database |
|---|---:|
| `baseline` | 88,776 |
| `company_event_deliveries` | 0 |
| `company_event_outbox` | 0 |
| `company_event_watermarks` | 0 |
| `company_revisions` | 801 |
| `conflicts` | 1 |
| `delivery_attempts` | 0 |
| `dirty` | 0 |
| `events` | 21,972 |
| `exact_local_acknowledgements` | 2 |
| `exact_local_applications` | 2 |
| `exact_local_apply_chunks` | 2 |
| `import_identities` | 55,257 |
| `import_progress` | 13 |
| `lookups` | 559,402 |
| `manual_choices` | 31,345 |
| `meta` | 13 |
| `records` | 140,468 |
| `review_input_revisions` | 1 |
| `scrape_outcome_deliveries` | 0 |
| `scrape_outcomes` | 0 |
| `sqlite_sequence` | 1 |
| `tabs` | 5 |

Within `records`, all 58,572 Job History rows, 641 Opportunities, 801
Companies, 48 Scan Cycles, and 80,406 Job Evidence rows matched. All 31,345
manual choices were on Job History and matched.

## Schema additions

| Object | Type | Rows |
|---|---|---:|
| `scrape_outcome_delivery_attempts` | Table | 0 |
| `scrape_outcome_delivery_receipts` | Table | 0 |
| `sqlite_autoindex_scrape_outcome_delivery_attempts_1` | Primary-key index | |
| `sqlite_autoindex_scrape_outcome_delivery_receipts_1` | Primary-key index | |

Every pre-existing schema object kept the same definition, owning table, and
root-page number. The schema version advanced from 41 to 43. The main file
gained four 4,096-byte pages, from 406,619 to 406,623 pages. The free-page
count, user version, and application ID were all zero in each database.

The added definitions match the writable-open schema statements in
[sqlite_repository.py](/home/chris/job-search-helper_old/src/job_search_helper/sqlite_repository.py:143).
That file had the same SHA-256 in the live tree, accepted candidate, and
temporary-retry overlay. The match establishes that a writable repository open
can add those objects. The database contents and file times alone do not
identify the process that ran the statements.

## Read boundary

SQLite connections used `mode=ro&immutable=1` and `query_only=ON`. The query
read the main files. The jobs WAL was zero bytes in the protected witness.
A second full comparison passed with 4,408 observations of each WAL, all
present and zero bytes. The main files kept the same device, inode, size,
and data modification time from start to finish, and their SHA-256 values
matched the initial fingerprints. The live main file data modification time
was November 20, 2026 at 10:33:41 a.m. Eastern. During the first scan, the live
WAL briefly disappeared and its metadata changed. The main file's change time
advanced while its data modification time and digest stayed fixed. These
observations support the comparison of checkpointed contents. Sampling
cannot rule out a transient WAL write between observations. The comparison
created no database copy.
