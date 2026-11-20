# CompanyIntakeDispatcher independent QA — ACCEPT (final hardened re-review)

## Scope

Read-only review of `company_intake_dispatcher.py`, its focused tests, and the
source-only design note. No protected/live source or service was changed.

## Resolved in re-review

The dispatcher now reconciles `latest.json` before running the bridge, requires
the workflow's `company_intake` request ID and digest to match exactly one
`CHILD_LAUNCHED` dispatch record, resumes only that record, and completes only
that same record. It also validates canonical bridge request/event/company/
source-revision identity. The sidecar is atomically written after reservation;
the controller validates it against the current request before creating a
workflow, saves the immutable copy into `workflow.json`, updates `latest.json`,
then removes the one-shot sidecar. These changes resolve the earlier
cross-workflow resume/completion findings.

## Final hardening: forged request plus matching sidecar is rejected

The former controller-side gap is closed. Both the dispatcher and
`scrape_first_pass.company_intake_handoff()` now use
`is_event_bound_company_request()`. It requires the canonical event schema,
`request_id == company-event:<event_id>`, exactly one matching company ID, and
matching request/event source revisions before the sidecar ID/digest comparison
can succeed. Thus a forged `next-scan.json` and a matching forged sidecar are
not sufficient to create a workflow when the event/request identity is wrong.

`test_matching_forged_sidecar_cannot_bypass_event_identity` specifically
constructs that pair with a matching digest and `request_id = not-company-event`;
the controller raises `Blocked` before workflow creation.

## Earlier finding (resolved)

### Workflow ownership was not bound to the request reservation

`_workflow_state()` returns only the latest workflow stage. The workflow
schema has no request ID or immutable request digest. When an unfinished
workflow exists, `run_once()` can:

1. bridge a new request before reconciling that workflow;
2. reserve that new request; and
3. invoke `job-search-scraper start --resume` for the unrelated existing
   workflow.

When no request file exists, `_launched_request_id()` chooses the sole
`CHILD_LAUNCHED` row without proving that `latest.json` belongs to it.
Likewise, `_mark_workflow_complete()` updates every launched row rather than
the exact reservation whose immutable workflow binding was verified.

This has been repaired as described above.

## Earlier finding (resolved)

The dispatcher and controller now both check the canonical
request/event/company/revision relationships, so the controller does not rely
solely on sidecar provenance.

## Positive observations

The new journal is disabled by default. It records `STARTING` before spawn,
uses real nonblocking flock checks for scraper/controller locks, applies
retained/release holds, invokes an absolute public command by default, and
does not add production host wiring; the design note explicitly keeps that
open.

## Evidence

Focused strict command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -W error -m unittest test_company_intake_dispatcher test_company_event_bridge test_runner_cycles test_sync_cli_lifecycle`

Final hardened focused command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -W error -m unittest test_company_intake_dispatcher test_company_intake_handoff test_scrape_first_pass`

Result: 42 tests passed with warnings treated as errors. This includes the
new forged-request-plus-matching-sidecar regression. The earlier adjacent
strict command also passed 78 tests. Production host wiring remains explicitly
open, so this is acceptance for the source-only dispatcher checkpoint, not
live activation.
