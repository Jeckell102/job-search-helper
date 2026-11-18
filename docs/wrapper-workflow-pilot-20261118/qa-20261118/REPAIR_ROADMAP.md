# Wrapper campaign repair roadmap

Updated: 2026-11-18

## Control rules

- Production remains paused: queue OFF, autopilot OFF, pilot unset, and no inference.
- Repair one finding group at a time. Do not begin the next group until the current group's focused tests, full host suite, migration dry run, and roadmap review pass.
- Staged source is the implementation source. Deployment requires a database backup, rollback copies, a stopped service, a post-deployment database integrity check, and confirmation that all controls remain OFF.
- Live scraper validation, production wrapper installation, and GitHub delivery remain separate operator gates.
- The seven groups below are the complete QA repair queue. A checked item means its acceptance evidence has been reviewed, not merely that code was written.

## Ordered checklist

### 1. Campaign membership, pause dispositions, and claim isolation — ACCEPTED IN STAGING

- [x] Add explicit campaign membership to imported tasks.
- [x] Separate `HELD_FOR_CAMPAIGN`, `SELECTED`, `USER_PAUSED`, and `EXCLUDED` dispositions.
- [x] Make campaign activation select only `HELD_FOR_CAMPAIGN` members of the active campaign.
- [x] Make campaign claiming claim only the selected campaign task; never use the generic queue claim in campaign mode.
- [x] Preserve a global campaign stop without converting it into an individual user pause or advancing to another company.
- [x] Add a compatibility migration for the exact existing 2026-11-18 backlog.
- [x] Add adversarial tests for explicit pause, exclusion, unrelated queued tasks, restart, and legacy migration.
- [x] Focused tests pass: 16/16 independent campaign-isolation tests.
- [x] Full host suite passes: 161/161 tests.
- [x] Migration dry run accounts for every intended existing task and changes nothing.
- [x] Roadmap review approves group 1 before group 2 starts.

Acceptance criteria:

1. An individual `pause` or `exclude` survives campaign start, service restart, and completion of other tasks. It is never cleared by automatic selection.
2. A generic PAUSED task, an unrelated direct-start QUEUED task, and a task from another campaign cannot be selected or claimed by the active campaign.
3. At most one campaign task has disposition `SELECTED` and at most one task globally is RUNNING or PAUSING.
4. Campaign stop leaves the current selected task resumable by that campaign and starts no additional action.
5. Migration is fail-closed and idempotent. It reports exact matched, held, user-paused, excluded, skipped, and conflicting task IDs.
6. Production controls remain OFF after migration and deployment.

### 2. Atomic pilot, campaign, queue, and activation transitions — ACCEPTED IN STAGING

- [x] Serialize pilot start/stop, campaign start/stop, generic queue control, and task activation in SQLite transactions.
- [x] Validate a pilot completely before publishing the pilot slot.
- [x] Prevent pilot and campaign modes from being enabled together under concurrent requests.
- [x] Add the recorded race, stale pilot slot, and concurrent control tests.
- [x] Focused and full suites pass; roadmap review approves group 2.

Acceptance criteria:

1. Every concurrent interleaving ends in exactly one allowed operating mode.
2. A failed pilot start leaves pilot, queue, campaign, and task state unchanged.
3. Restart preserves the last committed mode and never guesses an incomplete transition.

### Group 2 minimal design

Use SQLite `BEGIN IMMEDIATE` as the cross-thread and cross-process serialization boundary. The coordinator's Python lock may reduce contention, but correctness must not depend on it. Every control transition must read, validate, and write the settings and affected task state in one database transaction.

The only committed operating modes are:

- stopped: queue false, campaign false, pilot null;
- generic queue: queue true, campaign false, pilot null;
- campaign: queue true, campaign true with one active campaign ID, pilot null;
- pilot: queue false, campaign false, pilot set to exactly one resumable task.

No transition may publish a mixed mode. Keep the legacy autopilot flag synchronized inside the same transaction until it is removed by a later compatibility change.

Pilot startup has two phases because workspace preparation must not hold a database write lock:

1. Read the candidate and perform reversible/idempotent workspace preparation. Compute the resulting manifest and requirements, and retain the candidate's expected task-state digest or revision.
2. In one immediate transaction, reread the task and every relevant control. Require the expected task revision, queue and campaign stopped, pilot null, no other RUNNING/QUEUED/PAUSING assignment, isolated workspace, no unfinished intent, resumable status, valid authorization, remaining session/call/token/time budget, and unchanged prepared manifest inputs. Only then set the pilot slot and publish that exact task as QUEUED with its resume fields.

If preparation or final validation fails, pilot, queue, campaign, and task state remain unchanged. A prepared but unpublished workspace is inert and may be reused or removed later; it does not confer scheduling ownership.

Pilot stop must clear the slot and mark its task to stop in one transaction. Campaign start/stop and queue resume/pause must use the same transactional mode state. Global queue pause wins at its commit boundary: it disables queue and campaign together, retains any selected campaign member, and causes the next action boundary to pause; it never publishes a pilot. Campaign and queue start must reject a non-null pilot from the transaction's current snapshot. Pilot start must reject an enabled queue or campaign from that same snapshot.

Required focused tests:

