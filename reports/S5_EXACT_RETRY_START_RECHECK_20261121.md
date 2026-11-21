# Final optional exact retry admission recheck

**ACCEPT for the exact staged optional admission branch.** The original regression held on the corrected source, and the corresponding valid restart reused the genuine saved cycle.

| Reviewed file | SHA-256 |
| --- | --- |
| `scan_request.py` | `c5dbda4c01ab100a219b454e95db02cfd0d3372ed1123ec459b24b55b255d8dc` |
| `test_expected_repair_retry_admission.py` | `93996fb7333158db9ea7910cc61305229d64110930a1e44a843435706144a7ae` |

- The independent reproduction interrupted normal admission after checkpointing and before renaming the exact queue file. Changing the saved sole Company while retaining the real request fingerprint and binding caused the next optional admission to reject. Queue bytes, State, and the Jobs Scan Cycles mirror stayed unchanged.
- Repeating that interruption with the genuine checkpoint recovered the same cycle ID, kept exactly one cycle for the expected Company, and moved the identical queued bytes to `last-scan-request.json` once.
- All 17 tests in the optional exact admission and maintained generic retry replay modules passed offline. The optional branch checks current Company source and verifies the saved retry with the existing receipt binding. The no-option caller path remained compatible. [Revised admission boundary](/tmp/jsh-s5-exact-release-continuation.20261121/src/job_search_helper/scan_request.py:54)

This recheck used disposable Jobs and State databases under their normal scraper lease. The earlier rejecting report remains unchanged. No live or external operations ran.
