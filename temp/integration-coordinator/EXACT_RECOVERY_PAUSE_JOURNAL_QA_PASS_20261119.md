# Exact recovery pause-journal phase-A QA pass — 2026-11-19

## Result

PASS for the freeze/revalidation boundary only. The component cannot apply a
pause, write Google Sheets, save cycle State, mutate an inbox item, or wire the
runner.

## Accepted safeguards

- Requires the exact unfinished cycle and refuses any remaining unblocked
  durable inventory or plan.
- Requires terminal manifests to have valid structure and digest, be freshly
  revalidated byte-for-byte, and exactly cover the blocked inbox Company set.
- Derives the remaining queued/inventory candidates from State in preserved
  Company order; a caller cannot widen the list.
- Freezes the full decoded cycle digest, each candidate's pre-stage, every
  terminal-manifest digest, and `next-scan.json` presence/content digest.
- Uses a mode-0600 SQLite journal. Only canonical identical replay is
  idempotent; changed or corrupt payload/digest evidence is rejected.
- Pre-apply revalidation recomputes State, inbox, terminal-manifest, and request
  facts and performs no journal write.

## Evidence

Independent QA inspected the component and passed seven focused tests. The
coordinator independently passed the same seven tests plus `git diff --check`.

## Remaining gate

The phase-B pause adapter must add persisted per-chunk intent, bounded selected
Company writes and exact readback, uncertain-request readback-only recovery,
State `recovery_pause` finalization, and a separate exact Scan Cycles-row
receipt/readback. It must revalidate this journal immediately before apply and
pass independent QA before any production action.
