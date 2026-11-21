# Exact release-retry continuation components

November 21, 2026. The staged source is
`/tmp/jsh-s5-exact-release-continuation.20261121`.

The normal selector can now require the exact released retry. An empty
queue raises a scoped hold instead of returning to a full-scan caller. A
foreign full-scan request or altered canonical retry remains untouched.
The original independent QA found that the crash-before-queue-rename
path trusted a saved fingerprint without verifying saved ownership.
The correction checks the saved complete release and sole Company before
reusing the checkpoint, and verifies the current Company source. On genuine
restart the same cycle consumes the same queued bytes once.
[Original failure](S5_EXACT_RETRY_START_INITIAL_QA_20261121.md).
[Independent acceptance](S5_EXACT_RETRY_START_RECHECK_20261121.md).

The closeout method accepts one explicitly identified, already-published
retry. Under the normal scraper and writer locks it checks the matching
confirmed Inbox receipt and Jobs acknowledgement, updates only the local
retry checkpoint and Scan Cycles mirror, then records the one immutable
COMPLETE outcome. It recovers both the mirror-to-State and State-to-outcome
interruptions. The saved disposable Amphenol result retained all 18 local
jobs, the exact prior receipt, and unrelated cycles. Replay preserved the
same outcome. The closeout runs locally after publication.
[Author's source pins and results](S5_EXACT_RETRY_CLOSEOUT_HANDOFF_20261121.md).
[Independent closeout QA](S5_EXACT_RETRY_CLOSEOUT_INDEPENDENT_20261121.md).

The final composed focused sweep passed all 41 tests. The broader comparison
retained the same 24 previously failing legacy cases as its baseline, with
69 passing on the composed source and 57 on the baseline. The separate
legacy failures remain open as reported.

The next scoped implementation is to call these components in the maintained
release-owner path. Consume existing independent qualification through the
measured release controller, admit or resume only its immutable retry,
defer fetch storage to the existing exact publisher, and close and observe
the same retry. Native eligibility, installation QA and final deployment
acceptance remain open. Broad backlog and unqualified automatic releases
remain disabled.
