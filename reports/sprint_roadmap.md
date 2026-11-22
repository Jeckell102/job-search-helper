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
- Preserve the archived historical cycle `CYC-B639C6D864EC` and its unresolved
  Saronic provenance conflict. The owner retired it from active admission
  on November 21. Do not auto-reconcile, resume, delete, or overwrite it.
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

November 21 at 15:47 Eastern: independent QA reproduced the actual next
manual-start routing gap, then accepted a private source fix that uses
the inherited scraper lease and existing exact Company-event operations.
Seven checks passed, including real private verified-zero settlement.
The authorized live routing gate remains open. [Source and evidence](S4_NEXT_MANUAL_START_ROUTING_GAP_20261121.md).

November 21 at 15:57 Eastern: independent offline QA accepted the busy
cycle and next manual run, interrupted freeze publication recovery, and
lost workbook response recovery without a second fetch or write. The
changed output identifies the preexisting exact request and cycle.
[Recovery stage](S4_NEXT_MANUAL_START_RECOVERY_STAGE_20261121.md).

## Sprint 5 — Bounded repair, validation, release and scoped retry

Roadmap coverage: Milestones 4 and 5, including F5.

November 21 at 16:39 Eastern: the two-file builder is deployed and passed
independent native QA. A fresh real Amphenol-only pagination failure
produced one owned Jetson choice and a complete automatic candidate build.
The temporary enrollment was withdrawn. Current public qualification,
guarded release, fresh local save and live workbook confirmation remain
open. [Live build evidence](S5_AMPHENOL_FRESH_AUTOMATIC_BUILD_LIVE_20261121.md).

At 16:51 Eastern the exact current candidate and one-file proposal were
assembled. The independent public run stopped on its first 429 after 32
of 39 details. No contact before 17:48:55 Eastern and no public acceptance
credit. [Provider hold](S5_AMPHENOL_FRESH_PUBLIC_HOLD_20261121.md).

At 17:13 Eastern, independent offline QA accepted the separate inherited
Retry-After correction. Long 429 and 503 fixtures held without a second
detail call or whole-Company attempt. The actual generated wrapper and
its still-held live qualification retain their original identities.
[Transport source stage](S5_AMPHENOL_RETRY_AFTER_STAGE_20261121.md).

At 17:22 Eastern, independent offline QA accepted explicit recovery of
the same qualified COMPLETE activation without selecting installation.
This closes the staged native/application join for the cut before retry
settlement. It supplies no live source, job, or workbook acceptance.
[Recovery evidence](S5_AMPHENOL_COMPLETE_ACTIVATION_RESUME_STAGE_20261121.md).

At 18:22 Eastern, a single owner-requested retry after the prior cooldown
stopped on a fresh HTTP 429 after 35 of 39 details. The new provider floor
is 19:21:55 Eastern. Live qualification and release remain held.
[Retry evidence](S5_AMPHENOL_POST_COOLDOWN_PUBLIC_HOLD_20261121.md).

At 18:35 Eastern, independent offline QA accepted the paced public
evaluator, with a twelve-second minimum gap and the original coverage
checks. A single user-requested run is waiting out the provider cooldown.
[Paced preparation](S5_AMPHENOL_PACED_PREPARATION_20261121.md).

At 19:30 Eastern, the single paced public run passed with 39 of 39 full
descriptions, stable listing membership, and no 429. Carry the same pacing
into the exact production runtime. Installation, the scoped retry with
storage and workbook confirmation, and independent deployed QA are open.
[Verified paced outcome](S5_AMPHENOL_PACED_PUBLIC_RESULT_20261121.md).

At 19:40 Eastern independent offline QA accepted the exact composed
production adapter after 18 tests. The one-file proposal
`REL-f509ed362bf8781ea8840adc` preserves the owned build and separately
binds the reviewed pacing change. Package inspection passed. Independent
package/observer verification and exact public production-behavior
qualification remain open.
[Production adapter offline QA](S5_AMPHENOL_PRODUCTION_PACING_INDEPENDENT_QA_20261121.md).

