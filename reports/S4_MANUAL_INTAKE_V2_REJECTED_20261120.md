# Independent QA — Sprint 4 Manual Company Intake v2

Date: 2026-11-20

## Scope

Read-only review of `/tmp/jsh-s4-manual-intake-v2.8WVknvUm` only. No production paths, network, credentials, service, worker source, worker data, or installation were accessed or changed. Test dependencies were the isolated `/tmp/job-search-helper-current-overlay` source and fixture tree.

## Pin verification

- `scoped_manual_pilot_intake_v2.py`: `3414ac18b52a03867e1f1f96d1ecf8bf1fe2090baa7358530e03747943263f76`
- `test_scoped_manual_pilot_intake_v2.py`: `0ebb15af37a7694a103565fc521fe31b10ea956a749348e2a28898e719236aae`

## Checks executed

```text
env PYTHONPATH=/tmp/jsh-s4-manual-intake-v2.8WVknvUm:/tmp/job-search-helper-current-overlay/src:/tmp/job-search-helper-current-overlay/tests python3 -m pytest -q test_scoped_manual_pilot_intake_v2.py
# 24 passed in 2.04s
```

```text
env PYTHONPATH=/tmp/jsh-s4-manual-intake-v2.8WVknvUm:/tmp/job-search-helper-current-overlay/src:/tmp/job-search-helper-current-overlay/tests python3 -m pytest -q /tmp/jsh-s4-manual-intake-v2-independent-qa.py
# 1 passed in 0.15s; negative probe reproduced the defect below
```

An additional fresh scratch-SQLite probe placed an unrelated local Company at the same user-facing row number that the new remote Company would occupy. The helper preserved that unrelated local row and created the selected local Company at a distinct local record identity.

## What held

- Exact approval digest, literal scope, Greenhouse board, non-legacy identity, native `sheetId` plus `tableId`, ordered headers, fixed metadata ID, and custody checks are narrowly enforced.
- Recovery is read-only with respect to Sheets; it requires the retained exact claim and fresh metadata/row/metadata readback.
- V1 claim content, missing claims, stale/moved markers, changed rows, changed header/table data, and the same fixed metadata-ID collision hold without local import.
- Local import creates a baseline, one revision/event, and a receipt within the local transaction; a scratch row-number collision did not overwrite unrelated local data.

## Release-blocking defect: foreign concurrent duplicate is not excluded

`start_new_intake` checks marker/row/marker and then sends one unconditional `batchUpdate`. The atomic request only protects the candidate's fixed developer-metadata ID. It has no Sheets-side condition binding the Company identity/board absence.

The saved negative probe installs, immediately before the candidate batch executes, a foreign metadata ID and a literal duplicate Company row. The candidate's metadata ID remains unused, so the atomic batch succeeds and appends its own row. The post-write recovery check then sees two matching Company rows, raises `RepositoryError('Multiple rows...')`, and leaves two remote duplicates while local intake remains untouched.

This violates exact custody/last-concurrent-marker expectations for any environment with another writer. The current preflight detects only races that use the candidate's fixed metadata ID. Do not approve external/manual activation until the protocol has a server-enforced uniqueness/admission primitive, or is restricted by an independently enforced exclusive workbook writer boundary that includes all external writers.

## Recommendation

Reject for activation. The local protections and ordinary same-marker collision behavior are good, but the external duplicate-row race can create unreconciled remote data despite the intended atomic append. Keep the candidate isolated; no source or data was modified by this QA.