1. Barrier-controlled pilot-start versus campaign-start race: exactly one succeeds and the final mode matches the winner.
2. Pilot-start versus queue-resume race and two concurrent pilot starts: exactly one allowed owner, no mixed controls, and no second task activation.
3. Budget-exhausted, deadline-expired, gate-status, unfinished-receipt, non-isolated, or changed-during-preparation pilot candidate: startup fails with pilot null and byte-equivalent control/task state.
4. Failure injection after validation but before commit: the whole transition rolls back.
5. Pilot stop versus campaign/queue start: every final state is one of the allowed modes and the stopped pilot task retains the correct stop boundary.
6. Restart reads the exact last committed mode; no startup repair invents or activates a task.
7. Two store/coordinator instances satisfy the same invariants, proving the database transaction rather than the in-process lock provides safety.

Group 2 does not certify the separate inference-dispatch reservation race. That remains Group 5, but Group 2 must leave one transactional API that Group 5 can reuse immediately before model dispatch.

### Group 2 acceptance checklist

- [x] One store-level transaction owns complete pilot validation and publication; command code does not publish the pilot slot separately.
- [x] Pilot publication and the exact task's QUEUED/resume state commit together or both roll back.
- [x] Pilot stop clears the slot and publishes the task stop boundary atomically.
- [x] Campaign start/stop and queue resume/pause use the same database-serialized mode invariants.
- [x] No correctness claim relies only on the coordinator instance's Python `control_lock`.
- [x] Failed pilot preparation or validation leaves control and task rows unchanged and consumes no task budget.
- [x] Concurrent pilot/campaign, pilot/queue, and pilot/pilot tests prove exactly one allowed result without mixed controls.
- [x] Global pause precedence retains an existing selected campaign member and starts no replacement.
- [x] Restart and injected rollback tests prove only committed state is visible.
- [x] Focused verifier passes against two independent store/coordinator instances.
- [x] Full host suite passes with no regression to accepted Group 1 behavior.
- [x] Roadmap review approves Group 2 before Group 3 begins.

Current gate status: **ACCEPTED IN STAGING**. The terminal-state bypass was corrected. Public pause preserves `AWAITING_LIVE_VALIDATION`, `REVIEW_COMPLETE_LIVE_NOT_VALIDATED`, and `LIVE_VALIDATED`; resume and pilot-start reject them; exclude/include preserves the terminal status; `CAMPAIGN_FINISHED` is also treated as a gate. Legacy resume and control setters delegate to the canonical guarded transitions. Independent review passed all 12 transition tests, including the prior `LIVE_VALIDATED -> PAUSED -> QUEUED` reproduction as a command-level rejection. The implementation owner's final focused suite passed 70/70 and the full host suite passed 174/174 on the frozen corrected source. Production and inference remained untouched.

Final-QA reproduction note: the original `check_scheduler.py` race harness instrumented `set_pilot_task`. The corrected design replaces that multi-step publication path with one atomic transition, so final QA must reproduce the same adversarial pilot-versus-campaign outcome at the new transaction boundary. It must coordinate concurrent public commands or an explicit transaction test seam and assert the committed mode/task invariants. Failure to reach the obsolete hook, a harness timeout, or absence of the old method call is not a pass. Preserve the old result as historical evidence, and save the equivalent new reproduction with its exact final settings and task state.

### 3. Canonical identity and duplicate-company prevention — ACCEPTED IN STAGING

- [x] Make structured company identity authoritative for assignment text, evidence requirements, worker packets, and reporting.
- [x] Validate the identity again at activation and bind it with a stable digest.
- [x] Enforce unique campaign/company membership and explicit retry lineage.
- [x] Reject changed-batch duplicates and partial or conflicting backfill records atomically.
- [x] Add contradictory identity, duplicate batch, retry lineage, and migration tests.
- [x] Focused and full suites pass; roadmap review approves group 3.

Acceptance criteria:

1. Company ID, company name, configured URL, tests, and source targets cannot disagree across task state, evidence, worker packet, or report.
2. One campaign cannot contain two active assignments for one company ID.
3. A retry names its predecessor and cannot silently reset or replace historical evidence.

### Group 3 minimal design

Define one canonical integration identity object with exactly `company_id`, `company`, `configured_url`, `tests`, and `source_targets`. Normalize and validate it once at assignment/import, serialize it as sorted compact JSON, and store its SHA-256 as `integration_identity_digest`. The digest and structured identity are immutable task fields. Evidence requirements, editable targets, worker packets, status output, and activation checks must read these fields directly.

Do not let a free-form objective redefine the company. Retain the original objective unchanged as audited import/migration history, and add a separate immutable `worker_assignment` generated by one host-owned template from the canonical identity. Worker packets and evidence discovery use `worker_assignment`, the structured identity, and its digest; they never use the original objective as identity authority. Company ID, name, URL, tests, and source targets mentioned in executable instructions therefore come from one source. Activation recomputes the identity and worker-assignment digests and rejects any mismatch before queueing or inference.

Enforce campaign/company uniqueness in SQLite rather than by scanning task JSON. Add a campaign-assignment registry with a unique `(campaign_id, company_id)` key, the current task ID, identity digest, and lineage metadata. Batch import and registry insertion occur in one immediate transaction:

