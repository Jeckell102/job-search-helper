# Independent v2 staged QA

PASS on the refreshed actual MuleLab candidate. 66 executable tests pass: 44 independent normal-dispatch/HTML/real-detail tests, 16 existing shared-board tests and 6 independent schema/hash/AST/provenance tests. All 148 captured actual descriptions, titles, locations and departments match independently parsed source text. Invalid identity, missing or ambiguous fields, truncation and script-only evidence fail closed.

The transport guard is AST-identical to the prior 305/305 tested version. All eight actual Jetson choices are request-valid and deterministically generate the reviewed source. Three current production source files were refreshed in the isolated copy and their hashes rechecked before rerunning tests. Source and harness hashes are bound in the JSON report.

Candidate SHA256: `2c08149e746b98f970d6ed98f2944dde3c51db0e3cb4b2f69c728b7a3c706847`. Ready for a fresh isolated live run; no live success, installation or publication is certified.
