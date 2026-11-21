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

Current overall completion estimate: approximately 40% by acceptance gates.
This estimate changes only when a gate gains or loses verified evidence.

## Current operating priorities

The owner uses this as a single-operator system and adds companies rarely.
The next ordinary manually launched scrape may pick up a new or changed
Company. Immediate automatic dispatch on a spreadsheet edit is optional.
Prove that the pending Company is found once on that next run, with existing
jobs and decisions preserved. An advanced simultaneous-editor protocol is
outside this operating scope. Keep the safeguards that prevent lost events,
duplicate processing, accidental replacement, and unsafe replay.

The primary automation is automatic wrapper generation for a failed or
partial integration found during a scrape. For a supported source, save the
failure and partial evidence, then have the existing Python coordinator send
one bounded generation task to the Jetson without manual prompting. MuleLab
handles retrieval, validation, storage, and release. Use a fresh company-only
retry after the exact qualified release. Keep the single Jetson inference
lane and the existing release gates. Automation that speeds up the initial
Company intake must not delay the wrapper-generation path.

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
   it, and do not skip an open prerequisite because later code exists. Use
   the restart card's simplest-path rule. Add work only for an acceptance
   criterion or an observed failure. Record optional hardening for later.
7. Reconcile worker status before assigning work. Give each active lane explicit
   file/state ownership and prevent overlapping edits. Independent QA remains
   read-only and may not repair the candidate it judges.
8. Classify the previous turn as progress, verified wait or no progress. A
   status-only turn is not progress; a lock or note alone is not a live process.
   Take the next safe action whenever useful work remains.
9. Escalate when a decision is blocked on an unresolved architectural or
   release-safety question, or when an investigation repeats without a
   materially different test, hypothesis, or new evidence. Apply this rule
   during the sprint and immediately after a reset. Check the restart card and
   follow up with the existing higher-reasoning reviewer if one owns the
   question. Otherwise, directly send a review assignment to a ChatGPT reviewer
   explicitly configured for higher reasoning. Include the decision needed,
   the smallest reproducible failure, prior attempts, affected versions and
   paths, and the safety and acceptance requirements. Save the reviewer
   assignment, evidence, requested decision, and next action in the restart
   card before returning to independent work. Verify the recommendation and
   route any repair through independent QA before releasing. Keep one Jetson
   inference lane.
10. Record the active sprint, overall gate percentage, current-sprint percentage,
   latest evidence, blockers and next action in `COORDINATOR_STATUS.md` at the
   next meaningful checkpoint.
11. Never claim deployed, accepted, backed up or complete without current
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

Current status: deployed and independently accepted. The Nov. 20 Samtec pilot
collected 160 complete postings, saved 63 Job History and 63 full local Job
Evidence records, and independently verified all 63 writes and the original
Sheets acknowledgement. Terminal replay produced the same receipt with no
network activity. The historic cycle remains held. See
`F6_F7_SAMTEC_LIVE_PILOT_20261120.md` and
`F6_F7_SAMTEC_LIVE_INDEPENDENT_QA_20261120.md`.

## Sprint 4 — F1/F2 live event-to-retry chain and Milestones 2–3

Roadmap coverage: Milestones 2 and 3 plus remaining F1/F2 evidence.

Objective: turn a supported company add/source change into one scoped request,
and turn realistic scrape outcomes into the correct durable retry, hold or
repair action.

Required work and evidence:

1. Prove transactional/supported mutation outbox behavior plus reconciliation
   for external edits, bootstrap watermarking, durable acknowledgement and
   deduplication.
2. Verify detection on the next ordinary manually launched scrape, one
   logical outcome on rerun, and recovery from an interrupted handoff. A
   Company added during a scrape may wait for the next manual run.
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

Current status, November 20: the guarded installation passed independent
native checks. The Atomic Machines intake held after an unconfirmed external
append. Readback found no Company row or event. The guarded rollback restored
the original source, services and checkout paths, and the append claim
remains spent. A separate synthetic Sheets fixture reproduced the missing
worksheet-ID error and verified the corrected append with an atomic duplicate
marker. Independent QA rejected the direct append for a concurrent foreign
writer race. The genuine owner-created Freeform row passed remote-read-only
intake and a guarded live run fetched 80 postings, saved and published 16,
and queued the same 16 for first-pass review. Independent QA matched both
delivery receipts and verified all three checkout paths restored. The
ordinary next-manual-run intake proof remains open. The selected successor's no-publication
receipt and crash recovery passed the 198-test disposable regression.
See the restart card and `S4_SHEETS_APPEND_WIRE_DIAGNOSTIC_20261120.md`.

