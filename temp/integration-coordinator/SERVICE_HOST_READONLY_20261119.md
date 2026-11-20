# Read-only MuleLab watcher reconciliation — 2026-11-19

Observed at `2026-11-19T23:29:39-05:00`. This was a read-only service
inspection. No unit file, drop-in, service state, intake control, key, Google
record, lock, or application state was changed.

## Authoritative unit identity and state

- User unit: `job-search-sync.service`
- Unit file: `/home/chris/.config/systemd/user/job-search-sync.service`
- Existing drop-in:
  `/home/chris/.config/systemd/user/job-search-sync.service.d/expiry.conf`
- Active state: `inactive` / `dead`
- Enablement: `disabled`
- Current condition result: `no`

## Existing watcher command

The merged unit has one watcher command:

`/home/chris/job-search-helper_old/.venv/bin/python -m job_search_helper.sync_cli watch --interval 60 --max-batches 20`

It runs from `/home/chris/job-search-helper_old` with the project `src`
directory on `PYTHONPATH`.

The exact `systemctl --user cat job-search-sync.service` output observed in
this check had SHA-256
`4eebb5afea183c056453e108ce9e26cf49805b78fe908018bc24190b71729980`.
The base unit file had SHA-256
`b99e510cbaeca8fa9c056c0989c3489e112e4fb7e614e391b16af954d50c076c`,
owner UID `1000`, and mode `0644`.

## Existing expiry guard

The drop-in calls the existing checked-in guard:

`/usr/bin/python3 /home/chris/job-search-helper_old/scripts/sync_expiry_guard.py 2026-10-27T00:56:08+00:00`

The deadline is expired. The earlier offline package incorrectly named a
system-wide service and a nonexistent expiry module. That package must not be
installed. Its owner was instructed to regenerate every target, verifier, and
rollback receipt for this exact per-user unit and real guard, followed by fresh
independent QA.

The expiry drop-in had SHA-256
`715ecf9626dc5a91b715c40ee7ed0aecec97455df118980441586c1fde8ec884`,
owner UID `1000`, and mode `0644`.

## Durable intake controls

The read-only application control output was:

```json
{"state":"COMPANY_INTAKE_CONTROL","enabled":false,"retained_enabled":false,"retained_configured":false,"dispatches":{},"ownership":{},"last_error":""}
```

This proves both durable gates were off at observation time. It is not a
substitute for a fresh preflight immediately before and after any later
installation.
