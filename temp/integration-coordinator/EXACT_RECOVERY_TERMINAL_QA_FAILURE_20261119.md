# Exact recovery terminal-hold qualifier QA failure — 2026-11-19

## Decision

REJECT. The first isolated qualifier is read-only and preserves blocked work,
but it does not prove that its receipt/readback evidence belongs to the exact
cycle, payload, plan, and schedule. It is not wired or deployed.

## Blocking defects

1. The confirmed-receipt lookup treats a same-Company, same-record receipt as
   authority without first deriving and requiring the complete expected
   request/source/release/schedule binding. A receipt from another cycle can
   therefore qualify the hold.
2. The legacy readback callback accepts an untyped `confirmed=True` response
   and can qualify without a validated proposed receipt. The proof is not
   bound to selected rows, cycle, Company, payload digest, plan digest, cursor,
   records, or schedule.
3. Boolean cursors can compare equal to integer operation counts. Cursor type,
   domain, and exact end position must be enforced.
4. The returned manifest has no revalidation/CAS boundary for a later pause
   adapter. Any changed State, inbox payload, plan, cursor, receipt, or schedule
   must invalidate the preflight digest before apply.

## Required repair evidence

- Deterministically derive the exact expected receipt; use record lookup only
  to detect ambiguity and require full binding, records, schedule, and
  `SYNC_CONFIRMED` equality.
- Require a versioned, read-only legacy proof envelope and a separately
  validated, explicitly non-confirmed proposed receipt.
- Enforce an exact integer end cursor.
- Add a pure live revalidation/digest comparison API plus adversarial tests for
  different-cycle same-record receipts and post-preflight mutations.

Production remains on the accepted containment hold. No Google access, live
recovery, inventory acknowledgement, or State mutation occurred.
