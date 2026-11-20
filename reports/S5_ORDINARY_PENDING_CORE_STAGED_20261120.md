# Sprint 5 durable inventory handoff and existing outcome

2026-11-20 18:29 EST

The coordinator staged the selected ordinary verification checkpoint and
Jobs prior-outcome reader in `/tmp/jsh-s5-ordinary-pending-core.L7cSsg4I`.
Initial independent review rejected the source boundary on stale dispatch,
State/Inbox custody, contradictory reads, and malformed checkpoints even
though 13 tests passed. The revised source binds the in-flight assignment to
the original cycle/request/Company/source/generation, compares the exact
requested URL, and writes the inventory digest and typed disposition to
existing State before the unchanged inventory goes to the inbox.

The original State row uses an atomic update with the exact earlier bytes
as its precondition. Both readbacks compare the descriptor-bound State,
Jobs and Inbox, their workbook, and idle SQLite connections. Duplicate
checkpoint keys, ineligible blocked inventories, changed dispatches and
same-key foreign inbox records hold. If State saved its digest but the inbox
save was interrupted, the resume path holds without recreating the payload.

The private Jobs reader checks the persisted immutable sender record and
indexed request, Company, source and cycle. A valid exact prior outcome
wins regardless of classification. Malformed or competing exact evidence
holds. The generic outcome producer skips any item carrying the enrolled
marker, including malformed marker values, so the generic path cannot
consume the first outcome while this item is staged. Existing ordinary items
without a marker still use the normal producer.

All 28 focused tests passed in disposable local databases. The combined
focused and Engine, runtime custody and source snapshot run passed 105.
Independent final QA accepted this pinned handoff, including rejection of
a valid replacement generation during replay. It did not review normal
worker wiring or deployment.

| File | SHA-256 |
| --- | --- |
| `ordinary_verification_pending.py` | `c2b38e2cbed6d9ab33e95a2163d572b08d10cc96d2531f5748dec0efa4986856` |
| `ordinary_verification_outcome.py` | `8f80ddc88b737a21fcf5e016cc68c661a3a05178aaba6da9bac585fe3973c7c3` |
| `scrape_outcome_producer.py` | `2fc2eed5dd6e99444d958540b6f47b7f8491e8589a78c3e75c0148de2858bd5f` |
| `test_ordinary_verification_pending.py` | `bfe46fca5fa8538cedb4db9006d3ef8d81deaa69aa5e82c01876b4b321685316` |
| `test_ordinary_verification_outcome.py` | `bcb6cacebbc0133ba2d50733d360e347f9bcfaee31882a18220f509097b18ada` |

Production entry points do not invoke this source. Next wire the measured
runner lease, verified absence of a prior exact Jobs outcome, the State-owning
queue handoff, the exact publication proof before inbox cleanup, and the
terminal Jobs-to-State recovery. Exercise default ordinary and qualified
paths under the complete acceptance harness before any live integration.
