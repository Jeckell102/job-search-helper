# Sprint 5 reviewed verifier tool-vector update

The owner-bound verifier now uses the independently accepted PDW current-name validator. The exact reviewed tools digest is `86723e7fdc0e4e8acdae2dbdc9516c93f0e4557c60ef3b75d17f20869bd3eac0`. The verifier source is `ae39cb34ab229eee22b66f34dbe2d1486d2f08f0e1de0acc43970a8d15bbff14`. The candidate, authority parser and capture parser stayed at their previous exact offline versions. [Checked source list](S5_CURRENT_TOOL_VECTOR_SHA256SUMS_20261120.txt)

MuleLab passed 454 combined tests. Independent QA passed 20 on the final pins. Both exact PDW name projections returned `VERIFIED_MISMATCH` with 114 metered offline reads and reused the same durable receipt. A stale validator returned `CHANGED_INPUT` at zero reads and kept the original one-attempt budget. Old and new verifier binaries refused each other's assigned work before any supervisor reservation. An old terminal receipt stayed bound to its original verifier. [Independent QA](S5_CURRENT_TOOL_VECTOR_INDEPENDENT_20261120.md)

The measured worker, replay capture and candidate vectors matched the receipts. State, Jobs and Inbox remained byte-equivalent across the proof. This was an offline composition against saved responses. Its receipt has no application authority, and it does not qualify a candidate for release.
