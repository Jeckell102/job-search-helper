# Independent acceptance: healthy in-flight status repair

Date: 2026-11-18
Reviewer: final_qa_rollout; independent of scheduler repair implementation and original scheduler finding ownership.
Verdict: **PASS for this staged repair only**. Deployment concurrency repair and repeat final QA remain required. No production or real inference actions occurred.

## Source binding

Worker freeze was confirmed before test execution. Observed hashes match that freeze:

- coordinator_campaign.py: `ce2db9aa56517bd516607c03c2f9f5ac1eaafd6c10f3f895bc5497e53cc14062`
- test_campaign_inflight_status.py: `900ab1b8dc76acf801e73eb4729d3801180c4647ca05544a5d78fad12001aea9`
- coordinator.py: `e38f3c859122f8763c77cbdb97e5c06a358c8f89723a5b43d497bd631f5282e1`
- coordinator_inference.py: `0abce9be80411e913531c2bf3470e5f8a3110a9af062e2cf5f8578116b3a3f42`
- coordinator_store.py: `66aebf37b7580bdf674598799762121146405e62f877e47b1159f01731c3e581`

Complete host map: `independent-status-repair-source-binding.json`.

## Verification

Independently ran **90/90 passing tests**, with ResourceWarnings treated as errors, across healthy in-flight status, campaign completion/results/isolation, inference reservation/store, control transitions, and resilience. Log: `independent-status-repair-tests.log` (9.782 seconds). An initial invocation used three nonexistent module names and was corrected; that invocation is not counted as passing evidence.

The new event-driven regression exercises actual `Coordinator.session()` with a blocked injected callback and all public observational aliases: campaign-status, autopilot-status, queue, list, health, and task status. Controls and generation remain unchanged, owner remains RUNNING, no other company can activate, no second inference can begin, and the returned callback becomes COMPLETED with correct 150-token accounting.

Code inspection confirms the exemption requires exactly one DISPATCHING receipt, matching row/data request/task/status, unfinished receipt, exactly one active owner, open matching session, valid current identity/control ownership/deadline, matching phase/company/campaign run and identity digests, current control generation, and exact reserved-token/call/session counter consistency. The pending receipt remains a global selection barrier. It is not cleared or treated as completion.

Malformed or mismatched receipts, closed sessions, expired ownership, orphaned owners, duplicate pending dispatches, and UNCERTAIN/recovered dispatches remain reconciliation errors and stop advancement. Existing inference reservation tests retain pause-before-dispatch suppression, post-reservation response discard, no tool writes after stop, exactly-once accounting, and restart no-replay behavior.

Added **two independent event-driven tests**, both passing, in `test_status_repair_independent.py`. These invoke an actual session callback, interrupt through the public campaign-stop command or recovery, then issue every observational alias before returning the callback. Explicit pause leaves RESPONSE_DROPPED; recovery leaves UNCERTAIN. Neither path revives controls, activates another company, creates another session, or replays the single counted call. These independently cover real callback behavior beyond the repair's direct-store negative tests.

Total independent focused executions: **92/92 passed**. Historical failure JSON/Markdown was not rerun or overwritten by this reviewer. No implementation files were changed.
