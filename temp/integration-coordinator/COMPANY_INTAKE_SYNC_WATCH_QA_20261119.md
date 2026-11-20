# Company-intake sync-watch independent QA — ACCEPT

## Scope

Read-only review of the uncommitted watch integration in `sync_cli.py`, the
dispatcher status control, focused lifecycle tests, and the source-only design
note. No service, remote Sheets data, protected checkout, or live scraper was
used.

## Final repair verification

The normal dispatcher call now has its own exception boundary after a
successful Sheets cycle. A `run_once()` failure records
`COMPANY_INTAKE_ERROR_RETAINED`, leaves the primary SQLite `last_error` blank,
and does not increase the sync failure/backoff counter. The committed lifecycle
test proves this. The CLI test now also exercises the real command sequence
`intake-status -> intake-enable -> intake-status -> intake-disable` across
fresh repository instances.

The recorder-failure path is now independently contained too. If `run_once()`
and `record_error()` both fail, the watch emits
`COMPANY_INTAKE_ERROR_UNRECORDED` with separate intake and journal details.
It does not enter the outer sync error handler, write the primary SQLite
`last_error`, increment sync failures, or apply sync backoff.

I reproduced that double failure with a temporary ready SQLite database and a
successful fake sync cycle. The result contained no
`SYNC_ERROR_LOCAL_WORK_RETAINED`, the primary `last_error` stayed blank, and
the subsequent sleep remained within the normal five-second watch interval
(rather than the prior ten-second sync-backoff path).

## Positive observations

- Intake runs only in `watch`, after the bounded `writer.lock` context exits.
  It is not called for `once`, writer-busy, or a failing sync cycle.
- A new journal defaults to disabled; `intake-status` is read-only with respect
  to the primary SQLite repository, and the controls persist in the dispatch
  journal.
- The watcher reuses the current local repository and existing remote/sync
  instance. The dispatcher has no loop or scheduler: it is a one-tick call.
- Existing dispatcher boundaries retain requests on unavailable scraper or
  controller locks and apply retained-work/release holds before start. The
  company-only queue probe also checks unfinished local and workbook cycles.

## Evidence

Focused strict command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -W error -m unittest tests.test_sync_cli_lifecycle tests.test_company_intake_dispatcher tests.test_company_intake_handoff`

Result: **28 tests passed**.

The actual CLI persistence sequence is now in the focused test suite.
