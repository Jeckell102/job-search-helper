# Sprint 6 local Company intake observation

**Staged for independent QA.** The exact command is `./job-search-scraper storage intake-observe`. The existing `storage` route already reaches the local storage CLI without the mutating admission bootstrap. The shell, bootstrap and publication paths are byte-identical to the source baseline.

The command opens the existing Jobs DB in immutable, read-only mode and reads the existing bridge consumer’s latest pending outbox event per Company. It reports up to 100 events and signals an additional page. A current eligible proposal requires the exact latest recorded revision, a matching outbox identity and the application’s current eligible Company source revision. Withdrawal, ineligibility and stale source show as separate holds. Output scope is the local pending outbox page. Actual scrape admission remains subject to the normal queue and workflow checks. A nonempty SQLite WAL or rollback journal, or a changed snapshot, returns `STATUS_SNAPSHOT_BUSY` with exit 1. The command takes no lock and opens no State, dispatcher, Google or provider client.

| Artifact | SHA-256 |
| --- | --- |
| `src/job_search_helper/company_events.py` | `0c82c1091b413622f0fc4a727225efcd3792598e527d0731e78d3d427b5d265b` |
| `src/job_search_helper/sync_cli.py` | `4c94908e60638a49cf066e550829c9241d10a8c78d7583a6d7b8e8f0caffe529` |
| `tests/test_company_intake_observe.py` | `ae876c2a0562eda8ccecbd85cba7daea462917c191b6adf767ef7241b7c92927` |

The real public shell tests exercise latest revision, distinct disposition states, acknowledged event exclusion, committed WAL-only hold, and the 101-to-100 bound. The tests disable bytecode caching, deny socket/DNS, subprocess and Python filesystem-mutation events, and compare database and surrounding files, modes and modification times before and after each command. Application State remains absent in these fixtures. The reproducible run passed 18 tests across the three new CLI tests and adjacent Company bridge and retry status tests. One fixture was checked separately on both the candidate and unchanged baseline. `test_terminal_intake_event_becomes_one_next_scan_after_current_cycle_stops` stopped in both at `release_admission_bootstrap.py:117` with `No measurable dependency manifest is installed`. The supplied source-only snapshots were left without dependency changes.

No production paths, credentials, queue, provider, Google, model or live processes were used to run the prototype.