At 19:57 Eastern the actual staged production candidate independently passed
one observation-only public check. It returned 39 complete descriptions,
stable two-page listings, and verified its own twelve-second spacing.
The exact native readiness check is waiting for the current administrator
observer. Installation, the scoped live retry and deployed independent QA
remain open. This Sprint 5 run earns no Sprint 6 sequential credit.
[Production live qualification](S5_AMPHENOL_PRODUCTION_PACED_LIVE_QUALIFICATION_20261121.md).

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
The independently checked existing native routes cannot complete a fresh
qualified release while the historical cycle owns unfinished work.
Selected complete-inventory publication and disjoint event origin remain
distinct supported operations. A non-destructive supported disposition of
the old cycle is required to clear the fresh-release gate.
[Existing native route verdict](S5_EXISTING_NATIVE_RELEASE_ROUTE_INDEPENDENT_20261121.md).
Guarded production-data preflight identified one exact Saronic Job History
source-version mismatch in retained operation 194. All nine expected-before
values match locally and the proposed version is independently bound to its
retained inventory and operation 195. The installed late-control path holds
on that transition and does not supply terminal recovery. Leave the
intentional retained cycle protected until a separate reviewed disposition
can meet the actual recovery and publication gates.
[Exact retained-work triage](S5_RETAINED_SOURCE_TRANSITION_TRIAGE_20261121.md).
A signed staged admission now archives the old plan, inventory and cursor.
The existing exact local application verified the two selected operations
on a disposable copy of the real rows and preserved all seven manual
review fields on replay. Independent QA accepted that bounded result
after correction of a raw-text binding failure. The live guarded apply,
publication, terminal disposition and production wrapper pilot remain open.
[Recovery checkpoint](S5_LATE_CONTROL_SCOPED_CHECKPOINT_20261121.md).
The owner then selected archive-first retirement of only the unfinished
historical cycle. Preserve the original checkpoint, 45 saved inventories,
six plans and all confirmed publication history. Future still-active jobs
can be fetched through an independently owned run. Retirement uses a
distinct local control and no publication, cleanup, or Sheet changes. It
must keep old resume and publication unavailable while leaving unrelated
unfinished work and the release gates in force.
[Archive and ownership plan](S5_RETIREMENT_OWNERSHIP_MAP_20261121.md).
The 44-file production package is installed and independently verified.
The exact old cycle was retired against its independently verified archive.
All three alternate checkout routes were restored, and independently checked
with the original terminal installer receipt. The local admission view is
clear of unfinished cycles. No genuine Amphenol Company event or other pending
request exists. An ordinary operator queue request alone cannot create repair
authority. The live wrapper pilot, exact retry publication and its QA remain
open. [Native release evidence](S5_RETIREMENT_NATIVE_RELEASE_20261121.md).
The actual corrected staged host reached the real installer and refused an
unfinished legacy cycle before launch or any release, queue, workbook or
source effect. Its release status now explains this hold. An independently
reviewed versioned-worker design could preserve the old runtime for a
genuine disjoint Company later. The native audit found no pending event and
all current named cases overlap. The user was asked which scope to prepare.
[Native pilot directions](S5_NATIVE_PILOT_DIRECTION_20261121.md)
· [Exact operator hold QA](S6_NATIVE_RELEASE_HOLD_REASON_INDEPENDENT_20261121.md).
The complete current source-only candidate now has an exact 38-file
inventory and a reconstructed disposable overlay with 71 passing tests.
Independent QA confirmed the existing maintenance parser cannot admit
it. The staged newer policy preserves the old manifest rules and limits
wrapper changes to the exact 38-file manifest. The unchanged receipt
bridge stays in the controller protection witness. Independent QA
verified all 38 exact staged after-images and rollback in an isolated
installer transaction with synthetic before-images. Native controller,
host witness and service acceptance remain pending. Passive native
readback matched all 47 paths and restored routes of the installed
Freeform predecessor. The original successor required a rollback
receipt. The staged consolidated-only repair independently passed
source review. Its new handoff requires the existing installed receipt,
exact approved protected continuity and the same physical guard.
Native predecessor approval and Company eligibility remain separate.
The stable protected-state read reproduced seven changes from the original
Freeform witness. The independently reviewed successor now binds
historical and current pins separately. The 38 reviewed after-images and
unchanged checker code are staged and the existing launcher probes passed
on a disposable copy. A fresh live exclusion and eligible Company request
remain prerequisites.
[Native handoff readiness](S5_S6_NATIVE_HANDOFF_READINESS_20261121.md)
· [Release package checkpoint](S5_S6_RELEASE_PACKAGE_CHECKPOINT_20261121.md).
[Consolidated deployment preparation](S5_S6_CONSOLIDATED_DEPLOYMENT_PREPARATION_20261121.md)
· [Independent policy QA](S5_S6_MAINTENANCE_SOURCE_POLICY_INDEPENDENT_QA_20261121.md).
The staged Python host now has a default-off route from its completed
owned recipe build and exact independent approval to the guarded installer.
The focused callback coverage passed. The separately checked installed
runtime reader persisted its full measurements within the real disposable
release. Independent QA ran the corrected host through one measured
install and retry with 18 matching fixture jobs and terminal replay.
The initial held-retry replay bug was independently reproduced. A fresh
corrected host held its incomplete inventory without a second worker.
Production activation and workbook confirmation remain open.
[Owned build reader](S5_OWNED_BUILD_RELEASE_READER_20261121.md)
· [Installed runtime QA](S5_INSTALLED_RECIPE_READBACK_INDEPENDENT_20261121.md)
· [Host release QA](S5_OWNED_HOST_RELEASE_INDEPENDENT_QA_20261121.md).
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

