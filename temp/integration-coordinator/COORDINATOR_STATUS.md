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

- Goal: complete all six roadmap milestones and the final independent
  acceptance demonstration, with safeguards and scoped GitHub backups.
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
- Milestone 3: 76% — bounded outcome classification, local immutable records,
  independently reviewed intake, and durable exact-receipt delivery into the
  existing coordinator are implemented. The independently accepted normal-run
  producer records bounded scrape facts without dispatching work; malformed
  checkpoint data is safely skipped. Qualified defects are held once for
  triage, never dispatched. The remaining gap is guarded live verification.
- Milestone 4: 35% — a held repair can be promoted only into a paused,
  Company-version-bound coordinator task. It cannot resume without a fresh
  trusted Company lookup, and stale work is re-paused before it can be claimed.
  The coordinator host now has a local-only, read-only resolver wired in; no
  service was restarted and no scheduler has been started in this work.
- Milestones 5–6: not started.

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
- A fresh publication preflight found 60 pending system-field updates in the
  local outbox. Live read-only comparison confirmed that 59 already match the
  workbook and identified one remaining `Last Checked` date for Saronic
  Technologies / Product Manager. The bounded normal publisher reached the
  Google authorization boundary and made no change because interactive sign-in
  is still required. No scrape, recovery, lock, Company record, or user review
  choice was changed.

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

1. After interactive Google authorization is completed, run the bounded normal
   publisher only, then independently recheck the outbox receipt and the one
   remaining workbook date. Do not start a scrape.
2. Continue offline-safe repair workflow and release-gate work in the isolated
   feature copy.
3. Only after publication is clean, freshly recheck processes, locks,
   local/workbook cycle identity, deployed source identity, and sync health;
   then consider the guarded recovery command only if every preflight guard
   remains true.
