# Independent staged recipe QA

PASS for the staged recipe candidate, SHA256 `1bb6a807ca3e6356be29385d0ab3346dd94ef7fa81332a95d98de6a5f26258ef`.

51 executable tests pass: 29 independent normal-dispatch pagination/HTML boundary tests, 16 existing shared-board tests, and 6 independent recipe schema, hash, determinism, provenance and AST scope tests. The generated transport guard also passes all 305 URL/payload matrix cases.

Actual Jetson selection reproduces the staged output exactly. Unknown fields, wrong types or selection IDs, duplicate JSON keys, oversized JSON, changed source bytes and changed helper bytes are rejected. AST comparison confirms every pre-existing function and statement is unchanged except the additional Samtec-only transport permission and listing dispatch. Two Samtec helper definitions were added. Existing route, detail extraction, reconciliation and other-provider code remain identical.

Normal-dispatch tests retrieve all fixture pages and descriptions, reread every page, reconcile a changed final page, and reject missing/ambiguous/contradictory evidence, hostile pagination, duplicate IDs and overflow. The saved public-source selection was independently checked against all three hash-verified HTML pages and 148 unique IDs in the separate selection report.

This permits proceeding to an isolated live test. It does not certify live completeness or installation. This is AI-assisted configuration with host-written Python-generated listing and transport code, retaining the previously reviewed AI-authored route patch. Machine-readable report binds source and evidence hashes.
