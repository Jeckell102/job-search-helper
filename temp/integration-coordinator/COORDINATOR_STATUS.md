# Integration automation coordinator status

Updated: 2026-11-19. This is the current working card for the isolated,
source-only coordinator copy. It contains no production records, credentials,
locks, or runtime histories.

## Mandatory reread points

Read this card at the beginning of every resumed coordinator turn; before
assigning new work, changing a milestone boundary, or attempting a live test;
after every accepted or rejected review checkpoint; and before every scheduled
ten-minute user update. Update it immediately after any material result.

## Coordinator authority and modification log

- The coordinator owns this project end-to-end and may modify the MuleLab
  scraper as needed while preserving safeguards, evidence, and scoped GitHub
  backups.
- Temporary coordination Markdown files are the active handoff surface and
  must be kept current at the reread points above.
- Jetson changes are authorized when required by the roadmap. Before any
  Jetson modification, locate the appropriate existing Jetson modification
  log; record the exact change, reason, verification, and rollback evidence
  in that file immediately afterward. Do not claim or imply a Jetson change
  until both the system and its record have been updated.
- Jetson F4 source was deployed under recorded change control on 2026-11-18.
  On 2026-11-19 the corrected, reviewed operator-proof script was added to the
  existing F4 record without executing it; its exact hash, permissions,
  verification, and rollback boundary are recorded in the Jetson changelog,
  register, and dedicated staging receipt.

## Current position

- Coordinator checkpoint, 2026-11-19: the deployed F4 package is still
  byte-for-byte matched to the reviewed staged source and has a scoped rollback
  copy. It is deployed-but-unaccepted. The proposed real-HTTP proof corrected
  its private endpoint and generation-labeling defects, then added fsync-backed
  post-request checkpoints. Independent QA now accepts its source-level
  ordering: a durable `settlement_authorized` record precedes the only lane
  release, and a post-settlement evidence failure is recorded honestly. The
  actual Jetson proof, records, and deployed QA remained separate open gates
  until the verified 2026-11-19 live run described below.
- Goal: complete all six roadmap milestones and the final independent
  acceptance demonstration, with safeguards and scoped GitHub backups.
- Goal reference: `01a1f11f-e014-7493-8441-2f66502e23a9`; the persistent goal
  is active. Do not create a replacement goal.
- Main checkout: protected and heavily dirty. The accepted, hash-recorded
  integration file set was installed under the existing install lock on
  2026-11-19 with an exact rollback copy. Do not edit anything else, delete
  locks, or treat unrelated dirty files as part of this project.
- Isolated feature worktree: `/tmp/job-search-helper-integration-automation`
  on `codex/integration-automation-20261118`.
- Coordinator development checkout: `/home/chris/job-search-helper_old/dev/wrapper-coder/repo`
  is on `development/wrapper-coder` at `0c45d61`. Its code is clean, but four
  pre-existing documentation changes are preserved; it has no GitHub remote.
- Milestone 1: 92% — the normal request consumer now validates and admits one
  immutable Company-only request, runs only that Company, and refuses to
  supersede unfinished work or accept an altered retry. Independent source
  review accepted the offline proof; guarded operational proof is still
  required.
- Milestone 2: 90% — durable Company revisions, reconciliation, and scoped
  request provenance are implemented and independently reviewed. A narrow
  current-Company revision lookup now exists for the coordinator boundary;
  the active local store now has the additive event/outbox foundation. The
  existing Sheets sync now baselines current Companies once without scheduling
  them, then reconciles later changes. The normal runner turns a confirmed
  change into an exact Company-only request. Guarded live proof remains.
- Milestone 3: 88% — bounded outcome classification, local immutable records,
  independently reviewed intake, and durable exact-receipt delivery into the
  existing coordinator are implemented. The independently accepted normal-run
  producer records bounded scrape facts without dispatching work; malformed
  checkpoint data is safely skipped. Qualified defects are held once for
  triage, never dispatched. The remaining gap is guarded live verification.
- Milestone 4: 78% — a held repair can be promoted only into a paused,
  Company-version-bound coordinator task. It cannot resume without a fresh
  trusted Company lookup, and stale work is re-paused before it can be claimed.
  The coordinator host now has a local-only, read-only resolver wired in. The
  protected installed coordinator suite passes 434 checks; the queue remains
  paused and no repair campaign was started.
