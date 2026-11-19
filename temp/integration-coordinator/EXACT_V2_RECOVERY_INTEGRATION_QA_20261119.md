# Exact v2 recovery integration QA — 2026-11-19

Status: implementation complete in the isolated integration worktree; coordinator review required before commit or deployment.

## Scope

- Added a durable `InventoryInbox` remote-intent authority bound to cycle, company, local plan digest, exact Sheets projection digest, receipt ID, and intent ID.
- The first remote attempt is claimed atomically with receipt `SYNC_PENDING` and the exact chunk journal. `first_attempt_claimed` and `attempted_at` are durable and monotonic; duplicate claims return `first_attempt: false`.
- Receipt, chunk, and remote-plan confirmation are one transaction and retain the observed acknowledgement ID. Sheets local acknowledgement must prove the same stored `SYNC_CONFIRMED` binding.
- Exact v2 recovery applies and verifies bounded local chunks through `SQLiteRepository` APIs, advances only the local inbox cursor after chunk verification, mirrors `LOCAL_APPLIED`/`LOCAL_VERIFIED`, then publishes only the frozen selected projection.
- Recovery after a synthetic post-write uncertain result performs exact readback and makes zero additional remote commits.
- The accepted full-profile sealed-plan publisher remains enabled. The v2 path is separate; no legacy cursor is treated as Sheets progress.

## Ordering verified

1. Frozen plan and durable inventory exist.
2. Local chunk is applied and read back from the job database.
3. Only the local apply cursor advances.
4. Complete local application is mirrored `LOCAL_APPLIED`, then `LOCAL_VERIFIED`.
5. Local committed receipt and inventory State checkpoint exist.
6. Exact row scope is planned against the frozen remote projection.
7. Remote plan/receipt/intent bindings are frozen.
8. Inbox atomically claims the sole write attempt before Sheets commit.
9. Any subsequent pending attempt is readback-only.
10. Actual readback atomically confirms receipt, chunk, remote plan, and acknowledgement ID.
11. Sheets acknowledges selected local fields only after inbox confirmation.
12. Selected State and inbox cleanup occur last.

## Evidence

Focused plus adjacent command:

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_durable_inbox.py tests/test_exact_cycle_sync.py tests/test_exact_cycle_recovery.py tests/test_exact_cycle_planner.py tests/test_exact_local_plan.py tests/test_sheets_sync_exact_scope.py tests/test_sqlite_migration.py`

Result: **167 passed in 13.38s**.

Additional checks:

- Python compilation passed for `inbox.py`, `exact_cycle_sync.py`, and `exact_cycle_recovery.py`.
- `git diff --check` passed for the owned source and test files.
- Full-profile legacy exact publisher: **all existing focused expectations pass**.
- Durable inbox tests reproduce duplicate publish-claim refusal and forged acknowledgement refusal.
- Recovery test reproduces a remote mutation followed by a synthetic `UncertainWriteError`; restart confirms by readback with the remote commit count unchanged at one.
- Compact v2 isolation test preserves unrelated dirty rows, company-event outbox rows, unselected inventory, and unselected State.

## Boundaries and remaining review

- No production run or deployment was performed by this lane.
- No global pull, sync, once, publish-batch, prune, or backlog operation is called by the v2 recovery path.
- Remote projections are split into durable exact chunks bounded to 100
  operations / 500 KB. Each new chunk has one atomic first-attempt authority;
  an existing pending chunk is readback-only. The later independent final QA
  exercised a 106-operation projection with an uncertain second chunk and
  accepted its no-replay restart behavior.
- Existing databases receive additive `exact_remote_plans` columns for receipt/intent and one-time-attempt evidence. Coordinator/QA should review this migration and the retained full-profile branch before commit.
- No commit was created.
