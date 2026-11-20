# Sprint 1 jobs.sqlite3 growth investigation

**High-confidence attribution:** The restored
`wrapper-development-host.service` opened the jobs repository in write mode
during its immediate supervision catch-up. The repository's additive schema
initialization accounts for all 16,384 newly allocated bytes. No process-level
SQL or file-write audit record was available, so the exact PID is inferred
from the service timing and call path.

## Evidence

- The durable protected-state witness recorded **1,665,511,424 bytes**. The
  current file has **1,665,527,808 bytes** and 4,096-byte pages, an increase
  from 406,619 to 406,623 pages. The controller records `RELEASED / INSTALLED`.
- The user journal records the wrapper stopped at **10:33:32.789159 EST**
  and started at **10:33:41.140882 EST** on November 20. The database mtime is
  **10:33:41.471185478 EST**, about 330 ms after the start. There were no
  sync-service journal entries in the checked window. Systemd's journal
  records service lifecycle, not individual SQL statements.
- All four new pages are identifiable from the production schema and their
  raw B-tree headers. Each has zero cells.

| Root page | Schema object |
| --- | --- |
| 406620 | `scrape_outcome_delivery_receipts` |
| 406621 | `sqlite_autoindex_scrape_outcome_delivery_receipts_1` |
| 406622 | `scrape_outcome_delivery_attempts` |
| 406623 | `sqlite_autoindex_scrape_outcome_delivery_attempts_1` |

- The two new tables and the existing `scrape_outcome_deliveries` table have
  zero rows. A later persisted supervision snapshot reported
  `ACTIVE`, zero delivered, and zero remaining at 10:35:41 EST. The jobs WAL
  was empty before and after the inspection.
- Running just the two exact production CREATE TABLE statements on an
  in-memory SQLite database with 4,096-byte pages reproduced the allocation:
  two table root pages plus two primary-key index root pages, totaling
  precisely **16,384 bytes**.

## Call path

1. [Wrapper startup](/home/chris/job-search-helper_old/dev/wrapper-coder/tools/host_server.py:245)
   starts supervision. Its [default callback](/home/chris/job-search-helper_old/dev/wrapper-coder/tools/host_server.py:57)
   is `drain_scrape_outcomes(limit=20)`. The
   [supervision thread](/home/chris/job-search-helper_old/dev/wrapper-coder/tools/coordinator_supervision.py:198)
   runs its first tick immediately and waits 30 seconds between later ticks.
2. [Drain](/home/chris/job-search-helper_old/dev/wrapper-coder/tools/host_server.py:140)
   opens the production `SQLiteRepository` with the default `readonly=False`,
   before checking for pending outcomes. The two other wrapper calls that
   read company revisions/profile snapshots explicitly use `readonly=True`.
3. The [repository constructor](/home/chris/job-search-helper_old/src/job_search_helper/sqlite_repository.py:60)
   opens the existing file with `mode=rw`, validates it, and calls
   `_ensure_company_event_schema()`. Its
   [additive DDL](/home/chris/job-search-helper_old/src/job_search_helper/sqlite_repository.py:175)
   creates the two observed tables with compound primary keys. Even an empty
   outbox reaches this DDL, because construction precedes enumeration.
   The repository source predates the F3 install and is outside its 13-file
   scope. Restoring the wrapper activated the existing DDL path.

The byte-for-byte state witness failed. The page evidence identifies
additive schema allocation and shows no outcome delivery rows. It cannot
establish that every pre-existing database page or job record was unchanged
without a matched before image or audit trail. Do not attribute the growth
to a job scrape, Sheets publish, or installer source-copy operation. The
observed call path is local SQLite, and there is no evidence of those
activities in this investigation.

Production SQLite inspection used `mode=ro&immutable=1` and raw read-only file
reads, with the jobs WAL confirmed empty. The DDL reproduction was in memory.
No production write, wrapper request, restart, or Google operation was made.
