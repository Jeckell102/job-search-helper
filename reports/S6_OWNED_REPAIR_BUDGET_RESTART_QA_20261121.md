# S6 independent exhaustion and next-owner acceptance

**ACCEPT for the disposable one-session exhaustion gate.** The staged Coordinator used its regular owned repair intake, isolated promotion, pilot activation and claim, and worker step with workflow version 2. A single fixture reply was observed only after a durable `DISPATCHING` reservation with the exact control binding. The receipt reached `COMPLETED`, accounting one session, one call, and 560 tokens. The next real worker step reported `PAUSED_BUDGET` and saved progress. The test made no direct task/counter writes.

A fresh system Python process reopened the same SQLite store, ran recovery, and saw the same status and reason via the normal status command. Identical intake and promotion returned the original outcome/repair/task. Ordinary resume reported `Task budget exhausted`; the old task remained unclaimable. The entire original task State and all action/inference receipts matched after both replays and after the next pilot was claimed.

The second process used explicit pilot stop and then the normal owned intake, promotion, pilot start, and claim for another exact company and source revision. Its task, repair key and outcome ID were distinct. It reached `RUNNING` with one allowed session, zero consumed sessions/calls/tokens and no inference receipt. The broad queue and campaign stayed closed, and the second process issued zero inference calls.

The maintained [workflow exhaustion test](/tmp/jsh-s5-enrolled-retry-receipt.20261121/dev/wrapper-coder/tools/test_coordinator_workflow.py:151), [queue tests](/tmp/jsh-s5-enrolled-retry-receipt.20261121/dev/wrapper-coder/tools/test_coordinator_queue.py:45) and [campaign successor test](/tmp/jsh-s5-enrolled-retry-receipt.20261121/dev/wrapper-coder/tools/test_campaign_completion_qa.py:98) cover parts of this path independently. The disposable harness adds the process and distinct owner composition.

The local fixture used synthetic board evidence and one deterministic inference reply. The harness also substituted the baseline test runner, Git and workspace-source discovery. It kept the actual Store/Coordinator, acceptance, local evidence and accounting paths. A Python audit hook rejected socket transport. The initial fixture run stopped at that guard when it reached board retrieval; the passing run supplied the scoped synthetic board reply. No native application, production store, provider or external model was accessed. This checks one counted-session limit and claim of the second assignment.

## Evidence

- [Rerunnable proof](/tmp/jsh-s6-budget-restart-independent.0BhVV9FN/prove_budget_restart.py) SHA-256 `e220bc734fccd89c252d2c8de83a457bf78a12b3bc9cb096bed037241135b9fb`. Run with `/usr/bin/python3 -B /tmp/jsh-s6-budget-restart-independent.0BhVV9FN/prove_budget_restart.py` to create a fresh adjacent fixture.
- [Passing result](/tmp/jsh-s6-budget-restart-independent.0BhVV9FN/budget-run-ukeuam89/RESULT.json) SHA-256 `f32ff18643fa7102fe39bde25f4feafd8dca4478c1660e2be16f13b105ceb382`.

Staged pins in `/tmp/jsh-s5-enrolled-retry-receipt.20261121/dev/wrapper-coder/tools`:

| File | SHA-256 |
| --- | --- |
| coordinator.py | `dcf6f14ea4ff15e6c221ff3f46c29523419d931dfbf0dffe6e2edd6b0f427a91` |
| coordinator_store.py | `9f0a84a626fcf910f24233759ff940ff68db81c97b9b0e7096a3d4b0580ea835` |
| coordinator_inference.py | `4d94acad23e879089dee088c04826ddef4b062b77316915bf493ee2db17db968` |
| coordinator_campaign.py | `ce2db9aa56517bd516607c03c2f9f5ac1eaafd6c10f3f895bc5497e53cc14062` |
| coordinator_workflow.py | `4cad5294829ee212fa4b2da40dbefcddff45a52559b5a3baffc26db5d4202d6c` |
| coordinator_workspace.py | `c8b56ea7aedd7c9af5bcae87ff072ddf286f45cd7cb46fa58ee1e03c3be6f107` |
| test_coordinator.py | `14b7af68303c9aab38765df9b31538cd6691fd1689e7292f09f605fa1532728b` |
| test_outcome_intake.py | `2cede57547a9d4bee464a5a83d14cd9fe8edae0cdb1bf44be5d3fe402cf33946` |
