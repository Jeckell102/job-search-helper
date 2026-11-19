# Selected recovery final QA — 2026-11-19

Status: accepted in the isolated current-production adapter; not overlaid onto
the older feature mirror.

Independent final QA ran 105 focused tests: selected recovery integration,
selected legacy/local-plan/exact-cycle behavior, durable inbox behavior, and
publication receipts. All 105 passed.

Verified properties:

- Public apply uses the Inbox-owned selected-recovery journal and creates a
  sealed v2 local successor, with no receipt, remote intent, or remote write.
- The real ordinary exact-v2 publisher is the only release route. It enforces
  the unexpired signed authorization before it creates a receipt or intent.
- A Job History Source Hash remains a local row guard while the compact remote
  projection excludes that local-only field.
- An interruption after intent freeze resumes without replay; terminal cleanup
  archives the selected-recovery evidence.
- The historical fake receipt/journal path is absent from the accepted adapter.

Integration note: the existing feature mirror predates required production
exact-migration modules. A direct overlay failed collection with missing
dependencies, so it was restored rather than leaving a mixed or misleading
backup. The accepted source remains isolated at
`/tmp/jsh-selected-recovery-current-adapter` pending a dependency-complete
reconciliation against current production.
