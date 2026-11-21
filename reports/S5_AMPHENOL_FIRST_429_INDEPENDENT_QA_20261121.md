# Independent first-429 observer QA

**ACCEPT** the staged observer only at the exact pins below. This does not qualify the Amphenol candidate or authorize another public request, native installation or release.

The evaluator now latches an actual integer HTTP 429 before returning its response to the unchanged detail client. The dedicated hold derives from BaseException and therefore crosses the real adapter's ordinary Exception retry handling. A repeated get inside the same observation raises the original hold before transport; a swallowed hold followed by a cached body is rejected again before return. The original request getter is restored in finally. Main reports held_provider_rate_limit, rechecks the unchanged source manifest and returns 1. The script propagates that status. No response body, successful dispatch or qualification follows the first 429.

Independent verification ran 27 offline checks: all 22 maintained cases plus five selected checks. The independent normal-path fixture exercised actual ats.fetch_inventory, fetch_acquiretm and _DetailClient, substituting only the browser/context and request transport plus synthetic listing input. It made exactly one simulated 429 request, closed browser/context and emitted held status 1 without successful dispatch or qualification. Other checks prove unreadable headers cannot trigger a retry or leak their diagnostic, a swallowed BaseException followed by a real cached body cannot escape, a different-URL retry remains blocked, and both supported delay endpoints 0 and 86400 seconds are exact. Maintained tests cover ordinary 503/timeout retry behavior, successful cache reuse, HTTP dates, invalid or out-of-bound delay and restoration of the getter.

A fresh AST comparison against the previously accepted fb80eef5 evaluator confirms main is identical after removing exactly the new hold-catching branch. Retry-After parsing, source manifest generation and helper predicates are byte-structurally unchanged. All original complete inventory, final listing, employer, full-description, fixed prior-cohort and normalized-detail-digest checks remain. The only script-exit adjustment preserves success and propagates the new return 1. The candidate adapter remains pinned 895ec36e; no application runtime source or retry policy was changed.

Retry-After evidence remains sanitized: finite delays from 0 through 86400 seconds are recorded and added without the adapter's short delay cap to the exact UTC observation. Values above the evidence bound produce only an exceeds-bound flag; absent, invalid, negative, nonfinite or unreadable values produce no exact retry deadline but still hold. A recorded deadline is a lower bound for quiet time, not a retry authorization or provider availability guarantee. No scheduling or automatic retry was added.

| Input | SHA-256 |
| --- | --- |
| New evaluator | 6053756023435c7c82cbcfe56cabfde863e0397052537b393f9307105fe9e191 |
| Maintained tests | fc5320a4e02c96f0c853bef67da018b007e8984c61f50979730188295061f67f |
| Author offline runner | e47108feb281fd9fd52ae834d874ff3da37704fe3c7251e69676075034dbf13a |
| Prior accepted evaluator | fb80eef5e864c3ee277a249c40e02aa0b78bad9ef4e6359c7609762bc26cf22c |
| Unchanged candidate adapter | 895ec36e443eea5a1c49c622d99b505d5ed49d5ff6c22d37e71eb5a610bb3c9d |

Test command used system Python from this private scratch directory with PYTHONDONTWRITEBYTECODE=1, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 and only the private candidate src on PYTHONPATH. The independent audit hook refuses socket operations, subprocess/exec operations and opens under the production project. No real browser, provider, native data/config/service, Google or Jetson operation occurred. The author's stage was not changed. The initial local harness-writing command had a Python parse error before executing any code; its corrected command created this private fixture and the one test run passed.

The real-runtime guarantee assessed here is the pinned normal application path. Artificial arbitrary code catching the final outer hold and independently issuing a new request is outside this evaluator contract. Future public observations and eventual deployment retain their separate gates. Machine source/AST pins and independent fixture/result pins are in PINS.json, AST_RESULT.json and EVIDENCE_PINS.json beside this report.
