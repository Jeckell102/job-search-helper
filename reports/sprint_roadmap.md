# Integration automation sprint roadmap

Saved 2026-11-20. This is the gated execution overlay for
`AUTOMATION_ROADMAP.md`; it does not replace or narrow that roadmap.

## Persistent goal and completion rule

Keep one persistent goal active through all sprints. The goal covers all six
roadmap milestones, the final acceptance demonstration, independent QA, the
durable evidence/restart card, guarded deployment, and the verified scoped
GitHub backup. Passing one sprint is not project completion.

Only mark the persistent goal complete when every applicable roadmap exit gate
and every final acceptance demonstration has current, version-bound evidence.
Source tests alone are not deployment or live-operation acceptance.

Current overall completion estimate: approximately 25% by acceptance gates.
This estimate changes only when a gate gains or loses verified evidence.

## Mandatory context-reset and restart protocol

After every context reset, compaction, new window, model handoff, or resumed
session, do not begin implementation from remembered conversation state alone.
Restore alignment in this order:

1. Reassume the role of **senior engineering coordinator and release owner**
   for the complete Job Search Helper integration-automation roadmap. The role
   owns planning, explicit lane assignments, evidence reconciliation, guarded
   release decisions, independent-QA disposition, restart-card maintenance and
   final acceptance. It is not merely an implementation-worker role.
2. Resume the existing persistent goal only if it still names all six
   milestones and final acceptance. Never reopen the completed historical
   Samtec pilot goal, create a competing project goal, or treat one sprint as
   the whole objective.
3. Read completely, in order:
   - `NEW_WINDOW_HANDOFF.md`
   - `AUTOMATION_ROADMAP.md`
   - `QA_FINDINGS_LEDGER.md`
   - this `sprint_roadmap.md`
   - the newest top checkpoint in `COORDINATOR_STATUS.md`
   - the current sprint's named QA/design reports and applicable `AGENTS.md`
     instructions.
4. Treat the files and live state as authoritative. Verify the current code,
   processes, PIDs, locks, queue controls, durable requests, receipts, release
   journal, active worker assignments and backup head before acting. Do not
   assume a process is running or stopped from an old note alone.
5. Restate internally and preserve the non-negotiable safety state: historical
   cycle `CYC-B639C6D864EC` and its Saronic conflict are retained; Samtec stays
   exactly scoped; broad backlog processing and unqualified automatic releases
   stay disabled; existing job data and unrelated changes are preserved;
   Jetson has exactly one inference lane.
6. Identify the first incomplete sprint. Reconcile its requirements one by one
   against current evidence, then continue from the exact next action in the
   restart card. Do not redo accepted work unless current evidence contradicts
   it, and do not skip an open prerequisite because later code exists.
7. Reconcile worker status before assigning work. Give each active lane explicit
   file/state ownership and prevent overlapping edits. Independent QA remains
   read-only and may not repair the candidate it judges.
8. Classify the previous turn as progress, verified wait or no progress. A
   status-only turn is not progress; a lock or note alone is not a live process.
   Take the next safe action whenever useful work remains.
9. Record the active sprint, overall gate percentage, current-sprint percentage,
   latest evidence, blockers and next action in `COORDINATOR_STATUS.md` at the
   next meaningful checkpoint.
10. Never claim deployed, accepted, backed up or complete without current
    direct evidence at the required scope. A passing source suite is not live
    acceptance; a local commit is not a verified GitHub backup.

Restart outcome: continue the same persistent goal and current gated sprint.
Do not reset completion to zero, inflate it from implementation volume, or mark
the project complete until Sprint 7's exit gate is proven.

## Global safety boundaries

- Preserve unrelated working-tree changes and all existing job data.
- Retain historical cycle `CYC-B639C6D864EC` and its unresolved Saronic
  provenance conflict. Do not auto-reconcile, resume, delete, or overwrite it.
- Keep broad backlog processing and unqualified automatic releases disabled
  until their roadmap gates pass.
