# Allen exact source reconciliation decision

2026-11-22. Source and saved reports only; no application commands, production data, provider, Sheets, service, Jetson or shared-source writes. Root's S6_LEAN_NEXT_PILOT_CHECKPOINT_20261122.md records that the authoritative tracker and local Allen row genuinely still name Greenhouse. The installed registry already maps the exact supported stale source to https://jobs.ashbyhq.com/allen-control-systems. This lane did not refresh those live observations.

**Use external-first correction, then the existing field-aware local merger, then exact selected Company-event reconciliation. No new generic intake framework is needed.** There is no fully isolated installed public API combining the last two operations: the existing event reconciler scans all Companies. The smallest application change is an optional exact selection on that reconciler, preserving all current callers and the existing durable restart pattern.

## Existing safe components and one missing selection

- `SheetsSynchronizer.merge_remote` (sheets_sync.py:229-427) explicitly imports changed supplied fields. With `complete_snapshot=False`, one row containing stable Company ID plus only Official Careers URL and ATS / Source does not blank omitted columns or mark other Companies missing. Reuse it; do not pass a compact row to `import_companies_with_events`.
- `SQLiteRepository.import_companies_with_events` and `_import_rows_in_transaction` (sqlite_repository.py:414-459) materialize missing fields as blanks, replace the row/baseline, and refuse any dirty row. They are not the existing-row repair API.
- `SQLiteRepository.reconcile_external_company_events` (sqlite_repository.py:703-719) already checks the completed external watermark, runs a transaction, and uses `_record_company_event` (793-835). However, it iterates every Company. Add paired optional keyword arguments `company_id` and `expected_source_revision`: if both absent, retain the old full behavior; if selected, require exactly one existing Company, recompute and match its exact revision inside the transaction, then invoke `_record_company_event` for that row only. Missing/duplicate/mismatched selection fails before any event. No schema or new event type is required.
- `_record_company_event` already compares the latest semantic source digest, creates one monotonic Company revision/outbox event atomically, and returns no new event on same-revision replay. Its existing idempotency is the restart mechanism.

This exact selection is smaller than refactoring `merge_remote` into an externally nested transaction or adding a new callback. `SQLiteRepository.transaction` (265-275) uses BEGIN IMMEDIATE and is not nestable. Do not wrap the two existing public methods in an outer transaction. The installed normal `pull` itself merges first and reconciles afterward; preserving that supported two-transaction cut is sufficient when the selected entry always performs/replays both steps under normal ownership.

## Exact external-first order

1. Freeze the one genuine correction and its source evidence: workbook ID, COMP-0164 identity/name, current source revision, exact remote old ATS/URL, two new source values, installed registry/source pins. Use the fresh complete local row, baseline and dirty field set for preservation checks. Require the existing external event baseline; do not bootstrap the backlog as a side effect. Refuse an active/claimed Company, ambiguous identity, dirty/conflicted source fields, pending source delivery, or a conflicting active scope. Unrelated dirty fields remain untouched.
2. Under normal scraper/writer exclusion, freshly read only the selected authoritative Company control/source fields, and apply one existing guarded remote `Repository.commit` update with exact expected identity/source/control values and `append_if_missing=False`. Write only ATS / Source and Official Careers URL. Do not alter notes, decisions, salary estimates, local scan state, or other rows. Existing Sheets limitations around concurrent structural edits remain; do not claim an atomic server-side compare-and-swap.
3. Read back that exact remote row. Only a complete match to the approved after-state permits local reconciliation. For lost response, use readback; never assume it failed or blindly replay. A mixed or independently changed result holds. Preserve the immutable correction intent and observed before/after evidence in the caller's existing one-shot transcript.
4. Call the existing merger with only `{'Company ID': ..., 'ATS / Source': ..., 'Official Careers URL': ...}` and `complete_snapshot=False`. Compare the local guard again before entering it. Do not include unchanged Company name or other fields merely for convenience: even an echoed extra field may affect its baseline/dirty acknowledgement. The two selected fields must be clean and baseline-consistent before correction; unrelated dirty state survives.
5. Invoke the new exact selected reconciler for the expected corrected source revision. Read back the resulting revision/outbox record. This is the genuine external source migration event; it requires no manufactured toggle and no inference. Leave bridge delivery/admission to the next separately guarded step.

Local-first `mutate_company_with_event` is unsuitable here: it marks the source locally dirty and emits before remote confirmation, while bypassing the normal merger's source-transition protection. Replacing the full local row is also unsuitable.

## Recovery and protected older outputs

- Crash/uncertainty before confirmed remote write: fresh exact remote read; old state permits only the same guarded correction, desired state permits reconciliation, other state holds.
- Remote confirmed but local merge absent: rerun the same fresh read and selected merge; old local data remains durable meanwhile.
- Merge committed but event absent: selected reconciliation creates the one event from the new durable row. No refetch or second remote write is needed.
- Event committed but caller response lost: exact same revision produces no second event; recover the existing revision/outbox by Company and source digest, not a fresh invented event.
- Preserve `_hold_changed_company_source` (sheets_sync.py:192-211). It fences the Company and dirty historical outputs; old-source jobs are not silently revalidated by a changed URL. Existing source-fence conflicts may therefore be added intentionally, while record values and unrelated dirty fields stay unchanged. Do not clear that fence to make the subsequent pilot publish. Any exact new-attempt publication must retain its own source/provenance checks; this note establishes the origin seam only.

## Minimum tests and file scope

Application delta: `sqlite_repository.py` selected reconciliation only. Reuse existing `merge_remote` unchanged and use the existing guarded remote repository in the one-shot caller. Add focused cases in `tests/test_company_event_outbox.py` and/or `test_company_publication_controls.py`:

1. Real fake-workbook Greenhouse-to-Ashby two-field edit, narrow merge, exact event: every omitted local field and unrelated dirty entry identical; one Allen event; deliberately changed other Company produces no event.
2. Crash after remote update and after merge: same continuation yields exactly one event and no repeated remote update; exact replay is a no-op.
3. Wrong revision, duplicate/missing target, dirty/conflicted source or uncompleted external watermark: held before local mutation/event; no fallback to full reconciliation.
4. Existing source-change fence remains and old outputs stay held. Keep the original unselected reconciler behavior.

Existing tests to reuse: `test_external_reconciliation_seeds_once_then_emits_only_later_changes`, `test_external_reconciliation_rejects_use_before_safe_baseline`, `test_post_start_source_change_reconciles_to_one_outbox_event_only`, `test_crash_after_frozen_watermark_merge_restarts_as_one_catchup_event`, `test_source_change_stays_held_after_fresh_pull_and_repeated_retry`, and `test_late_old_source_output_is_held_by_durable_company_fence`. No need for another broad baseline suite.

## Measured source pins

- sheets_sync.py: 305c59767cf679b3d757f65c1d3e7eee2080e17c2df55ce8774cc6e62822d5fa
- sqlite_repository.py: 3ab772748e685a131f885c0eefa7bd8055ed5c22114d4f89204a6dce3d8ff742
- tests/test_company_event_outbox.py: a124881e2beccede76c195e03d68e59d548af3c943516254a6fd29c698845995
- tests/test_company_publication_controls.py: 9b93b432cfffb03d10aa375584ad4b898386989da84e8338f453ea62be1f0a1d

Paths are beneath /home/chris/job-search-helper_old/. This is a source-only recommendation, not a deployed command or a claim that Allen has a new event. A clean intake from the resulting event still does not alone prove the frozen model-choice/qualified-release/saved-retry completion. No display/transport failure occurred.
