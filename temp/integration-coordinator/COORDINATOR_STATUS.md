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
- Milestone 2: 92% — durable Company revisions, reconciliation, and scoped
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
- Milestone 6: 76% — F4 receipt/recovery source review and controlled Jetson
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
  sequential acceptance matrix remain. The independently accepted exact-cycle
  overlay is now installed in the protected checkout under the existing
  install lock with a 27-file rollback receipt. A separate installed-hash pass
  found zero mismatches, and 186 focused plus 180 adjacent protected checks
  passed. No live Google, scraper, service, database, queue, lock-deletion, or
  Jetson action was part of this install.

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
  record, or pending receipt was changed. The owner has now set a narrow
  salary policy: the spreadsheet estimate may be used only when the current
  posting extraction is truly blank; it can never replace a nonblank or dirty
  posting salary. The isolated-source guard accepts only the exact known empty
  compensation envelope (or blank), requires a numeric estimate, and passed
  63 focused synchronization checks. It has not been run against local
  protected data or Google. The missing `Prepared` Company remains held; no
  bulk import, overwrite, restore, or conflict clearing is permitted.
- Independent QA passed the new salary fallback safeguard. Its requested
  partial-envelope regression was added before the final 63-check focused
  synchronization/review run passed. Coordinator next action: install the
  reviewed guarded source, then perform a bounded identity- and
  current-state-checked reconciliation/readback under the existing roadmap
  authorization. The live publisher gate remains otherwise held.
- Guarded salary-fallback reconciliation is now accepted: 20 eligible
  spreadsheet estimates reconciled into blank local extractions, the sole
  pending `Last Checked` receipt settled without replay, and a final no-op
  Google readback confirmed zero pending rows/cells and only the intentionally
  held missing `Prepared` Company conflict. No scraper, broad recovery, or
  automatic queue was enabled. See
  `SALARY_FALLBACK_LIVE_RECONCILIATION_20261119.md`.
- Milestone 1 read-only Samtec preflight exposed two still-open gates. The
  legacy `CYC-B639C6D864EC` cannot be paused while its 47 saved inventories
  and eight partial plans remain unreconciled, and the direct normal CLI
  previously rejected the compact-profile `Opportunity ID` column before it
  could prove its safe queue refusal. Independent QA accepted the minimal
  schema-preservation repair; protected focused tests pass, but the real
  Google-backed dry run did not yield a usable terminal receipt and is not
  acceptance evidence. No Samtec request or scrape was created. Coordinator
  owns the read-only cycle reconciliation decision. See
  `M1_READONLY_BLOCKERS_20261119.md`.
- Read-only exact-cycle reconciliation found all 47 inventory payloads and all
  eight frozen plans structurally valid and cycle-bound, but 39 durable
  inventories have a stale `queued` checkpoint. More importantly, the current
  exact-cycle command runs unrelated global cleanup/manual synchronization
  before it reaches the named cycle. Coordinator/release lane owns the narrow
  scope hardening; no live cycle sync will run until independent QA accepts it.
- Independent QA rejected the first exact-cycle scope-hardening candidate:
  despite its named-cycle preflight, it still starts the normal synchronization
  worker, whose global pull and startup publication could affect unrelated
  data. The candidate test also did not correctly prove the isolation boundary.
  The rejection and concrete repair criteria are recorded in
  `EXACT_CYCLE_SCOPE_QA_FAILURE_20261119.md`. Coordinator/release is repairing
  it; the independent QA lane is concurrently defining the required narrow
  delivery and exclusion proof. This is the current focus. No live recovery,
  scrape, automatic release, or broad backlog action is authorized by this
  checkpoint.
- Independent QA has now **passed record-level containment** for the replacement
  exact-cycle hold. A named `sync --cycle-id` verifies only that the exact
  durable inbox cycle exists, then exits before the global synchronizer,
  Sheets pull/publish, state/pipeline, cleanup, review export, manual import,
  outcome delivery, or performance writes. Its focused tests preserve an
  unrelated dirty local row, coordinator outbox record, and second inbox cycle
  unchanged. This is deliberately not a scoped remote recovery: it has no
  selected remote write/readback and leaves the named inventories untouched.
  The protected-source compatibility lane owns installing the same containment
  guard with its own focused evidence; a future narrow-delivery design remains
  required before the 42 unblocked inventories can be processed.
- Protected-source containment is also independently accepted and verified:
  production `runner.py` returns immediately after its read-only exact-cycle
  validator and before repository/Google creation. The focused protected
  `test_runner_cycles` suite passed 16 tests. The scoped evidence is
  `EXACT_CYCLE_CONTAINMENT_QA_20261119.md`. Because the protected tree was
  already broadly dirty, this guard must be captured with a scoped release
  manifest/backup rather than a wholesale production diff. Current next
  action: design and independently test the dedicated identity-scoped remote
  publisher/readback; keep exact-cycle work, the Company-only request, queues,
  and broad processing held in the meantime.
- Independent architecture review now fixes the actual recovery design: a new
  selected-plan publisher must use the current remote repository's existing
  identity/expected guards, persist `SYNC_PENDING` before its one selected
  write, and require a fresh selected-row remote fingerprint match before any
  plan advance or inventory acknowledgement. Pending receipts are readback-
  only and never automatically replayed. The global synchronizer and local
  pipeline receipt path are explicitly disqualified. Implementation lane owns
  the isolated source/tests; independent QA owns the acceptance matrix in
  `EXACT_CYCLE_SCOPED_PUBLISHER_DESIGN_20261119.md`.
- Coordinator review rejected treating the first selected-publisher draft as
  deployable. It initially used a full-tab readback, unbounded remaining-plan
  commit, no Company control guard, inherited blocked-inventory retry, lacked
  digest-bound chunk/CAS semantics, and could acknowledge without first
  applying the frozen final state to the named cycle checkpoint. Those gaps
  are assigned back to the implementation lane and production remains on the
  accepted no-global hold. The live inbox audit further confirms that only
  eight inventories have frozen plans; 39 unblocked inventories have no plan.
  A separate read-only architecture lane now owns the exact local-planning
  design. No refetch, Google write, live recovery, or blocked-inventory retry
  has occurred.
- The exact-planner architecture lane has completed its read-only design and
  now owns an isolated module/test implementation. It will explicitly select
  bounded Company IDs, consume the existing durable payloads without fetch,
  use narrow local and remote Company guards, freeze an immutable plan and
  `LOCAL_COMMITTED` receipt first, then update only that Company's cycle
  checkpoint. It cannot reuse `LocalPipeline.run/stage`, publish, drain local
  dirty rows, block on failure, or iterate the whole cycle implicitly. Shared
  runner/inbox integration is deferred until the publisher and planner each
  pass independent QA.