- an exact replay with the same identity digest and import provenance returns the existing task ID;
- the same campaign/company with a changed identity or changed batch provenance is an atomic conflict with zero new tasks;
- concurrent imports cannot create two assignments;
- a different campaign may reference the company only as an explicitly separate campaign.

A retry is a distinct explicit transition, not a batch re-import. It requires `retry_of`, verifies the predecessor belongs to the same campaign/company and is no longer active, preserves the predecessor and its receipts, and records a new run/task ID in lineage. Only the registry's current pointer may advance, atomically, to the reviewed retry. A retry cannot reset or overwrite prior budgets or evidence.

Compatibility backfill must consume the reviewed campaign manifest. It may attach the identity digest and registry row only when objective mapping, full identity, tests, source targets, campaign membership, and manifest digest all agree exactly. Missing, partial, duplicate, or conflicting metadata aborts the entire backfill. Repeating the same backfill is a no-op; a changed identity requires a separate reviewed correction path.

Required focused tests:

1. Contradictory free-form company text versus structured identity is rejected or replaced by the exact host-generated assignment before task creation.
2. Worker packet, evidence requirements, edit targets, status, and activation all expose the same identity and digest.
3. Exact batch replay reuses IDs; changed-batch duplicate and partial/conflicting backfill abort atomically.
4. Two concurrent imports for one campaign/company create exactly one registry assignment and one task.
5. Activation rejects post-import mutation of any identity field, test, source target, assignment text, or digest.
6. Explicit retry preserves predecessor receipts/budgets, records `retry_of`, and cannot coexist as a second active assignment.
7. Existing 102-member migration gains exact identity registry rows on a disposable copy with a no-op second run and controls remaining off.

Current gate status: **ACCEPTED IN STAGING**. `commit_activation()` now validates the complete bound identity after applying activation fields and before publishing either task state or pilot controls; the replacement-evidence regression proves rollback. Independent review passed all 15 identity/backfill/registry tests, including concurrency, immutable packet identity, changed-batch conflicts, retry lineage, and activation mutation. The frozen full host suite passed 189/189. The disposable production-snapshot rehearsal bound exactly 102 campaign identities and registry rows, changed nothing during dry run, changed zero rows on its second apply with byte-identical post-apply database hash, preserved prior status/budget/history and nonmembers, retained controls OFF, and finished with `quick_check=ok`. Production was not modified.

### 4. Edit scope and independent acceptance assertions — ACCEPTED IN STAGING

- [x] Enforce the assigned editable file set at the host tool boundary.
- [x] Add an explicit reviewed scope-expansion transition.
- [x] Protect host-owned acceptance assertions from worker edits.
- [x] Detect weakened or removed required tests before offline completion.
- [x] Add unassigned-edit, weakened-test, scope-expansion, and verification tests.
- [x] Focused and full suites pass; roadmap review approves group 4.

Acceptance criteria:

1. A worker cannot modify a file outside the current approved scope.
2. Editable regression tests are never the sole proof of correctness.
3. Offline-ready requires both editable regression tests and immutable host-owned acceptance checks.

### Group 4 minimal design

Gate status (2026-11-18): **ACCEPTED IN STAGING.** The host tool now rejects create/edit when mutation authority is absent; an isolated `/tmp` reproduction confirmed both operations fail and leave the filesystem unchanged. The authenticated manual bridge grants only the exact requested path in the shared checkout and refuses inherited task workspaces, while coordinator dispatch installs the persisted task scope. Frozen-acceptance receipts bind source manifest, scope digest/version, and bundle digest, and promotion rechecks those bindings plus the complete editable manifest and test/config inventory. A deterministic post-acceptance source mutation now ends `PAUSED_FILES_CHANGED`. Independent verification passed 13/13, the three roadmap blocker regressions passed independently, and the corrected full host suite passed 214/214. The reviewed exact-102 baseline migration and real systemd/Landlock/seccomp frozen-acceptance rehearsal also passed. Production remains unchanged and paused.

Persist an exact per-task write allowlist and digest. Its initial paths are the canonical integration `source_targets` and editable `tests`, plus any exact output document path declared by the reviewed campaign manifest. Host `code_edit` and `code_create` must receive the active task scope and reject every normalized path not exactly listed before opening or creating it. Directory-wide grants and model-supplied paths do not expand scope. Existing path traversal, symlink, hardlink, hidden-file, size, and single-edit guards remain additional checks.

Scope expansion is a dedicated operator transition, never a worker tool. It requires the task ID, exact added paths, reason, expected task/scope digest, a paused safe boundary, no unfinished receipt, and no active claim. In one transaction it appends an audit record, increments `edit_scope_version`, stores the new digest, and invalidates affected reads/baseline verification. Company identity, canonical tests, and canonical source targets remain immutable; a change to those fields requires an explicit reviewed retry/new assignment. Auxiliary source or documentation paths may be added to the separate write scope without redefining company identity. A worker may checkpoint a scope request, but Python cannot approve it automatically.

Before any worker edit, build a host-owned acceptance bundle outside the editable workspace. Copy the original assigned tests and every local fixture/config input they consume, store a hash manifest in task state, and expose the bundle read-only to verification. At acceptance time, run those frozen original tests in a disposable sandbox against the task's edited source tree. The test path and fixtures come from the immutable bundle; the import path points to edited workspace source. Verify bundle hashes before and after execution and save the exact command, source manifest, bundle digest, and result receipt.

