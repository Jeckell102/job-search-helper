# Persistent integration development

Python runs on MuleLab as the existing enabled `wrapper-development-host.service` user service. The Jetson supplies one inference slot. Python owns the FIFO queue, evidence collection, tests, budgets, durable checkpoints, and stage transitions. The AI receives a fresh bounded context for each decision. It supplies edits and short checkpoints; it cannot reset its budgets or certify live scraping.

## Everyday controls

In the Jetson Wrapper Coder chat:

```
/wrapper queue
/wrapper queue-pause
/wrapper queue-resume
/wrapper autopilot-start
/wrapper autopilot-status
/wrapper autopilot-stop
/wrapper status WRAP-xxxxxxxxxx
```

Status and queue commands are handled directly by Python and require no model calls. Pausing the queue lets an already-started action finish and stops the next action. Resuming the queue affects queued tasks only; blocked, exhausted, completed-review, and uncertain-recovery tasks remain stopped. A blocked company is recorded and Python selects the next queued company.

`autopilot-start` is the persistent backlog control. Python atomically selects the oldest untouched imported company only when no other company is queued or running. Every other company remains paused. The selected company uses the Jetson's single inference lane until it reaches offline completion or a fail-closed pause; Python then selects the next untouched company. `autopilot-stop` persists across service restarts and lets the current bounded action finish before holding the lane. Failed, budget-exhausted, previously activated, and operator-gated tasks are never retried implicitly.

Each selection receives a new integration-run identity and starts with zero model calls, tokens, sessions, and no model checkpoint. Model messages are rebuilt from that company's own receipts for every call. No chat context, counters, or summary from the prior company is carried into the next worker. Python retains the durable campaign order and historical receipts outside the disposable worker context.

The durable list is stored on MuleLab, not on the Jetson. This keeps the queue, source, tests, and receipts together and prevents a context reset on the small model from losing or duplicating assignments. The Jetson sees one bounded company packet at a time and performs one inference call at a time.

All files remain under `/home/chris/job-search-helper_old/dev/wrapper-coder` on MuleLab. Each batch company has `tasks/WRAP-.../repo`, its own source-only development copy, plus receipts, checkpoint, and HANDOFF files. `queue-base` is a saved source snapshot. Another company's draft never becomes the next company's baseline. No task data or development files are stored on the Jetson.

## Backlog import

The November 17 handoff is the source of company identity, current implementation notes, and saved claims. Its triage JSON supplies navigation hints. Historical failures are not fresh evidence. Import preserves every company in `import-report.json` and holds completed entries, existing validation/claims, adoption-only work, and entries lacking an existing test assignment. The latter need a specific test/development assignment before joining the automatic queue; they are not silently dropped or marked complete.

`import_integration_backlog.py HANDOFF TRIAGE SOURCE_ROOT OUTPUT` prepares company context documents, batches, and an import report. Install its `docs/backlog` into the source snapshot before submission. Submit each prepared batch on MuleLab with `python3 dev/wrapper-coder/tools/wrapper_task.py enqueue BATCH.json`. The file has explicit per-company development permissions. Identical batch resubmission returns the original task IDs and never resets budgets. A changed batch containing an already assigned company is rejected atomically. A different campaign is a distinct assignment; an explicit retry within the same campaign preserves the predecessor and records its lineage.

The authoritative original handoff is preserved. Queue claims and progress live in SQLite and task handoffs; review those before assigning the same company elsewhere. Only promote a tested draft after required live validation and review, then reconcile the original ledger. The workflow does not install drafts, publish Sheet updates, or claim integrated companies automatically.

## Work and recovery contract

1. Copy the approved source snapshot into an isolated company workspace and run its baseline tests.
2. Python retrieves bounded source excerpts and employer evidence, rendering a JavaScript shell once if necessary. Redirect aliases require observed provenance and company identity, not model assertions. Public evidence expires after 30 minutes.
3. Send a compact evidence packet and concrete assignment to the AI. Reuse unchanged read receipts. Three decisions without new evidence or an edit stop the company instead of looping.
4. Guard edits against current hashes, save durable action intents/results, run a host-produced diff and offline verification.
5. Record `AWAITING_LIVE_VALIDATION` or a precise blocker, then advance to the next company. Offline success is not a successful production scraper run.

New workflow tasks have at most 48 model calls, 120,000 accounted tokens, 80 automatic preparation actions, and their configured worker-session limit. The one-hour wall clock starts at first assignment, excludes initial queue wait, and includes subsequent pauses. A fresh context or service restart retains every counter. Older tasks retain their original creation-based lifetime and workflow rules. A restart with an unfinished tool intent pauses for inspection; it never guesses whether the action succeeded or replays an uncertain edit.

The model's compact packet can contain only excerpts of a retrieved file. Retrieval receipts prove collection, not full model comprehension. Live validation must still use normal scraper dispatch, prove employer scope, complete pagination/full descriptions and stable final membership, and retain explicit empty-state evidence when there are zero jobs.

## Verification

Run the coordinator, workflow, queue, importer, permissions, transport, and coding-tools tests before deployment. Queue acceptance covers long initial waits, cumulative budgets, duplicate submission, atomic rejection, FIFO advancement, global pause across restart, isolated drafts, and uncertain-action recovery. Import acceptance covers completed records, saved claims, missing test assignments, and identity disagreement.