## Sprint 5 — Bounded repair, validation, release and scoped retry

Roadmap coverage: Milestones 4 and 5, including F5.

Objective: run one minimal automatic wrapper generation loop for a qualified
failed or partial integration. Start from real failure evidence and produce
the wrapper with the Jetson, then validate, release, make a fresh scoped retry,
and verify saved jobs without manual prompt copying.

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

Current status, November 21: Amphenol Aerospace's installed AcquireTM
adapter stopped after 25 of 39 advertised postings. The two bounded
free-form attempts ended held. Independent browser QA rejected the draft.
A fresh public same-click capture then verified the old 25 postings and
14 disjoint refreshed postings, with the unchanged total. The exact
typed diagnostic source passed independent QA. The Jetson then made one
valid evidence-backed choice. MuleLab generated the isolated candidate using
the frozen recipe. Independent live-capture QA accepted both complete
normal-dispatch runs with 39 jobs each, all descriptions and stable rereads.
A separate fixture exercised the existing ordinary event's qualified
failure settlement and one Jetson repair choice. The guarded fixture release
then queued one fresh company-only retry. The pre-captured 39-posting
inventory passed normal filtering and exact recovery, with 18 matching
stored and workbook rows and one terminal receipt bound to the actual
fixture release. Independent QA accepted the exact combined publication.
The staged recipe pilot also retained the accepted choice across a restart
and produced the identical live-tested wrapper with no second inference.
Independent host QA accepted one enrolled source-only trigger, and the
composed disposable run produced the expected wrapper automatically.
Genuine production ownership, deployment, release, retry, publication
and installed QA remain open. Read-only native verification found no
eligible owned origin while the protected historical cycle retains Amphenol.
Independent staged QA accepted the exact admission replay guard and terminal
receipt join. A disposable Amphenol replay produced one sender COMPLETE and
one receiver VALIDATED_COMPLETE. The staged release owner now calls the
measured installer and the fresh exact worker. Independent disposable
checks proved the guarded shell and captured Amphenol storage paths.
The staged enrolled coordinator now delivers the exact completed retry
through matching receipts. Independent replay recovered the same receipt
after a lost response without sending a second outcome. Native deployed
proof remains open.
A fresh official Amphenol scrape also exercised the normal disposable
pipeline in the same attempt. It returned 39 full jobs, kept 18 through
filtering and confirmed the same local/workbook records in one batch.
Replay made no further provider or workbook calls.
An independent isolated installation now verifies the guarded installer,
fresh measured worker, normal storage and coordinator enrollment on one
retry. A separate injected installed-verification failure held worker
admission, preserved the stores, and restored the previous source.
Independent review confirmed the current native release boundary. The
approved public adapter and the complete isolated install prove different
stages. Native acceptance requires one current application-owned failed
request bound to independent validation of the exact full candidate release.
[Native qualification boundary](S5_NATIVE_QUALIFICATION_BOUNDARY_20261121.md).
One real inference on the disposable host would use a separate host
reservation and recovery ledger. The production coordinator's existing
single-task pilot requires a current application-owned repair. Keep prior
real and simulated inference results under their original task identities.
[One-lane feasibility](S5_OWNED_LIVE_CHOICE_FEASIBILITY_20261121.md).
[Retry evidence and QA](S5_RETRY_ADMISSION_AND_TERMINAL_DELIVERY_20261121.md).
[Release continuation components](S5_EXACT_RELEASE_CONTINUATION_20261121.md).
[Measured owner evidence](S5_MEASURED_RELEASE_OWNER_JOIN_20261121.md).
[Enrolled retry receipt](S5_ENROLLED_RETRY_COORDINATOR_RECEIPT_20261121.md).
[Fresh combined public-source test](S5_AMPHENOL_PUBLIC_COMPOSED_PASS_20261121.md).
[Isolated installed same-attempt proof](S5_ISOLATED_INSTALLED_SAME_ATTEMPT_20261121.md).
[Current deployment scope](S5_S6_DEPLOYMENT_SCOPE_AND_ACCEPTANCE_20261121.md).
[Public witness](S5_AMPHENOL_PUBLIC_PAGINATION_WITNESS_20261121.md) ·
[Independent candidate live verdict](S5_AMPHENOL_RECIPE_LIVE_ACCEPT_20261121.md) ·
[Test-workbook result](S5_AMPHENOL_FIXTURE_WORKBOOK_PASS_20261121.md) ·
[Existing coordinator restart and wrapper result](S5_AMPHENOL_CHOICE_SCHEDULER_REHEARSAL_20261121.md) ·
[Host-trigger rehearsal](S5_AMPHENOL_HOST_TRIGGER_REHEARSAL_20261121.md).

