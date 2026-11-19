# Exact v2 normal recovery — independent final QA

Date: 2026-11-19

Verdict: **ACCEPT (source-level candidate only)**

## Scope and boundary

This was an independent read-only review of the uncommitted exact-v2 normal
recovery candidate. No protected production source, live state, Google/Sheets
endpoint, scraper, queue, or lock was changed. This verdict is not deployment
or live-publication acceptance.

## Fresh verification

Command:

```text
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests \
  /home/chris/job-search-helper_old/.venv/bin/python -W error -m pytest -q \
  tests/test_durable_inbox.py tests/test_exact_cycle_sync.py \
  tests/test_exact_cycle_recovery.py tests/test_exact_cycle_planner.py \
  tests/test_exact_local_plan.py tests/test_sheets_sync_exact_scope.py \
  tests/test_sqlite_migration.py
```

Result: **169 passed in 18.90s**. `git diff --check` also passed.

## Evidence reviewed

- `exact_cycle_recovery._prepare_exact_v2_local` applies at most 100 local
  operations, readbacks each chunk before advancing the inbox's local cursor,
  and treats an existing `APPLIED` chunk as a verification-only no-replay
  boundary. It mirrors only proven `LOCAL_APPLIED` then `LOCAL_VERIFIED`
  state before any remote path is entered.
- The v2 publisher requires that verified local application, exact immutable
  plan/remote-projection seals, current compact schema, fresh Company controls,
  and a receipt before it freezes the remote intent. It does not use the
  legacy `sync_plans.cursor` as remote progress.
- `InventoryInbox` persists a remote plan bound to local-plan digest,
  projection digest, receipt ID, and intent ID. It atomically records each
  chunk before the request, permits the first write only for a new chunk row,
  and requires readback before confirming the chunk/cursor. A retry of an
  existing pending chunk is readback-only.
- The >100-operation test writes a 106-operation projection as bounded
  chunks, injects an uncertainty after the second physical write, then restarts
  with `remote.commit` forbidden. The restart confirms the existing writes;
  assertions show each chunk has 1--100 operations and total physical writes
  remain 106 operations, not a replay.
- Post-confirmation-crash and uncertain-single-write recovery tests likewise
  forbid both local and remote replay on restart.
- Exact Sheets scope is derived from the verified local row identity and then
  compared structurally with the frozen remote projection. Its guards retain
  manual `Added to Opportunities?`, final local `Source Hash`, and salary
  protections; selected-only acknowledgement updates only confirmed fields and
  preserves newer dirty fields, unrelated dirty rows, delivery attempts,
  company-event outbox rows, and unselected inventory/state.
- The established full-profile publisher remains on its separate legacy path;
  v2 dispatch occurs only for `exact_plan_version == 2` and legacy plans do
  not use v2 remote progress semantics.

## Required documentation follow-up (non-blocking source defect)

`EXACT_V2_RECOVERY_INTEGRATION_QA_20261119.md` still says that multi-chunk
remote publication is not enabled. That statement is now obsolete: the
candidate implements `_bounded_exact_chunks` and the fresh recovery test
exercises it. Amend or supersede that implementation note before presenting
the evidence externally, so the written scope matches the code and test
result.

## Remaining external condition

This review supplies no live Sheets, production, or operational acceptance.
Any installation or live recovery still requires its separately authorized
protected-source and controlled-runtime evidence.
