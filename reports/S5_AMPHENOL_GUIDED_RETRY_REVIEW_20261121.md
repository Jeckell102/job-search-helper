# Amphenol guided retry — read-only decision, 2026-11-21

**Use a fresh bounded successor with a separate trusted diagnostic. The
current native endpoint does not support supplying one.** Do not resume the
same stalled context, edit its database, change its phase, or reintroduce the
caller objective into model input. No live task or system was accessed here.

## Concrete diagnosis to convey

The saved live report records Amphenol Aerospace COMP-0490 returning a partial
25 of 39 advertised postings with `AcquireTM total changed or pagination
repeated.` The existing focused baseline passed. These are the observations
in `S5_AMPHENOL_FIRST_GENERATION_20261121.md`, not a new live check. The count
is a dated observation, not a required constant for the repair.

The inspected source has the exact reported AcquireTM SHA-256
`88893583bb01ed0b8878020d9b71ddb9043bbfcdb70d6e0eb6b2475bc8855392`:

- `src/job_search_helper/acquiretm.py:55-63`: the wait compares
  `document.body.innerHTML` with the supplied prior value.
- `:77-85`: that prior value comes from `page.content()` (the full document),
  then the adapter clicks the next page and parses immediately after the wait.
- `:86-92`: the existing overlap, total and complete-count checks hold repeated
  or incomplete results.

Comparing these different document representations does not establish that
the results listing changed. It can let the wait finish before the new page
arrives. That is a precise source-supported explanation to investigate,
**not independently proven live causation**. Ask Jetson to inspect these
spans, establish the smallest pagination-readiness repair and its regression
test, and preserve the existing employer, overlap, total, full-description,
timeout and stable-reread requirements. Leave the actual edit to Jetson.

## Why a plain retry or new objective is insufficient

The current source inspected is the saved wrapper snapshot in
`/tmp/jsh-s5-promoted-repair-isolation.jzhc_e8c` (coordinator SHA
`b9fe2de378bcf942e1a7123e3d3e727ec97c41c803703ef6a2bae982a6a74175`).

- `coordinator_identity.py:65-74,98-104` intentionally derives the model's
  assignment from canonical identity. `test_identity_integrity_qa.py:117`
  protects exclusion of contradictory audit-objective text. Preserve it.
- `coordinator.py:525-541` supports a fresh retry and bounded evidence refresh,
  but passes no diagnostic or guidance to the store. Extra caller fields do
  not constitute a supported guidance operation.
- `coordinator_store.py:788-860` creates the successor with fresh workflow,
  while preserving the predecessor, baseline and identity and checking the
  predecessor state and stopped controls. There is no guidance setter.
- `coordinator.py:967,977-991` already presents `workflow.operator_guidance`
  as trusted steering. Supplying that field is the missing interface.

## Smallest source adjustment

Extend the existing authenticated **retry** action with one optional bounded
trusted diagnostic, separate from the audit objective. Bind it to this
predecessor and the already-frozen Company/source identity. Its small closed
shape should contain the observed failure, the saved evidence digest and
diagnostic file spans with their baseline source hashes. Accept only existing
assigned file paths and bounded spans; it must not expand edit or URL scope.
Render that validated finding into the successor's existing
`workflow.operator_guidance` before the same transactional insert. Preserve
the existing predecessor compare, current campaign pointer, paused successor,
isolated workspace and single-pilot admission. Do not copy predecessor phase
receipts or claim its evidence has been recollected by the successor.

There is no need to add `required_edit_paths` or force implementation. Keep
normal baseline → inspect → implement progression and its existing evidence
checks. A diagnostic does not count as a tool read or validated repair.
No new endpoint, scheduler or model lane is needed. The only source seams
are the existing retry command and successor construction; existing callers
without a diagnostic keep their behavior.

A separate source-copy diagnostic note is safe reference material, but this
native retry path verifies the existing queue baseline and does not expose a
per-task alternate baseline selector. Merely writing such a note elsewhere
will not make it model input; changing the existing queue baseline would
instead fail its immutable-baseline check. Do not treat that as a no-code
native fix without demonstrating an already-supported enrollment path.

The smallest proof is one disposable retry round trip showing the diagnostic
in model input, the original objective still excluded, the predecessor and
receipts unchanged, and the successor still at normal paused/baseline state;
reuse the existing identity/retry tests and add refusal of an unassigned or
wrong-hash diagnostic span. Source review only here: no tests, runtime changes,
production files, coordinator data, Jetson, network or Sheets access.
