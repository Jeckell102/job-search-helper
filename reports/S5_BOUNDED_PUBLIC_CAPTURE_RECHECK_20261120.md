# Sprint 5 Rippling public capture independent repair recheck

**ACCEPT** the exact repaired helper for its synthetic, owner-supplied capture contract. The prior mutable-binding provenance rejection is resolved. This review grants no live transport, verdict, or release approval.

## Exact review pins

| Artifact | SHA-256 |
| --- | --- |
| Repaired capture helper | `6a8ff763c69f7aeebf3da0f60b85a2d7deba17c9f2b20677d9a5e75db58bd571` |
| Repaired maintained tests | `45bb58b0e7a5a1ac329b59927c6e9204df55df0b94bae035f544dd8224439185` |
| Original independent probes, unchanged | `7776fb71bda52387dfbb30f6c1ff847a1ba5e9146518354b304299c87e4de78a` |
| New independent callback probes | `52d16b1d5304a1a0236bc110da621569961fae02e1fbd3f3ee8b68991a78c31b` |

The standalone original rejection remains unchanged, SHA `06781b03f8bc64d86aed64d01540cd18abdbe0f1fa46e58ad5fed8bb3f138c64`. [Original rejection](/tmp/jsh-s5-rippling-public-capture-independent.xAJY2FGx/INDEPENDENT_QA.md)

## Findings

- The helper forms canonical bytes for binding, window, Company projections and response policy before the first clock, ledger or transport callback. It decodes a private snapshot and uses it for all validated limits, Company inputs, dispatch and manifest binding digest. A subsequent capture-input comparison can hold the operation. It cannot change the data used to construct the manifest. The original failing provenance probe passed unchanged. [Snapshot serialization](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation/rippling_public_capture.py:78) · [Entry snapshot](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation/rippling_public_capture.py:243) · [Manifest handoff](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation/rippling_public_capture.py:294)
- Independent callback probes show persistent drift on the first clock or first empty-ledger read holds with zero attempts and zero transport calls. A binding change during the final complete ledger read or its following clock callback holds the capture with all 31 exact receipts retained. Restoring the original inputs leaves that spent ledger ineligible for another collection. A change restored within a single callback can go unobserved and leaves the original frozen manifest identity unchanged. This checks snapshot provenance at the defined boundaries. A subsequent consumer must revalidate current authority for its own use. [Callback comparison](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation/rippling_public_capture.py:125) · [Independent callback probes](/tmp/jsh-s5-rippling-capture-recheck.r86EhibI/test_callback_binding_recheck.py:10)
- Exact append and completion acknowledgement, same boot and bounded clocks, redirect and alias checks, pagination and original evidence byte accounting retained the prior independently observed behavior. The supplied clock and single-reservation ledger must be trusted. The reviewed transport must enforce one authorized GET per invocation with TLS and exact URL provenance, preserve raw ordered headers and original entity bytes, enforce elapsed and byte limits inside I/O, and distinguish successful completion from partial or quietly short responses. The helper compares the supplied response policy digest. Independent measurement of the loaded transport, durable ledger and capsule custody, and freshness at subsequent approval still belong to caller integration. [Transport and ledger contract](/tmp/jsh-s5-rippling-public-capture.lJ9DMuzb/dev/pre_release_validation/rippling_public_capture.py:224)

## Completed runs

- **42 passed in 3.17 seconds** in the focused run. This comprises 27 maintained cases, all ten original independent cases including the unchanged provenance regression, and five new callback cases.
- **215 passed, 11 deselected in 15.46 seconds** in the broader run including typed Rippling mismatch and retained issuance slot fixtures. The first broad run exposed unrelated environment problems. Pointing the real slot subprocesses at the same staged pytest support corrected their framework import. Eleven Playwright-dependent cases remained outside the independent run because Playwright was absent from the isolated interpreter. The author's 221-case report is separate from this independent count.
- Runs used system Python 3.11, a clean inherited environment, staged dependencies and disposable directories. Socket connections and lookup were disabled for the collector tests. The focused fixtures used synthetic HTTP responses throughout. No production source or application state, credential material, real request, or candidate source edit was involved.
