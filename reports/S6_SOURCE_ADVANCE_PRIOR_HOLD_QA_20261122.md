# Independent source-advance recheck

The original interrupted **durably sealed** record now resumes. With the approved predecessor and exact before-image still active, the new branch checks the sealed relative paths, package manifest, predecessor journal metadata and every expected before/staged endpoint. It reuses the record and only then writes PREPARED, applies the reviewed five files and commits the receipt. The reviewed passing fixture exercises this cut and the prior rollback after PREPARED.

**HOLD for one directory durability barrier.** An interruption between the record rename and its initial parent-directory fsync can leave a visible record whose directory entry has yet to become durable. The reuse branch should fsync that same parent after revalidation and before returning to write PREPARED in the separate state directory.

- Installer SHA-256 `73e0d60491dad9af95a475b816a5c7b88e083e9fd4707ee4d4b8b6677e3d56d3`
- Composed fixture SHA-256 `54e99d5b34941eab6a74d5280deb2e1be4a34acc92aa6f9af9ff8659dcffc5e7`
- Prepared package SHA-256 `9e6a0d04a5d932dff086f30a8783b9d0c452a89a2d80ff768ec6e960ac2ef5a4`

Source-only review of the existing fixture and reported passing run. Native exclusion and approval remain separate.