## QA repair rollout — campaign membership

Campaign membership is explicit and separate from task progress. Imported work starts `HELD_FOR_CAMPAIGN`. Selecting it changes its disposition to `SELECTED`; a company pause changes it to `USER_PAUSED`, and exclusion changes it to `EXCLUDED`. Campaign start cannot undo a company pause or exclusion. The campaign scheduler claims only its selected member; generic queue tasks and other campaigns cannot enter that lane. Stopping the campaign preserves the selected company for an explicit restart.

Legacy records must not be adopted by guessing from `PAUSED`. Use `migrate_campaign_membership.py` with the reviewed task-ID file and required expected-cohort evidence. The November 18 migration is bound to the exact 102-task cohort, canonical identity digest, and original batch membership. Controls must be off, pilot unset, no active tasks or unfinished receipts, and database integrity must pass. Rehearse on a backup copy before applying while the service is stopped. An unreviewed pause remains paused; conflicts abort the entire transaction. Migration never starts work or resets accumulated budgets.

Repair rollout remains paused until all original QA findings and an independent final QA pass. A failed final QA creates a new report and a fresh repair/verification cycle. Passing coordinator QA does not replace live scraper validation or authorize automatic production installation.

## Control transition contract

Pilot startup prepares the isolated workspace before publishing scheduling ownership. It then rechecks the task, controls, unfinished actions, authorization, and remaining budgets in one SQLite transaction. If a pause, another start, a task change, or deadline expiration wins first, startup fails without creating a pilot slot or activating the task. Preparation alone never authorizes work.

Pilot, campaign, and generic queue modes are mutually exclusive. A pilot stop clears its slot and records the task stop together. Failed commands preserve the previously committed mode; a service restart reads that mode rather than guessing whether startup succeeded. Pause, exclude, and include preserve completed or awaiting-validation states. They cannot make a task eligible to resume across its operator gate.

## Canonical company assignment

Structured company identity owns the company ID, name, configured URL, assigned tests and source targets. The original imported objective is retained only for audit. Python builds the worker assignment from validated structured fields and freezes identity, assignment and evidence digests. Activation rejects any mismatch.

Each campaign/company pair has one current registry assignment. Exact batch replay returns existing IDs and budgets. Conflicting or duplicate batches write nothing. An explicit `retry` creates a successor only with controls off and a stopped predecessor; its history and receipts remain preserved, and the superseded task cannot resume.

For the reviewed legacy cohort, run the membership migration first, then `backfill_campaign_metadata.py TASKS BATCHES --identity` for a dry run and repeat with `--apply` only after reviewing the exact match. Run with the service stopped and all controls off. The identity migration binds only the exact reviewed campaign members, records original import provenance, preserves status and budgets, and must be a no-op on immediate rerun. Do not rerun this legacy backfill after explicit retries have added historical assignments.

## Exact edit scope and independent offline acceptance

The worker can edit only its exact assigned source and test files. A scope request in a checkpoint does not grant access. For an auxiliary file, stop scheduling and individually pause the task, then inspect `wrapper_task.py status TASK --json`. Review the returned `state_digest` and `state.edit_scope.digest`. A local approval JSON must contain exactly `paths`, `reason`, `expected_state_digest`, and `expected_scope_digest`. Apply it using `wrapper_task.py scope-expand TASK --approval-file APPROVAL.json`. This audited transition rejects stale state, active claims, unfinished actions, duplicate paths, or unsafe paths. It preserves company identity and budgets and requires fresh baseline/inspection evidence.

Before any edit, Python captures original tests, fixtures and test configuration outside the editable repository. Final offline verification runs both the current editable tests and those frozen assertions against the edited source in the offline OS sandbox. Both must pass, and receipts retain the acceptance bundle and source digests. Changed or missing baseline assertions stop the task; the worker cannot supply its own replacement acceptance authority. A separately reviewed new baseline and assignment are required in that case.

The legacy identity backfill additionally needs `--baseline-root QUEUE_BASE --baseline-manifest REVIEWED_JSON` to pin the original acceptance inputs for the exact untouched cohort. Review and rehearse this source manifest before deployment. It does not alter existing workspace tests or bless tests from a task that already ran.

## Inference accounting

MuleLab reserves each model call in a database transaction immediately before dispatch. The reservation rechecks pause controls, company ownership, identity, deadline and cumulative budget. Its commit is the start boundary: a pause that commits earlier prevents dispatch; a later pause cannot promise cancellation of that already-reserved call, but its returned tools must be discarded.

Model receipts contain request, tool and response digests and accounting evidence, rather than prompt contents. Finalization adjusts a reservation once using valid observed usage; invalid usage retains the reservation and stops for inspection. A crash or uncertain transport result never triggers an automatic resend of that request. Restart preserves counters and unresolved evidence. The existing Jetson endpoint is not claimed to provide provider-side idempotency.

An unresolved model receipt is a global safety stop across companies. A timed-out request may still be running on the Jetson. Python therefore blocks later inference reservations and pauses scheduling rather than assuming that a timeout freed the lane. Inspect the recorded request and reconcile the provider state explicitly; elapsed time or a new chat does not authorize replay or clear the uncertainty.
