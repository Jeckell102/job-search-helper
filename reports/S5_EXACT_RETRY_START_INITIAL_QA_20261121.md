# Independent optional exact retry admission QA

**REJECT the reviewed optional branch.** All 16 maintained exact and generic admission tests passed using offline disposable State and Jobs stores. A narrower restart case consumed the correct queued request and reused the wrong saved Company checkpoint.

| Reviewed file | SHA-256 |
| --- | --- |
| `scan_request.py` | `edc96c9be74003e7ea004cfdafeaa6b140418e75d786fe723d54e5df4479e3ae` |
| `test_expected_repair_retry_admission.py` | `be3586220fb5f130b4a5e753e2e3ea95ccad5476762d0311a785deb0eb5a87ee` |

The test ran normal exact admission under the existing scraper lease with a real temporary SQLite State and Jobs repository. It interrupted the final queue-file rename after State and Jobs saved the cycle, then changed only the saved single Company key. The queued canonical request, start request ID, saved retry binding, and original request fingerprint remained intact. Resuming the optional call returned the prior cycle ID, whose sole Company had changed, and consumed the queue. The current found-cycle branch compares the request fingerprint without validating the saved retry runtime and Company ownership. [Existing-cycle branch](/tmp/jsh-s5-exact-release-continuation.20261121/src/job_search_helper/scan_request.py:83)

Validate the found saved cycle with the shared retry receipt binding and the exact expected retry before writing the intake checkpoint or consuming the queue. Keep the normal no-option invocation compatible. An intact saved cycle and still-pending exact request should remain recoverable across this interruption.

No production or external effects occurred. The closeout path was outside scoped QA.