- Independent QA **rejected** the first exact-planner implementation despite
  its otherwise sound isolation. Existing-plan crash recovery did not bind
  the retained plan and receipt to the exact saved inventory payload, so a
  stale/fabricated same-URL plan could advance the local checkpoint. The
  repair must persist and recheck payload/plan digests plus the full receipt
  binding/records/schedule and strengthen current-control evidence. See
  `EXACT_CYCLE_PLANNER_QA_FAILURE_20261119.md`. No production or live planning
  was attempted.
- Independent QA has now **passed the repaired exact planner**. New frozen
  plans seal the exact inventory payload, operation-record fingerprint, plan
  digest, typed active/unclaimed Company control evidence, and the exact
  `LOCAL_COMMITTED` receipt binding before advancing only that Company's local
  checkpoint. Crash recovery recomputes every digest and requires the full
  cycle/request/source/release/records/schedule receipt identity; absent,
  altered, ambiguous, pending, or confirmed receipts fail closed. The focused
  planner suite passes 13 tests, including missing-receipt, wrong-binding,
  changed-payload, and crash-after-save adversarial cases. No runner wiring,
  production planning, Google access, or live mutation occurred. The
  publisher lane is aligning to control-evidence version 1 and this exact
  receipt contract before a combined orchestration can be reviewed.
- Independent QA also **rejected** the first completed publisher candidate.
  Its 127-test focused regression passed and runner remains safely unwired,
  but invalid cursor domains, stale/missing Company provenance, terminal State
  holds, and final-identity collisions were not all rejected. Coordinator
  review additionally found cross-cycle receipt-binding ambiguity and a
  possible in-memory State mutation leak after a failed save. The publisher
  lane owns all six repairs and adversarial tests; see
  `EXACT_CYCLE_PUBLISHER_QA_FAILURE_20261119.md`. No production/live publisher
  action occurred.
- Current worker ownership: the coordinator owns integration, release gates,
  the restart card, and live safety; the publisher lane owns only
  `exact_cycle_sync.py`, its inbox support, and focused tests while repairing
  the six recorded publisher defects; independent QA owns acceptance or a new
  failure report. The planner is accepted and frozen except for the additive
  control-evidence version field needed by the shared publisher contract.
- Independent QA **rejected** the first terminal-hold qualifier. It was
  read-only, preserved blocked evidence, and passed four focused tests, but a
  same-Company/same-record receipt from another cycle could qualify the hold;
  the legacy proof was untyped, its cursor accepted booleans, and no live
  manifest revalidation/CAS boundary existed. The isolated terminal lane owns
  those repairs and adversarial tests. See
  `EXACT_RECOVERY_TERMINAL_QA_FAILURE_20261119.md`. No live or production
  action occurred.
- Independent QA has now **passed the repaired terminal-hold qualifier**. It
  requires exact terminal State and blocked inbox evidence, distinguishes
  absent receipt evidence from pending/mismatched/ambiguous evidence, accepts
  only the exact confirmed receipt, and permits legacy qualification only with
  a closed read-only proof envelope. Fresh manifest revalidation cannot reuse
  cached legacy evidence. Six focused tests pass, and no write/replay path
  exists in the component. See
  `EXACT_RECOVERY_TERMINAL_QA_PASS_20261119.md`. The exact pause adapter remains
  unimplemented and unauthorized.
- Coordinator integration review added an explicit bounded-selection gate:
  the scoped publisher may not iterate every pending Company in the named
  cycle. It must require a unique caller-selected Company list, reject empty,
  duplicate, blocked, unknown, and over-bound requests before remote mutation,
  and leave every unselected plan/inventory untouched. The combined
  planner/publisher ordering, crash boundaries, isolation fixture, and
  activation gates are frozen in
  `EXACT_CYCLE_COMBINED_ORCHESTRATION_DESIGN_20261119.md`. The publisher lane
  owns this API repair; runner wiring remains held.
- The publisher's first six-defect repair and explicit-selection tests reached
  152 passing focused regressions, but coordinator crash-ordering review found
  two further blockers before independent QA. A fully matching remote plan can
  reach final reconciliation while its receipt is still `LOCAL_COMMITTED`, and
  a crash after State finalization but before inbox acknowledgement cannot yet
  settle on restart. The lane is adding a readback-proven pending transition
  with zero replay and a narrow confirmed-receipt/final-State acknowledgement
  recovery path. Changed State or readback must still hold. Runner and live
  recovery remain on the containment return.
- Independent publisher re-review remains **REJECTED** after the crash repair:
  a `SYNC_CONFIRMED` receipt with a pre-end cursor could still enter the normal
  chunk loop and issue a remote commit when readback differed. Confirmed
  receipt state must be zero-replay: only an end cursor, exact full readback,
  exact frozen final-State projection, and cleanup are permissible. QA also
  requires an explicit exact final projection/digest rather than an
  under-specified subset comparison. The lane owns these adversarial repairs;
  no publisher is wired or deployed.
- Independent QA has now **passed the repaired scoped publisher component**.
  Confirmed receipts cannot replay a pre-end cursor; nonrecoverable State is
  receipt-lookup-only; full-plan readback can safely settle a local receipt
  with zero commit; post-State-save cleanup requires the exact confirmed
  receipt, end cursor, selected readback, current controls, and frozen final
  projection. The planner, publisher, and terminal qualifier now share one
  deterministic receipt derivation. The focused QA regression passed 159
  tests, and the lane's broader set passed 163. See
  `EXACT_CYCLE_PUBLISHER_QA_PASS_20261119.md`. Runner wiring and live recovery
  remain held pending combined orchestration QA.
- With terminal qualification accepted, a separate non-overlapping lane now
  owns only the durable exact-pause journal freeze/store in new files. It must
  refuse any residual unblocked saved inventory, bind the full remaining
  queued/inventory candidate set and every accepted terminal manifest, record
  State and request-file digests without mutation, and be idempotent only for
  an identical payload. It has no remote apply or runner authority.
- Independent QA has now **passed the phase-A exact-pause journal**. Seven
  focused tests prove authentic fresh terminal-manifest coverage, zero
  remaining unblocked saved work, State-ordered candidate derivation, full
  cycle and request-file binding, mode-0600 immutable storage, corruption
  refusal, and read-only pre-apply drift detection. The component has no
  remote or apply path. See
  `EXACT_RECOVERY_PAUSE_JOURNAL_QA_PASS_20261119.md`. Phase-B selected-row pause
  application and exact Scan Cycles finalization remain unimplemented.
- Accepted planner, publisher, terminal-hold, pause-journal, containment,
  tests, and evidence were committed as `6d2797a` and pushed to the private
  GitHub branch `codex/integration-automation-20261118`. `git ls-remote`
  independently returned the same full hash
  `6d2797a5225bc8fdf64c7b6703e73b9439f7721a`. Unaccepted orchestration and
  phase-B work were deliberately excluded from that checkpoint.
