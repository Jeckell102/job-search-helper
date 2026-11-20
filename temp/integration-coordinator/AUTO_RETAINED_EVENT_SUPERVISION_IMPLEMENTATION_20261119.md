# Automatic retained Company-event supervision — implementation note

## Delivered scope

The existing Company intake dispatcher now has a second durable gate for the
retained route. It is false by default and is controlled separately with
`intake-retained-enable` / `intake-retained-disable`. `intake-status` reports
only whether retained key configuration is present, never the key itself.

For an exact event-bound request blocked by exactly one unfinished cycle, the
dispatcher verifies the active signed exception and current manifest using
read-only local authority before reserving retained ownership. It invokes only
the public `job-search-scraper run-retained-company-event` command. Key ID and
public key remain environment-only; neither appears in the command or status.

The journal has one request-owner row across normal and retained routes. A
request cannot reserve both. Retained child liveness uses PID plus Linux start
identity. A dead or crash-before-PID reservation restarts only the idempotent
public retained route. Completion requires the exact archived request and
`FIRST_PASS_RELEASED_CONSUMED` receipt; child exit alone is never completion.
A different newer request remains in `next-scan.json` while old receipt
recovery is recorded.

The pre-spawn owner token is written with the retained reservation and passed
only through the public child's environment. After a supervisor crash, the
next tick scans same-user `/proc` for that exact token and verifies the public
runner command and project working directory before adopting PID plus Linux
process-start identity. The token and key material are never included in
status or command arguments.

Adoption additionally requires the current UID, a non-zombie Linux process,
the exact wrapper-exec interpreter and argv shape, project working directory,
and a `PYTHONPATH` whose first entry is the project `src` directory. Token-only
or fake-module processes are rejected.

## Verification

Used the production wrapper virtual environment:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /home/chris/job-search-helper_old/.venv/bin/python -W error -m unittest tests.test_company_intake_dispatcher tests.test_sync_cli_lifecycle tests.test_company_intake_handoff tests.test_company_event_bridge tests.test_retained_company_event tests.test_retained_work_exception`

Result: focused/adjacent strict verification passed with the production wrapper
environment. Coverage includes a real subprocess adoption after the parent-side
post-Popen crash window and a real Ed25519 active-record plus manifest
revalidation preflight. `git diff --check` passed.
