# Exact-cycle planner QA failure — 2026-11-19

## Result

**REJECTED.** The first isolated planner candidate correctly avoided fetch,
publication, and global synchronization, but its restart-recovery proof was
not strong enough to advance the selected cycle checkpoint.

## Blocking defect

For a newly planned inventory, the candidate saved the immutable plan plus
`LOCAL_COMMITTED` receipt before updating State. On restart, however, the
existing-plan branch checked only plan shape, requested URL, and a
self-consistent Company-control digest. It did not bind the plan to the exact
durable inventory payload and did not require the exact matching stored
receipt/binding/records/schedule.

A syntactically valid stale or fabricated plan with the same URL could
therefore be treated as recovered and change the selected checkpoint from
queued to inventory. No live or production invocation occurred.

## Required repair

- Freeze a canonical full inventory-payload digest and plan/records digest in
  every new plan.
- On recovery, recompute the payload digest and derive the exact receipt from
  cycle, Company, payload, and plan.
- Require one stored receipt whose full binding, records, schedule, and safe
  lifecycle state match exactly; records-plus-Company lookup is insufficient.
- Missing, ambiguous, stale, altered-cycle, or altered-payload evidence holds
  without changing State.
- Company-control evidence must contain bounded active/unclaimed control
  fields, not only the Company ID and URL.
- Adversarial no-receipt/wrong-receipt/altered-payload cases must pass, while a
  genuine crash after plan+receipt persistence must still recover.

The planner lane owns the repair. Independent QA must re-review it before any
runner wiring or production install.
