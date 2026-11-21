# Initial enrolled retry receipt review

November 21, 2026. **REJECT the original helper.** SHA-256
`6b76943af45a48d5f10cf9883bd5a771af824fdbf1c6ba5f0ef076c1ee72ccfd`.

The initial implementation found exactly one Jobs outcome but followed its
State cycle ID without checking for another saved owner of the same
immutable retry. The independent fixture duplicated the admitted State
cycle while retaining the genuine confirmed publication and outcome.
The original helper still reported `RECIPE_RETRY_CONFIRMED`.
Independent QA reconstructed and verified the original helper bytes, then
reproduced the acceptance on the unchanged disposable host fixture.

Before sending any receipt, require one saved State owner matching the
request ID, request fingerprint or attempt ID. Keep the existing exact
frozen source, release and publication checks. Final independent QA used
the same duplicate fixture and confirmed it held before delivery.
[Retest and fixture](S5_ENROLLED_RETRY_RECEIPT_INDEPENDENT_20261121.md).
