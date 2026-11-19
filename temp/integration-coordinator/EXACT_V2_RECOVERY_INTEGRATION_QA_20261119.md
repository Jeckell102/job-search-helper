# Exact v2 recovery integration QA — 2026-11-19

Status: implementation complete in the isolated integration worktree; coordinator review required before commit or deployment.

## Scope

- Added a durable `InventoryInbox` remote-intent authority bound to cycle, company, local plan digest, exact Sheets projection digest, receipt ID, and intent ID.
- The first remote attempt is claimed atomically with receipt `SYNC_PENDING` and the exact chunk journal. `first_attempt_claimed` and `attempted_at` are durable and monotonic; duplicate claims return `first_attempt: false`.
- Chunk confirmation is a Sheets-owned fresh-read/CAS operation. Final receipt
  and remote-plan confirmation are one guarded transaction and retain the
  acknowledgement derived from that fresh full-projection read.
- QA's forged zero-write path is closed: `InventoryInbox` exposes no remote
  confirmation method or token. `SheetsSynchronizer` owns live readback plus
  the durable transition as one operation; final local clearing uses the
  combined durable-key-only `confirm_and_acknowledge_exact_scope` API and no
  supported callable accepts caller-supplied readback, observed records, or an
  acknowledgement as authority.
- Final confirmation and acknowledgement accept only durable cycle, company,
  plan, receipt, and intent keys. Sheets reconstructs the projection from
  `exact_remote_plans` and the row scope/sent evidence from the sealed inbox
  plan plus the verified local application; caller-provided row metadata is
  not an input.
- The internal full-read confirmation and local-acknowledgement helpers use the
  same durable-key-only boundary. Neither accepts an exact plan, readback rows,
  observed records, or an acknowledgement ID from a caller; the local helper
  performs its own fresh full remote read before clearing selected fields.
- Public inbox cleanup preserves the exact-v2 marker unless both the remote
  journal is `LOCAL_ACKNOWLEDGED` and the bound receipt independently stores
  the same `SYNC_CONFIRMED` acknowledgement. Pending cleanup therefore cannot
  reopen a legacy confirmation route.
- Promotion to `LOCAL_ACKNOWLEDGED` additionally requires the concrete job
  SQLite database to prove the matching application is `VERIFIED` and that its
  `exact_local_acknowledgements` row binds the same apply ID, receipt ID,
  acknowledgement ID, and nonempty SHA-256 selected-evidence digest. Cleanup
  repeats this proof after checking the terminal inbox/receipt states.
- The same cleanup barrier applies before remote registration: any frozen
  `exact_plan_local_state` without a terminal exact remote journal is
  immutable. Legacy receipt and chunk reconciliation also recognizes this
  pre-registration marker, while unblock remains non-destructive.
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
10. After each network read, Sheets rereads and compare-and-swaps the immutable
    plan, projection slice, cursor, receipt, and intent binding.
11. A new full-projection read atomically confirms the receipt and remote plan;
    the same combined operation then acknowledges only the selected local fields.
12. Selected State and inbox cleanup occur last.

## Evidence

Focused plus adjacent command:

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_publication_receipts.py tests/test_durable_inbox.py tests/test_exact_cycle_sync.py tests/test_exact_cycle_recovery.py tests/test_exact_cycle_planner.py tests/test_exact_local_plan.py tests/test_sheets_sync_exact_scope.py tests/test_sqlite_migration.py`

Result after the local-ack lifecycle binding repair: **183 passed in 16.34s**.
The independently owned legacy test verifies that the required
pre-registration cleanup refusal preserves inventory, plan, and local state.

Additional recovery/pause/terminal/SQLite integration matrix:

`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q tests/test_exact_recovery_pause.py tests/test_exact_recovery_pause_apply.py tests/test_exact_recovery_pause_executor.py tests/test_exact_recovery_terminal.py tests/test_sqlite_integration.py`

Result: **52 passed in 10.21s**.

Additional checks:

- Python compilation passed for `inbox.py`, `exact_cycle_sync.py`, and `exact_cycle_recovery.py`.
- `git diff --check` passed for the owned source and test files.
- Full-profile legacy exact publisher: **all existing focused expectations pass**.
- Durable inbox tests reproduce duplicate publish-claim refusal and forged acknowledgement refusal.
- An adversarial Sheets test directly claims the only attempt, confirms there
  is no importable inbox/module confirmation symbol, performs zero remote
  batches, fabricates matching fingerprints and an acknowledgement, and proves
  it cannot set `SYNC_CONFIRMED` or clear any dirty field.
- Legacy inbox receipt reconciliation, legacy exact-chunk begin/confirm, and
  `publication_receipts.reconcile_sync` all reject receipts enrolled in an
  exact remote plan. Exact registration also rejects a pre-confirmed legacy receipt.
- Adversarial tests reject a forged projection slice, a remote row move between
  identity lookup and `read_row`, and a durable intent change during the network read.
- A direct public `acknowledge` call against a pending exact-v2 plan is rejected
  before any row is deleted; the exact marker, local state, and frozen plan all
  remain, and legacy receipt reconciliation remains blocked.
- A caller-crafted exact plan whose row evidence points at an unrelated company
  is rejected at the API boundary. The durable-key-only call then acknowledges
  the intended company while the unrelated company's dirty fields remain.
- Direct calls to both internal full-confirmation and local-acknowledgement
  helpers with retargeted Company 2 plan/readback metadata are rejected by the
  function boundary and leave all dirty data unchanged.
- Pre-registration exact-v2 tests prove public cleanup and discard are refused,
  both legacy chunk APIs and both receipt reconciliation APIs remain closed,
  and unblock preserves the inventory, plan, and local-state marker.
- A real fixture publishes and fully confirms the remote scope, deliberately
  skips local acknowledgement, then proves the public local-state transition
  and cleanup both refuse. Inventory, frozen plan, `SYNC_CONFIRMED` remote
  journal, selected dirty fields, and the zero-row local acknowledgement
  journal all remain intact. Normal recovery after an actual local
  acknowledgement continues to pass.
- The 105-job uncertain-later-chunk test changes an earlier confirmed remote
  row before final readback, proves receipt confirmation remains pending, then
  restores the row and completes without replaying either remote chunk.
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
- Threat model: these guarantees cover misuse of supported public APIs and
  crash/restart behavior. They do not claim protection from malicious
  same-process code that directly edits SQLite tables, monkey-patches private
  implementation methods, or otherwise has arbitrary code/database access.
