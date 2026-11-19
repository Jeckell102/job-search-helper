# Exact recovery terminal-hold and pause design — 2026-11-19

## Fresh authoritative status

The protected read-only recovery command was rerun on 2026-11-19. It confirms
that `CYC-B639C6D864EC` is the sole blocking cycle, with 800 Companies:

- 764 queued
- three inventory
- three blocked
- two unsupported
- 20 complete
- eight partial
- 47 saved inventories, eight plans, and eight cursors greater than zero
- 767 current pause candidates

It remains in `SAVED_WORK_MUST_BE_PUBLISHED_OR_RECONCILED`. No change was
applied.

The 42 unblocked saved inventories comprise 39 queued checkpoint/payload
splits and three existing plans. Once they are safely planned/published and
their checkpoints become terminal, approximately 725 unsaved queued Companies
remain for an explicit recovery pause. The other five saved inventories are
existing terminal manual holds (three blocked and two unsupported) and must be
retained rather than published, retried, acknowledged, or deleted.

## Why the current pause command is disqualified

The current recovery gate counts every saved inventory/plan, so retained
manual holds prevent eligibility forever. The current apply command also calls
the global synchronization worker before and after pause, which can pull and
publish unrelated data. It cannot be relaxed or reused for this exact-only
recovery.

## Terminal-hold manifest

Add an audit-only `recovery_terminal_holds` manifest while retaining the
original blocked inventory and optional frozen plan in place. Each manifest
entry binds the exact cycle/Company, terminal State stage, inventory digest,
optional plan digest/cursor/count, confirmed receipt/fingerprint, and version.

Classification fails closed. A terminal hold requires blocked inbox state,
State stage exactly `blocked` or `unsupported`, and no unconfirmed remote work.
A plan must be at its end cursor and have a full exact remote fingerprint
confirmation. The current legacy holds have no receipt table yet; qualification
therefore needs a **readback-only** selected-row reconciliation that may create
and confirm the receipt only when the remote fingerprint already matches. It
must never write or replay the held plan. A mismatch remains unsafe saved work.

## Exact pause adapter

After all 42 unblocked inventories are reconciled and the five terminal holds
are manifest-qualified, freeze a pause journal containing only the remaining
queued/inventory candidate IDs plus pre-state and hold-manifest digests.

The new adapter must:

1. Persist the journal and per-chunk intent before any request.
2. Use narrow current Company-control reads and expected guards.
3. Commit only the selected candidate Company hold fields in bounded chunks.
4. Require exact selected-row readback before confirming each chunk; uncertain
   requests are readback-only on restart and never blindly replayed.
5. After all Company holds are confirmed, save only the exact cycle's
   `recovery_pause` checkpoint while preserving the five existing terminal
   stages and their inbox evidence.
6. Directly update/read back only the exact `Scan Cycles` row through a separate
   finalization receipt. No global synchronizer, local dirty outbox, normal
   pipeline, or generic full-tab read is allowed.
7. Leave `next-scan.json` unchanged. The next normal start owns Company-only
   request admission after the cycle becomes terminal.

## Acceptance boundary

Tests must prove terminal-hold qualification/refusal cases, exact candidate
selection, unrelated-state isolation, bounded pause chunks, uncertain-write
recovery, crash ordering around State and cycle-row finalization, preserved
manual holds, `Complete with exceptions` with zero remaining, and request-file
nonmutation. Production remains on the containment hold until the planner,
publisher, terminal-hold reconciler, and exact pause adapter all pass
independent QA.
