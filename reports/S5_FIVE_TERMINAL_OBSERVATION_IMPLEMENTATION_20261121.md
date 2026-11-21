# Five terminal Companies observation adapter — disposable implementation

Implemented only in `/tmp/jsh-retained-continuation.uqzSOPbJ`:

- `src/job_search_helper/exact_legacy_terminal_observation.py`
- `tests/test_exact_legacy_terminal_observation.py`

## Effect

`build_terminal_observation_binding(state, inbox, repository, cycle_id,
company_id)` accepts only one completed legacy `Companies` operation for an
exact `blocked`/`unsupported` State Company and blocked Inbox inventory.  It
requires cursor `1/1`, a matching original requested URL, current compact
profile, one unique local Company, no dirty/conflict/manual-choice/delivery
attempt, and no existing exact/receipt work.  Compact-visible fields retain
strict clean-baseline validation.  Compact-excluded fields are accepted only
when their current values exactly equal the frozen plan, and their baseline
presence/value digests are pinned as local-only evidence.

`observe_terminal_plan(...)` rederives the binding, uses only
`SheetsSynchronizer.plan_exact_scope(..., delivery_mode='observation_only')`
and `readback_exact_scope`, and returns an in-memory
`REMOTE_OBSERVED_MATCH` receipt.  It has no Inbox persistence API and does not
call normal publishing, remote-plan freezing, attempt claiming, migration, or
cleanup.

## Offline evidence

```
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
  python3 -m unittest -v tests/test_exact_legacy_terminal_observation.py
```

Result: **5 passed in 0.534s**.  The RangeSheets fixture is offline.  The
positive fixture has stale `Active Cycle ID` and `Record Updated` baselines,
exact compact readback, zero local/Inbox byte changes, and zero batch-request
bytes.  The remote subclass raises if a commit is attempted.

Negative fixtures hold before a remote read for visible baseline drift,
local-only current-value drift, an injected stale local-only dirty mark,
wrong shape, and existing receipt.  A remote mismatch creates no receipt and
no write.

## Limits

This is not installed and has no durable receipt table, terminal-state
transition, replay persistence, or `qualify_terminal_holds` integration.
It neither authorizes nor performs a live Sheets read, State/Inbox mutation,
publication, cleanup, or terminal disposition.  Those remain a separate
reviewed persistence/authority task.