- Milestone 5: 76% — source candidates now provide crash-durable,
  Company-version-bound release-to-retry intent, exact complete-release pins,
  normal company-only admission/recovery, stale-source refusal at admission
  and storage, and release/attempt identity through publication and outcomes.
  The same existing scraper lock now gates release activation; a durable
  journal blocks startup after a partial install, complete source/configuration/
  dependency versions and validation evidence are pinned, and exact guarded
  rollback is implemented. A maintained controller now turns only the exact
  completed release receipt into one retry and recovers a crash after
  activation without reinstalling. The coordinator now records retry lineage,
  suppresses late original failures from reopening work, rejects competing
  successors and creates a fresh repair for a genuinely failed repaired
  attempt. Protected-source reconciliation is now complete in a temporary,
  source-only copy: the current scraper behavior and M5 selection passed 72
  checks, nine repaired publication/restart checks passed, eleven current
  durable-inbox checks passed, the disposable release/start race passed, and
  the combined MuleLab coordinator suite passed 398 checks with strict
  resource warnings. A reconciliation-specific safeguard now refuses silent
  replanning after any acknowledged publication slice. The evidence and exact
  hashes are recorded in `M5_PRODUCTION_RECONCILIATION_REPORT.md`.
  Independent QA accepted that exact candidate. Its two required test
  follow-ups are now independently accepted: the full durable-inbox suite
  passes 12 checks and a real partial-publication review conflict retains the
  exact plan, pending receipt, manual note, and blocked inventory without
  duplicate jobs. Owner-reviewed protected integration is complete: the
  protected integration selection passes 202 checks and exact rollback/source
  hashes are recorded. The live release-to-saved-jobs proof remains.
- Milestone 6: 61% — F4 receipt/recovery source review and controlled Jetson
  placement are complete. An isolated F8 candidate now extends the existing
  coordinator with one maintenance owner, durable boot/reconnect catch-up,
  disk-pressure holds, explicit evidence-retention counts, and planned
  shutdown that waits for the current action boundary. Its first independent
  review rejected a watchdog/shutdown race; the corrected path now passes a
  live-scheduler/watchdog test and records recovery-required instead of a false
  safe pause on timeout. Independent QA accepted the corrected exact source
  and its real-host retention wiring. The protected host now runs this source;
  a controlled stop persisted `SHUTDOWN_PAUSED`, restart catch-up returned
  `ACTIVE`, and the queue stayed paused. The live service has now entered
  `DISK_PRESSURE_HOLD` under a temporary
  threshold, preserved every tracked count without cleanup, then returned to
  `ACTIVE` after the override was removed. Independent QA accepted the final
  threshold control and independently confirmed both services healthy, no
  temporary override, no running work or open receipts, and unchanged
  retention counts. The interrupted-cycle recovery status candidate was
  corrected after two independent reviews, installed under the protected
  integration lock with an exact rollback, and passed 113 protected checks.
  Its live read-only report safely refused the current cycle because 47 saved
  inventories and eight partially applied plans still require publication or
  explicit reconciliation; no recovery was applied. An exact-cycle sync path
  was then independently accepted, installed with a separate exact rollback,
  and passed 117 protected checks. It refuses completed/superseded historical
  inventory and selects only the active named blocker. Live publication did
  not start: the sandbox blocked the first attempt before lock acquisition and
  permission review requires explicit user approval for the concrete Google
  Sheets payload. Independent post-install verification accepted the exact
  installed hashes, Git checkpoint, historical-cycle refusal, and unchanged
  47-inventory/eight-plan live counts without accessing Google. The
  administrator-authenticated Jetson interruption proof and the full
  sequential acceptance matrix remain.

## Definition of fully completed

Completion means a newly added eligible Company in the Google Sheets database
creates one durable, company-scoped request; the normal scraper runs for that
Company; an existing integration is used or the existing coordinator safely
builds and validates the needed wrapper within its approved capability; the
resulting jobs and evidence are saved through the normal Job Search Helper
path and confirmed in Google Sheets; and the managed first-pass review begins.
The same flow must be restart-safe, avoid duplicate work, preserve manual
choices, expose plain-language status, and pass the final independent
acceptance demonstration. Offline code, a local receipt, a fixture test, or a
partial Google Sheets write alone is not completion.

