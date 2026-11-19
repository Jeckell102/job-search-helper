# Exact-Scope Sheets Primitives QA — 2026-11-19

Status: **STAGED / OFFLINE TESTED / NOT YET ORCHESTRATOR-WIRED**

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
- Applies the existing salary fallback rule: a blank/known-empty extracted
  salary cannot replace a plausible baseline estimate.
- Canonically requires the derived selected operations to equal the immutable
  frozen projection before any remote intent or write.

### `publish_exact_scope(...)` and `readback_exact_scope(...)`

- Require nonblank receipt and intent IDs plus an intent projection digest
  equal to the exact scoped plan.
- The write API accepts only an explicitly authorized first `SYNC_PENDING`
  attempt, revalidates selected local values/guards immediately before write,
  and enforces 100-operation/500,000-byte maximum bounds.
- The recovery API performs readback only and never calls commit.
- Readback uses only each selected stable identity and exact row, verifies
  frozen values/append-only suffixes, and produces a deterministic
  receipt/intent/projection-bound acknowledgement ID.
- A timeout after a synthetic real mutation is recovered by readback with zero
  additional commits.

The durable external intent journal remains the authority that decides whether
the first attempt is authorized. A pending/uncertain restart must call only
`readback_exact_scope`; this primitive does not invent replay permission.

### `acknowledge_exact_scope(...)`

- Fails closed unless the selected `(cycle, company, plan_digest)` has a
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

`PYTHONPATH=src:tests python3.11 -m unittest tests.test_sheets_sync_exact_scope -v`

Result: **PASS — 6 tests**.

Focused coverage includes explicit-scope isolation, optional row hint
revalidation, frozen-projection mismatch before write, bounded first-attempt
authorization, synthetic lost acknowledgement with readback-only recovery,
scoped baseline/dirty acknowledgement with a newer edit, local-only and
unrelated-state preservation, manual/source/salary controls, tampered
readback, missing verified local journal, missing receipt binding, mismatched
intent projection, and oversized projection.

Adjacent command:

`PYTHONPATH=src:tests python3.11 -m unittest tests.test_sheets_sync_exact_scope tests.test_compact_sheets tests.test_sqlite_integration tests.test_run_scoped_sync tests.test_exact_local_plan -q`

Result: **PASS — 80 tests in 12.873s**.

Syntax and whitespace checks also passed:

- `python3.11 -m py_compile src/job_search_helper/sheets_sync.py tests/test_sheets_sync_exact_scope.py`
- `git diff --check -- src/job_search_helper/sheets_sync.py tests/test_sheets_sync_exact_scope.py`

## Remaining integration work

- The recovery/publisher orchestrator must supply the immutable v2
  `remote_projection`, the explicit local-journal row scope, frozen local
  Source Hash/manual guards, receipt ID, and durable pending intent ID/digest.
- It must call `plan_exact_scope` before journaling a remote intent, use
  `publish_exact_scope` only for the first authorized attempt, and use
  `readback_exact_scope` exclusively after an uncertain/pending attempt.
- It must call `acknowledge_exact_scope` only after remote confirmation and
  before selected State/inbox cleanup.
- Legacy local cursors remain local-application cursors and are not accepted
  by these APIs as remote progress.
- No production pilot is authorized by this lane alone. Broad backlog and
  automatic release must remain disabled until end-to-end independent QA.

