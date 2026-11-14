# CEKB validator v1.1 — Phase 13 integrity repair

Status: **deterministic validation passed; production résumé generation remains locked**. This sanitized release note excludes candidate claims, old résumé wording, source excerpts, and private evidence.

## Checks performed

| Check | Result |
| --- | --- |
| Original Phase 2 synthetic regressions | 56 passed, 0 failed |
| Canonical 17-table structural gate | 0 errors |
| Eligible factual records and published facts | 226 each |
| Current applicable controls | 109 |
| Publisher evidence references | 297 |
| Capability-index entries | 400 |
| Accepted capability mappings | 200, exactly two index entries each |
| Approved inter-fact relationships | 0 |
| Frozen original-source versions | 27, SHA256-checked |
| Independent research / writing / audit | Not performed |
| Production release status | INVALIDATED / LOCKED |

## Versioned changes

The v1.1 validator retains closed-schema and canonical full-payload SHA256 contracts, adds the typed RF WATTS unit, rejects nonempty exported columns beyond the schema while tolerating blank formatting-only XLSX cells, and handles narrowly approved atemporal pricing rules and open-ended annual rates without inventing periods. The private canonical database was repaired for source foreign keys, integer version numbers, timezone-aware metadata, superseded-control resolution, frozen-source locators, claim review metadata, canonical hashes, and evidence links.

The new release uses full-schema fact/control epochs rather than the weaker prior ID/hash list. The original Phase 2 validator and earlier historical releases remain unchanged. Executable validator v1.1 source, synthetic test fixtures, full source snapshots and detailed QA are stored privately in the user's Google Drive CEKB QA History / Evidence Archive.

Do not publish private career data or source documents into this public repository. Neither a validation pass nor this engineering note certifies actual model-context isolation, independent résumé quality, or submission readiness. Production remains locked pending independent tests and explicit release acceptance.