- The source-only combined planner/publisher orchestrator now requires the
  injected writer-lock assertion, an exact unfinished cycle, and one to five
  explicit locally prevalidated unblocked inventories. Eleven focused tests
  now include real Engine/State/Inbox/Memory and SQLite paths: normal
  end-to-end settlement, plan-save/State-save recovery, post-State-save cleanup
  with zero replay, second-Company hold isolation, unselected/other-cycle and
  request preservation, and unchanged local dirty/outbox rows. It is in
  independent QA and remains unwired.
- Phase-B1 now has a storage-only apply ledger with an immutable journal-bound
  run, predeclared chunk/State/Scan digests, monotonic acknowledgement-bound
  confirmation, and strict phase ordering. Its first QA rejected a causal
  `COMPLETE` gap; the repair now requires the full confirmed intent chain and
  an exact `FROZEN -> COMPLETE` compare-and-swap. Eight tests cover the added
  corruption/race cases. Independent re-review has now **passed** this repaired
  storage ledger. A `COMPLETE` run must prove every frozen chunk plus the exact
  State and Scan intents were confirmed at their frozen digests, and Scan
  confirmation rolls back unless the same transaction performs the exact
  `FROZEN -> COMPLETE` transition. This remains storage-only evidence and does
  not authorize remote pause application.
- Independent QA **rejected activation of the combined exact-cycle
  orchestrator on one remaining containment defect**: its injected
  `writer_lock_assertion` can be forged by a caller returning literal `True`,
  so it does not prove ownership of the existing normal scraper/writer lock.
  All other focused orchestration, planner, publisher, terminal, and pause
  storage checks passed (68 tests in 2.408 seconds), including selected-only
  behavior and crash recovery without replay. A dedicated lane now owns only
  a real non-forgeable lock gate plus contention proof; runner wiring and live
  recovery remain held.
- Independent QA has now **passed the repaired combined exact-cycle
  orchestrator**. Its public API internally acquires the real normal scraper
  lock derived from file-backed State before any State, inbox, planner,
  publisher, or remote access; fake assertion injection is no longer accepted.
  Real lock contention raises `WriterLockBusy` with zero protected access.
  Independent QA passed 170 recovery/planner/publisher/inbox/pipeline/sync/
  runner tests in 26.249 seconds and `git diff --check`. The source remains
  unwired, and no live or production data was accessed. See
  `EXACT_CYCLE_ORCHESTRATOR_QA_PASS_20261119.md`.
- The first full Phase-B executor lane completed its contract analysis but
  deliberately created no partial implementation because the frozen-run,
  intent, readback, State, and Scan crash boundaries require one continuous
  implementation and interruption-test pass. A fresh dedicated lane now owns
  only the new executor source and tests. The coordinator retains integration,
  release gating, evidence, and live safety. Overall roadmap progress remains
  approximately 82%; this is an active safety bottleneck, not an external
  blocker, and no user action is required.
- A fresh Phase-B executor candidate implemented the full frozen-run, selected
  Company chunk, readback-only uncertain intent, State, and exact Scan Cycles
  sequence and passed its own 77-test set. Independent QA **rejected** it on
  two reproducible activation defects: its public API accepted an arbitrary
  caller-selected lock path, and an individually oversized entry following a
  small entry could escape the 500000-byte chunk bound. QA otherwise passed a
  204-test adjacent regression and accepted the crash/scope/finalization
  structure. The executor lane owns only these two repairs and adversarial
  tests. See `EXACT_RECOVERY_PAUSE_EXECUTOR_QA_FAILURE_20261119.md`. Runner and
  live recovery remain held.
- Independent QA has now **passed the repaired Phase-B executor**. The public
  API derives the normal scraper lock from a present regular file-backed State
  database and actual contention proves zero protected access; caller path
  injection is impossible. Every entry is singleton-size checked, the former
  small-then-oversized case is rejected, and independent 75-entry evidence
  stayed within both 50-Company and 500000-byte bounds. Focused QA passed 36
  tests and the adjacent recovery matrix passed 206 tests in 28.11 seconds.
  The accepted hashes and full boundary are recorded in
  `EXACT_RECOVERY_PAUSE_EXECUTOR_QA_PASS_20261119.md`. Runner wiring and live
  recovery remain held pending their own QA.
- The accepted combined orchestrator, Phase-B1 ledger, full pause executor,
  tests, retained failure reports, pass reports, and coordinator checkpoint
  were committed as `c6504d6` and pushed to the private GitHub branch
  `codex/integration-automation-20261118`. Local `HEAD` and an independent
  `git ls-remote` both returned
  `c6504d635e62a2993b632809a048efd65931a46b`. A dedicated runner lane now owns
  only explicit bounded exact-sync command wiring and its tests; pause wiring,
  production activation, and live recovery remain held.
- Runner integration stopped without changes at a verified lock/API boundary:
  the accepted recovery API owns the non-reentrant scraper lock but requires a
  preconstructed Engine, State, inbox, local repository, and remote. Calling it
  from the existing locked runner would deadlock; constructing those writable
  dependencies outside the lock would weaken the accepted gate. A dedicated
  lock lane now owns a narrow active-context capability that acquires the real
  lock first, binds it to the canonical State path and current execution
  context, permits dependency construction under that lock, and authorizes the
  locked recovery core without reacquisition. This boundary must pass focused
  independent QA before runner work resumes. No runner or live files changed.
- Independent QA **rejected the first lock-capability design** because one live
  capability was reusable and a context copied after issuance inherited it;
  both cases reached State instead of failing before protected access. Other
  lock/path/thread/expiry/isolation checks and 80 focused/adjacent tests passed.
  The repair direction removes the escaping capability entirely: a public
  lazy-factory entrypoint will acquire the real normal lock itself, construct
  and close dependencies only within that lock, validate the exact canonical
  Engine State path, and execute the existing locked core. See
  `EXACT_RECOVERY_LOCK_CONTEXT_QA_FAILURE_20261119.md`.
- Independent QA has now **passed the replacement lock-owned lazy factory**.
  All capability/ContextVar/registry machinery was removed. The public factory
  entrypoint validates the request and canonical regular State database,
  acquires the exact normal scraper lock, invokes one dependency context only
  inside that lock, validates the Engine's exact canonical State path before
  protected access, and closes dependencies before release. Invalid inputs,
  wrong paths, and real contention invoke neither the factory nor State/inbox/
  remote access. Independent focused/adjacent verification passed 120 tests in
  6.75 seconds. See `EXACT_RECOVERY_LOCK_FACTORY_QA_PASS_20261119.md`. Runner
  wiring can resume; live recovery remains held.
- The accepted lazy-factory boundary, retained failure evidence, pass report,
  focused tests, and coordinator checkpoint were committed as `2e44444` and
  pushed to the private GitHub branch. Local `HEAD` and `git ls-remote` both
  returned `2e44444476163174e0ad499e7e1b4c73f20ab93f`. Runner integration is
  active against this exact accepted base; production and live recovery remain
  held.