- Keep the durable Samtec request scoped and held until its exact admission
  and authorization gates pass. Never substitute a test signer.
- MuleLab owns coordination, retrieval, development files, tests, validation,
  storage, receipts, and backups. Jetson retains exactly one inference lane.
- Do not infer completion from unit-test counts, an installed file, or a
  historical pilot. Require the evidence named by each sprint gate.
- Independent QA may reject a sprint. Repair the finding and repeat QA without
  weakening the criteria.

## Ownership model

| Lane | Ownership | Isolation rule |
| --- | --- | --- |
| Coordinator/release | Release admission, coordinator state, repair/retry/release flow, evidence reconciliation, restart card and backup | Sole writer for release/coordinator files during its sprint |
| Scraping/intake | Company-only request, normal filtering/storage/publication, intake/outcome/scheduling behavior | Sole writer for scraper/intake files during its sprint |
| Independent QA | Read-only adversarial review, test execution, live-evidence assessment and acceptance verdict | Does not modify candidate files; returns ACCEPT or REJECT with exact evidence |
| Jetson inference | One reviewed inference-control implementation lane only | No parallel inference requests; follow Jetson README, changelog, catalog, backup and rollback rules |

The coordinator assigns explicit file ownership before parallel work. Lanes may
run concurrently only when their files and mutable runtime state do not
overlap.

## Sprint 1 — F3 release/startup version safety

Roadmap coverage: Milestone 5 prerequisite F3.

Objective: prove that activation, scraper startup, rollback and retry admission
share one fail-closed contract and that every attempt uses one complete source,
configuration and dependency version.

Required work and evidence:

1. Put scraper admission before replaceable application imports using a stable,
   standard-library-only bootstrap.
2. Hold the same admission lock continuously through import, fetch and save;
   do not unlock for an exec/reacquire window.
3. Validate the exact active release, source, configuration and dependency
   binding under the lock and persist the runtime binding with the attempt
   before provider fetch.
4. Make completed activation and rollback replay exact, active-release-bound,
   receipt-backed and crash-recoverable.
5. Route supported launch/controller paths through the bootstrap and reject an
   unsafe direct released start.
6. Document and test writer/scraper/release lock order.
7. Exercise real subprocess barriers in both startup/activation orderings plus
   rollback and crash boundaries.
8. Obtain independent adversarial QA and record its verdict.

Exit gate: independent QA accepts the real startup/import/activation/rollback
tests and exact attempt-version evidence. Until then automatic release remains
disabled.

Sprint 1 passed independent installed QA on MuleLab on November 20. All 13
deployed files matched their approved hashes and modes. All 898,061 existing
database rows were preserved. The 16 KiB additive schema change was reproduced
byte for byte from the exact before image. The installed verdict and the
171 application and 41 maintenance test results are recorded in
`F3_DEPLOYED_INDEPENDENT_QA_20261120.md`. Broad processing and unqualified
automatic releases remain disabled. Sprint 2 awaits operator resume.

## Sprint 2 — F4 Jetson inference reconciliation

Roadmap coverage: Milestones 4 and 6 prerequisite F4.

Objective: make one Jetson inference request durable and safely reconcilable
after lost transport, without replay or double accounting.

Required work and evidence:

1. Read `/home/chris/AI/README.md` and the Jetson documentation index before
   changes.
2. Align the MuleLab request-control schema with the deployed Jetson adapter:
   request ID, fingerprint and owner generation.
3. Add authenticated, owner-bound, sanitized status/result retention and
   POST-only orphan recovery through the reviewed server adapter.
4. Atomically record request ownership before native dispatch.
5. Prove duplicate delivery invokes native inference once, a dropped response
   is reconciled without replay, and resource accounting settles once.
6. Exercise gateway/coordinator crash and stale-owner cases.
7. Record deployed hashes, before/after evidence, backup and rollback in the
   Jetson changelog and file catalog; back up only non-sensitive scoped files.
8. Obtain independent QA of source and deployed behavior.

