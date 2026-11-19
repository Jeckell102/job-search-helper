# Exact-cycle planner independent QA pass — 2026-11-19

## Result

PASS for the isolated exact-cycle planning component. This is source/test
acceptance only. It does not authorize runner wiring, Google access, live
planning, publication, recovery, or backlog processing.

## Accepted boundary

- Planning is limited to explicit bounded Company IDs and consumes only the
  existing durable inventory payload.
- A new plan seals the inventory-payload digest, operation-record digest,
  immutable plan digest, and typed active/unclaimed Company control evidence.
- The plan and its exact `LOCAL_COMMITTED` receipt are saved before the
  selected Company's State checkpoint advances.
- Crash recovery recomputes every sealed digest and requires the complete
  cycle/request/source/release/records/schedule receipt binding.
- Missing, altered, ambiguous, pending, or confirmed receipts fail closed and
  do not repair State.
- Manual-review and legacy-job identity protections remain frozen into the
  plan.

## Independent evidence

Independent QA inspected the repaired implementation and adversarial tests,
then ran:

`PYTHONPATH=src:tests python3.11 -m unittest tests/test_exact_cycle_planner.py`

Result: 13 tests passed.

The coordinator independently reran the same focused suite with verbose
output. Result: 13 tests passed in 0.433 seconds.

The suite covers missing receipt, wrong binding with matching records,
altered durable payload, invalid plan, changed Company control evidence,
blocked payload, bounded scope, manual-review/legacy identity guards, partial
payloads, and crash recovery after plan save but before State save.

## Remaining gate

The publisher must share versioned control-evidence semantics and exact
receipt derivation, pass its independent re-review, and then the combined
planner/publisher orchestration must be reviewed. Production remains on the
accepted containment hold.