Current checkpoint, November 21 at 12:45 Eastern. The native one-time
Amphenol trigger and one Jetson choice are verified. The MuleLab coordinator
source-selection correction is installed and independently verified. The
recovered wrapper completed one current run at 39 and two subsequent
provider-blocked runs stopped at 35 and 37. The window ended held. Release
preflight for the retained operator build passed independently and the actual
proposal stayed held at the missing qualified approval. A separate Forterra
ordinary composition passed independently in disposable fixtures. Its real
issuer and separate PDW regression remain open.
[Current provider decision](S5_AMPHENOL_VALIDATION_FINAL_WINDOW_HOLD_20261121.md)
· [Retained preflight QA](S5_AMPHENOL_RETAINED_RELEASE_INDEPENDENT_QA_20261121.md)
· [Forterra composition QA](S5_FORTERRA_ORDINARY_COMPOSITION_INDEPENDENT_QA_20261121.md).

At 13:01, a narrow staged operator completion connector independently
passed eight focused checks, including canonical operator request pin,
unchanged event path and physical qualification owner, and original request
receipt after Company/last-request advancement. No native qualification,
installation, retry receipt or new inference. Current-source measured
worker and combined disposable terminal proof are separate gates.
[Operator terminal staging](S5_AMPHENOL_OPERATOR_RETRY_TERMINAL_STAGED_20261121.md).

At 13:11, the exact Amphenol operator fixture completed the guarded
release, one measured retry, one matching local and workbook fixture job,
and one Python coordinator VALIDATED_COMPLETE event. Independent QA checked
the durable paired receipts and absence of duplicate fetch/write, tasks,
inference and unrelated fixture changes. Live candidate approval and native
execution remain held on provider evidence.
[Combined rehearsal](S5_AMPHENOL_OPERATOR_COMBINED_DISPOSABLE_20261121.md)
· [Independent readback](S5_AMPHENOL_OPERATOR_COMBINED_DISPOSABLE_INDEPENDENT_READBACK_20261121.json).

A distinct one-shot live read at 13:15 returned the same initial 39-job
listing and zero observed descriptions. Independent QA ended it held.
The original current scorecard is one complete observation and three
incomplete confirmations, with 35, 37 and 0 details. The operator
activation-cut branch independently recovered the same disposable
installed release and retry from no intent or queue, preserved the
adapter file and activation receipt, and confirmed one fixture job.
A competing rollback held under the existing scraper lock. The native
admitted one-shot entry, live approval and scoped retry are open.
[Fresh hold](S5_AMPHENOL_FRESH_WINDOW_INDEPENDENT_HOLD_20261121.md)
· [Recovery QA](S5_AMPHENOL_OPERATOR_ACTIVATION_CUT_INDEPENDENT_QA_20261121.md).

Independent QA accepted the corrected one-shot operator entry after
11 focused checks and two durable test-copy readbacks. Default-off
holds; controls precede writable movement; and the terminal-only
existing Store attachment skips schema initialization. Both first
activation and interrupted recovery produced one confirmed fixture job
and one stored coordinator completion, with replay unchanged. Live
Amphenol qualification and the actual maintenance-bound first run
remain required. [One-shot QA](S5_AMPHENOL_OPERATOR_ONE_SHOT_INDEPENDENT_QA_20261121.md).

The bounded maintenance wrapper reused the existing Systemd condition
and restoration logic in a private end-to-end fixture. Independent QA
verified one fixture job/receipt and two restored service windows.
Wrong application configuration is rejected before service changes;
failed restoration proof reapplies the fence. The six-file planned
tool source scope has exact before/after measurements. Fresh actual
native admission and complete Amphenol public details remain open.
[Quiet window QA](S5_AMPHENOL_OPERATOR_QUIET_WINDOW_INDEPENDENT_QA_20261121.md)
· [Staged source scope](S5_AMPHENOL_OPERATOR_NATIVE_SOURCE_SCOPE_HELD_20261121.json).

At 14:28 Eastern, independent QA had accepted the corrected six-file
source scope for the historical package. A new bounded public validation
returned 30 of 39 details before actual HTTP 429. The cohort is unqualified.
No Amphenol contact before 15:22:24 Eastern. Fresh source evidence also
showed that ordinary deduplication would leave the same-revision outcome
under the already-spent repair owner. Stage one explicitly enrolled
successor through existing paused-task and single-pilot controls. Keep the
predecessor and receipts immutable. Prove the first-429 stop offline and
independently verify the composed route before any fresh native request.
[Source QA](S5_AMPHENOL_SIX_TOOL_CORRECTED_QA_20261121.md)
· [Public hold](S5_AMPHENOL_PUBLIC_429_HOLD_20261121.md)
· [Fresh route](S5_AMPHENOL_FRESH_ROUTE_INDEPENDENT_20261121.md).

