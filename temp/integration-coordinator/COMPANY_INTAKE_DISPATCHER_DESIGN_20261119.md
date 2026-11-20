# Company-event automatic intake dispatcher — source-only design

## Boundary

`CompanyIntakeDispatcher.run_once()` is a single bounded call for the existing
coordinator supervision/catch-up loop. It is not a scheduler and never
implements scraping, storage, Sheets publication, or FIRST PASS itself.

1. It invokes the existing `CompanyEventBridge` to durably convert current
   Company events to the ordinary one-company request.
2. It reads the existing company-only queue status. Unfinished cycles and
   paused/busy intake remain held; no request is widened or removed.
3. It checks the actual nonblocking flock for the normal scraper lock and the
   actual `scrape-first-pass/controller.lock`, then applies retained-work and
   release embargoes before spawning anything.
4. It records a request-id/digest reservation in a local SQLite control store
   before invoking the public project `job-search-scraper start` script through
   `Popen`. The tick remains responsive; it does not wait through scraping or
   FIRST PASS.
5. A subsequent tick treats `scrape-first-pass/latest.json` plus its workflow
   journal as the lifecycle authority. A stopped, unfinished workflow resumes
   through `job-search-scraper start --resume`; a completed workflow is not
   inferred from a PID. A crash before spawn is a recoverable `STARTING`
   reservation; an ambiguous launched request without a workflow is held to
   avoid duplicate work.

Child launch failure is stored as `CHILD_FAILED`; the scoped request remains
untouched. No service, Google account, protected data, or live process was
activated.

The control store defaults to **disabled**. `set_enabled(True)` is the explicit
durable local control needed before a host may call the dispatcher. This
overlay does not contain tracked host-supervision source, so production host
wiring remains deliberately open rather than being implied by this module.

## Focused checks

`PYTHONPATH=src:tests python -m unittest tests.test_company_intake_dispatcher tests.test_company_event_bridge tests.test_company_event_outbox`

Result: 53 tests passed. Coverage includes idle launch, busy/paused hold,
duplicate restart prevention, child failure retention, controller flock
observation, pre-spawn crash recovery, and restart of a durable paused
workflow through the public resume path.