Run current editable regression tests separately. Offline-ready requires both current tests and the immutable acceptance bundle to pass. If an assigned test did not exist at baseline or its frozen assertion cannot represent the reviewed requirement, the task remains blocked until an operator supplies or revises a host-owned acceptance check through a separate audited transition. A worker-created or worker-edited test is never the sole acceptance proof. This design relies on the existing OS sandbox for arbitrary test-process containment; Group 4's contract is exact host-tool writes and independent assertions, not a new hostile-code sandbox.

Required focused tests:

1. Edits and creates succeed for every exact assigned path and fail without filesystem change for an unassigned source, test, document, traversal, symlink, or hardlink path.
2. A worker scope request does not grant access; only the explicit operator transition expands scope, and concurrent/stale expansion fails by digest.
3. Scope expansion is rejected while running, claimed, or carrying an unfinished receipt and records a durable reason/version/history when accepted.
4. Weakening the current test to `pass` cannot reach offline-ready when the frozen original assertion fails against the edited source.
5. A correct edited source passes both the frozen original tests and current editable tests; receipts prove the frozen test path and edited source import path.
6. Missing, changed, or substituted acceptance bundle/config/fixture hashes fail closed before test execution.
7. A task with no baseline independent assertion cannot become offline-ready until an operator-owned acceptance bundle is recorded.
8. Existing read, diff, evidence, source-drift, and Jetson/host scope-parity tests remain passing.

Practical implementation gates from design review:

- Mutation scope must fail closed when task scope context is absent. Every MuleLab tool-dispatch path must install the persisted scope; Jetson suggestions never carry authority.
- `scope-expand` may authorize auxiliary exact paths, but it must not mutate the canonical company tests/source targets established in Group 3. Revising those fields requires a reviewed retry/new assignment.
- Existing untouched campaign members need acceptance bundles before their first activation. Any legacy task with prior edits, tool receipts, or unverifiable workspace provenance must block rather than snapshot its current tests as “original.”
- Freezing all tests and configuration is useful only if local fixtures/data/conftest inputs are also included. The bundle manifest must cover every copied input consumed by the acceptance command; Group 7 later broadens global baseline reproducibility.
- Run acceptance from a disposable copy of the immutable bundle so ordinary cache/temp writes do not alter the sealed original. Verify the sealed bundle hash before and after, and bind the receipt to the current edited-source manifest, scope digest/version, and acceptance-bundle digest. Any later source or scope change invalidates the receipt.
- AST assertion checks are a supplemental floor for editable tests, not semantic proof. Frozen host-owned assertions remain the independent gate; a simplistic count of `assert` nodes cannot certify behavior.

### 5. Atomic inference reservation and safe pilot startup — IN PROGRESS

- [ ] Atomically recheck controls and reserve model budget immediately before inference dispatch.
- [ ] Block inference when pause, stop, deadline, or ownership wins first.
- [ ] Complete pilot validation before atomically publishing pilot/task state.
- [ ] Add pause-before-inference, deadline, failed-pilot, and restart tests.
- [ ] Focused and full suites pass; roadmap review approves group 5.

Acceptance criteria:

1. No inference begins after a committed pause or stop.
2. A rejected or failed pilot start leaves no stale slot and consumes no task budget.
3. An uncertain dispatched inference remains accounted for and cannot execute returned tools after control loss.

### Group 5 minimal design

Add a durable `inference_receipts` table separate from tool receipts. Each row binds a unique request ID to task ID, campaign/run/session identity, phase, canonical identity digest, prompt digest, offered-tool digest, reserved prompt/output/total tokens, pre-reservation counters, timestamps, provider request ID when available, status, observed usage, response digest, and terminal reason. Valid statuses are `DISPATCHING`, `COMPLETED`, `RESPONSE_DROPPED`, and `UNCERTAIN`; no dispatched request is deleted or replayed.

Budget calculation and request construction may happen outside the database transaction. Immediately before calling the Jetson/model transport, use one `BEGIN IMMEDIATE` transition to:

1. reread the task, controls, registry ownership, control generation, deadline, cumulative counters, and unfinished inference receipts;
2. require RUNNING state, no stop/pause, current campaign/pilot/generic owner, current canonical identity, remaining session/call/token allowance, and no prior in-flight or uncertain inference;
3. recompute the allowed reservation from current counters and the prepared prompt estimate;
4. insert one `DISPATCHING` receipt and increment call/token counters exactly once.

That commit is the inference-start linearization point. A pause committed first makes the transition fail and the existing three-argument model callback is never invoked. A pause committed after it records a stop boundary against an already-started call; the coordinator cannot promise cancellation of that reserved call and must discard its tools. MuleLab's durable receipt and no-replay rule provide the required safety without a Jetson change. A request ID may be forwarded only after the endpoint schema explicitly supports it; do not claim Jetson idempotency or deduplication otherwise.

When a response returns, finalize it in another immediate transaction. Record valid observed usage and response digest exactly once. If usage is valid and within reservation, replace only that receipt's reserved amount with observed usage. Invalid/missing usage retains the full reservation; over-reservation records at least the observed amount and pauses for inspection. Counters are derived from the receipt's saved pre-reservation values/current serialized state, never a stale in-memory task snapshot.

