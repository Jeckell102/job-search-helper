# Exact local durability implementation

Date: 2026-11-19

Status: source and offline tests complete for the version-2 freeze/local-apply
boundary. No Google request, production database, live inventory, lock, queue,
or Jetson state was touched by this lane.

## Implemented contract

- Compact-profile planning now persists an immutable version-2 plan before
  mutation. It retains complete `local_operations`, the compact
  `remote_projection`, the exact publication schema/profile, local and remote
  expected record sets, finalization evidence, and deterministic seals.
- New Opportunity IDs are assigned by the in-memory planning pass and survive
  in the frozen local operation stream. Duplicate final targets are rejected
  before persistence so a bounded chunk cannot split one record's atomic work.
- The inbox saves `sync_plans` plus `exact_plan_local_state=FROZEN` in one
  transaction and does not create a `LOCAL_COMMITTED` receipt or advance the
  State checkpoint. `sync_plans.cursor` remains the local apply cursor.
- Inbox mirrors are monotonic (`FROZEN`, `LOCAL_APPLIED`, `LOCAL_VERIFIED`),
  compare immutable plan/application evidence, and refuse payload tampering.
  Cleanup remains exact-company and transactional.
- The job SQLite schema now has authoritative exact application, bounded
  chunk, and acknowledgement-ledger tables. Each local mutation chunk and its
  APPLIED row are committed in the same `BEGIN IMMEDIATE` transaction.
- Recovery treats APPLIED as a no-replay boundary. It rereads the exact stable
  identities, verifies the frozen fingerprints, and only then marks the chunk
  VERIFIED. The parent reaches VERIFIED only after a complete contiguous
  chunk prefix and a fresh whole-plan readback.
- A VERIFIED row scope gains local `row_id` hints only after inserted rows
  exist. Every later read revalidates each hint against its stable identity.
  Scope `fields` contain only remote mutations; identity remains separate.
  Job History scope also retains frozen Source Hash, manual-choice, and salary
  guards without exposing those local-only values as remote fields.
- The salary fallback keeps a plausible existing estimate when extracted pay
  is blank or the known empty envelope. The estimate becomes an expected
  guard and is omitted from local/remote mutation.
- The rejected local remote-acknowledgement API was removed. This lane cannot
  treat plan-derived fingerprints as Google evidence or baseline planned
  values. The exact Sheets publisher owns receipt/readback-bound
  acknowledgement; only its additive ledger table is installed here.

## Verification

Focused planner/local durability:

`PYTHONPATH=src python3 -m unittest tests.test_exact_local_plan tests.test_exact_cycle_planner`

Result: 30 tests passed (before the additional scope-guard regression).

Final focused and adjacent exact recovery/inbox selection:

`PYTHONPATH=src:tests python3 -m unittest tests.test_exact_local_plan tests.test_exact_cycle_planner tests.test_durable_inbox tests.test_exact_cycle_sync tests.test_exact_cycle_recovery`

Result: 110 tests passed in 8.723 seconds.

Additional SQLite/local pipeline regression:

`PYTHONPATH=src:tests python3 -m unittest tests.test_sqlite_integration tests.test_sqlite_migration tests.test_local_pipeline`

Result: 87 tests passed in 27.328 seconds.

The focused cases cover atomic rollback, APPLIED crash recovery without
replay, deterministic/tamper-evident plans, cross-company refusal, changed
source guards, salary-estimate preservation, exact cleanup, cursor separation,
row-hint revalidation, selected-dirty field scope, Job History guard retention,
and unrelated-company isolation.

## Deliberately remaining integration work

- The separately owned exact publisher/recovery path must consume
  `remote_projection` only after matching authoritative job-DB VERIFIED and
  inbox `LOCAL_VERIFIED` evidence, then create the publication receipt.
- The publisher must use the verified row scope, equality-check its exact
  dirty-cell plan, bind actual Google readback/receipt evidence, and perform
  scoped baseline/dirty acknowledgement. No local API in this lane does that.
- The additive legacy-migration and remote-plan tables are installed, but the
  eight legacy cursor plans are not migrated by this lane. Their original
  local cursor semantics remain unchanged; they still require the documented
  prefix-readback migration before any remote operation.
- Cross-database mirror repair and State checkpoint/receipt ordering belong to
  the recovery orchestrator. Until wired and independently reviewed, a frozen
  v2 plan is intentionally not publishable.

## Owned files

- `src/job_search_helper/exact_cycle_planner.py`
- `src/job_search_helper/inbox.py`
- `src/job_search_helper/sqlite_repository.py`
- `src/job_search_helper/exact_local_plan.py`
- `tests/test_exact_cycle_planner.py`
- `tests/test_exact_local_plan.py`
- this report
