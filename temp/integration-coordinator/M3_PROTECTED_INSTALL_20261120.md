# Protected MuleLab install — M3 ordinary normal-cycle outcome slice

## Result

The independently accepted nine-file source/test patch from sanitized commit
`c8a4cb0c6dc2fccfee88e61520b53ab22daf413e` was installed narrowly in
`/home/chris/job-search-helper_old`.

Before installation, every protected target blob exactly matched sanitized
parent checkpoint `0bf2d4a`; no overlapping local file change was overwritten.
Exact rollback copies are retained at
`/tmp/job-search-helper-protected-backup-m3-c8a4cb0`, and every backup blob was
verified against that parent checkpoint before the copy. After installation,
all nine protected target blobs exactly matched `c8a4cb0`.

Installed source files:

- `src/job_search_helper/engine.py`
- `src/job_search_helper/local_pipeline.py`
- `src/job_search_helper/outcomes.py`
- `src/job_search_helper/scrape_outcome_producer.py`
- `src/job_search_helper/sqlite_repository.py`

Installed focused tests:

- `tests/test_engine.py`
- `tests/test_local_pipeline.py`
- `tests/test_outcomes.py`
- `tests/test_scrape_outcome_producer.py`

## Protected-runtime verification

The changed-boundary protected-runtime matrix passed **266 tests in 40.35s**.
The only warning was that pytest could not write its optional cache in the
read-only execution sandbox; it did not affect tests or application state.

After the test run:

- `job-search-sync.service` remained inactive/dead and disabled;
- both Company intake controls remained false and unconfigured;
- the preserved scraper, writer, review, and controller lock bytes were
  unchanged;
- no scraper, coordinator, or wrapper process was running;
- no service, Google, database, request, cycle, receipt, credential, raw-job,
  or Jetson state was changed.

## Scope limit

This install is source/test progress only. It does not close M3, F6, or any
milestone. Generic cycle-level `storage_confirmed`, pre-write stale protection,
company-only outcome production, richer failure facts, coordinator behavior,
and live acceptance remain open.