The finalize transaction also rechecks stop, deadline, task status, canonical identity, registry/control ownership, and receipt state. It returns an explicit `tools_allowed` decision. Any control loss produces `RESPONSE_DROPPED`; the response may be retained by digest for audit but no tool call is executed. Every tool still passes the existing atomic `active_intent` gate, so loss after response finalization but before a tool also fails closed.

Transport timeout, process crash, malformed response, or database uncertainty after `DISPATCHING` becomes `UNCERTAIN` with the full reservation retained. Restart/recovery never resends it and never executes its response. It pauses the task for operator inspection unless a future provider-specific reconciliation can prove the exact request result. Session-start accounting must use the same serialized ownership/deadline checks so session, call, and token counters remain cumulative across fresh contexts and restarts.

Required focused tests:

1. Deterministic pause-versus-dispatch race: if pause commits first, model invocation count is zero; if dispatch commits first, it is recorded as already started and returned tools are dropped after pause.
2. Deadline expiry, campaign/pilot ownership loss, identity mutation, or budget exhaustion during prompt preparation prevents receipt creation and model invocation.
3. Two coordinator/store instances racing one task create exactly one `DISPATCHING` receipt and one call/token reservation.
4. Crash/timeout after dispatch retains one uncertain receipt and full reservation; restart performs zero redispatches and zero tool actions.
5. Valid usage adjusts only the reserved receipt; missing/negative/zero/over-reservation usage follows the documented fail-closed accounting without counter reset.
6. Pause or deadline after model return but before the first and subsequent tool intents yields zero new tool receipts after control loss.
7. Request/response digests, identity/run binding, and cumulative session/call/token totals survive restart and appear in operator evidence without exposing prompt secrets.
8. Existing pilot startup, action-intent, resilience, and cumulative-budget tests remain passing with no live inference.

### 6. Campaign completion and truthful reporting — WAITING

- [ ] Persist campaign totals and terminal `DRAINED` or `DRAINED_WITH_EXCEPTIONS` outcomes.
- [ ] Report company identity, current stage, exception reason, and next allowed action.
- [ ] Correct held-batch, paused-queue, gate, resume, and live-validation wording.
- [ ] Keep offline-ready distinct from live-validated and installed.
- [ ] Add terminal accounting and status text tests.
- [ ] Focused and full suites pass; roadmap review approves group 6.

Acceptance criteria:

1. Every campaign member is reconciled exactly once into an explicit result bucket.
2. Zero eligible tasks cannot be reported merely as an active autopilot waiting forever.
3. No status offers a command that the service will reject or claims evidence that has no receipt.

### Group 6 minimal design

Persist campaign-level reconciliation separately from task lifecycle state. Add a current campaign record plus append-only terminal snapshots/revisions containing campaign ID, reviewed membership digest, unique current-company total, mutually exclusive category counts and task/company IDs, state (`RUNNING`, `PAUSED`, `DRAINED`, or `DRAINED_WITH_EXCEPTIONS`), reconciliation digest, timestamps, and control generation. Build the denominator only from `campaign_company_registry.current_task_id`, one row per canonical company. A superseded predecessor and its receipts remain audit history but never count as another company or outcome.

Retire a selected task only through one store transaction that rereads its current registry ownership and run ID. Operator-gate statuses become explicit nonexception outcomes such as `OFFLINE_READY_AWAITING_LIVE_VALIDATION`, `REVIEW_COMPLETE_AWAITING_LIVE_VALIDATION`, or `LIVE_VALIDATED_AWAITING_INSTALLATION`; none means installed or that all jobs were downloaded. `PAUSED_BUDGET`, `PAUSED_ERROR`, `PAUSED_BLOCKED`, `PAUSED_TEST_FAILURE`, `PAUSED_FILES_CHANGED`, `PAUSED_RECOVERY`, authorization failures, and other nonresumable scheduler stops become named exception outcomes with the exact reason and receipt pointer. A selected task paused only by the global campaign stop remains `SELECTED` and blocks advance. A per-task user pause is already `USER_PAUSED`; it frees the lane, is an explicit campaign exception, and remains individually resumable. `EXCLUDED` is also an explicit exception.

After retirement and before selection, reconcile all current registry owners in one transaction. If any `HELD_FOR_CAMPAIGN` member remains, select exactly one as usual. If a valid `SELECTED` member remains, do not advance or finish. When neither remains, require every current company to map to exactly one recognized success/operator-gate or exception category. Persist `DRAINED` only when there are zero exception categories; persist `DRAINED_WITH_EXCEPTIONS` otherwise, atomically turn campaign and queue scheduling OFF, retain the active campaign ID for audit, and bump the control generation. An unknown disposition/status, missing registry owner, duplicate company, stale retry owner, or count mismatch is a reconciliation error: controls turn OFF and the campaign reports `PAUSED_RECONCILIATION`, never drained.

`DRAINED` is a scheduler result, not an integration certification. Its summary must say that Python processed all current campaign members to their recorded boundary and give separate counts for offline-ready, review-only, live-validated, installed-with-explicit-receipt if that concept is later added, and exceptions. `DRAINED_WITH_EXCEPTIONS` must list each exception's company ID/name, task ID, stage/status, reason, and next allowed action. Bound long human output while preserving complete machine-readable JSON and a durable report artifact.