## Accepted checkpoints

- `b0fda48`: Company-event provenance persists through restart recovery.
- `3179eba`: classified outcome records are bounded, idempotent, and local
  only; forged actions and private identity fields are not stored.
- Source-only coordinator copy accepted after independent review and saved as
  `b002564`.
- Classifier-derived, held-only repair intake accepted by independent review
  and saved as `fecfc7d`.
- Repeated repair evidence was independently accepted and saved as `c9fcc8b`.
- A held repair can be promoted exactly once to an independently reviewed,
  paused, source-version-bound task, saved and pushed as `834fc4d`.
- The MuleLab coordinator source now matches the reviewed copy for this
  checkpoint; its new focused test exposed that the active Job Search Helper
  source was missing the shared outcome-classifier module. That source module
  was reconciled and 142 focused MuleLab checks passed; the coordinator
  remained off and no repair task was started.
- Current-Company guard accepted after re-review: the isolated coordinator
  stops stale or unverifiable repairs before any direct worker step or tool
  action, as well as on normal resume and every claim path. The repaired
  implementation passed 145 focused coordinator checks and 13 focused
  Company-event checks. MuleLab reconciliation remains pending.
- The accepted guard now matches the MuleLab coordinator source exactly; its
  focused suite passed 145 checks there with no coordinator scheduler started.
- The MuleLab coordinator host now supplies a local SQLite-only Company
  resolver. Syntax and safe-failure checks passed; activation/restart and any
  live task remain deliberately deferred.
- The active local repository now has additive Company-event and scrape-outcome
  tables. An isolated temporary database proved one event and one idempotent
  classified outcome; no live database or Company record was changed.
- The active Sheets synchronizer now seeds existing Companies only as a
  one-time watermark and later reconciles changes into the outbox. An isolated
  check seeded one Company, created no pending request, and remained
  idempotent on the second call.
- The active bridge was proven against an isolated temporary database: one
  eligible Company event wrote and read back one Company-only request for that
  exact ID, then acknowledged the event. No live state was used.
- Independent review rejected activating that bridge: the active request
  consumer currently accepts only fresh-full-scan requests, so its
  Company-only request would safely fail rather than run. Compatibility and
  an end-to-end normal-path proof are required before any guarded live test.
- The compatibility repair was independently accepted: a bridged Company-only
  request is schema-checked, bound to exactly one Company, waits behind any
  unfinished cycle, and retains an immutable retry fingerprint. Twenty-four
  focused request/runner checks passed locally; the independent reviewer also
  confirmed the active-source path with ten focused request checks. No service
  or live scrape was started.
- Fresh live-state inspection found no running scraper or coordinator process,
  but the authoritative local state contains multiple historical cycles still
  marked In Progress (including the latest broad cycle with 800 Companies).
  The retained scraper/writer locks name absent PID 485601. No
  lock, cycle, request, Company, or Sheets data was changed. This prevents a
  safe live company-only demonstration until the documented recovery path is
  reviewed and exercised without discarding existing work.
- Independent review accepted the new read-only Company queue-status surface:
  it exposes the exact single Company, queue age, local/remote blocking cycles,
  timing targets, and recovery guidance without opening Sheets in local-only
  mode, altering the request, touching locks, or starting a scrape. The active
  source passed 25 focused request/runner checks; no live state changed.
- The normal-scraper-to-coordinator intake command is now independently
  accepted in both active and isolated sources. It accepts only bounded facts,
  reuses the shared classifier, creates at most a held repair record, and
  cannot create, resume, claim, or start a coordinator task. Thirty focused
  active and isolated coordinator checks passed; no service was activated.
- Durable outcome delivery is accepted: an immutable local outcome remains in
  the Job Search Helper outbox until the coordinator accepts the exact same
  outcome ID. Rejection, mismatch, or an unavailable coordinator leaves it
  pending for retry. The isolated feature copy passed 34 focused coordinator
  delivery/intake checks and 41 local repository checks; no service, worker,
  or live scraper was started.
