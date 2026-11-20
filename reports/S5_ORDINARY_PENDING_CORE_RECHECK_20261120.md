# Independent recheck of the ordinary State-first handoff

2026-11-20 18:29 EST

**ACCEPT WITH ONE REQUIRED FOLLOW-UP for the staged handoff core.** Verified source pin `961b774a37e2f64ccc31708f40c6cbfdff676ad910137c88a2f82bdc79e1eccc`. The combined disposable run passed all 19 marker and 8 outcome/producer cases in 3.22 seconds.

- First write now checks the dispatch digest and canonical requested employer URL, verifies the owned physical State, Jobs and Inbox plus workbook and idle SQLite handles, then compares the exact marker after the Inbox write and readback. Re-arm checks stage and existing plan. The authority reader refuses duplicate keys, and a blocked inventory remains readable for reconciliation but cannot be exported to the verifier. `ordinary_verification_pending.py:51-107,208-253,270-335`.
- **Required replay check.** The already-PREPARED branch checks the initial marker against `prepared`, then calls `read_prepared_inventory` and directly returns its newly read cycle. The inner read checks its own before/after marker, so a different valid prepared marker appearing between the first and second reads could be returned for the original dispatch. Reuse the exact comparison already performed on a first write after final Inbox readback. No changes to the existing lease or store guards are needed. `ordinary_verification_pending.py:270-283,311-324`.
- The separate Jobs reader filters by indexed identity, checks exact canonical immutable evidence and matching indexed columns, compares the cycle, and refuses conflicting exact ownership. The generic producer skips both valid and malformed items bearing the private marker. These seams still need a caller that proves the current State owner, verifies fresh managed Jobs, and holds the shared leases. `ordinary_verification_outcome.py:11-49`, `scrape_outcome_producer.py:25-34`.

The initial rejection remains preserved. Real provider integration, exact publication proof, terminal outcome/State writes, and launcher wiring remain outside this recheck. No implementation edits or live actions were performed.