Exit gate: lost transport can be reconciled to an authenticated retained result
or an explicit safe terminal state without issuing a second inference request.

Sprint 2 passed independent deployed QA on November 20. The installed pair
reconciled a deliberately dropped response from one live synthetic turn.
Usage settled at one call and 19 tokens with zero tool executions. The
previous independently accepted Ollama interruption covers safe terminal
orphan recovery. See `F4_PAIRED_DEPLOYED_QA_20261120.md`. Production queues
remain held, and Jetson retains one inference lane.

## Sprint 3 — Milestone 1 company-only storage and synchronization

Roadmap coverage: Milestone 1 plus F6 and F7.

Objective: run a bounded Samtec company-only request through normal filtering,
durable local storage and exact synchronization, without touching the retained
historical cycle or other companies.

Required work and evidence:

1. Reverify current processes, locks, requests, queue controls and receipts.
2. Admit exactly one known company ID; empty/unknown selection must fail closed
   and omission must never become an all-company scan.
3. Use the normal fetch, filtering, identity, full-description, duplicate and
   writer-coordination paths.
4. Prove `LOCAL_COMMITTED`, `SYNC_PENDING` and `SYNC_CONFIRMED` receipts bind
   request, company, source revision, release and exact record identities.
5. Prove lost write acknowledgement recovers without refetch and without
   overwriting intervening manual fields, including preserved estimated salary
   when a posting has no salary.
6. Measure idle and busy intake-to-start behavior and record queue age,
   blocking cycle and old-paused-cycle recovery policy.
7. Verify current public inventory and expected applicable stored records; do
   not assume the historical Samtec job count.
8. Repeat safely and prove no duplicate records or unintended closures.
9. Obtain independent QA of the deployed path and evidence.

Exit gate: only Samtec is fetched; applicable filtered records and full evidence
are durably saved; exact synchronization is confirmed; rerun and lost-ack
recovery are safe; local versus remote state is explicit.

Current status: partial source-boundary work accepted, live gate open. The
Samtec request remains held pending exact safe admission/authorization.

## Sprint 4 — F1/F2 live event-to-retry chain and Milestones 2–3

Roadmap coverage: Milestones 2 and 3 plus remaining F1/F2 evidence.

Objective: turn a supported company add/source change into one scoped request,
and turn realistic scrape outcomes into the correct durable retry, hold or
repair action.

Required work and evidence:

1. Prove transactional/supported mutation outbox behavior plus reconciliation
   for external edits, bootstrap watermarking, durable acknowledgement and
   deduplication.
2. Exercise idle/busy delivery, duplicate events, reordered revisions, crashes
   on both sides and restart catch-up.
3. Emit structured outcomes from full and company-only runs.
4. Verify complete/zero, temporary provider error, access block, broken
   qualified integration, unsupported capability, storage/publication failure,
   and stale/paused/removed company classifications.
5. Deduplicate repair tasks and retain partial evidence without falsely closing
   unseen jobs.
6. Prove a repaired attempt has a fresh release/source-bound identity and
   cannot reuse or erase the failed attempt's pending publication state.
7. Obtain independent QA of the actual event-to-outcome-to-action chain.

Exit gate: a supported company change creates one logical scoped request and
realistic failures create exactly the correct retry, hold or repair task across
duplicates, restarts and source drift.

Current status: important F1/F2 source boundaries are independently accepted;
the live and full-chain evidence remains open.

## Sprint 5 — Bounded repair, validation, release and scoped retry

Roadmap coverage: Milestones 4 and 5, including F5.

Objective: complete one minimal repair loop from failure evidence through a
qualified candidate, validation, guarded release, fresh company retry and
verified saved jobs without manual prompt copying.

Required work and evidence:

1. Freeze the supported capability matrix and named acceptance cases before
   qualification.
2. Reuse proven adapters/recipes first; isolate bounded code proposals for
   reviewed engineering qualification.