- The normal-run producer is independently accepted after two safety repairs:
  it records only bounded normal-cycle facts, holds ambiguous failures rather
  than guessing a repair, and skips malformed saved data without changing the
  completed scrape result. Fifty-five focused producer, classifier, runner,
  and request checks passed. No live action was taken.
- The interrupted-cycle recovery pause is independently accepted in the
  isolated source. It requires an exact unfinished cycle, matching workbook
  scope and per-Company membership, preserves completed/blocked work, and
  writes a reversible prior-stage receipt before releasing a safe boundary.
  Thirty-nine focused recovery/scheduling checks passed. It has not been run
  against the live 764-Company checkpoint.
- The explicit `recover-interrupted-cycle` command is independently accepted:
  it requires the exact cycle ID, a reason, and `--apply`, uses the normal
  writer/synchronization boundary, and cannot start/resume a scrape or delete
  locks. Forty focused recovery/scheduling checks passed.
- Independent QA accepted the held-repair safety boundary: promotion remains
  paused, and resume, queue claim, and direct-step paths all fail closed when
  the current eligible Company revision is missing or stale. The host resolver
  is local SQLite-only and returns no approval on missing configuration or any
  read failure. Forty-seven focused coordinator checks passed.
- Independent QA accepted the M3-to-M4 profile evidence repair: qualified
  outcomes now retain their bounded repair category through local storage and
  coordinator intake, while earlier category-less records stay readable and
  held. The deterministic selector requires exact Company, current revision,
  provider, adapter version, repair category, and URL; its enabled registry is
  intentionally empty until F5 qualification. No profile can start a worker.
  Forty-one focused coordinator checks and fifty-seven local classifier/store
  checks passed.
- F4 recovery assessment confirmed the remaining Jetson boundary: MuleLab
  already prevents duplicate or unaccounted inference after a transport loss,
  but the current synchronous Jetson endpoint cannot report retained request
  state or acknowledge cancellation by MuleLab request ID. This remains a
  safe hold, not F4 closure; the bounded protocol and test requirements are
  recorded in `F4_INFERENCE_RECOVERY_GAP.md`. No Jetson modification occurred.
- Independent QA accepted the isolated F4 control-receipt store: it retains
  only request/owner fingerprints, timestamps, terminal state, bounded scalar
  usage, and a response digest; it never accepts prompt, source, inventory, or
  model content. It rejects duplicate/conflicting IDs, permits only one running
  Jetson request, and requires matching ownership to request cancellation.
  Nine focused local checks passed. It is not yet wired into host/Jetson routes,
  so this is an implementation component, not F4 closure.
- Independent QA accepted the host-side F4 binding: each model call derives
  its exact request ID, request fingerprint, and owner generation only after
  the durable reservation is saved. Legacy calls remain unchanged until the
  Jetson endpoint is upgraded, and an injected transport failure proved the
  binding is cleared while the durable request enters `UNCERTAIN`. Twenty-three
  focused host/inference checks passed. Jetson endpoint wiring is still open.
- Independent QA accepted the staged F4 receipt-settlement repair: a Jetson
  model error now settles its receipt as `FAILED`, an already requested stop
  settles it as `CANCELLED`, and either terminal state releases the one-turn
  guard without retaining error text. Thirty-one host/store checks and six
  staged wrapper checks passed. The staged HTTP control routes then passed two
  local loopback checks: they require the existing wrapper token, reject a
  mismatched owner, and accept only a matching status/stop request. This is
  staged evidence only; no Jetson file, service, or live request changed.
- Final staged QA marked the earlier F4 package `ACCEPT WITH REQUIRED FOLLOW-UPS`:
  no code blocker remains before staging/backup. Before any live deployment,
  use the Jetson change-control path, collect fresh service preflight and
  rollback evidence, record the actual modification in the Jetson log, and
  prove the deployed authenticated endpoints. Generated staging bytecode was
  removed; the clean staged checkpoint is GitHub commit `8b5081a`.
- A fresh publication preflight found 60 pending system-field updates in the
  local outbox. Live read-only comparison confirmed that 59 already match the
  workbook and identified one remaining `Last Checked` date for Saronic
  Technologies / Product Manager. The bounded normal publisher reached the
  Google authorization boundary and made no change because interactive sign-in
  is still required. No scrape, recovery, lock, Company record, or user review
  choice was changed.