Any later explicit include, resume, or reviewed retry of a current exception atomically reopens the campaign as a new reconciliation revision before making work eligible. Preserve the earlier terminal snapshot. A retry transfers current registry ownership to the new task, so later totals still contain one company. Campaign start with no work must return the existing reconciled result rather than poll forever; a changed membership digest requires a new reviewed campaign/import transition.

Correct command text at the same time. Batch import says assignments were imported and held. Direct start says whether it is queued or saved behind paused controls. Task status names company and exact stage; operator-gate tasks show live validation or installation as the next action and never print a rejected resume command. Held, selected, user-paused, excluded, offline-ready, live-validated, and installed states remain distinct in both human text and JSON.

Required focused tests:

1. Two offline-ready current companies yield one durable `DRAINED` snapshot, controls OFF, exact total two, and no claim of live validation, installation, or complete job download.
2. Offline-ready plus `USER_PAUSED`, `EXCLUDED`, budget, blocked, and error examples yields `DRAINED_WITH_EXCEPTIONS` with exhaustive mutually exclusive totals and correct next actions.
3. A selected budget/error stop is retired as an exception and the next held company advances; a globally stopped `SELECTED`/`PAUSED` task is retained and prevents advance/drain.
4. Reconciliation counts only registry `current_task_id`: a retry predecessor and its terminal receipts do not increase totals or appear as the current outcome.
5. Concurrent scheduler instances cannot retire/select/finalize twice; restart returns the same terminal snapshot and does not resume polling or alter counts.
6. Explicit resume/include/retry after a terminal snapshot creates a new campaign revision before work becomes eligible and later redrains with one outcome for that company.
7. Unknown state, missing/stale registry ownership, duplicate company, or nonexhaustive totals produces `PAUSED_RECONCILIATION` with controls OFF, never `DRAINED`.
8. Human and JSON status tests cover held import, paused direct start, active company, each operator gate, every exception, exact next action, and absence of invalid resume guidance.
9. Existing campaign isolation, pause, atomic controls, identity, scope, inference, restart, and cumulative-budget tests remain passing without live inference.

### 7. Ownership, reproducibility, deployment, and final rehearsal — WAITING

- [ ] Enforce scheduler ownership inside `run()` as well as `start()`.
- [ ] Include every copied test/config input in the campaign baseline digest and drift checks.
- [ ] Make the deployment script reproduce every staged host and Jetson-forwarder file required by its tests.
- [ ] Refresh the reviewed frozen baseline or document and verify the chosen version.
- [ ] Run all original QA reproductions and the full suite.
- [ ] Run a bounded two-company fake-model rehearsal: fresh worker per company, respected user pause, safe restart, exact exception accounting, and zero live inference.
- [ ] Review rollback evidence and production-off checks before any canary authorization.

Acceptance criteria:

1. No internal entry point can run the scheduler without ownership.
2. A change to any source, test, protocol, configuration, or list consumed by tests triggers baseline drift.
3. A clean deployment from the saved script produces the same tested source set.
4. Final rehearsal ends with a durable reconciled result and no cross-company context, file, counter, or receipt contamination.

## Group 1 minimal design

### State model

Add immutable campaign membership fields to eligible imported task state:

- `campaign_id`: a stable identifier for the exact reviewed campaign manifest.
- `campaign_company_id`: copied from canonical structured identity for indexed comparison.
- `campaign_disposition`: one of `HELD_FOR_CAMPAIGN`, `SELECTED`, `USER_PAUSED`, `EXCLUDED`, or a later terminal value.
- `campaign_selected_at` and `campaign_run_id`: set only by campaign activation.
- `campaign_manifest_digest`: digest of the reviewed campaign manifest entry.

Keep lifecycle `status` and `phase` separate. `status` describes execution; `campaign_disposition` describes whether campaign automation may select the task. Do not infer campaign eligibility from generic `PAUSED`, `reason`, `isolated_workspace`, or zero counters.

Store the active campaign ID and campaign enabled flag together. Campaign mode and generic queue mode must use separate selectors. In campaign mode:

1. In one `BEGIN IMMEDIATE` transaction, confirm campaign enabled, pilot unset, no globally RUNNING/PAUSING task, and no existing `SELECTED` task for the campaign.
2. Select the oldest task where `campaign_id` matches and disposition is exactly `HELD_FOR_CAMPAIGN`.
3. Set disposition `SELECTED`, lifecycle status `QUEUED`, a fresh campaign run ID, and selection timestamp. Do not clear a user pause because user-paused records are not candidates.
4. Claim only a task with that campaign ID and `SELECTED` disposition. The generic `claim_queued()` path must not run while campaign mode is enabled.

### Pause semantics

- Per-task `pause`: set `campaign_disposition=USER_PAUSED`, `stop_requested=true`, and stop at the action boundary. It frees the campaign to advance after the current action stops.
- Per-task `exclude`: set `campaign_disposition=EXCLUDED`; it cannot be resumed without an explicit include operation.
- Global campaign stop: disable campaign scheduling but retain the current task as `SELECTED`. At the next safe boundary it remains resumable by the same campaign; it does not become `USER_PAUSED` and Python does not select another company.
- Explicit per-task resume: validate lane ownership. A user-paused campaign member becomes `SELECTED` and QUEUED only if the campaign lane is free; otherwise return a clear conflict. An excluded task requires explicit include before resume.

