# AcquireTM long Retry-After staging result

Root corrected the existing AcquireTM detail client's short inline retry
path in `/tmp/jsh-acquiretm-retry-after.KOtytYLJ`. A valid provider wait that
exceeds the existing eight-second budget now becomes a blocked hold with
the provider deadline in UTC. The correction retains the response status
even when there is no reason to retrieve the body in Python. Short waits,
bounded retries, and successful detail caching retain their normal flow.

Independent source and composed offline QA accepted the exact correction.
The original adapter tried three times when the server asked for one hour.
An early correction also demonstrated why a detail-loop fix alone is
insufficient. Its long 503 reported a partial result, and the ordinary
whole-Company retry ran again. The corrected version reported a hold and
made one detail request and one Company attempt for each long 429 and 503
fixture. All seven maintained tests passed. Playwright still buffers the
response before exposing status to Python.
[Failure record](S5_AMPHENOL_RETRY_AFTER_INITIAL_QA_20261121.md)
· [Independent QA](S5_AMPHENOL_RETRY_AFTER_INDEPENDENT_QA_20261121.md).

| Exact staged artifact | SHA-256 |
| --- | --- |
| Adapter | `63f7a91af1185bcb171cb70a8a93e7097d46519bd43f1a198911acc84a27f2c8` |
| Maintained tests | `9729563bb49716ce9236b70ad6b05c636dd4999bd17dd7778e7e2e7df2552841` |

The ordinary blocked state provides a manual hold. Its saved reason is
evidence for the operator and does not schedule against a provider
deadline. Bound any manual retry to the recorded cooldown. The existing
selected temporary retry's fixed five-minute policy cannot stand in for
that deadline. Broad automatic retry and unqualified release stay off.

The production adapter remains `a95953af…`. The actual automatic build
remains `895ec36e…`, with all original task artifacts and proposal
`REL-53592bb86b62492840c58267` intact. The transport change was human
engineering on MuleLab and is a separate source stage. It cannot be
substituted into the original generated build, independently qualified
vector or release ID. Any combined successor needs exact separately
reviewed composition and fresh whole-runtime qualification. The original
one-off route remains unqualified until full public evidence exists.
[Release provenance decision](S5_AMPHENOL_RETRY_AFTER_RELEASE_DECISION_20261121.md).

No provider, Jetson, service, Google Sheets, or production jobs were
touched in this checkpoint. Respect the existing no-contact floor of
17:48:55 Eastern. Time alone does not justify another public run.
