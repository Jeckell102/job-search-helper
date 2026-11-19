# Selected recovery authorization/journal QA acceptance — 2026-11-19

Independent QA accepted the repaired isolated candidate at
`/tmp/jsh-selected-legacy-recovery-j291Qp`.

- Focused matrix: 27 passed (7 local recovery, 6 integration, 14 legacy).
- Forced crash after successful local commit leaves `PREFIX_VERIFIED`; retry
  reads immutable frozen signed claims before mutable live state, reaches
  `REMOTE_PLAN_FROZEN`, and reports recovery.
- Altered scope and newly expired authorization are rejected before journal
  creation. Test-only verifier remains opt-in; default candidate path uses
  Ed25519 verification.
- Independent fixtures confirm zero publication receipts and zero exact remote
  plans, with no Google/HTTP/scrape/queue action.

This accepts only authorization, local journal, and local-only adoption. Exact
receipt binding, remote intent/write/readback, production installation, and
any live pilot remain separate open gates.
