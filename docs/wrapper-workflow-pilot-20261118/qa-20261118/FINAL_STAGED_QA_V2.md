# Independent final staged QA v2

**PASS for the exact staged candidate. Installed-state QA remains the next mandatory gate.** This review is independent of the implementation owners. It does not certify production installation, campaign activation, live scraper validation, generated-wrapper installation, or complete job downloads. No production source, service, database or inference endpoint was changed by this reviewer.

## Exact reviewed candidate

- Manifest: `candidate-release-v2-manifest.json`, canonical digest `3fb8c7ce00a4bed1ca7a6c93784eba04678552b4b35ca0ad1dcfbf21e919a17f`.
- Complete clean release: `/tmp/wrapper-final-v2-ce6fjvrr/release`, digest `0322c36d5dcfea01e8d18a73895e9a8d5b84e1f5a69bb21189264f2f87a62c15`.
- Independently verified all 66 source files, all 682 prerequisites, complete clean-tree inventory, and reviewed migration inputs against the manifest. The entire host Python hash map equals the independent status-repair acceptance map. All three deployment source hashes equal the independent rollout-repair acceptance map. Evidence: `final-staged-v2-independent-binding.json`.

## Findings and acceptance

I read the original seven-finding assessment, reproduction mapping, final plan, completion audit, roadmap, both preserved final-QA failures, and both fresh independent repair reports. I inspected the mapped regression scenarios and relevant current status, release, rollout, recovery and migration paths. Assertion-based regressions appropriately replace historical diagnostic scripts that only print failures or target removed hooks; zero exit from those old scripts is not accepted as success.

| Original group | Current staged acceptance |
| --- | --- |
| 1. Membership/pause | Exact membership selector and claim assertions cover user pause/exclusion, generic and other-campaign isolation, completion advance, restart and concurrent claim. |
| 2. Atomic modes | Competing pilot/campaign/queue transitions, preparation pause, failed commit and failed validation preserve one committed owner and prevent stale pilot slots. |
| 3. Identity | Canonical worker assignment and evidence identity, immutable activation bindings, conflicting/duplicate imports and concurrent retry lineage have executable coverage. |
| 4. Scope/acceptance | Exact path authority and guarded expansions fail closed; source-bound frozen assertions cannot be replaced by editable stubs. `real-acceptance-verification.json` additionally records actual sandbox failure of bad source and success of corrected source. |
| 5. Inference stop/accounting | Pause before reservation suppresses callback; reserved work retains honest accounting; subsequent tools are blocked after stop; uncertain dispatch blocks other work and replay. |
| 6. Completion/status | Durable current-company denominator, revisions, explicit exceptions and truthful live/install gates are covered. The healthy in-flight status cancellation failure is repaired without exempting orphaned/uncertain receipts. |
| 7. Ownership/release | Direct/private scheduler paths require process ownership; all copied assignment inputs are pinned. Complete source/prerequisite assembly, stopped-service rollback, crash recovery and durable rollout ownership are covered. |

Fresh complete clean-host execution passed **282/282** in 23.924 seconds (`final-v2-host-suite.log`, executed by the coordinating reviewer; result independently inspected here). This includes all mapped host regression modules. The exact same host bytes have **92 passing independent status-repair executions**, including real blocked callbacks interrupted by explicit pause and recovery. The exact rollout bytes have **27 passing independent ownership/release/rollback executions**, including cross-process contenders, process death, matching recovery, installed-terminal verification and malformed pending markers. Counts overlap and must not be summed into a unique-test total. No redundant suite was rerun by this reviewer after source/evidence parity was proved.

The status fix recognizes only one fully bound current DISPATCHING reservation and retains its selection barrier. Invalid ownership, stopped/recovered sessions and UNCERTAIN receipts still block advancement. The rollout fix holds one permanent-inode process lock across the whole transaction and uses a durable marker to block fresh operations after process death. Recovery must match that marker and reviewed binding; terminal installed recovery verifies current installation instead of restoring an obsolete backup. These directly address the two preserved final failures. No unresolved staged blocker was found.

The two-company rehearsal records separate workspaces and fresh packets, pause/restart, real guarded edits/tests and final `DRAINED_WITH_EXCEPTIONS`: one offline-ready company awaits live validation, and one blocked company requires operator clarification. Its four model callbacks are simulated. It does not establish live or installed success.

Fresh exact-102 migration rehearsal passed with 102 membership changes, 102 identity changes, 102 registry entries, preserved nonmembers/history, second-run no-op, all controls OFF, pilot null and integrity `ok` (`final-v2-controller-migration-rehearsal.json`). An additional two-copy same-process check proves exact rehearsal/apply result parity (`final-v2-migration-parity.json`). Postmigration digests can differ between separate Python processes because persisted JSON key order differs; the controller compares rehearsal and apply in the same invocation, and the additional check resolves this concern. The original database digest remains exactly the manifest binding.

## Release boundary

This report supersedes the earlier staged FAIL decisions for this candidate only; preserve both original failure reports and reproductions. Historical completion-audit/roadmap labels require reconciliation with this new gate and are not evidence of installed acceptance.

The next authorized stage is the exact reviewed paused coordinator rollout with backups, migration rehearsal, durable journal and rollback verification. Then independently verify installed source/forwarder parity, single scheduler owner, health, exact migration counts, unchanged post-start logical database, controls OFF, pilot unset, no active work and integrity. Final GitHub-to-installed parity remains pending. Any candidate change invalidates this manifest-bound PASS. Any installed failure reopens the affected gate and requires rollback or a documented safe paused state.

Machine-readable gate and evidence hashes: `FINAL_STAGED_QA_V2.json`.
