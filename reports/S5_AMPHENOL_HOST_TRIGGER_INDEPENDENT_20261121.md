# Independent QA: exact Amphenol host enrollment trigger

2026-11-21. **ACCEPT for this narrow source-only host trigger.** All six supplied enrollment cases passed. No new trigger-boundary failure was found. A sampled existing host-supervision assertion fails identically on the untouched baseline and remains explicitly recorded below; this verdict is not a claim that the whole host test suite is green.

Candidate: `/tmp/jsh-s5-amphenol-host-trigger.gn2qvpsd`.

| File | SHA-256 |
| --- | --- |
| `dev/wrapper-coder/tools/host_server.py` | `e4d8036b3cd090298e70e5b3c8732a52bb0158b42d21d35535681f41229e141b` |
| `dev/wrapper-coder/tools/test_amphenol_host_enrollment.py` | `eefaece1ad47f284e44a03753ba43afe02b5f8975a179a381dd9fc3c3a5d7c6c` |
| Corrected promoted-input dependency `amphenol_recipe_choice_input.py` | `0c5162fcaeb4cba599250ebe4dd20e6cb7e97628a608c9d2906eaaee8d77c800` |

Requested candidate pins were checked before and after review. Source and tests ran only in private `/tmp/jsh-s5-host-trigger-independent.7a49t0rm`; source candidate remained unchanged. System Python 3.11 used isolated explicit paths, no bytecode or plugin autoload, and an audit hook rejected network/DNS operations. Host imports used the tests' disposable token substitution. No native process, credentials, provider, model, Google, service or production database access occurred.

## Boundary evidence

- Process enrollment is absent by default and accepts only the exact event ID, derived request ID and source revision. It accepts no selected outcome ID; the request can be selected before the outcome is available. Missing/multiple/wrong request or revision outcomes remain held. This is a format and lookup contract, not retrospective proof of when a process environment was installed.
- Catch-up requires the exact current qualified ordinary terminal record and settled frozen observation. It derives the workbook identity from co-located Inbox under the application locks, verifies actual Jobs destination, then delivers only the selected outcome through the existing two-sided receipt bridge. It does not drain the unrelated backlog.
- The existing accepted readback rechecks sender acknowledgement, receiver receipt/intake and current source before preparation. The reviewed profile is enabled only inside the selected preparation context. Preparation yields one isolated review-mode task, one session, exact source/test scope; the same promoted owner is rechecked before pilot activation.
- Workspace and control serialization protect selection/preparation, while existing queue/campaign controls and HTTP task-control handling use the control lock. Active work, unresolved inference or existing pilot keep this path held. Catch-up only queues the existing one-task pilot; it does not itself call inference. No scheduler is started by the test or by catch-up.
- Genuine disposable delivery/promotion confirms the sender receipt equals the prepared receiver receipt, only the selected task is queued, and an unrelated pending outcome is unchanged. Global queue and campaign remain disabled.
- Repeated catch-up with a live pilot holds; stopping the pilot does not allow catch-up to restart it. A cut after promotion leaves its task paused permanently for explicit disposition. A cut after durable acknowledgement resumes from that acknowledgement without resending it and creates only the one task. An uncertain inference and its saved task/receipt remain unchanged.

## Test execution and retained baseline mismatch

Combined command ran `test_amphenol_host_enrollment.py` and `test_host_supervision.py`: **9 passed, 1 failed in 14.67s**. All six new enrollment cases passed; three sampled normal-host cases passed. The remaining normal-host assertion is:

`HostSupervisionWiringTests.test_host_persists_external_retention_counts_from_zero_argument_probe`

It expects `outcome_consumer='wrapper-coordinator'`; actual is `repair-coordinator`, which matches current `scrape_outcome_delivery.CONSUMER`.

Re-ran only that exact assertion against untouched `/tmp/jsh-s5-owned-choice-readback.PpzW7IwU`: **1 failed in 0.74s**, same expected/actual mismatch. Baseline host SHA `2c57952bcc67dbaf321377956f7efa3ac45f39ed1ef40cb0f9e8aaccfcb62ae0`; unchanged legacy test SHA `7060e43c1194beeb86a9f267e7e7c9a7289062af9617b2ed4a9d2fd0c89cfcf0`. `BASELINE_FAILURE.txt` preserves this disposition. No test expectation or source was edited. This baseline fixture mismatch remains outside the new trigger seam and must not be reported as a passing broader suite.

No extra negative fixture was added because no concrete new architectural gap emerged. Full event-to-candidate execution, scheduler-driven inference, native enrollment/service behavior, release and real publication remain separate evidence and acceptance gates owned by the coordinator.
