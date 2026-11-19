# Selected legacy recovery receipt-integration design — 2026-11-19

## Decision

Keep the accepted prefix primitive local-only. Add a dedicated signed selected-
recovery journal and runner; promote only a fully locally verified successor
into the existing exact-v2 receipt/readback pipeline. Do not overload the
complete-cursor Davidson migration journal.

## Phases

1. Verify an external Ed25519 authorization envelope before any writable
   database opens. Bind action/version, exact cycle/company/workbook, legacy
   and inventory digests, verified prefix/readback, successor plan/projection,
   and expiry. Private signing material remains outside MuleLab/Git.
2. Add `exact_selected_legacy_recoveries` with immutable evidence and monotonic
   states `FROZEN -> PREFIX_VERIFIED -> LOCAL_COMPLETE -> REMOTE_PLAN_FROZEN`.
   A selected successor replaces only its selected legacy plan after complete
   local verification; all changed evidence holds.
3. Add explicit preview (read-only SQLite) and apply (selected local-only under
   writer lock/release-settled control) commands. Apply journals the prefix and
   applies only the suffix; it creates no receipt or remote call.
4. Only after local completion use the existing exact-v2 receipt/remote-intent/
   readback path. Receipt binding includes authorization digest; mismatched,
   expired, or missing authorization holds before receipt/intent/write.

## Non-negotiable boundaries

No normal scraper, broad resume, queue route, automatic retry, or automatic
release may invoke this path. Exact remote publishing remains a later explicit
command after independent QA. Preflight must also hold if legacy cycle request
identity cannot satisfy exact receipt semantics.

Required tests cover forged/expired/wrong-scope authorization; no-write preview;
prefix/suffix restart; journal collisions; foreign records/manual fields;
receipt authorization binding; readback-only recovery; and unselected company
isolation.
