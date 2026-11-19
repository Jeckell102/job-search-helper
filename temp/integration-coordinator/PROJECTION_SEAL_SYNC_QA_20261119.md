# Projection-seal sync and recovery gate — 2026-11-19

Status: IMPLEMENTED; FOCUSED AND ADJACENT TESTS PASS; LOCAL DURABILITY REMAINS A REQUIRED EXTERNAL GATE

## Scope

This change is limited to the selected-plan publisher and its focused recovery tests. It does not implement or claim a durable local-application journal.

## Accepted behavior

- The publisher validates publication projection version, profile, current remote schema digest, remote operations digest, and remote projection digest before Company controls, receipt creation, readback, or remote commit.
- A `full` publication plan is accepted only when its local operations digest and local operations-plus-finalization digest are recomputable from the frozen plan.
- Any non-full profile is held with `non_full_plan_requires_durable_local_commit_journal`. A compact projection cannot prove omitted local-only work from its Sheets operations.
- `sync_plans.cursor` is treated only as durable local-application progress. It must equal the complete local operation count before publication and is never advanced by remote publication.
- Full plans derive that count from `operations`; a future projected plan derives it from `local_operations`, never from the shorter remote projection. Compact publication remains disabled before this comparison until its journal contract exists.
- Remote progress is tracked only by the immutable publication receipt and `exact_sync_chunks`. Lost acknowledgements are resolved by exact readback without replay.
- Legacy/pre-projection plans and incomplete local-application cursors fail closed without remote writes.
- Compact Company control composition remains unchanged: local-only claim/scan controls stay local, while shared visible controls are compared with a bounded remote read.

## Verification

Focused command:

`PYTHONPATH=src python3.11 -m unittest tests.test_exact_cycle_sync tests.test_exact_cycle_recovery`

Result: PASS — 58 tests.

Adjacent command:

`PYTHONPATH=src:tests python3.11 -m unittest tests.test_exact_cycle_planner tests.test_exact_recovery_terminal tests.test_exact_recovery_pause tests.test_exact_recovery_pause_apply tests.test_exact_recovery_pause_executor tests.test_runner_cycles`

Result: PASS — 91 tests.

`git diff --check` passed for all three changed source/test files.

An all-tests discovery run was attempted but intentionally stopped after the required focused and adjacent suites passed because the broader repository run exercises unrelated environment-dependent and concurrently changing work. It was not used as acceptance evidence.

## Remaining gate

New full-profile plans currently stop at `local_plan_not_durably_applied`, and compact plans stop at the explicit journal requirement. A separate implementation must durably apply the complete local operation stream, prove exact local readback/finalization, and advance the local cursor before this publisher is allowed to perform any Sheets work. The rejected local-plan proposal must not be used because plan-derived fingerprints are not authoritative local readback evidence.

No production data, Google Sheets, Jetson service, or production worktree was changed by this lane.