- Independent QA has now **passed the exact runner integration**. Public exact
  sync requires one to five unique repeatable `--company-id` values with one
  exact cycle; invalid or unknown/blocked/finished/invalid-stage selections and
  unsettled releases stop before direct remote construction. All dependencies
  are constructed and closed inside the accepted recovery-owned normal lock,
  and the exact branch returns before global sync, cleanup, review, manual,
  outcome, or performance hooks. Independent verification passed 168 tests in
  10.73 seconds. See `EXACT_CYCLE_RUNNER_QA_PASS_20261119.md`. A fresh protected
  production preflight plus scoped source/rollback manifest are now required
  before the first one-Company live recovery action.
- Fresh protected read-only status now supersedes the older multi-cycle note:
  `CYC-B639C6D864EC` is the sole blocker, with 764 queued, three inventory,
  three blocked, two unsupported, 20 complete, eight partial, 47 inventories,
  eight plans, and 767 pause candidates. After the 42 unblocked saved items
  reconcile, roughly 725 unsaved queued Companies need an explicit exact
  recovery pause. Independent QA disqualified the existing pause apply path
  because it invokes global synchronization. It designed a separate exact
  terminal-hold manifest/readback and pause adapter that preserves the five
  blocked/unsupported inventories in place, journals bounded selected Company
  writes, and finalizes only the named cycle row. See
  `EXACT_RECOVERY_TERMINAL_HOLD_AND_PAUSE_DESIGN_20261119.md`.
  See `EXACT_CYCLE_READONLY_RECONCILIATION_20261119.md`.
- A separate read-only scope proposal now identifies `COMP-0024` Draper as a
  possible Workday third distinct-structure candidate. Its historical evidence
  includes a human-verification block and no current-cycle inventory, so it is
  not qualified or substituted. Independent QA accepted it only as an
  owner-reviewed scope-amendment proposal; it did not authorize activation,
  qualification, or completion. Owner approval, a matrix amendment, fresh
  public preflight, and the separate publisher gate remain mandatory. See
  `THIRD_STRUCTURE_SCOPE_PROPOSAL_20261119.md`.
- A host cleanup removed the ephemeral feature and reconciliation worktrees,
  but did not affect production or its job data. The coordinator removed only
  the stale feature-worktree registration and recreated the isolated feature
  worktree from the already verified local/private-GitHub branch. Its restored
  `HEAD` is still exactly `c689ebba5ede3c8b5189e88691550cf8c2d3855c` and
  the worktree is clean. Temporary reconciliation and independent-QA lanes
  were restarted with the same non-overlapping ownership.
- Fresh read-only production preflight acquired and released the actual
  `.state/scraper.lock` nonblockingly and `assert_release_settled` returned a
  settled state with no pending release journal. No scraper, synchronization,
  or data mutation was started.
- Fresh read-only Google preflight made five read requests and zero writes.
  `COMP-0035`, `COMP-0052`, and `COMP-0054` each matched exactly once between
  local authority and the compact Sheet on Company ID, Active status, provider,
  and careers-URL digest; all three local control rows have empty claim owner
  and token and remain bound to `CYC-B639C6D864EC`. Local Scan State is
  Complete for 0035/0052 and Queued for 0054. The compact Sheet has no row for
  that active local cycle, so remote cycle finalization remains a separate
  explicit gate and cannot be inferred from Company-row agreement.
- Production is still deliberately unmodified by the exact-cycle deployment.
  The eight accepted `exact_*` source modules and their seven focused test
  files are absent there, while production `inbox.py`, `runner.py`,
  `test_run_scoped_sync.py`, and `test_runner_cycles.py` differ from the
  accepted branch. Reconciliation must preserve the newer production
  scrape-to-FIRST-PASS behavior; direct file replacement remains forbidden.
- A second narrow Google read proved `Scan Cycles` has zero data rows (three
  reads, zero writes), rather than only a missing target identity. Combined
  with compact-v1 local-only Company controls, this disqualifies the accepted
  full pause executor from production activation as written. It safely fails
  before mutation, but a separate compact-profile repair must freeze and apply
  local authoritative versus remote-visible projections and explicitly handle
  empty-tab cycle insertion/finalization. This later gate does not broaden or
  release the backlog; the executor remains undeployed.
- Independent QA **passed the compact-profile Company control repair**. Exact
  recovery now reads claims/manual-hold state from local SQLite under the real
  normal lock, reads only remote-visible ID/status/URL from Google, requires
  exact agreement on shared controls, and uses the same composite six-field
  evidence for planning and every publisher path. Missing guard or any drift
  fails before receipt persistence or commit. Root reproduced 54 focused
  checks and independent QA reproduced the 158-test adjacent matrix.
- Overall activation remains **REJECTED** on the next compact-profile boundary:
  newly frozen plans still contain local-only Company/Job History fields that
  compact Google cannot accept. Read-only shape inspection also proved each
  of the three existing candidate plans ends with a Company operation
  containing local-only fields; 0035 and 0052 are already at their legacy end
  cursor, while 0054 is at 67/208. No legacy plan will be silently rewritten.
  A separate planner-projection lane owns deterministic remote projection,
  retained full local finalization evidence, manual/salary guards, and explicit
  nonzero-cursor legacy refusal before any live action.
- Independent deployment QA found the deeper authoritative boundary: inbox
  `sync_plans.cursor` is a **local SQLite apply cursor**, not a Google
  publication cursor. `LocalPipeline` applies the frozen operations to local
  SQLite and advances that cursor; only the separate synchronizer projects
  dirty visible cells to compact Google. The proposed direct exact publisher
  must therefore never send a legacy local plan to Google.
- Live read-only evidence confirms all eight current plans are legacy local
  plans with only `final`, `operations`, and `requested_url`; every cursor is
  nonzero (six 1/1 plans, 0035 at 19/19, and 0054 at 67/208). None has control
  evidence, sealed digests, projection metadata, or exact receipt binding.
  0035 includes 9 Job History + 9 Job Evidence + 1 Companies operations; 0054
  includes 105 Job History + 97 Job Evidence + 5 Opportunities + 1 Companies
  operations. All would hold under the new seal and none is qualified for
  direct Google publication. 0052 is not a valid live pilot candidate yet.
- The required production repair is now explicitly scoped as selected local-
  plan resume plus selected dirty-cell Sheets publication/acknowledgement under
  one crash-durable journal. It must qualify legacy nonzero cursors from exact
  local/remote readback, preserve manual/salary/source-hash/identity controls,
  clear only the selected acknowledged dirty fields, and never drain the
  global outbox. A dedicated design lane owns this contract; overall deployment
  remains **REJECTED** and production is unchanged.