At 14:36 Eastern, independent boundary and composed offline QA accepted
the fresh owner and confirmed exactly one pilot in the success case.
The first-429 observer passed separate offline QA. The two tool files
are staged pending the guarded native tool update. The previous -03
controller's terminal check still requires the old host bytes and cannot
authorize the new scope unchanged. [Fresh build stage](S5_AMPHENOL_FRESH_BUILD_STAGE_20261121.md).

At 14:47 Eastern, independent QA accepted the corrected two-file updater
and the fresh -04-aware predecessor guard in offline checks. The live
native process-exclusion and restart proof remain open. No change was
applied to production. [Maintenance stage](S5_AMPHENOL_TWO_TOOL_NATIVE_STAGE_20261121.md).

At 14:59 Eastern the exact launcher passed independent source QA. Native
read-only preflight reached the fresh administrator observation boundary
after verifying the previous transaction and current source layout. The
administrator observer must confirm the two inaccessible system helpers
before the two-file tool change. A separate private combination preserves
the new successor Store behavior while supporting the application release's
existing-only coordinator entry. No provider call or native change began.
[Preflight](S5_AMPHENOL_NATIVE_LAUNCHER_PREFLIGHT_20261121.md).

At 15:07 Eastern independent offline QA accepted the fresh completed-build
reader and shared scoped release selector after focused repairs. Tool-only
installation still waits for actual administrator observation. The live
application release must qualify the exact freshly produced candidate
and verify its real company-only retry and workbook receipts.
[Fresh release source stage](S5_AMPHENOL_FRESH_RELEASE_SOURCE_STAGE_20261121.md).

At 15:17 Eastern the fresh operator input and temporary environment
helpers passed focused independent tests. Native installation still waits
for the administrator observation. Fresh build output is required to
restamp candidate and qualification pins. [Enrollment preparation](S5_AMPHENOL_FRESH_ENROLLMENT_PREPARATION_20261121.md).

At 15:27 Eastern, independent QA accepted the exact native fresh-pilot
armer and its bounded listener-read repair. The seven planned application
tool images passed the refreshed scope and focused fixtures. Local intake
returned zero alternate requests. The actual native builder update still
waits for administrator observation, and the application candidate remains
pending an authentic fresh build. [Native stage](S5_AMPHENOL_NATIVE_ARMER_STAGE_20261121.md).

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
The first activation step has a staged local intake preview through the
existing `storage intake-observe` command. Independent shell QA verified
latest-revision proposals, stale and withdrawn holds, and a busy result
while committed SQLite changes await checkpoint. The preview acknowledged
no event and created no request. The staged command read the native Jobs
store in place under an immutable guard and reported zero pending events.
The installed normal shell/runner was later independently verified
with zero pending events and zero audited write, network, mutation or
subprocess attempts. Seven source pins and all scoped file content
matched. Two SQLite sidecar timestamps changed with matching contents.
This accepts the installed observe-only activation subgate.
[Independent observation QA](S6_INTAKE_OBSERVATION_INDEPENDENT_QA_20261121.md)
· [Installed readback](S6_INSTALLED_OBSERVE_ONLY_INDEPENDENT_20261121.md).
The staged separate scrape-launch control allows intake to keep a valid
request queued while new launches are paused. Independent shell QA verified
the exact ordinary admission once enabled, preserved publication handoff
and checked the temporary and retained launch reservations. Its commands
change only the intake dispatcher journal.
[Separate launch control](S6_INTAKE_SCRAPE_CONTROL_20261121.md).
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

The next supported separate live named case still requires a real
eligible Company event and exact ordinary fetch/publish. The installed
observation was empty. No tested isolation route exists for normal
generic queue/start without an event. The first-company compact
bootstrap is restricted to absent rows and cannot safely update Allen.
[Current named origin review](S6_NEXT_GENUINE_NAMED_ORIGIN_REVIEW_20261121.md).

## Sprint 7 — Final acceptance, deployed independent QA and backup

The November 21 effective reconciliation covers all six milestones,
F1–F8 and the seven demonstrations. The operator guide is saved, and
the remaining gates still require direct live evidence.
[Effective acceptance](S7_EFFECTIVE_ACCEPTANCE_20261121.md)
· [Operator guide](INTEGRATION_AUTOMATION_OPERATOR_RUNBOOK.md).

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
