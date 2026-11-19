# Exact recovery terminal-hold qualifier QA pass — 2026-11-19

## Result

PASS for the isolated, read-only terminal-hold qualification component. This
does not authorize the exact pause adapter, any receipt creation, any Google
write, or production wiring.

## Accepted safeguards

- An exact cycle member must have State stage `blocked` or `unsupported` and a
  retained blocked inbox inventory.
- A plan, when present, must have an exact non-boolean end cursor and valid
  record fingerprints.
- Receipt authority is derived from the planner's exact cycle/request/source/
  release/records/schedule contract. Same-record lookup is ambiguity detection
  only; the expected receipt must be `SYNC_CONFIRMED` with exact fields.
- Any same-Company receipt prevents a no-plan hold from qualifying, and any
  pending, mismatched, or different-cycle receipt prevents legacy fallback.
- Legacy qualification requires a closed versioned envelope bound to cycle,
  Company, inventory digest, plan digest, cursor/count, records, selected-row
  readback digest, and an explicitly non-confirmed `PROPOSED` receipt.
- Revalidation requires a fresh selected-row proof for legacy evidence and
  compares the complete fresh manifest digest. Cached proof cannot stand in
  for live readback.
- The component performs no State save, inventory acknowledgement, plan
  replay, receipt mutation, remote write, or runner action.

## Evidence

Independent QA inspected the repaired source and ran:

`PYTHONPATH=src:tests python3.11 -m unittest tests/test_exact_recovery_terminal.py`

Result: 6 tests passed.

The coordinator independently ran the verbose form of the same suite; all six
tests passed in 0.196 seconds.

## Remaining gate

The manifest is only a precondition for a future exact pause adapter. That
adapter must persist its own journal, revalidate these manifests immediately
before apply, use bounded selected-row writes/readback, and pass separate
independent QA.
