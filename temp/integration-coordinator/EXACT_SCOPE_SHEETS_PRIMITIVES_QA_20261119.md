# Exact-Scope Sheets Primitives QA — 2026-11-19

Status: **QA REPAIRED / OFFLINE TESTED / INTEGRATION REVIEW REQUIRED**

## Ownership and safety boundary

This lane changed only:

- `src/job_search_helper/sheets_sync.py`
- `tests/test_sheets_sync_exact_scope.py`
- this report

It did not change production, staging, Google data, the coordinator/recovery
runner, inbox, local-application implementation, Jetson, or any live job data.

## Implemented APIs

### `plan_exact_scope(row_scope, frozen_projection)`

- Requires a nonempty explicit sequence of stable tab/identity/field scopes.
- Accepts a row ID only as an optional hint and re-resolves the stable identity.
- Reads only the named local rows, their selected dirty fields, and their
  selected conflict/control state.
- Never calls `pull`, `once`, global `publish_batch`, global `_operations`, or
  `prune_local_only_delivery`.
- Rejects non-publishable/local-only fields, unresolved conflicts, missing or
  ambiguous identities, stale row hints, missing dirty mutations, unsafe
  identity changes, user-owned application-field writes, non-append note
  changes, missing Source Hash guards, and changed manual/source guards.
- Requires the row scope to carry every frozen remote-visible `expected`
  guard. It reconstructs those guards exactly, including Salary / Range and
  the manual Added-to-Opportunities choice. Local-only Source Hash remains a
  prewrite/local-ack guard and compact-v1 rejects it in remote `expected`.
- Applies the existing salary fallback rule: a blank/known-empty extracted
  salary cannot replace a plausible baseline estimate, while the estimate is
  retained as a remote compare-before-write guard.
- Canonically requires the derived selected operations to equal the immutable
  frozen projection before any remote intent or write.

### `publish_exact_scope(...)` and `readback_exact_scope(...)`

- Require a concrete `InventoryInbox` whose durable destination equals the
  synchronizer workbook, plus nonblank cycle/company/plan/receipt/intent IDs.
- The write API atomically calls `claim_exact_remote_attempt` before commit.
  Only the inbox-derived first claim can issue one Google commit; every later
  call is readback-only. Caller-supplied `first_attempt` and `intent_state`
  authority has been removed.
- A never-attempted intent revalidates selected local values/guards before and
  immediately after its durable claim. Recovery of an already-attempted intent
  does not reject a newer local edit; acknowledgement preserves it as dirty.
- The API enforces 100-operation/500,000-byte maximum bounds.
- The recovery API performs readback only and never calls commit.
- Readback uses only each selected stable identity and exact row, verifies
  frozen values/append-only suffixes, and produces a deterministic
  receipt/intent/projection-bound acknowledgement ID.
- Two calls using the same real durable intent produce exactly one remote
  commit and identical readback acknowledgement evidence.

### `acknowledge_exact_scope(...)`

- Requires the same concrete destination-bound `InventoryInbox` and calls
  `require_exact_remote_confirmed` for the exact plan/projection/receipt/
  intent/acknowledgement tuple before changing any local field.
- Fails closed unless the selected `(cycle, company, plan_digest)` also has a
  matching `VERIFIED` row in `exact_local_applications`.
- Requires untampered receipt, intent, projection, readback rows, and
  acknowledgement ID.
- Revalidates stable local identity and frozen local guards.
- In one local transaction, updates only selected visible baseline fields to
  actual confirmed Google values.
- Clears a selected dirty cell only when its current local value still equals
  the frozen sent value; newer local edits stay dirty.
- Leaves local-only baseline fields, unrelated dirty cells, conflicts, outbox
  data, and every normal-writer `delivery_attempts` row untouched. The exact
  path creates no shared delivery-attempt row, so none is attributable to it.
- Inserts an idempotent acknowledgement bound to `apply_id`, receipt ID,
  acknowledgement ID, and selected-field digest in
  `exact_local_acknowledgements`.

## Test evidence

Focused command:

`PYTHONPATH=src:tests python -m unittest test_sheets_sync_exact_scope -v`

Result: **PASS — 7 tests in 0.645s** (repeat: 7 in 0.648s).

Focused coverage includes explicit-scope isolation, optional row hint
revalidation, frozen-projection mismatch before write, exact blank-salary
projection equality with the estimate preserved in `expected`, durable
first-attempt authorization, duplicate-call readback-only recovery,
scoped baseline/dirty acknowledgement with a newer edit, local-only and
unrelated-state preservation, manual/source/salary controls, tampered
readback, fabricated exact-shape readback with zero remote writes, missing
verified local journal, wrong inbox type, missing receipt binding, mismatched
durable plan binding, and oversized projection.

Adjacent command:

`PYTHONPATH=src:tests python -m unittest test_compact_sheets test_sheet_read_optimization test_sqlite_integration test_sqlite_migration test_durable_inbox test_exact_local_plan -v`

Result: **PASS — 126 tests in 20.903s**.

An earlier broad command also exposed concurrent integration-suite churn: 50
legacy exact-cycle expectation failures plus three nonexistent module names.
Those failures consistently predated this Sheets boundary in the current
shared worktree (`legacy_exact_plan_requires_migration`) and belong to the
coordinator/integration lane. They were not hidden or weakened here.

Syntax and whitespace checks also passed:

- `python -m py_compile src/job_search_helper/sheets_sync.py tests/test_sheets_sync_exact_scope.py`
- `git diff --check -- src/job_search_helper/sheets_sync.py tests/test_sheets_sync_exact_scope.py`

## Remaining integration work

- The recovery/publisher orchestrator must supply the immutable v2 remote
  projection, explicit local-journal row scope including remote `expected`
  and local `guards`, and the matching durable inbox IDs.
- Its owned call sites must use the repaired signatures. Sheets now performs
  the atomic durable claim internally; orchestration must durably call
  `confirm_exact_remote` from exact readback evidence before acknowledgement.
- It must call `acknowledge_exact_scope` before selected State/inbox cleanup.
- Legacy local cursors remain local-application cursors and are not accepted
  by these APIs as remote progress.
- No production pilot is authorized by this lane alone. Broad backlog and
  automatic release must remain disabled until end-to-end independent QA.
