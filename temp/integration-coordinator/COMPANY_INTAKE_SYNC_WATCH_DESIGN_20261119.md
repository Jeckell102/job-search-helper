# Company intake from bounded sync watch cycles

The normal `sync watch` loop now invokes `CompanyIntakeDispatcher.run_once()`
only after its bounded Sheets cycle exits `writer.lock`. It reuses the existing
local SQLite repository; the dispatcher independently applies its normal
scraper/controller, retained-work, release, and historical-cycle safeguards.

`sync once` never constructs or invokes the dispatcher. Intake remains
disabled in a new control store. These local, no-Google CLI controls expose
the state and make the operator decision durable:

- `intake-status`
- `intake-enable`
- `intake-disable`

Watch emits a separate JSON record with the dispatcher result. A busy or held
result is reporting only: the request remains durable and no child is started.
An intake exception is caught after successful sync, recorded in the intake
control store, and emitted as `COMPANY_INTAKE_ERROR_RETAINED`; it never changes
the Sheets sync `last_error` or its retry/backoff state.
If the intake error journal itself fails, the watcher instead emits
`COMPANY_INTAKE_ERROR_UNRECORDED` with both failure details and still preserves
the completed sync result and normal timing.

Focused validation:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python -W error -m unittest tests.test_sync_cli_lifecycle tests.test_company_intake_dispatcher`

Result: 59 strict related tests passed, including default-disabled status,
CLI enable/status/disable persistence across fresh commands, explicit control,
post-lock watch dispatch, busy/held reporting, and absence of intake in `once`.
No service, protected checkout, Google data, live scraper, or GitHub remote was
used.