- Higher-model review then rejected the staged F4 package: post-turn receipt
  validation could leave a receipt RUNNING; ambiguous backend transport was
  incorrectly terminalized; restart orphan records had no guarded settlement;
  status disclosed cancellation credentials; and MuleLab could not reconcile a
  retained Jetson terminal receipt. Corrective isolated changes now cover all
  five boundaries: post-turn terminal settlement, lane-blocking UNCERTAIN
  transport/orphan states, ownership-proved and sanitized status, persisted
  control bindings, and one-shot host recovery into RESPONSE_DROPPED or another
  retained terminal state. Focused MuleLab tests: 34 passed. Focused Jetson
  staging tests: 12 passed before a new independent legacy-path finding. The
  legacy payload now cannot bypass a retained UNCERTAIN lane; an independent
  recheck reproduced the fix. The normal Jetson worker also honors this shared
  lane hold. Staging regression suite: 13 passed. F4 and all
  later deployment/rollout gates remain open pending live change control.
- F4 source checkpoint `9dd1070` has been pushed to the scoped GitHub branch
  after the independent legacy-lane recheck. A Jetson preflight/rollback
  procedure is prepared in `F4_JETSON_PREFLIGHT_AND_ROLLBACK.md`. It states
  the current essential limitation: no independent, request-correlated Ollama
  inactivity proof exists for a post-restart orphan, so an `UNCERTAIN` receipt
  must keep the sole inference lane blocked. Deployment cannot close F4 until
  that proof is designed, implemented, and live-tested.
- A read-only Jetson inspection confirmed that the missing proof can be bound
  to `ollama.service` generation (main PID plus systemd monotonic start time),
  not to an opaque HTTP timeout. `F4_BACKEND_INACTIVITY_CONTRACT.md` defines a
  fail-closed, owner-bound settlement after a deliberate recorded Ollama
  restart proves the original process generation ended. The contract is now
  implemented in the staged source checkpoint, but not deployed or F4 closure.
- Independent review rejected the first backend-generation admission slice: an
  Ollama restart can occur between recorded generation G1 and native dispatch,
  allowing the lost request to run on G2. A corrected isolated implementation
  now records both G1 and recovery-observed G2, then settles only after a
  distinct G3 is active and both earlier PIDs are absent. Sixteen focused
  Jetson-stage checks and twenty-seven host checks pass; independent re-review
  and all deployment gates remain open.
- Independent source QA accepted the corrected G1/G2/G3 backend-inactivity
  protocol: it does not expose receipt credentials, accepts no client-provided
  process identity, rejects an owner mismatch, and keeps the lane blocked until
  the distinct replacement generation proves both potentially executing
  predecessors absent. The staged suite passed 16 checks and the focused
  MuleLab suite passed 35 checks. This is not deployment approval.
- Follow-up route review found that the orphan-recovery path did not initially
  restrict its HTTP method. The isolated route now accepts only `POST`; `GET`
  and `DELETE` are proven to leave the receipt unchanged. The corrected staged
  suite passed 17 checks and the focused host suite passed 27 checks. Fresh
  independent confirmation is still required before deployment.
- Fresh Jetson preflight then found the accepted F4 package already installed,
  exactly matching staged `server.py`, `wrapper_inference.py`, and
  `inference_control_store.py`, with a scoped pre-change source rollback at
  `project-records/f4-inference-receipts-20261118`. The user-level
  `local-ai-orchestrator.service` and `ollama.service` were active; the live
  health endpoint returned version 0.2.2. The unit listens at
  `192.168.1.146:8787`. The deployment has no recorded synthetic acceptance,
  F4 changelog/register entry, or final independent deployed QA, so it remains
  deployed-but-unaccepted and F4 remains open.
- The actual F4 rollout has now been reconciled and recorded: only
  `local-ai-orchestrator.service` was restarted, its aggregate health and
  database integrity stayed clean, and aggregate task counts did not change.
  Synthetic non-user-data checks confirmed authentication, ownership,
  sanitized status, duplicate non-replay, cancellation acknowledgement, and
  POST-only recovery handling. The scoped record and rollback source are in
  `/home/chris/AI/project-records/f4-inference-receipts-20261118`, with durable
  entries in the Jetson CHANGELOG and change register. The G1/G2/G3 proof is
  pending only because `ollama.service` requires interactive administrator
  authorization to restart; no uncertain receipt was released or replayed.
