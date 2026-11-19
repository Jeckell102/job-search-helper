# Exact-cycle scoped publisher independent QA pass — 2026-11-19

## Result

PASS for the isolated selected-plan publisher component. This acceptance does
not wire the runner, authorize a live recovery, or replace the production
containment return.

## Accepted boundary

- Requires an explicit unique bounded Company selection and refuses blocked
  retries; unselected inventories and plans are never inspected or changed.
- Uses selected identity-column and selected-row reads only. It does not enter
  global synchronization, local dirty publication, review export, cleanup, or
  coordinator outbox paths.
- Requires sealed inventory, records, typed current Company controls, final
  projection, and deterministic exact receipt binding/records/schedule.
- Rejects post-write identity collisions before a request.
- Persists bounded chunk intent, verifies acknowledged prefixes, advances
  cursors with compare-and-swap, and confirms only exact selected readback.
- Pending mismatches and uncertain writes are readback-only and never blindly
  replayed. An already-visible full plan can transition from local to pending
  only after exact full readback, with zero remote commit.
- A confirmed receipt with a pre-end cursor fails closed with zero replay.
- Post-State-save/pre-inbox-cleanup recovery requires an end cursor, an
  existing confirmed exact receipt, exact readback, current controls, and the
  exact frozen final projection. A nonrecoverable State path cannot create or
  transition a receipt.
- State finalization reloads and deep-copies the cycle, preventing a failed
  save for one Company from leaking into another Company's checkpoint.

## Evidence

Independent QA reviewed the current source and passed a 159-test focused
regression. The coordinator passed the preceding 155-test regression and the
implementation lane passed the final 163-test set including the shared
receipt and terminal components. The runner remains `HELD_NO_EXACT_PLANNER`.

The deterministic receipt contract now lives in `exact_cycle_receipt.py` and
is shared by planner, publisher, and terminal qualification; missing fetched
and cycle-start timestamps fall back to the exact cycle ID rather than a
run-dependent timestamp.

## Remaining gate

The combined planner/publisher orchestration must acquire the existing scraper
writer lock, require at most five explicit Companies, construct only local
planning and direct selected-row remote repositories, pass its interruption
and isolation matrix, and receive independent QA before production wiring.
