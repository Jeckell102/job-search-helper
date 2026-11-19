# Exact-cycle combined orchestrator — independent QA pass

Date: 2026-11-19

Scope: `src/job_search_helper/exact_cycle_recovery.py` and its focused
composition tests. This approval does not itself authorize runner wiring or a
live recovery operation.

## Result

PASS after the lock-gate repair recorded in
`EXACT_CYCLE_ORCHESTRATOR_QA_FAILURE_20261119.md`.

The public `recover_exact_cycle` API no longer accepts a caller-controlled
lock assertion. It derives the normal scraper lock from the file-backed State
path and `scraper_lock_name()`, acquires that real lock before reading State,
inbox, or remote data, and holds it through planning and publishing. In-memory
or otherwise non-file-backed State fails closed.

The contention test holds the same normal lock with another owner and proves
that recovery raises `WriterLockBusy` before any State cycle read, inbox read,
remote selected-row read, or remote commit. Passing the former
`writer_lock_assertion=lambda: True` argument now raises `TypeError` without
protected access.

Independent QA passed 170 tests in 26.249 seconds across recovery, planner,
publisher, inbox, local pipeline, scoped synchronization, and runner suites.
`git diff --check` also passed. No production or live data was accessed.

## Remaining boundary

The orchestrator remains source-only and unwired. Runner integration must
retain explicit one-to-five Company selection and must not surround this API
with a second acquisition of the same non-reentrant lock. Live recovery stays
held until the full pause executor, runner command, and activation checks pass
independent QA.