- Independent deployed QA rejected the first local G1/G2/G3 script as final
  evidence: it manufactured an uncertain receipt directly in SQLite rather
  than exercising the authenticated wrapper request and a bounded dropped
  response. It remains only a settlement smoke check and must not be run for
  F4 closure. A revised, source-reviewed synthetic fault-injection path is
  required before any further Ollama restart.
- Fresh MuleLab state verification found no scraper, coordinator, review, or
  Sheets process running. The retained scraper, writer, review-writeback, and
  first-pass controller lock owners are absent; their historical lock files
  remain preserved. The last saved request is an old 509-company
  `fresh-full-scan`, and the latest visible first-pass checkpoint is a drained
  historical run. Do not resume, delete, or supersede either without the
  explicit guarded interrupted-cycle recovery path.
- Independent QA accepted a local M1-M4 reconciliation candidate built from
  the protected checkout's hash-recorded source/test snapshot. It preserves
  protected behavior and restores the guarded Company-event, Company-only
  request, recovery-provenance, and SQLite-outbox contracts; 68 protected
  overlap checks and 39 event/outbox/outcome checks passed. It is not merged
  or deployed because the candidate is relative to extensive uncommitted user
  work. See `M1_M4_PRODUCTION_RECONCILIATION_REPORT.md`.
- Coordinator review rejected the first real-HTTP F4 proof candidate before
  execution. Its repair now resolves the runtime endpoint without committing
  private addressing and correctly treats pre-request process sampling as
  non-authoritative. Independent QA still rejects the candidate: the
  post-request checkpoint now fsyncs its file and directory and a first-write
  failure test preserves a sanitized hold. Independent QA accepted the final
  sequencing repair: a durable `settlement_authorized` checkpoint with
  `lane_released: false` comes before `settle`; post-settlement evidence failure
  keeps that truthful boundary and never replays. Twenty-six focused staging
  checks passed. This is source acceptance only; no service restart or live
  request occurred.
- Independent QA accepted the final staged real-HTTP proof at source level:
  it uses the authenticated wrapper route without direct receipt-store access,
  records a crash-durable pre-settlement authorization before the sole release
  call, and handles later evidence persistence honestly. Twenty-six focused
  staging checks passed in independent QA; coordinator added a client-route
  contract test and reran twenty-seven focused checks. The source is staged
  for the next scoped backup commit.
- Fresh read-only Jetson preflight after that source acceptance found
  `local-ai-orchestrator.service` and `ollama.service` active, health 200/ok,
  and all three deployed F4 file hashes matching the recorded installed hashes.
  The control-receipt aggregate is `CANCELLED=1`, `COMPLETED=1`, with no
  `RUNNING` or `UNCERTAIN` hold. The existing rollback script and source copies
  remain present. `ollama.service` restart still requires interactive sudo;
  no live proof, source installation, service restart, receipt mutation, or
  deployment record update has occurred in this checkpoint.
- The exact reviewed proof is now installed as
  `project-records/f4-inference-receipts-20261118/run_synthetic_http_recovery.py`.
  Its installed SHA-256 matches the GitHub-backed reviewed source, its mode is
  0700, its syntax parsed successfully, and both required services remained
  active. The placement is recorded append-only in the Jetson changelog,
  register, and a dedicated staging receipt. No proof request, receipt
  mutation, or service restart has occurred; the older
  `run_synthetic_g1g2g3.py` remains rejected historical evidence and must not
  be run.
- Milestone 5 F2 implementation candidate now persists a release-to-retry
  intent before the normal Company-only request, binds the full source,
  dependency and configuration release identity, carries it across restart
  and publication, and blocks Company source drift before storage. The focused
  request/event/storage/outcome suite passes 151 checks. This is isolated
  source evidence only; F3 release admission and activation remain open and no
  production behavior was enabled. See `M5_REPAIR_RETRY_CANDIDATE.md`.