- Production-based runner/inbox reconciliation is otherwise accepted in
  staging: current FIRST-PASS behavior is preserved, the public start-flag
  side-effect escape is closed, compact control changes are refreshed, and
  the isolated staged directory passed 191 tests. This candidate remains held
  until the local/remote durability path replaces the incorrect direct-publish
  assumption and is independently reverified.
- The exact local-durability design is now complete and coordinator-reviewed.
  It freezes version-2 local operations plus compact remote projection before
  mutation, journals local SQLite apply/readback separately from remote
  publication, treats all eight retained legacy cursors only as local apply
  progress, and requires an exact scoped SheetsSynchronizer plan/acknowledgement
  with readback-only recovery after an ambiguous write. It defines the 34
  no-plan path, legacy migration envelope, salary/manual/source protections,
  failure matrix, file ownership, and a 30-test acceptance matrix. See
  `EXACT_LOCAL_DURABILITY_DESIGN_20261119.md`.
- An unowned concurrent `exact_local_plan.py` draft and its tests were
  independently **REJECTED** despite eight narrow passing tests: it could mark
  local work committed without exact post-commit verification, accept an
  insufficiently bound plan digest, skip the local cursor/chunk/migration
  contract, and clear local delivery state without a receipt-bound confirmed
  Google readback. It is not wired, committed, deployed, or accepted. A named
  local-durability implementation lane owns replacement within planner/inbox/
  SQLite boundaries; a separate projection-seal lane owns only exact sync and
  recovery validation. Production and broad processing remain unchanged and
  disabled.
- Projection-seal integration is now accepted as a fail-closed prerequisite
  and saved locally as `775a79e`. It validates profile/schema/local/remote
  digests before controls or receipts, treats `sync_plans.cursor` only as local
  apply progress, and uses `exact_sync_chunks` plus the immutable receipt as
  the sole remote progress authority. Compact publication remains disabled
  until a matching local journal exists. The lane passed 58 focused and 91
  adjacent checks; the coordinator independently reproduced a 188-test exact
  planner/sync/recovery/pause/runner matrix. A local-durability lane now owns
  planner/inbox/SQLite journal replacement, while a separate exact-Sheets
  lane owns only selected-scope planning/write/readback/acknowledgement helpers.
  No production, Google, Jetson, or broad queue state changed.
- The accepted projection-seal/design checkpoint is backed up to the private
  GitHub branch. Local `HEAD` and independent `git ls-remote` both returned
  `775a79ec10f4b36bbf6af5e3b48a7559411c9048`. Later local-durability and
  exact-Sheets work is still in progress and is not covered by that verified
  remote hash yet.
- The version-2 local durability journal is accepted at `565b798`, and the
  exact selected-scope Sheets primitives are accepted at `332b2f9`. Root
  reproduced 111 exact planner/inbox/sync/recovery checks, 87 SQLite/local-
  pipeline checks, and 80 scoped-Sheets/compact integration checks. Both
  checkpoints are backed up to the private branch; local `HEAD` and
  `git ls-remote` matched
  `332b2f90fd16d6c3bdd776f07c9aaa561c20ab85`. Recovery orchestration wiring is
  active in a separately owned lane, while an independent lane audits the two
  accepted components read-only. Production and broad processing remain held.
- Independent combined-boundary QA has now **REJECTED activation** despite 166
  passing boundary checks and 87 passing SQLite/local-pipeline checks. It
  reproduced two missing adversarial gates: caller-asserted first-attempt and
  acknowledgement values could replay a remote commit or clear selected local
  dirty fields from fabricated readback without a confirmed receipt; and a
  valid blank-posting salary fallback plan could not equal the reconstructed
  remote projection because its visible estimated-salary guard was omitted.
  Repair ownership is explicit: inbox/sync/recovery owns a durable single-use
  remote-intent claim plus confirmed-receipt authority, while sheets_sync owns
  mandatory use of that authority and visible salary-guard reconstruction.
  Duplicate-write and zero-write-forged-ack cases are required tests. No live
  or production state was accessed by this QA or repair assignment.
- Independent QA accepted the source-level exact local-durability and
  exact-selected-Sheets candidate. Version-2 plans freeze the complete local
  stream and compact remote projection before mutation; every bounded local
  apply and APPLIED journal row share one SQLite transaction; restart recovery
  verifies rather than replays; and complete local readback is required before
  VERIFIED. Exact Sheets planning equals the frozen projection and never uses
  global discovery, pull, or publish. Scoped acknowledgement preserves newer
  edits, unrelated dirty rows, and unrelated delivery state while retaining
  manual, source-hash, and salary safeguards. The coordinator reproduced 94
  focused checks; independent QA reproduced 76 focused/adjacent checks with
  strict warnings. This is source-level acceptance only. Normal-command
  orchestration, a verified GitHub hash for this checkpoint, installation, and
  any live Google action remain open; production was not accessed.
- The settled candidate additionally resolves and persists each exact local
  row identity/row hint only after complete local verification, then
  revalidates that mapping on recovery. One coordinator review found and
  repaired a false-hold edge: when Source Hash changes locally as part of the
  frozen operation, the later Sheets guard now uses the final frozen value,
  not the pre-apply expected value. Independent QA accepted that correction
  and reproduced 78 focused checks. The coordinator's final combined local,
  Sheets, planner, publisher, recovery, inbox, and SQLite matrix passes 177
  checks with strict warnings. Normal-command orchestration remains the next
  open boundary; no live or production action occurred.
- The accepted exact-local and exact-Sheets primitive checkpoints are backed
  up to the private GitHub feature branch. Local HEAD, the local remote-tracking
  ref, and an independent `git ls-remote` query all returned
  `332b2f90fd16d6c3bdd776f07c9aaa561c20ab85`. The worktree was clean at that
  verification point. Normal-command orchestration remains unimplemented and
  is the active next task.
- Normal-command exact-v2 orchestration is now implemented and under final
  independent review. Offline recovery freezes, applies, and completely
  verifies the selected local stream before any remote attempt; then publishes
  only the exact compact projection through a durable per-chunk intent. A
  synthetic ambiguous write, a crash after remote confirmation/local
  acknowledgement, and an uncertain second chunk in a 105-job/106-operation
  company all recovered by readback without repeating local or remote work.
  The bounded recovery/publisher/local/Sheets/inbox matrix passes 104 checks,
  and the adjacent planner/migration/runner/scoped-sync/local-pipeline matrix
  passes 269 checks with warnings treated as errors. Full-suite and independent
  final QA is accepted. No production, Google, Jetson, or broad queue action
  occurred; the last verified private GitHub backup remains `332b2f9` until
  this candidate is independently accepted and committed.
