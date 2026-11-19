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
- Milestone 1: 65% — implementation is present; guarded operational proof is
  still required.
- Milestone 2: 70% — durable Company revisions, reconciliation, and scoped
  request provenance are implemented and independently reviewed. A narrow
  current-Company revision lookup now exists for the coordinator boundary;
  guarded live proof remains.
- Milestone 3: 50% — bounded outcome classification, local immutable records,
  and independently reviewed intake into the existing coordinator are
  implemented. The active Job Search Helper source now has the shared
  classifier; qualified defects are held once for triage, never dispatched.
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

1. Reconcile the Company-side bridge with the active Job Search Helper source
   without overwriting the protected, pre-existing local worktree changes.
2. Reconcile the durable Company-event bridge with the active Job Search
   Helper repository and normal runner without overwriting local work.
3. Design the normal Company-to-scrape handoff with one durable owner, then
   prove it in a guarded live test.
