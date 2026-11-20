# Independent QA — F1 external-Sheets bootstrap/catch-up — final re-review

## Verdict

**ACCEPT for the offline source-level F1 reconciliation slice.** This does not
establish live Google Sheets behavior, installation status, or the separate
idle/busy operational acceptance gate. No protected/live database, Google,
service, or lock was changed during this review.

## Repaired contract verified

* The first snapshot refuses an otherwise eligible ID-less Company before any
  merge, local helper-ID assignment, pending watermark, baseline, or intake
  event. A later external repair supplying a stable ID seeds history; the
  follow-on source change is exactly one catch-up event.
* Paused, removed, and incomplete ID-less historical rows use the separate
  excluded watermark. At finish, each is bound to its assigned local ID and
  reconstructed canonical fact; anything canonically eligible is refused.
  Initial excluded history creates no intake event.
* Stable snapshot records require a canonical fact and matching 64-hex source
  digest. Malformed facts, non-hex and mismatched revisions, and missing or
  forged excluded watermark content fail closed.
* Duplicate stable IDs are rejected both while preparing a live first snapshot
  and now while finishing an on-disk pending watermark. The new `pending_ids`
  preflight runs before the revision-insert loop, so a corrupt duplicate cannot
  partly seed history.
* The mandatory post-finish Companies reread preserves the first snapshot as
  history while turning an intervening source change into normal, durable
  catch-up work. Crash/restart, reorder, later eligible addition, source
  change, withdrawal, and repeated-pull idempotence remain covered.

## Independent duplicate-corruption reproduction

Using a temporary SQLite file only, I prepared a one-item stable-ID watermark,
appended an otherwise-valid duplicate item directly to the pending metadata,
and called finish. Result:

```text
RepositoryError External Company bootstrap watermark is corrupt. None 0 0
```

The fields after the error are, respectively: no baseline, zero
`company_revisions`, and zero pending intake events. This proves the previous
duplicate corruption path now rejects before any seed side effect.

## Fresh focused offline matrix

From `/tmp/job-search-helper-protected-current-reconcile`:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=src:tests \
  /home/chris/job-search-helper_old/.venv/bin/python -m pytest -q \
  tests/test_company_publication_controls.py tests/test_company_event_outbox.py \
  tests/test_company_event_bridge.py tests/test_sync_cli_lifecycle.py \
  tests/test_sqlite_migration.py
```

Result: **107 passed in 10.55s**.

## Remaining F1 acceptance gate

Before F1 can be called live/deployed acceptance, run an explicitly authorized
controlled Google Sheets verification against the installed source: prove the
first external snapshot remains non-enqueuing, a controlled post-watermark
eligible/source change appears exactly once in the existing outbox, and both
idle and busy normal runtime paths preserve the same gate. Those live checks
were intentionally not performed here.
