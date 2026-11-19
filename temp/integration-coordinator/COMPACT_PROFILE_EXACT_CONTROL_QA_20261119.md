# Compact-profile exact control repair QA

Date: 2026-11-19

Scope: source-only repair in the isolated integration worktree. No Google,
production database, lock, queue, receipt, or live job data was accessed or
changed.

## Defect

The accepted exact-cycle path asked the remote Companies sheet for `Claimed
By` and `Claim Token`. Those fields are intentionally local-only in
`compact-v1`, so the guarded recovery would fail before publication even when
the selected Company was otherwise valid.

## Repair

- Exact recovery now constructs one composite Company guard while it owns the
  normal scraper lock.
- Every guard invocation freshly reads the authoritative local Company fields,
  including claims, scan state, and the manual-retry hold.
- It separately reads only `Company ID`, `Company Status`, and `Official
  Careers URL` from the remote compact projection.
- It requires one unique row on each side, an active/unclaimed/non-held local
  Company, the requested local board, and exact field-aware agreement for all
  three shared controls.
- The same six-field composite evidence seals a new plan and validates every
  publisher path, including post-checkpoint cleanup recovery.
- `publish_exact_cycle` now fails closed unless its caller supplies the trusted
  Company guard. Guard failure occurs before receipt persistence or remote
  commit, preserving the prior zero-replay behavior.

## Adversarial coverage

The focused suite proves:

- compact-v1 publication succeeds without asking Google for local-only fields;
- a missing guard fails before receipt creation or remote work;
- a local claim or manual hold added after planning prevents publication;
- local status or board drift prevents publication;
- local/remote status or board disagreement prevents publication;
- missing or duplicate local/remote Company identities prevent publication;
- every failure above leaves both remote commits and new publication receipts
  at zero; and
- the orchestrator injects the identical composite guard into planning and
  each selected publisher call.

## Verification

Focused command:

`PYTHONPATH=src python3.11 -m unittest tests.test_exact_cycle_sync tests.test_exact_cycle_recovery`

Result: **54 tests passed**.

Adjacent command:

`PYTHONPATH=src:tests python3.11 -m unittest tests.test_durable_inbox tests.test_exact_cycle_planner tests.test_exact_cycle_sync tests.test_exact_cycle_recovery tests.test_exact_recovery_terminal tests.test_exact_recovery_pause tests.test_exact_recovery_pause_apply tests.test_exact_recovery_pause_executor tests.test_runner_cycles`

Result after the final local-drift cases: **158 tests passed**.

Static verification:

- `py_compile` passed for both modified source modules and both modified test
  modules.
- `git diff --check` passed for the owned changes.

## Remaining gate

This report is source-level evidence only. Independent review, protected-source
reconciliation, production tests, rollback capture, and any bounded live
publication remain coordinator-owned release gates.

An adjacent issue was exposed while trying a newly frozen empty-inventory plan
against an in-memory compact repository: the planner currently seals local-only
Companies values (for example `Scan State` and `Active Cycle ID`) into a new
remote operation, which a compact repository correctly rejects. That is
separate from this remote-control-read repair and belongs to
`exact_cycle_planner.py`, outside this lane's assigned file ownership. Existing
pre-frozen compact-compatible plans can use this guard repair, but any selected
inventory without a frozen plan must remain held until the coordinator assigns,
reviews, and verifies a profile-aware planning repair.