- Milestone 5 F3 implementation candidate now shares the normal scraper lock,
  pins complete source/configuration/dependency and reviewed-validation
  identities, journals before replacement, blocks actual runner startup after
  interrupted activation, and provides guarded exact rollback. Eleven release
  fault checks and 162 combined focused checks pass. It remains isolated,
  unreviewed source; no production release or automation was enabled. See
  `M5_RELEASE_ADMISSION_CANDIDATE.md`.
- The maintained M5 controller now binds the reviewed failed request into the
  release manifest, activates the release, and creates the retry only from the
  completed receipt. Crash-after-activation, occupied-queue and post-activation
  source-drift checks pass without reinstalling or duplicating the attempt.
  The combined focused selection passes 178 checks. This is still isolated
  source and has not changed protected production.
- M5 stale-result precedence now records a durable successor chain in the
  coordinator. Late pre-release failures remain evidence but cannot reopen the
  old repair, a competing successor is rejected, and a failed repaired attempt
  receives a fresh repair identity. The full isolated coordinator suite passes
  195 checks; with 178 scraper/release checks, the two surfaces total 373.
  This remains isolated source pending
  independent review and protected-store reconciliation.
- M5 protected-source reconciliation is now accepted as a temporary
  source-level candidate, not a deployment. It preserves the current protected
  scraper behavior while adding exact release/retry/publication lineage and a
  fail-closed boundary for a review change after partial publication. The
  current-source M5 selection passed 72 checks, nine publication/restart checks
  passed, eleven durable-inbox checks passed, the release/start race passed,
  and the combined MuleLab coordinator suite passed 398 checks. Exact hashes,
  boundaries, and remaining gates are in
  `M5_PRODUCTION_RECONCILIATION_REPORT.md`. Protected production was not changed.
- Independent QA accepted the exact M5 reconciled hashes and then accepted
  both required follow-ups. A real nonzero-cursor review conflict now proves
  the frozen plan, pending receipt, manual decision and blocked inventory are
  retained without duplicate Job Keys. The corrected option-forwarding test
  keeps the real `main(start ...)` scrape/FIRST-PASS preflight intact. The full
  current durable-inbox suite passes 12 checks. Source-level independent QA is
  closed; integration/deployment/live acceptance remain open.
- The isolated F8 supervision candidate now passes 233 coordinator checks and
  34 focused checks over the protected-source reconciliation copy. Its real
  host-wiring check proves the zero-argument probe supplies the database and
  consumer identities and persists nonempty external counts. It protects
  coordinator state plus unacknowledged scraper events, publication receipts,
  and active release evidence without automatic cleanup. A live coordinator
  action test proves planned shutdown makes the watchdog stand down, waits for
  scheduler ownership to end, and only then records a durable pause; a timeout
  remains explicitly recovery-required. Independent QA accepted the corrected
  exact source. It is now installed through the rollback-backed protected
  integration and its restart, planned-stop, live disk-hold and recovery
  evidence is independently accepted. See `F8_SUPERVISION_CANDIDATE.md` and
  `PROTECTED_INTEGRATION_REPORT_20261119.md`.
- A second fresh preflight confirmed the same active services, 200 health, and
  terminal-only receipt aggregate. A `sudo -n` restart attempt returned 1
  without changing service state, confirming that only an interactive
  administrator-authenticated terminal can perform the deliberate Ollama
  interruption.
- The guarded F4 proof was then run from that terminal and printed PASS. Fresh
  independent verification found both services active, health 200, sanitized
  terminal evidence (`UNCERTAIN` observed then `FAILED` settled), no active
  lane, and aggregate receipts `CANCELLED=1`, `COMPLETED=1`, `FAILED=1`.
  Jetson authoritative change records, rollback references, catalog, state,
  roadmap, and a local sanitized-mirror commit `623a483` were updated. F4 is
  verified with limits. Independent deployed QA accepted the F4 transport-
  recovery sub-gate: the authoritative evidence is mode 0600 and sanitized,
  receipts are terminal-only, deployed file hashes match their installation
  record, and the authoritative records agree. Later MuleLab final-acceptance
  gates remain open. See `F4_LIVE_PROOF_VERIFICATION.md`.

## Safety boundaries

- Do not create a second repair scheduler. Extend the copied existing
  coordinator only after its contracts and tests are present.
- Do not copy databases, locks, credentials, tokens, runtime histories, or
  private inventories from the protected main checkout.