### Compatibility migration

Use a reviewed manifest built from the exact installed campaign batch records. Migration must run with service stopped, controls OFF, pilot unset, no active tasks, no unfinished receipts, and a successful database integrity check.

For each manifest entry, match exactly one existing task by objective plus canonical company ID and verify:

- isolated workspace task;
- status PAUSED, phase baseline;
- no activation or selection timestamp;
- zero model calls, sessions, and tokens;
- no tool receipts;
- full structured identity equals the manifest entry.

Only these exact legacy records may convert their historical blanket `stop_requested=true` / `Pause requested.` state to `campaign_disposition=HELD_FOR_CAMPAIGN` with `stop_requested=false`. Record the conversion in migration output and task audit metadata. Any activity, conflicting identity, duplicate match, changed reason, or nonzero receipt/counter remains `USER_PAUSED` or `EXCLUDED` and makes the migration report non-clean; never silently hold it for automation.

The migration is idempotent: rerunning with the same campaign manifest changes zero rows and returns the same accounting. A changed manifest gets a different campaign ID and must not adopt already-owned tasks.

### Exact legacy cohort evidence

Read-only reconciliation of the current production database and staged batch files found one exact 102-task compatibility cohort.

Production controls and database state at reconciliation:

- SQLite `quick_check`: `ok`.
- `queue_enabled=false`, `autopilot_enabled=false`, `pilot_task=null`.
- No RUNNING, QUEUED, or PAUSING task.
- The original imported campaign is recorded by three `batches` rows containing 50, 50, and 4 task IDs. Their original batch digests are:
  - `d7c2ef69eb86c5eb6fc5fd5c1660c9474d1abbb1c8901b4c43eeda190cdf2640`
  - `9d9c0c0fa3af04befb1320cdca626b4f89b5199f4d1905ba05a9b052e642431b`
  - `c6bdc58f1b0498eb96ac401ff79ea966aee34da80dea3dbec8799f03240ac938`
- The staged enriched batch files contain 104 unique company IDs. Their file hashes are:
  - `batch-001.json`: `b3b2dbf93e713489218f5377232dfcf3f1af483cc57f5f4c2ee1737a660a169e`
  - `batch-002.json`: `89206844d0f949d99a489260214cbab52f5319541eb8e3294cac88c13fd94481`
  - `batch-003.json`: `db93aa2bc2c1ee74dcaa73009c2dd4fdc99a4c7923fd173d0b000e610d8198f7`

All 102 eligible task records satisfy every one of these predicates:

- task ID belongs to one of the three original imported batch rows;
- exact objective match to exactly one enriched batch entry;
- full structured `integration` dictionary equals that entry;
- unique company ID across the cohort;
- `isolated_workspace=true`;
- `status=PAUSED`, `phase=baseline`, `stop_requested=true`, and exact reason `Pause requested.`;
- `activated_at=null` and `selected_at=null`;
- zero calls, sessions, tokens, and tool receipts;
- empty manifest, checkpoint, and workflow;
- `authorization_version=1`, `workflow_version=2`, `mode=develop`, `max_sessions=10`;
- evidence requirements version 1.

The reviewed manifest should be the ordered list of `{task_id, company_id, objective, integration}` records in staged batch order, after applying the predicate above. Canonical compact JSON with sorted object keys hashes to:

`e3237070c6c895675a1ae57caa0a35d1cb150938bf0d3b6b4a9425478c740b02`

The first accepted record is `WRAP-8be410e6f4` / `COMP-0097`; the last is `WRAP-07489a59fd` / `COMP-0795`.

Exactly two staged batch entries are excluded:

- `COMP-0344` Mass Virtual has no exact eligible imported-task match. Its original task was narrowed after import and ended `PAUSED_BUDGET`; its successful continuation is a separate `LIVE_VALIDATED` task.
- `COMP-0348` VideoRay matches the enriched identity but is already `LIVE_VALIDATED` with nonzero activity. It must remain historical completion evidence and must not join the compatibility cohort.

One additional record, `WRAP-3d6765138f`, is PAUSED/baseline with zero counters and the same pause reason, but it is a separate non-isolated Mass Virtual continuation with no structured integration metadata. This is the concrete reason the migration must require original batch membership, isolation, and exact identity rather than use the apparent pause state alone.

The database cannot by itself prove whether one of the 102 identical legacy pause commands represented a private per-company exclusion. Historical workflow evidence says the entire untouched backlog was blanket-paused for the pilots. Therefore conversion to `HELD_FOR_CAMPAIGN` must be an explicit reviewed compatibility migration, must not enable the campaign, and must preserve a durable list of all converted task IDs. Any set size other than 102, any manifest hash change, or any predicate mismatch aborts the whole transaction with zero writes.

Recommended migration selection algorithm:

