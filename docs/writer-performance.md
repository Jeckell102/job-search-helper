# Sheets writer performance and recovery verification

Measured on 2026-09-24 against baseline `89a91de`. No live scraper, job-board request, or spreadsheet write was used.

## Measured offline result

The median end-to-end fixture run fell from **31.40s to 3.63s** (88.4% less elapsed time; 8.6x in this fixture). The largest gain is indexed precommit preparation. Mock write execution itself did not improve.

| Phase | Before | After |
| --- | ---: | ---: |
| End-to-end elapsed | 31.397s | 3.635s |
| Sheets read execution | 1.343s | 0.800s |
| Job lookup / staging | 1.141s | 0.533s |
| Precommit identity / cell validation | 26.336s | 0.202s |
| Building write entries | 0.159s | 0.041s |
| Sheets write execution (mock) | 1.906s | 1.921s |
| Saving SQLite checkpoints / inventories | 0.099s | 0.116s |
| Throttle waiting (fixture only) | 0.000s | 0.000s |

| Count / size | Before | After |
| --- | ---: | ---: |
| Read API calls | 44 | 42 |
| Write API calls | 13 | 13 |
| Entries inside atomic writes | 13,851 | 57 |
| Read response JSON bytes | 32,965,158 | 5,983,838 |
| Write payload JSON bytes | 3,644,231 | 1,863,522 |

The optimized run also durably stored 850,239 bytes of inventory JSON in SQLite. This added local persistence is included in the after timing. The dashboard still counts only acknowledged new Sheets rows.

These are local wall-clock timings against an in-memory API, not production Google latency. Each version ran three times with fixed record timestamps; the table uses the median elapsed run. Before elapsed range: 30.34–32.20s. After: 3.60–3.66s.

The fixture contains 600 existing rows with long descriptions and three company inventories of 200 new jobs each. It exercises the controller, planning cache, writer, row growth, and checkpoints. The range-aware API returns only requested cells and applies multi-row updateCells blocks atomically. Both versions finish with exactly 1,200 distinct Job Keys. The benchmark includes setup/control reads and writes; API and checkpoint timings are subsets of elapsed time.

**No live speedup was measured.** Throttle sleeping is disabled only for the offline fixture. Production start pacing remains 1.1 seconds, the existing five read retries/backoff remain enabled, and ambiguous writes are never automatically retried. Counted API calls exclude retries inside the Google client. Reported bytes are uncompressed JSON sizes rather than compressed network traffic. Real wall-clock improvement depends on quotas, latency, workbook size, and job descriptions.

## What changed

1. Subsequent large-tab commits reread identity columns, full affected rows, and the append tail instead of all wide rows. Small control tabs retain one fresh read. The tail check protects manual rows without IDs and formula-only rows; destination validations are checked before insertion.
2. A planning snapshot and normalized identity indexes are reused across companies and updated after acknowledged commits. Commit-time identity, formula, review-state, and user-field checks remain authoritative.
3. New-row values are grouped into blocks, separately from precise existing-row updates, inside one atomic Sheets request. Sparse gaps are never cleared. Stable identity checks handle ambiguous write responses on replay.
7. Fetch results commit to a durable SQLite inbox before workers take another assignment. Normal start synchronizes automatically; `start --defer-sync` followed by a separate `sync` invocation supports collecting first and syncing later. Deferred mode still synchronizes company/cycle control records. Only the controller accesses Sheets.

## Recovery and verification

Focused acceptance: **63 tests passed**. Coverage includes:

- Formula preservation, strict dropdowns, sparse updates, rich URL identity matching, manual orphan rows and fresh identity checks after row movement.
- Manual review/exclusion changes after caching and new URL aliases arriving after the cached read.
- Lost response after a remotely applied write, interruption after write acknowledgement before checkpoint, restart with an independent inbox connection, and duplicate-free replay.
- Destination binding, immutable saved inventory ordering, pause/retry, missing inventory detection, and retention of blocked company payloads.
- Workers persisting results and taking new assignments while the writer is busy; dashboard and confirmed-job counts.
- Company errors continuing to later companies even when the company error-status cell cannot be written; CLI sync/defer routing and numeric metrics.

The untouched full suite already had 65 failing/erroring cases (36 failures, 29 errors). The updated suite has the same cases and no new failures; unrelated legacy expectations were not rewritten. These include older batch/default and review-queue expectations. The focused acceptance suite above passes.

## Reproduce without network access

From the repository:

```bash
PYTHONPATH=src:tests .venv/bin/python tests/benchmark_writer.py
PYTHONPATH=src:tests .venv/bin/python -m unittest test_writer_optimization test_durable_inbox test_fetch_pool test_job_screening test_v33_pro_work test_v3_direct_sheet test_core_cli.CliTests.test_scraper_start_passes_parallel_options test_core_cli.CliTests.test_scraper_start_still_runs_start_command -q
```

For a before comparison, export baseline `89a91de` into a separate directory and put its `src` directory before this checkout’s `tests` in PYTHONPATH, then run this same benchmark file. The script uses no credentials. [Raw three-run measurements](writer-benchmark.json) include all results.

## Use after updating

Stop the existing scraper with Ctrl+C, wait for it to exit, then run `./job-search-scraper start`. The running process retains the old code until restarted. Keep `.state`. Old interrupted work without inbox data is refetched; new saved inventories replay from SQLite.

Use `./job-search-scraper performance` for numeric timing, request, and payload totals saved at normal exit or Ctrl+C. Fix company errors first, then `./job-search-scraper sync` replays retained inventories, including blocked saved work by default. Both commands share the writer lock. Continue to avoid structural sheet edits during a commit: Sheets does not provide a transaction spanning the identity read and the later write.

API references: [spreadsheets.get ranges and field masks](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/get) and [UpdateCellsRequest](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request#UpdateCellsRequest).
