# Local processing and consolidated Sheets synchronization

Measured on 2026-09-24 against `95df972`. All measurements use an in-memory, range-aware Sheets API and synthetic job inventories. No live scraping, credentials, or spreadsheet writes were used.

## Measured result

The median fixture run fell from **18.89 seconds to 2.14 seconds**, an **88.7% reduction / 8.8× speedup**. Sheets requests fell from **326 to 28**. This is an offline measurement, not a prediction of production Google latency.

| Metric | Before | After |
| --- | ---: | ---: |
| End-to-end elapsed seconds | 18.893 | 2.138 |
| Sheets read calls | 229 | 21 |
| Sheets write calls | 97 | 7 |
| Read response JSON bytes | 19,717,452 | 5,374,919 |
| Write payload JSON bytes | 663,994 | 634,977 |
| Entries inside atomic requests | 412 | 200 |
| Read execution seconds (mock) | 2.752 | 0.250 |
| Write execution seconds (mock) | 13.303 | 0.812 |
| Local staging seconds | 0.305 | 0.334 |
| Precommit preparation seconds | 0.833 | 0.134 |
| Request construction seconds | 0.008 | 0.007 |
| Checkpoint / inventory / plan seconds | 0.739 | 0.658 |
| Checkpoint / inventory / plan JSON bytes | 1,260,786 | 1,201,766 |
| Throttle seconds (fixture only) | <0.001 | <0.001 |

The fixture has 600 existing rows and 24 companies with 8 new jobs each. Both versions finish with exactly 792 distinct job identities, a completed cycle, and no pending inventories. Three runs per version produced ranges of 18.56–19.18 seconds before and 2.11–2.18 seconds after. The table uses the run with median elapsed time, including setup/control writes. The request counts were identical across each version's three runs. [Raw results](local-pipeline-benchmark.json).

The in-memory API copies and validates sheet state on every write; reducing write count therefore reduces fixture CPU time substantially. Network latency and quota delays are not simulated. Throttle sleeping is disabled only in the fixture; production keeps its 1.1-second request interval, five internal read retries, and no automatic retries of ambiguous writes. Byte counts are uncompressed JSON; client-internal retries are not counted separately. Timings overlap and should not be added together.

## Behavior and recovery

- Fetchers save full inventories to SQLite and continue taking assignments while the controller stages or uploads. The assignment window limits queued fetch assignments, not accumulated disk inventories.
- One startup snapshot supports local indexed screening and duplicate checks. Per-company plans, including final company status, are saved durably before upload. Small companies share atomic batches; large plans split by operation count and payload budget.
- `--sync-interval 60` flushes partially filled batches between company planning steps. Full batches and the final batch flush immediately. This does not guarantee a 60-second maximum visibility delay.
- Before each batch, the writer rereads company pauses, external claims, manual holds and careers URLs. The repository still resolves fresh row identities and checks expected review values, formulas, strict validation, and user-owned fields. No worksheet is replaced wholesale.
- Frozen operations and their acknowledged cursors survive restarts. Only an acknowledged write advances a cursor. A company payload is deleted after all its operations and its cycle checkpoint succeed. A lost response keeps the exact plan for explicit keyed replay; confirmed validation failures retain the inventory for fresh planning on explicit retry.
- One company's preflight rejection is isolated from other companies. Fetch and write errors are logged; blocked payloads remain available. `sync` retries saved blocked work by default, and `start` can also refetch failed sources. Use `--no-retry-blocked` to leave blocked work on hold.
- The dashboard separates locally processed inventory items from confirmed new Sheets rows. Companies in Sheets reflect synchronization progress; use the dashboard for current fetch activity. New company intake is included on the next run.

## Validation

**101 focused tests passed.** The full suite ran 384 tests and retained the same 65 baseline failures/errors (36 failures, 29 errors), with no newly failing cases. These unrelated legacy expectations were not rewritten.

Focused tests cover durable reopen/replay, interruption before and after cursor acknowledgement, lost write responses, bounded assignments continuing during blocked uploads, timer-driven partial batches, local-save failure, deferred/sync-only mode, company error isolation, blacklist rules, manual exclusions, formula preservation, fresh company pauses/claims/URL edits, absence reconciliation and active review protection. Existing writer tests additionally cover strict dropdown validation, sparse updates, row movement, URL aliases, user fields, and unchanged throttle/read retry behavior.

Run the focused suite:

```bash
PYTHONPATH=src:tests python -m unittest test_local_pipeline test_writer_optimization test_durable_inbox test_fetch_pool test_job_screening test_v33_pro_work test_v3_direct_sheet test_core_cli.CliTests -q
```

Reproduce the benchmark:

```bash
PYTHONPATH=src:tests python tests/benchmark_local_pipeline.py
```

For a before comparison, export `95df972` to a separate directory and put that directory's `src` ahead of this checkout's `tests` in `PYTHONPATH`, then run the same benchmark script. It selects the older controller when the local pipeline is unavailable.

## Load the update

The running scraper retains its existing code. Press Ctrl+C once, wait for the process to exit, and run `./job-search-scraper start`. Keep the entire `.state` directory. Existing inventory databases gain the plan table automatically; previously saved inventories are processed locally and replayed by stable identity, including legacy partially written companies. Do not start a second writer.