- The combined repair for the durable remote-intent authority, forged-
  acknowledgement refusal, retained estimated-salary guard, and version-2
  recovery orchestration reached coordinator verification. Root independently
  reproduced 167 focused checks and 126 adjacent compact/SQLite checks with no
  failures. A broader 394-check regression matrix then exposed one relevant
  unaccepted edge: a compact version-2 recovery containing 105 new jobs could
  not reconstruct the frozen remote insert operations after local SQLite apply,
  because local post-apply baseline state was incorrectly used to infer remote
  insert shape. The candidate is therefore still **REJECTED for activation**;
  no commit, production install, Google write, or backlog release occurred.
  A scoped Sheets/row-scope lane owns that repair while independent QA reviews
  the entire uncommitted candidate. The same broad run also reproduced one
  unrelated pre-existing direct-sheet title-filter expectation failure; it is
  not being conflated with this integration repair.
- The compact insert-semantics repair removed the 105-job failure; root then
  reproduced 169 focused/adjacent checks and a 390-test broad integration
  matrix with no integration failures. Fresh independent adversarial QA still
  **REJECTED** the stable candidate on a remaining P0 trust boundary: a caller
  could claim a remote attempt, supply fabricated observed records and an
  acknowledgement directly to the public inbox confirmation method, and then
  clear selected local dirty fields with zero remote batches and unchanged
  Google state. The normal flow's readback does not cure that bypass. A narrow
  inbox/exact-Sheets/sync repair lane now owns removal of the public caller-
  asserted confirmation shortcut and must bind actual remote readback to the
  durable confirmation operation. The exact zero-write exploit is a required
  regression test. No commit, production install, Google write, or queue
  release has occurred.
- The preceding 105-job insert-shape rejection is **superseded by repair and
  independent ACCEPT**. Exact row scope now seals explicit insert semantics
  and reconstructs the frozen values/on-insert/expected split rather than
  inferring it from post-apply baseline state. The 105-job case publishes 106
  operations in bounded chunks, injects uncertainty after the second physical
  write, and completes on restart with every remote commit forbidden. Final
  independent QA reproduced 169 strict focused/adjacent checks and accepted
  local no-replay, per-chunk remote authority, exact guards, scoped
  acknowledgement, unrelated-state preservation, and full-profile legacy
  separation. The coordinator's final focused matrix passes 170 checks, and
  its adjacent runner/scoped-sync/local-pipeline matrix passes 270 checks with
  warnings treated as errors. One additional direct journal regression proves each new chunk
  receives exactly one attempt while a repeat at the same cursor receives
  none. Git checkpoint/remote-hash verification remains open; no live action
  occurred.
- A later adversarial review **rejected** the first confirmation hardening:
  its module-private capability token was importable and therefore could not
  prove a real Sheet read. That token and every Inbox confirmation method are
  now removed. The only remaining confirmation operations live inside
  `SheetsSynchronizer`; each performs the exact remote read itself before the
  durable transition, and no callable accepts caller-supplied observed
  records. A zero-write forged-record/acknowledgement regression enumerates
  all Inbox/module confirmation names, finds none, and proves state stays
  `SYNC_PENDING` with dirty fields intact. The repaired candidate passes 170
  strict focused checks, 270 adjacent runner/sync/local-pipeline checks, and
  52 pause/terminal/SQLite integration checks. Independent re-review is in
  progress. The pushed `d7eb1ab` remains a non-final checkpoint until this
  boundary is accepted and a follow-up hash is verified. No live action
  occurred.
- An intermediate source checkpoint was created as `d7eb1ab` and the local
  remote-tracking ref currently names the same commit. It is a recoverable
  private-branch backup, **not an accepted release**: its committed final-QA
  report correctly rejects the importable `_SHEETS_CONFIRMATION_CAPABILITY`
  design because arbitrary in-process code can import the same object and call
  the private inbox transition with fabricated readback. A subsequent
  uncommitted patch improves confirmed-chunk recovery but does not remove that
  fundamental bypass. Production and Google remain untouched. A dedicated
  higher-reasoning read-only architecture lane now owns the replacement design;
  implementation remains paused only at this confirmation boundary while
  independent QA and other non-mutating verification continue.
- A subsequent higher-reasoning review invalidated the later source-level
  acceptance claim at `14afd48`: two supported-API P0 paths are reproducible
  in in-memory fixtures. First, public inbox cleanup can delete the
  `exact_remote_plans` ownership marker while a receipt is still pending,
  allowing legacy reconciliation to mark it `SYNC_CONFIRMED` without any
  remote read or write. Second, the combined confirmation/acknowledgement
  operation accepts caller-controlled exact-plan row metadata; its remote
  operations can confirm Company 1 while local acknowledgement clears Company
  2's selected dirty fields. The candidate is therefore **REJECTED** again.
  A single cross-file repair lane owns durable finalization guards and
  server-derived local row evidence; independent QA is reproducing both
  exploits before accepting any repair. No production, Google, scraper, lock,
  job data, backlog, or automatic release state has changed.
- The subsequent cleanup and durable-row-evidence repair closed those two
  paths, and root reproduced 193 strict exact tests, 52 adjacent
  pause/terminal/SQLite tests, and 399 broader regression tests (with one
  third-party Python-3.11 deprecation warning). Fresh independent QA then
  found one remaining lifecycle defect: after a real exact remote confirmation
  but before local acknowledgement, the public
  `mark_exact_remote_locally_acknowledged` transition could be invoked without
  a matching `exact_local_acknowledgements` row. Public cleanup could then
  discard the inventory/plan/journal while selected local fields remained
  dirty. The candidate remains **REJECTED**. A narrow repair now requires the
  verified local application plus exact local acknowledgement evidence before
  either LOCAL_ACKNOWLEDGED or cleanup. No live or production state changed.
- The lifecycle repair is now independently **ACCEPTED at source/fixture
  level**. A premature local-acknowledged transition or cleanup after real
  remote confirmation, but before local acknowledgement, refuses without any
  inbox or dirty-field change; the state remains SYNC_CONFIRMED. The genuine
  combined local acknowledgement persists the matching application/receipt/
  acknowledgement/selected-digest evidence, after which LOCAL_ACKNOWLEDGED
  and cleanup succeed. Independent QA also rejected missing/fake repositories,
  wrong workbook/apply/receipt/acknowledgement bindings, malformed selected
  digests, pre-registration cleanup, legacy reconciliation, and cross-company
  row metadata. Its 13-file matrix passed 235 checks; root reproduced 194
  strict exact checks and 52 adjacent pause/terminal/SQLite checks. This is
  not a live or deployed acceptance. The next checkpoint is scoped commit and
  verified private-GitHub backup, followed by protected-source reconciliation
  and the still-required bounded operational gates.
