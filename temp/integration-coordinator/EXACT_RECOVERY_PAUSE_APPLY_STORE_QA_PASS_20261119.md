# Exact recovery pause apply store — independent QA pass

Date: 2026-11-19

Scope: storage-only `PauseApplyStore` in
`src/job_search_helper/exact_recovery_pause_apply.py`. This approval does not
authorize a remote Company update, State finalization, Scan Cycles update,
runner wiring, or a live recovery operation.

## Result

PASS after repair.

The first review rejected a causal-completion gap: a corrupt or racing writer
could make a run appear `COMPLETE` without the full confirmed intent chain, and
Scan confirmation did not prove that it performed the corresponding
`FROZEN -> COMPLETE` transition.

The repaired store now:

- validates that every frozen Company chunk intent is `CONFIRMED` at its exact
  frozen digest before accepting a completed run;
- validates the exact State and Scan finalization intents and digests as part
  of the completed-run proof;
- requires the Scan confirmation transaction to update exactly one run from
  `FROZEN` to `COMPLETE`; and
- rolls back the Scan intent confirmation when that transition fails.

Eight focused tests passed, including manual premature completion and a raced
completion immediately before Scan confirmation. Independent QA also ran the
combined pause-store, orchestrator, planner, publisher, and terminal set: 68
tests passed in 2.408 seconds.

## Remaining boundary

The ledger contains no remote or State mutation logic. The full Phase-B
executor must separately prove frozen-run construction, selected-row writes,
uncertain-write readback without replay, exact State and Scan finalization,
writer-lock ownership, interruption recovery, and unrelated-data isolation.