- Preserve manual decisions, Opportunities, existing cycles, and locks.
- Do not claim live completion from offline tests. Before any live action,
  freshly verify processes, locks, state, source identity, and authorization.
- Save accepted source and test checkpoints to the scoped GitHub branch.

## Next actions

1. Keep the protected queue paused while the final three-company readiness
   matrix is refreshed from current local evidence. Select distinct source
   structures plus the shared-adapter regression control; do not start work
   from historical candidate names alone.
2. The refreshed publisher preflight now shows one pending local Opportunities
   `Last Checked` receipt and 21 protected remote-edit conflicts. Identify the
   pending receipt and reconcile or explicitly retain every conflict under the
   normal safeguards before requesting interactive Google authorization. Do not
   start a scrape.
3. Only after publication is clean, freshly recheck processes, locks,
   local/workbook cycle identity, deployed source identity, and sync health;
   then perform the final demonstration one Company at a time, proving normal
   company-scoped dispatch, wrapper/adapter handling, confirmed Sheets
   publication and managed FIRST PASS start before advancing to the next.

The refreshed matrix is recorded in
`FINAL_ACCEPTANCE_READINESS_20261119.md`. It freezes Forterra/Rippling and
Allen Control/Greenhouse as conditional completion candidates, General
Atomics/BrassRing as the first hold-control, and PDW as the mandatory shared
Rippling regression. General Atomics cannot count as a completed Company while
its legal-entity/membership proof remains absent. Fresh process inspection also
confirmed that the scraper, writer and scrape/FIRST-PASS controller lock files
name absent PIDs `485601`, `634767` and `283795`; the files remain untouched.
Historical broad cycles and the empty automatic profile registry prevent a
safe company-only run until an exact guarded recovery is owner-reviewed.

## Checkpoint — final-readiness independent audit, 2026-11-19

- Independent QA rejected the prior readiness document only because it still
  described F4 as open. This card and the readiness record now state the
  independently accepted, limited F4 transport-recovery result accurately;
  no later acceptance gate was closed by that correction.
- Fresh read-only protected evidence: no active scraper/coordinator/review
  process; queue, campaign, and autopilot disabled; empty automatic-profile
  registry; retained absent-PID locks unchanged. `CYC-B639C6D864EC` is the
  800-company in-progress broad cycle with 47 inventories (five blocked) and
  eight partially-applied sync plans. Its absent-owner
  RUNNING/SCRAPING workflow is recovery evidence only. Nineteen historical
  cycles are also in progress.
- Fresh local publisher preflight: one pending Opportunities `Last Checked`
  cell and 21 protected remote-edit conflicts. No Google connection or write
  was attempted. This is a new explicit blocker ahead of any bounded publisher
  request.
- A first bounded workbook inspection incorrectly treated local row identifiers
  as current remote sheet rows. It changed no data and was caught before any
  action. A corrected identity-bound reread located each conflict by immutable
  Opportunity ID and showed all 20 remote `Salary / Range` values are estimated
  salary ranges; the 21st conflict remains one missing Companies row named
  `Prepared`. The sole dirty delivery is the Saronic Technologies `Last
  Checked` update; it shares a protected salary conflict, so the normal
  publisher correctly excludes that row. No conflict, remote value, local
  record, or pending receipt was changed. This is an owner-approved,
  record-by-record reconciliation gate; no bulk import, overwrite, restore,
  or conflict clearing is permitted.
- QA lane ownership is complete for this checkpoint. Coordinator next action:
  obtain the required owner direction recorded in
  `PUBLISHER_RECONCILIATION_DECISION_RECORD_20261119.md` before Google
  publication can proceed.
- A separate read-only scope proposal now identifies `COMP-0024` Draper as a
  possible Workday third distinct-structure candidate. Its historical evidence
  includes a human-verification block and no current-cycle inventory, so it is
  not qualified or substituted. Independent QA accepted it only as an
  owner-reviewed scope-amendment proposal; it did not authorize activation,
  qualification, or completion. Owner approval, a matrix amendment, fresh
  public preflight, and the separate publisher gate remain mandatory. See
  `THIRD_STRUCTURE_SCOPE_PROPOSAL_20261119.md`.
