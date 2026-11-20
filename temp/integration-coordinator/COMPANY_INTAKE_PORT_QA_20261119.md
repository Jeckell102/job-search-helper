# Guarded Company-intake port independent QA — ACCEPT

## Scope

Read-only review of committed checkpoint `2b95dd7` only. Uncommitted retained
Company-event, runner, and test work was excluded. No protected/live state,
service, Sheets access, or source implementation was changed.

## Acceptance evidence

- The dispatcher accepts only the canonical one-company bridge identity:
  event schema, `company-event:<event_id>` request ID, exact singleton company
  ID, and matching source revision. The first-pass handoff independently
  repeats that identity check and requires the exact request digest before
  workflow creation.
- The dispatcher uses real nonblocking scraper/controller lock probes and
  retained/release lifecycle holds before reserve/start. Existing workflow
  reconciliation happens before the bridge; resume and completion require the
  exact durable request ID/digest binding.
- Intake is disabled by default. `intake-status`, `intake-enable`, and
  `intake-disable` persist through fresh command instances.
- Only `sync watch` invokes the dispatcher, and only after its bounded
  `writer.lock` scope has exited. `once`, writer-busy, and sync-error paths do
  not invoke it. The watcher reuses the current local repository and has no
  dispatcher loop or second scheduler.
- A normal intake failure is reported as
  `COMPANY_INTAKE_ERROR_RETAINED` without changing sync error/backoff state.
  If the intake error journal also fails, it is reported as
  `COMPANY_INTAKE_ERROR_UNRECORDED`; it still does not become a sync error or
  backoff.

## Evidence

No relevant source/test path differs from `2b95dd7` in the present worktree.

Strict adjacent command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.11 -W error -m unittest tests.test_sync_cli_lifecycle tests.test_company_intake_dispatcher tests.test_company_intake_handoff tests.test_company_event_bridge`

Result: **37 tests passed**.

This accepts the committed source port only; it does not activate the watcher
or authorize any live Company intake.