The next bounded case is `COMP-0490` Amphenol Aerospace, exact AcquireTM
board and independently observed delayed page-two membership. The approved
test choice is the versioned membership-wait recipe. Unknown outcomes,
different employers or boards, unavailable public evidence, access blocks,
and unvalidated variants stay held in this experiment. The Jetson supplies
only the finite evidence-backed choice. The candidate keeps the original
scope, full-description, total, unique-ID, and stable-reread gates. This
case does not expand the supported production family or enable release.

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

Current status: open. The maintained 103-test offline baseline and a
follow-up 114-test composed run passed on the staged coordinator and
exact owner reader. The final installed version and the sequential
deployed pilot remain open.
A separate 79-test staged fix and independent QA cover a low-disk hold
of the selected pilot. The enrolled host replay also preserved the
paused task after space recovered.
Two fresh-process staged QA checks proved planned shutdown with a late
counted reply and no new candidate, and a visibly exhausted task that
remained held across restart while a distinct owned task started with
fresh counters.
An independent staged test changed the Company source after exact enqueue.
A fresh measured bootstrap launched the worker once. It held the stale
request before admission, provider fetching or publication, preserving the
request, the release records and all three logical stores. The staged local
retry status now identifies that hold and reports confirmation only when
both stores have matching evidence. The corrected reader passed physical
no-write checks with idle databases and pending journals.
[Measured source hold](S6_MEASURED_QUEUED_SOURCE_DRIFT_QA_20261121.md).
[Exact retry status](S6_EXACT_RETRY_OPERATOR_STATUS_20261121.md).
The composed two-Company fixture proved that a provider hold is saved
without a repair, and that the next eligible Company proceeds to exact
local and workbook-fixture storage. Live sequential acceptance with
three qualified completion structures remains open.
For the frozen Allen Control Systems case, current official employer
evidence identifies Ashby as the successor to the old Greenhouse
configuration. Normal dispatch returned 19 listed postings with full
descriptions and a stable reread. Treat the Ashby migration as the reviewed
candidate structure; production admission and end-to-end acceptance remain
open. Independent staged QA accepted the one-entry source correction.
The proposed Draper third structure remains held. Its current official
link still identifies the exact Workday tenant. The bounded public reader
was redirected to Workday's outage page, leaving inventory and description
qualification open.
The independently reviewed November 21 amendment adds Amphenol AcquireTM
as the third named completion case alongside Forterra Rippling and Allen
Ashby. It fixes the sequence and keeps the original external holds and PDW
regression. Prior runs do not contribute deployed sequential completion.
[Sequential matrix amendment](S6_SEQUENTIAL_MATRIX_AMENDMENT_20261121.md).
[Allen source qualification](S6_ALLEN_ASHBY_PUBLIC_QUALIFICATION_20261121.md).
[Allen source QA](S6_ALLEN_ASHBY_SOURCE_INDEPENDENT_20261121.md).
[Reliability baseline](S6_COORDINATOR_RELIABILITY_BASELINE_20261121.md).
[Disk pressure and pilot hold](S6_DISK_PRESSURE_PILOT_HOLD_20261121.md).
[Provider hold and continued progress](S6_SEQUENTIAL_PROVIDER_HOLD_REHEARSAL_20261121.md).
[Planned shutdown QA](S6_OWNED_CHOICE_SHUTDOWN_QA_20261121.md).
[Budget restart QA](S6_OWNED_REPAIR_BUDGET_RESTART_QA_20261121.md).
[Current Draper source hold](S6_DRAPER_CURRENT_AVAILABILITY_HOLD_20261121.md).

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
