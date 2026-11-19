# Exact-cycle publisher QA failure — 2026-11-19

## Result

**REJECTED.** The selected-row publisher is safely unwired and its expanded
restart/chunk regression passes, but six correctness guards remain required.

## Independent QA findings

1. Stored cursor domain was not validated. Negative or beyond-end cursors
   could select the wrong slice or reach final acknowledgement.
2. The planner's saved Company-control evidence was not compared with fresh
   current controls/source revision before publication.
3. State stage was not required to be the exact recoverable planned stage; a
   terminal manual hold with a stale unblocked inbox flag could be published.
4. Duplicate-target validation used original identities, so two legacy
   identities could both migrate into the same final identity.

## Coordinator findings

5. Receipt lookup matched Company plus record fingerprints but did not require
   the exact cycle/request/source/release binding and schedule. A receipt from
   another cycle could be selected.
6. The in-memory cycle object was mutated before State save. If that save
   failed, a later Company's successful save could persist the failed
   Company's final state despite its retained plan/inventory.

## Repair evidence required

Adversarial tests must prove invalid cursor refusal, stale/missing provenance
hold, terminal State hold, final-identity collision refusal, wrong-cycle or
wrong-source receipt refusal, and two-Company State-save failure isolation.
The existing selected-row, digest-bound chunks, prefix validation, lost-ACK
readback, CAS, blocked exclusion, and checkpoint-before-ack tests must continue
to pass. Runner wiring and production/live use remain forbidden pending
independent re-review.
