# Integration automation coordinator status

Updated: 2026-11-18. This is the current working card for the isolated,
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
- No Jetson modification has been made during this roadmap run as of this
  checkpoint.

## Current position

- Coordinator checkpoint, 2026-11-19: the deployed F4 package is still
  byte-for-byte matched to the reviewed staged source and has a scoped rollback
  copy. It is deployed-but-unaccepted. The proposed real-HTTP proof corrected
  its private endpoint and generation-labeling defects, then added fsync-backed
  post-request checkpoints. Independent QA now accepts its source-level
  ordering: a durable `settlement_authorized` record precedes the only lane
  release, and a post-settlement evidence failure is recorded honestly. The
  actual Jetson proof, records, and deployed QA remain separate open gates.
- Goal: complete all six roadmap milestones and the final independent
  acceptance demonstration, with safeguards and scoped GitHub backups.
- Goal reference: `01a1f11f-e014-7493-8441-2f66502e23a9`; the persistent goal
  is active. Do not create a replacement goal.
- Main checkout: protected and heavily dirty. Do not edit, delete locks, or
  deploy from it. Its untracked coordinator source is read-only reference.
- Isolated feature worktree: `/tmp/job-search-helper-integration-automation`
  on `codex/integration-automation-20261118`.
- Coordinator development checkout: `/home/chris/job-search-helper_old/dev/wrapper-coder/repo`
  is on `development/wrapper-coder` at `0c45d61`. Its code is clean, but four
  pre-existing documentation changes are preserved; it has no GitHub remote.
- Milestone 1: 88% — the normal request consumer now validates and admits one
  immutable Company-only request, runs only that Company, and refuses to
  supersede unfinished work or accept an altered retry. Independent source
  review accepted the offline proof; guarded operational proof is still
  required.
- Milestone 2: 85% — durable Company revisions, reconciliation, and scoped
  request provenance are implemented and independently reviewed. A narrow
  current-Company revision lookup now exists for the coordinator boundary;
  the active local store now has the additive event/outbox foundation. The
  existing Sheets sync now baselines current Companies once without scheduling
  them, then reconciles later changes. The normal runner turns a confirmed
  change into an exact Company-only request. Guarded live proof remains.
- Milestone 3: 80% — bounded outcome classification, local immutable records,
  independently reviewed intake, and durable exact-receipt delivery into the
  existing coordinator are implemented. The independently accepted normal-run
  producer records bounded scrape facts without dispatching work; malformed
  checkpoint data is safely skipped. Qualified defects are held once for
  triage, never dispatched. The remaining gap is guarded live verification.
- Milestone 4: 68% — a held repair can be promoted only into a paused,
  Company-version-bound coordinator task. It cannot resume without a fresh
  trusted Company lookup, and stale work is re-paused before it can be claimed.
  The coordinator host now has a local-only, read-only resolver wired in; no
  service was restarted and no scheduler has been started in this work.
- Milestones 5–6: not started. F4 transport-recovery sub-gate remains open
  pending independent re-review and deployment-specific change control.

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

1. Prepare the accepted staged F4 proof for the guarded Jetson procedure:
   recheck deployed source identity, service health, rollback evidence, active
   lane state, and interactive administrator availability before a privileged
   restart of only `ollama.service`. Until a live proof passes, leave uncertain
   receipts lane-blocking.
2. Use the accepted M1-M4 reconciliation candidate only through an explicit,
   hash-recorded integration review; do not mechanically apply it to the
   protected checkout.
3. After interactive Google authorization is completed, run the bounded normal
   publisher only, then independently recheck the outbox receipt and the one
   remaining workbook date. Do not start a scrape.
4. Only after publication is clean, freshly recheck processes, locks,
   local/workbook cycle identity, deployed source identity, and sync health;
   then consider the guarded recovery command only if every preflight guard
   remains true.