- The confirmation-boundary replacement is now independently **ACCEPTED**.
  The importable token and all Inbox remote-confirmation methods are gone;
  only the Sheets synchronizer can advance durable confirmation, and it first
  performs the actual exact remote readback itself. A zero-write adversarial
  test proves fabricated rows and acknowledgement data cannot advance
  `SYNC_PENDING` or clear dirty state. A final legacy-reconcile guard also
  refuses to confirm an enrolled exact receipt through the older public
  recovery API. Root freshly reproduced 176 strict focused checks, source/test
  compilation, and whitespace validation. The
  earlier rejection notes remain as history but are superseded by this result.
  A final follow-up commit and three-way private-branch hash verification are
  now the active checkpoint; production, Google, Jetson, and live queues
  remain untouched.
- The accepted source/evidence checkpoint was committed and its local HEAD,
  local remote-tracking ref, and independent private GitHub query all matched
  `3246f230cb0e1991c111b693e668d0b4a4412289`. Three additional adversarial
  tests then arrived from the shared review workspace and passed without a
  source change: they reject a pre-confirmed legacy receipt at exact-plan
  enrollment, hold on a changed earlier remote chunk during restart, and
  refuse confirmation when the frozen binding changes during readback. The
  expanded focused matrix passes 179 strict checks. A test/evidence-only
  follow-up backup is the active finalization step; live state is untouched.
- Coordinator checkpoint, 2026-11-19 (current turn): role is release owner
  and coordinator; current focus is source-only reconciliation of the accepted
  exact finalization lifecycle into the protected MuleLab baseline.  The final
  repair was committed as `0a4691832a3364438fdb975fa03da58a1e3fbd70` and
  independently verified on private GitHub branch
  `codex/integration-automation-20261118`.  Independent fixture QA passed
  235 checks; coordinator reproductions passed 194 strict exact and 52
  adjacent checks.  It is source/fixture evidence only, not deployment or
  live acceptance.
- Fresh read-only MuleLab snapshot: no scraper, coordinator, publisher, or
  review process is running.  Retained controller (`283795`), scraper
  (`5325`), writer (`717646`), and review-writeback (`4`) lock-owner PIDs are
  absent; locks remain untouched.  `CYC-B639C6D864EC` still has 47 saved
  inventories and eight partial durable plans, so it remains an active
  recovery hold.  The protected checkout is broadly dirty and does not yet
  contain `exact_cycle_sync.py`; its inbox, publication-receipt, and
  sheets-sync sources differ materially from the accepted isolated candidate.
  No job data, lock, queue, Google record, scraper, release, or Jetson state
  was changed.
- Milestones retain their existing operational status (M1 92%, M2 92%, M3
  88%, M4 78%, M5 76%, M6 72%): live/company acceptance gates remain open.
  Current worker assignments are isolated and read-only: the coordinator owns
  protected-source/release reconciliation and the restart card;
  `protected_reconciliation_plan` owns the semantic merge plan; and
  `protected_compatibility_qa` owns independent compatibility and test-scope
  assessment.  Goal reference remains
  `01a1f11f-e014-7493-8441-2f66502e23a9` (active).
- Current blocker/next action: no Samtec or exact-cycle publication is safe
  while the stale broad-cycle records remain and the protected source lacks a
  reviewed selected-plan publisher.  Await the two source-only assessments,
  create a temporary protected-baseline reconciliation copy, then run only
  independently selected fixture/temporary-state checks.  Google publication
  still requires explicit approval of the concrete payload; broad backlog and
  unqualified automatic releases remain disabled.
- Both source-only assessments are complete.  The current protected source
  cannot receive `0a46918` by cherry-pick or wholesale replacement: it lacks
  the exact modules, while its newer compact-profile, Company-source,
  baseline-token, and salary guards must be retained.  A disposable
  source/tests-only copy at
  `/tmp/job-search-helper-protected-reconciliation-o8XL4Q` contains nine
  additive exact modules that compile.  A conflict-preserving seam pass left
  visible rejects only for `inbox.py`, `runner.py`, `sheets_sync.py`, and
  `sqlite_repository.py`; it did not replace protected behavior.  The first
  temporary test evidence identifies the missing exact-local journal and
  narrow Sheets APIs as the first real merge requirements.  See
  `PROTECTED_BASELINE_EXACT_RECONCILIATION_20261119.md`.  The coordinator now
  owns manual seam reconciliation; no worker owns production changes.
- The first manual seam is complete in the disposable copy only: additive
  SQLite exact-local journals and the Inbox v2 freeze/local-apply/local-verify
  state now coexist with the protected Company-event/outcome behavior.
  `test_exact_local_plan.py` passes 11/11 there.  Remote-plan registration,
  Sheets confirmation/readback, and runner wiring are intentionally still
  absent; this does not change the live hold or authorize any deployment.
- The protected-source reconciliation is now fully assembled in the sanitized
  disposable copy. The accepted final lifecycle repair was applied to the
  earlier production-based merge, which passed 186 focused checks and 264
  complete staging-package checks plus 180 protected-adjacent workflow checks.
  That vetted file set now matches the full sanitized protected copy, where
  186 focused and 180 adjacent checks passed again with strict warnings.
  Candidate source files contain no merge markers; preserved `*.rej` files are
  audit-only and excluded. Exact hashes are recorded in
  `PROTECTED_BASELINE_EXACT_RECONCILIATION_20261119.md`. Independent review of
  this exact candidate is active. No protected file, Google row, lock,
  process, database, queue, release, or Jetson state changed.
- Independent QA subsequently **REJECTED** the candidate after finding that
  terminal recovery could treat a caller-provided legacy readback-digest
  envelope as remote confirmation.  That proof could reach later pause
  finalization, so the prior source-level acceptance is superseded.  The
  isolated repair removes the legacy callback route entirely: completed plans
  now require their own durable `SYNC_CONFIRMED` receipt created by the narrow
  Sheets confirmation path.  The four residual `*.rej` merge artifacts were
  also removed from the disposable candidate.  The focused repair matrix
  passes 122 checks, but fresh independent QA is still required before any
  protected install.  Live Google publication remains separately
  approval-gated.
- A narrow additional Sheets planning seam was verified in that disposable
  copy: it constructs sealed exact operations from an explicit scope without
  any discovery, pull, prune, publish, remote read, or remote write.  It
  retains source-hash and blank-salary protections, rejects user-owned
  Opportunities and non-append Notes, and requires frozen baseline guards.
  Three focused planning checks and compilation passed.  The goal remains
  active; next is an independent review of the assembled candidate followed
  by the still-required protected install and live acceptance gates.
- Replacement-goal checkpoint: the terminal legacy-proof bypass repair is now
  independently accepted in the disposable candidate.  It removes all
  caller-supplied readback proof parameters, requires a matching durable
  `SYNC_CONFIRMED` receipt before terminal qualification, and removes residual
  `*.rej` artifacts.  Fresh independent QA passed 168 exact and
  protected-overlap checks.  The next safe action is a rollback-backed,
  one-file protected-source repair install; the former live recovery command
  remains disabled because its legacy cursor proves only local application,
  not Google publication.