1. Validate the three staged batch file hashes, 104 unique company IDs, and the three original database batch digests.
2. Limit candidates to task IDs in those original batch rows.
3. Join each candidate to exactly one staged entry by exact objective, then require full integration equality and the complete untouched-state predicate above.
4. Require exactly the reviewed 102 task IDs and the canonical manifest hash.
5. Report the two pilot exclusions and the non-campaign Mass Virtual record explicitly.
6. Only after the dry-run report is reviewed may one atomic transaction attach campaign membership and convert the historical blanket pause to `HELD_FOR_CAMPAIGN`. Leave all global controls OFF.

### Required group 1 tests

1. QA reproduction: individual pause remains paused after campaign start.
2. QA reproduction: unrelated direct QUEUED task is never claimed in campaign mode.
3. EXCLUDED and USER_PAUSED tasks are skipped while the next HELD task is selected.
4. Global campaign stop retains the selected task and restart resumes no action until explicitly restarted.
5. Generic queue mode never claims campaign-held tasks.
6. Two scheduler/store instances cannot select or claim different campaign tasks concurrently.
7. Migration cleanly adopts the exact legacy hold, but rejects activity, duplicates, identity conflicts, partial metadata, receipts, and changed pause reasons.
8. Migration rerun is a no-op with identical accounting.
9. Existing non-campaign start, review, pilot, recovery, and queue tests remain passing.

### Group 1 migration review — ACCEPTED IN STAGING

The corrected compatibility migration passes its independent staged gate. Production has not been modified.

Reviewed behavior and evidence:

- `host/migrate_campaign_membership.py` requires `--expected-cohort` on its operator CLI. The reviewed path validates the exact count, canonical cohort hash, exact original database batch rows, reviewed-ID membership in those rows, full identity, legacy untouched-state predicates, `stop_requested is True`, and the historical pause reason before release.
- The production-specific predicates additionally require `max_sessions=10`, task tests equal identity tests, evidence-requirements version 1, and exact empty manifest/checkpoint/workflow dictionaries.
- `expected-legacy-cohort.json` binds exactly 102 records to canonical cohort hash `e3237070c6c895675a1ae57caa0a35d1cb150938bf0d3b6b4a9425478c740b02` and the three exact original database batch rows.
- `membership-migration-verification.json` records the snapshot hash, all three staged batch hashes, reviewed-ID file hash, expected cohort, dry run, first apply, second apply, database hashes, integrity result, controls, and shortened-cohort rejection.
- Disposable-copy verification passed contemporaneously: dry-run database bytes were unchanged; first apply changed exactly 102 tasks; second apply changed zero tasks and left identical database bytes; `quick_check=ok`; queue and autopilot remained false and pilot remained null; a shortened reviewed cohort was rejected.
- All seven independent migration tests pass, including the corrected `stop_requested=False` case and expected-cohort mismatch before any write.

Operator constraint: use the documented CLI or verification path with both reviewed IDs and expected-cohort evidence. The lower-level Python helper retains an optional `expected_cohort` for synthetic tests and must not be used directly for the production legacy migration without that evidence.

The earlier in-progress resume-test mismatch was corrected before final review. A contemporaneous rerun passed all 16 independent campaign-isolation tests, including resume/include lane ownership, campaign action-intent ownership, direct-step guards, global queue pause precedence, restart, concurrency, and migration. The complete staged host suite then passed all 161 tests. Group 1 is accepted in staging; production migration and deployment remain deferred.

## Dependency review

- Group 1 owns the campaign state vocabulary and selector. Group 2 must reuse its transaction boundary rather than create another control path.
- Group 3 will define the final canonical identity digest. Group 1 may store a manifest-entry digest now, but must not claim complete identity immutability until group 3 passes.
- Group 6 terminal dispositions will extend the group 1 disposition enum; group 1 should centralize enum validation so that extension is controlled.
- Existing production task JSON supports additive fields without a SQLite table rewrite. A campaign table may be added later for totals, but group 1 must not rely on free-form status reasons as state.
- `backfill_campaign_metadata.py`, `coordinator_store.py`, `coordinator.py`, queue tests, migration tests, deployment/rollback scripts, and WORKFLOW documentation are directly affected.
- Production's current 102 untouched records all carry the legacy stop flag. They must remain paused until the reviewed compatibility migration explicitly classifies them. No normal startup path may reinterpret them automatically.

## Mandatory independent final QA gate

After all seven finding groups are individually accepted and combined staged tests pass, start a separate independent final-QA phase. Its reviewers must not be the implementation owners for the behavior they test.

Final QA must:

1. Rerun every original QA reproduction and every regression added during the seven repairs.
2. Inspect the final staged diff, deployment manifest, migration evidence, rollback bundle, and production-off controls.
3. Run the full host suite and the bounded two-company fake-model rehearsal from a clean disposable database and workspace.
4. Verify fresh per-company context, exact campaign membership, individual pause/exclusion, pilot/campaign mutual exclusion, canonical identity, edit scope, immutable acceptance checks, atomic inference stop, safe restart, terminal accounting, and no live/install overclaim.
5. Produce a new dated QA report with evidence paths and an explicit PASS or FAIL verdict.

If any final-QA check fails, the workflow does not release. Create a new QA report for that failure, reopen the affected finding group, and assign fresh implementation and independent verification lanes. Repeat the repair and final-QA cycle until an independent report passes every required check. Production migration, campaign enablement, and live inference remain deferred until that PASS is reviewed.