3. Keep company/source identity guards, independently captured fixtures,
   baseline tests and affected shared-adapter regressions.
4. Validate public scope, pagination, stable identities, full descriptions and
   explicit zero-opening evidence through normal dispatch.
5. Release only the exact validated version with rollback, documentation and
   F3 admission evidence.
6. Create and observe a fresh company-only retry using F2 identity and ordinary
   storage/publication.
7. Hold unqualified structures honestly; do not count them as repaired.
8. Record GitHub delivery separately from release/scrape/publication status.
9. Obtain independent QA of the entire induced-failure recovery chain.

Exit gate: an induced qualified integration failure leads to one validated
release, fresh scoped retry and verified saved jobs without manual stage
movement; unsupported capability is held rather than forced through.

Current status: open. Individual source components and historical pilot
evidence do not yet prove the maintained end-to-end loop.

## Sprint 6 — Reliability and sequential staged activation

Roadmap coverage: Milestone 6 plus F8.

Objective: operate multiple companies sequentially with one current repair
owner, one Jetson inference request, bounded budgets, restart recovery and
visible controls.

Required work and evidence:

1. Implement durable leases, ownership generations, cooldowns, bounded
   successor attempts and persistent failure history.
2. Extend supervised services with one-instance ownership, boot/reconnect
   catch-up, pause/shutdown behavior, disk-pressure handling and protected
   retention.
3. Expose separate intake, scrape, repair-generation and automatic-release
   controls plus plain-language status.
4. Freeze at least three unfinished companies with distinct source structures,
   including a shared-adapter regression and one external-block case.
5. Exercise restart at every boundary, duplicates, lost Jetson connection,
   budget exhaustion, source drift, user pause and rollback.
6. Prove a held external-block case does not stop another company.
7. Progress through the staged activation sequence; do not enable broad backlog
   or automatic release earlier than its qualified stage.
8. Obtain independent QA of deployed sequential operation.

Exit gate: the frozen cases complete sequentially with fresh context and no
manual prompting, while holds/exhaustion remain visible and later work
continues safely.

Current status: open.

## Sprint 7 — Final acceptance, deployed independent QA and backup

Roadmap coverage: complete-system acceptance and release ownership.

Objective: prove the deployed system satisfies the roadmap completion contract
and preserve auditable evidence.

Required work and evidence:

1. Run all seven final acceptance demonstrations through the actual
   event-to-storage path.
2. Reconcile every roadmap milestone, F1–F8 finding and sprint exit gate to
   current version-bound evidence. Missing or indirect evidence is a failure.
3. Have independent QA assess the deployed system. If rejected, save a new
   failure report, assign the narrow repair, rerun relevant regression and live
   evidence, and repeat QA without weakening criteria.
4. Update the coordinator restart card, evidence index, known limitations,
   enabled controls and unsupported capability list.
5. Create and verify a scoped GitHub backup of source, tests, plans and reports.
   Exclude credentials, databases, locks, raw job data, private backups and
   Sheets contents. Verify the remote branch/commit and selected files.
6. Confirm broad backlog processing and unqualified automatic releases remain
   disabled unless their own activation gates were explicitly passed.

Exit gate: every requirement has direct current evidence, deployed independent
QA accepts it, the scoped backup is remotely verified, and the final report
states what is enabled, what remains unsupported and where the evidence lives.
Only then may the persistent goal be marked complete.

Current status: open.

## Checkpoint discipline

At every meaningful checkpoint:

1. Update `COORDINATOR_STATUS.md` with role/current sprint, gate status, lane
   ownership, persistent-goal reference, latest verified evidence, blockers
   and exact next action.
2. Save code/tests/reports incrementally without including mutable production
   data or credentials.
3. Reread the top restart-card section after any context reset.
4. Report progress as two values when useful: current-sprint completion and
   overall completion by roadmap acceptance gates.
5. Stop promptly if the user asks to pause; save `PAUSED_NOT_COMPLETE` and
   leave the persistent goal intact for later continuation.
