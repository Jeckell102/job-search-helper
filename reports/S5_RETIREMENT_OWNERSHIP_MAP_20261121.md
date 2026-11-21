# Owner-requested retirement of CYC-B639C6D864EC

**Existing supported cancellation/archive commands do not implement the requested retirement.** The smallest legitimate new operation is an explicit, archive-backed owner retirement of this exact cycle's execution authority, without claiming successful scraping or publication. Preserve original State, Jobs mirror, inventories, plans/cursors, receipts and tracker/review data; do not use Complete, Complete with exceptions or SYNC_CONFIRMED as retirement labels.

Read-only source review only. No application, database, Google, provider, lock, service or write command ran. This report uses the coordinator-supplied user direction and existing saved cycle context; it does not re-observe native data.

## Existing routes are not suitable

- `runner.interrupted_cycle_recovery_status` (`runner.py:1124–1178`) requires no saved inventories/plans. `runner.pause_interrupted_cycle` (`:1181–1224`) starts scoped synchronizers before/after changing the cycle. `Engine.pause_interrupted_cycle` (`engine.py:955–981`) edits Company controls, stages and the Scan Cycles mirror. This conflicts with the requested retained unfinished work and no tracker changes.
- `execute_exact_recovery_pause` (`exact_recovery_pause_executor.py:272`) requires exact terminal manifests, performs remote Company/Scan Cycles effects and is designed to account for settled saved work. Its prerequisite checks must remain intact.
- `cancel_selected_recovery` (`selected_recovery_runner.py:164`) archives only an untouched FROZEN selected successor, not the original retained cycle or partially applied plan.
- Explicit `fresh-full-scan` can supersede old cycles (`Engine.start_cycle`, `engine.py:652–721`; `requested_scan`, `scan_request.py:39`), and its tests preserve old Inbox. But it immediately creates a new cycle and Company effects, may supersede more than this one effective cycle, and is not standalone retirement. A later rescrape may use its normal authority; do not manufacture a fake new scan now.

## Minimum retirement semantics

1. Under the existing normal scraper then writer ownership, verify exact CYC-B639C6D864EC identity, current State and unique Jobs Scan Cycles mirror/scope, no active run/inference/remote write owner, and settled release/maintenance state. Refuse foreign or changing scope. Reuse real lock identities; never remove or replace locks.
2. Create a durable, independently read-back scoped archive before retiring anything: original raw State JSON, exact Jobs mirror row and control metadata, all cycle-owned Inbox inventory/plan raw payloads and original cursors, exact receipt/attempt/journal history, and relevant unsynced work/provenance. Preserve both source versions and original user choices. Fsync archive and its manifest. Retain the live records as well; no deletion or acknowledgement is needed.
3. Record a versioned explicit owner-retirement control entry for exactly this cycle, including user-request scope, reason/time, original state/mirror/archive digests and publication disposition **unpublished/unfinished work retained**. Its effect is only to remove verified retired execution ownership from admission; it is not a data-success or remote-write receipt. A missing/corrupt/stale archive or partial retirement stays held. To honor no tracker changes, keep the original State/mirror row bytes and use this validated local control overlay, rather than synchronizing an invented terminal status to Sheets.
4. Prevent the retired work from being resumed, staged, published or cleaned up automatically. The archive does not by itself isolate unsynced dirty cells: normal generic Sheets drain must not publish them later. Preserve dirty markers and existing receipts without marking clean. Freeze exact ownership where attributable; ambiguous dirty ownership stays held, rather than deleting or globally clearing it. A later independently owned scrape gets new attempt authority and must explicitly reconcile overlaps with retained dirty work.

## Exact affected seams; avoid a generic terminal-state bypass

- Admission: `scan_request._unfinished_from_views` (`:362–375`) currently unions local and mirror blockers and honors supersession only. `Engine.start_cycle` (`:652–674`) repeats the local/mirror checks; both must use the same verified retirement authority for this exact target. The qualified install owner also calls these admission views; do not add a blanket Retired/Archived string to the terminal set or ignore missing mirrors.
- Execution: `runner.resolve_cycle`, `Engine.check_admitted_cycle`, `Engine.resume`, `resume_local`, `resume_parallel`, and reconstruction must refuse the retired target before effects. Filtering only the normal start selector would leave explicit --resume or exact cycle calls open.
- Publication: `publish_exact_cycle`, exact pending publication entry points, and `SheetsSynchronizer.publish_batch/_publish_batch/once` must respect retained retired-work ownership. Existing exact receipt confirmation and cleanup guards remain unchanged. Never use `InventoryInbox.acknowledge` to enact retirement.
- Storage/control: a small separate retirement journal/control reader is appropriate because `State.save_cycle` (`engine.py:134`) rewrites JSON and removes embedded jobs; it is not a byte-exact archive operation. No Company, Job History, Job Evidence, Opportunities, manual_choices or review fields need editing. Original mirror remains authoritative historical evidence; a later cache refresh must not silently reactivate a verified retirement or hide a changed/mismatched one.
- F3: reuse `integration_release.activate_release`/`rollback_release` normal scraper lease and stable bootstrap's pre-import lock ownership; no release guard is disabled. The retirement verifier supplies a distinct owner disposition recognized by the same admission predicate. The original five blocked plans remain archived incomplete evidence, not false terminal receipts, and other cycles remain unaffected.

## Minimum checks and existing fixture locations

Reuse `tests/test_fresh_scan_request.py` (old Inbox preservation, default unfinished blocking, exact request replay), `test_exact_recovery_pause.py` (saved-work and stale-manifest holds), `test_exact_recovery_pause_executor.py` (real lock contention, replay cuts and unrelated preservation), and `test_release_admission_bootstrap.py` (lock-before-import and mixed-version refusal).

Add only retirement-specific proof: crash before archive verification has no retirement effect; verified retirement/replay leaves original record bytes and all job/review data unchanged; missing/tampered archive or changed mirror holds; explicit old resume/exact publish/global dirty drain cannot replay retired work; another unfinished cycle still blocks; fresh genuinely owned work can be admitted without declaring old work complete; restoration/reopening is a separate explicit operation, never implicit. Tests must show zero remote calls and zero new SYNC_CONFIRMED receipts during retirement.

This is a concrete implementation boundary, not authorization to perform a live retirement yet. The user has supplied the disposition choice; remaining work is implementation and independent verification of these exact preservation and no-replay guarantees.

All installed code/test paths above are relative to `/home/chris/job-search-helper_old/`.