- The exact protected overlay is backed up and three-way hash verified on the
  private branch at `79dd7969abe9b0440ff815abe9bccbe038e1cc30`. A guarded
  installer with pre-hash checks, the existing install lock, durable per-file
  rollback, atomic copies, and post-install hash verification is ready. The
  permission reviewer stopped it before execution because the protected
  checkout is dirty and five core targets are already modified or untracked.
  No protected file changed. Fresh explicit owner approval to replace those
  five exact targets and add the nine exact modules/tests is now required;
  this approval would still authorize no Google write, scrape, service start,
  queue release, database change, lock deletion, or Jetson action.
- The owner gave the exact dirty-checkout install approval. The guarded
  installer then installed and verified all 27 approved files in the protected
  checkout. The rollback receipt is
  `/tmp/job-search-protected-exact-backup-20261119T185825Z-2_4dpn9p/manifest.json`;
  a second SHA-256 verification checked all 27 installed files with zero
  mismatches. Protected offline verification passed 186 focused checks and
  180 adjacent checks with warnings treated as errors. No Google access,
  scrape, service restart, live-database change, lock deletion, queue release,
  or Jetson modification occurred. Milestones are now M1 92%, M2 92%, M3 88%,
  M4 78%, M5 76%, and M6 76% (about 88% overall). The next authorization gate
  is the concrete live Google/company acceptance payload; final independent
  end-to-end acceptance remains after that.
- Fresh post-install read-only status confirms there is still no active
  scraper/reviewer process and no pending Company-only request. Exact cycle
  `CYC-B639C6D864EC` remains the sole blocker with 47 saved inventories,
  11,313 saved jobs, and eight plans containing 233 operations: 92 reflected
  by local-application cursors and 141 not yet locally applied. Remote Google
  presence is not proven by those cursors. Davidson Technologies
  (`COMP-0035`) is the narrow first preview candidate because its local cursor
  is 19 of 19, but its legacy plan cannot be published until separately
  reconciled. The bounded preview and stop conditions are in
  `LIVE_GOOGLE_RECOVERY_APPROVAL_PACKET_20261119.md`.
- Correction after source-level cursor review: the 92/141 split is local
  SQLite application progress, not Google publication evidence. Davidson's
  cursor is 19 of 19 locally, but its remote presence is unknown. Its retained
  plan also predates the required publication seals, so the installed exact
  publisher will refuse it with `publication_projection_version_invalid`
  before remote access. The sync command has not been run and is no longer
  proposed. The next safe gate is a separately approved, selected-row,
  read-only Google preview with no commit, receipt, cleanup, or local state
  change; the approval packet has been corrected accordingly.
- The read-only preview tool was tightened for the retained plan's historical
  full workbook schema. It validates every frozen tab/field before remote
  access and exposes no commit API; seven offline tests pass. Davidson's real
  snapshot reaches the deliberately disabled remote boundary after all local
  validation. The read-only OAuth token has a refresh grant but its access
  token is expired, so an approved preview may refresh only that protected
  read-token file. No Google request has been made.
- The terminal-proof security repair is now installed in the protected source
  through the existing lock.  It changed exactly two files and retained a
  rollback receipt at
  `/tmp/job-search-terminal-repair-20261119T191420Z-aire17hb/manifest.json`;
  its status is `INSTALLED_HASH_VERIFIED`. The two protected hashes exactly
  match private commit `ca5d5d472b06a6f219ff06f37a11ad0bff43f258`, while the
  rollback copies match the prior installed hashes. Fresh protected offline
  verification passed 222 focused and 180 adjacent tests; independent QA
  separately accepted the source repair after 229 checks. No Google, scraper,
  job-data, queue, service, lock-deletion, or Jetson action occurred.
- The Davidson-only Google read preview has now completed. It
  returned `REMOTE_PROFILE_INCOMPATIBLE`: current `Companies` lacks the legacy
  plan's required control fields. The result has `mutation_performed: false`;
  no write, receipt, cleanup, replay, migration, scrape, queue, or local state
  change occurred. Davidson and `CYC-B639C6D864EC` are retained as explicit
  legacy-profile holds. Evidence:
  `DAVIDSON_LEGACY_PLAN_PREVIEW_20261119.md`.
- Post-preview state is unchanged at 47 inventories, 11,313 saved jobs, eight
  plans, 92 total local-cursor operations, and 233 frozen operations. The
  Davidson local migration assessment resolved all 19 identities: 17 still
  match exactly, while two Job History rows differ only in the protected
  human-review fields `Review Status` and `Decision`. The current compact
  projection would contain one Companies and nine Job History operations,
  with nine Job Evidence operations retained locally only. The unadjusted
  projection is not approved because it still contains the two superseded
  decisions. The required CAS, journal, guard, and preview contract is in
  `DAVIDSON_LOCAL_MIGRATION_ASSESSMENT_20261119.md`.
- F1 periodic external-intake candidate is independently accepted in its
  isolated source copy: a bounded scheduled pull/reconciliation observes
  post-start Company changes without turning two-second local polling into
  Google reads. It preserves the outbox/baseline on a failed pull and produces
  one event without a historical flood. The original private `_publish`
  callable seam was restored after QA caught a compatibility regression; the
  corrected 74-test suite passes. It is source-only pending guarded protected
  reconciliation and does not yet admit mid-run events into a scrape.
- F2/F3 exact release-binding admission candidate passed isolated logic QA but
  remains source-only: matching `COMPLETE` release bindings admit a retry;
  missing, mismatched, nonterminal, or rolled-back bindings hold its durable
  request before cycle creation or consumption. Its five required files were
  initially untracked in the copied source, so an exact sealed source package
  is now stored on private GitHub commit `8d5e805`. Full retry lifecycle,
  stale-result precedence, and live acceptance remain open.
- F1 periodic intake is now installed through the existing integration lock.
  Its rollback receipt is `/tmp/jsh-f1-intake-20261119T193843Z-s7odz7bf` and
  reports `INSTALLED_HASH_VERIFIED` for exactly three files. Protected offline
  verification passed 74 tests. This is source activation only: no scrape,
  queue admission, Google mutation, backlog processing, or automatic release
  was enabled.
- F2/F3 release-admission delta is now installed through that same existing
  lock. It first passed independent archive reconstitution: its sealed
  five-file package (`0f3f8c33c560...d32d2864`) was overlaid on a disposable
  copy of the current protected source and passed 65 focused tests. The
  guarded install then recorded
  `/tmp/jsh-f2-f3-release-20261119T194453Z-d03rx1s1/manifest.json` as
  `INSTALLED_HASH_VERIFIED` for exactly five files; a fresh protected run of
  the same 65 checks passed in 14.37 seconds. This is source activation only:
  no scraper, Google call, queue, release, job-data change, or automatic
  backlog processing was started. The implementation closes only the
  installation/immutable-binding admission slice; full retry lifecycle,
  stale-result precedence, and guarded live acceptance remain open.
