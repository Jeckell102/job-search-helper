# Higher-model review handoff — Job Search Helper integration automation

## Purpose

Review the staged, safety-bounded Jetson inference-control addition before any
deployment. This is a design and implementation review only. Do not deploy,
restart services, alter Google Sheets, run a scrape, alter locks, or change
production records.

## Plain-language system goal

Adding one eligible Company to the existing Google Sheets database must
eventually create exactly one company-specific scrape, publish the resulting
jobs through the normal Job Search Helper path, and begin the managed first
review. Work must be restart-safe, avoid duplicates, preserve manual user
choices, and be demonstrably safe before activation.

## Current roadmap position

- Milestone 1 — 88%: Company-specific request intake is implemented and
  offline-reviewed; guarded live proof remains.
- Milestone 2 — 85%: durable Company revisions and reconciliation exist;
  guarded live proof remains.
- Milestone 3 — 80%: bounded scrape outcomes can be delivered to a held-only
  coordinator intake; guarded live proof remains.
- Milestone 4 — 65% (planning estimate, not a passed acceptance gate): safe held-repair promotion and a staged inference
  recovery protocol exist; Jetson deployment and live protocol proof remain.
- Milestones 5–6 have not started.

## Existing external blockers and boundaries

- Interactive Google authorization is required before normal publication can
  be verified. The normal publisher stopped at that boundary without changes.
- The production scraper has historical interrupted cycles and retained locks.
  Do not delete locks, restart a scraper, or use recovery merely to test this
  protocol.
- The main checkout is read-only reference. Work is in the isolated feature
  directory below.
- User has authorized Jetson changes if needed, but every actual Jetson change
  must be recorded in its existing modification log with reason, verification,
  and rollback evidence. No Jetson change has yet been made.

## What is staged for review

Directory:
`/tmp/job-search-helper-integration-automation/temp/integration-coordinator/jetson-f4-staging/`

Files:

- `inference_control_store.py`: small local receipt database. It retains only
  request/owner fingerprints, timestamps, terminal state, a response digest,
  and bounded numeric usage. It never stores prompts, jobs, source code, model
  output, or exception text.
- `wrapper_inference.py`: accepts the pre-existing request shape unchanged.
  For a controlled request it verifies the payload fingerprint, reserves one
  request, and reports a durable terminal receipt. A duplicate does not invoke
  the model again. Model errors settle as `FAILED`; an already-requested
  cancellation settles as `CANCELLED`.
- `server.py`: stages protected status (`GET`) and cancellation (`DELETE`)
  endpoints under `/api/wrapper-control/<request_id>`, using the existing
  wrapper-host token mechanism.
- `test_wrapper_inference.py`: isolated unit checks.
- `test_wrapper_control_routes.py`: real local HTTP checks for authentication,
  ownership, status, and cancellation routing, with all unrelated services
  mocked.

Canonical shared receipt-store implementation and tests are in:
`/tmp/job-search-helper-integration-automation/temp/integration-coordinator/tools/`

## Evidence already obtained

- The original error-path defect was independently found: an AI backend error
  could leave a request marked running indefinitely.
- The repair was independently accepted: exception -> `FAILED`, cancellation
  -> `CANCELLED`, and the single-running-request gate is released. It stores
  no error content.
- The final focused run passed 31 MuleLab host/store checks and 8 staged checks
  (6 inference checks plus 2 HTTP-route checks). The 8 canonical receipt-store
  checks are included in the 31, not additional checks.
- Final independent review accepted this as a staged stopping point, with
  deployment and live service verification still required. The code checkpoint
  is `8b5081a`; the subsequent status checkpoint is `88bcd7f`.
- All assigned workers are finished. Implementation is paused for this review
  at the user's request. The full six-milestone objective remains incomplete.

## Required review questions

1. Can a duplicate, stale, or altered request cause a second model turn?
2. Can a request become permanently running after an error, cancellation, or
   transport loss? Is the terminal receipt state sufficiently conservative?
3. Do the new status/cancellation routes expose anything unnecessary or permit
   an unauthenticated/unauthorized cancellation?
4. Does either route weaken existing wrapper authentication, normal legacy
   inference, task isolation, or private-data boundaries?
5. What exact additional tests or safeguards are required before a cautious
   Jetson rollout? Separate must-fix issues from optional hardening.

## Expected review output

Return `ACCEPT`, `ACCEPT WITH REQUIRED FOLLOW-UPS`, or `REJECT`. Cite exact
file and line(s) for each finding, explain the concrete failure mode, and list
the smallest test that proves the fix. Do not make live changes.

Save the complete review to:
`/tmp/job-search-helper-integration-automation/temp/integration-coordinator/HIGHER_MODEL_REVIEW_RESULTS.md`

Include the reviewed Git commit, files inspected, commands actually executed,
test outcomes, concrete findings, unresolved uncertainties, and an ordered list
of next actions for the returning coordinator. Verify concerns against source;
the earlier acceptance and passing tests are evidence, not a reason to assume
the complete protocol is safe. In particular inspect process restart, errors
after the model returns, and the host's use of retained status/cancel receipts.
Writing this review report is authorized; implementation changes are outside
this review assignment. The returning coordinator must read the saved report
and current coordinator card before resuming implementation.
